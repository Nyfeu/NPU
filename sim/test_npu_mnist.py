# ==============================================================================
# File: test_npu_mnist.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import math
import os
import urllib.request
import numpy as np 
import test_utils

# Tenta importar sklearn para treinar um modelo real
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# ==============================================================================
# CONSTANTES & REGISTRADORES
# ==============================================================================

REG_CTRL       = 0x00
REG_QUANT_CFG  = 0x04
REG_QUANT_MULT = 0x08
REG_STATUS     = 0x0C
REG_WRITE_W    = 0x10 
REG_WRITE_A    = 0x14 
REG_READ_OUT   = 0x18 
REG_BIAS_BASE  = 0x20

STATUS_OUT_VALID  = (1 << 3)
CTRL_ACC_CLEAR    = 0x04
CTRL_ACC_DUMP     = 0x08

ROWS = 4
COLS = 4
NUM_LABELS = 10
INPUT_SIZE = 784 # 28x28

# ==============================================================================
# DRIVERS MMIO
# ==============================================================================

async def mmio_write(dut, addr, data):
    dut.addr_i.value = addr
    dut.data_i.value = int(data) & 0xFFFFFFFF
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1:
            break
    dut.vld_i.value = 0
    dut.we_i.value  = 0
    await RisingEdge(dut.clk) 
    await RisingEdge(dut.clk)

async def mmio_read(dut, addr):
    dut.addr_i.value = addr
    dut.we_i.value   = 0
    dut.vld_i.value  = 1
    data = 0
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1:
            data = int(dut.data_o.value)
            break
    dut.vld_i.value = 0
    await RisingEdge(dut.clk) 
    await RisingEdge(dut.clk)
    return data

def pack_int8(values):
    packed = 0
    for i, val in enumerate(values):
        val_8bit = int(val) & 0xFF
        packed |= (val_8bit << (i * 8))
    return packed

def unpack_int8(packed):
    values = []
    for i in range(4):
        raw = (packed >> (i * 8)) & 0xFF
        if raw & 0x80: raw -= 256
        values.append(raw)
    return values

async def reset_dut(dut):
    dut.rst_n.value = 0
    await Timer(20, unit="ns") 
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    for _ in range(5): await RisingEdge(dut.clk)

# ==============================================================================
# DATASET & MODELO
# ==============================================================================

def load_mnist_data():
    """Baixa e carrega MNIST (usando npz local se existir)"""
    if not os.path.exists("mnist.npz"):
        url = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz"
        test_utils.log_info(f"Baixando MNIST de {url}...")
        urllib.request.urlretrieve(url, "mnist.npz")
    
    with np.load("mnist.npz", allow_pickle=True) as f:
        x_train, y_train = f['x_train'], f['y_train']
        x_test, y_test = f['x_test'], f['y_test']
    
    # Flatten (28x28 -> 784)
    x_train = x_train.reshape(-1, 784).astype(np.float32)
    x_test = x_test.reshape(-1, 784).astype(np.float32)
    
    return x_train, y_train, x_test, y_test

def train_and_quantize_model():
    """
    Treina uma Regressão Logística no MNIST (se sklearn instalado) 
    ou gera pesos aleatórios (fallback).
    Retorna pesos quantizados e parâmetros.
    """
    x_train, y_train, x_test, y_test = load_mnist_data()
    
    # Obter Pesos (Float)
    if HAS_SKLEARN:
        test_utils.log_info("Treinando modelo LogisticRegression rápido (1k amostras)...")
        
        # Subsample para ser rápido no teste
        mask = np.random.choice(len(x_train), 1000, replace=False)
        X_small = x_train[mask]
        y_small = y_train[mask]
        
        # StandardScaler ajuda na convergência
        scaler = StandardScaler()
        X_small = scaler.fit_transform(X_small)
        # Precisamos da referência de escala para o X de teste depois
        
        clf = LogisticRegression(solver='lbfgs', max_iter=200)
        clf.fit(X_small, y_small)
        
        # Sklearn retorna shape (n_classes, n_features) -> (10, 784)
        # NPU quer (Input, Output) -> (784, 10)
        weights_float = clf.coef_.T
        bias_float = clf.intercept_
        
        # Para teste, usamos o scaler nos dados de teste também
        x_test_norm = scaler.transform(x_test[:50]) # Pega 50 pra teste
        y_test_sub  = y_test[:50]
        
    else:
        test_utils.log_warning("SKLEARN não encontrado. Usando pesos aleatórios (Acurácia será ~10%).")
        weights_float = np.random.uniform(-0.5, 0.5, (784, 10))
        bias_float    = np.random.uniform(-0.1, 0.1, (10,))
        x_test_norm   = (x_test[:50] / 255.0) * 2 - 1 # Normalização simples
        y_test_sub    = y_test[:50]

    # Quantização (Float -> Int8)
    # Define escalas baseadas no range dinâmico dos pesos e entradas
    max_w = np.max(np.abs(weights_float))
    max_x = np.max(np.abs(x_test_norm))
    
    # Evita divisão por zero
    if max_w == 0: max_w = 1.0
    if max_x == 0: max_x = 1.0
    
    scale_w = max_w / 127.0
    scale_x = max_x / 127.0
    
    # Quantiza
    W_int = np.clip(np.round(weights_float / scale_w), -128, 127).astype(int)
    B_int = np.clip(np.round(bias_float / (scale_w * scale_x)), -128, 127).astype(int)
    X_int = np.clip(np.round(x_test_norm / scale_x), -128, 127).astype(int)
    
    # Calcular parâmetros da PPU (Post-Processing Unit)
    # O acumulador interno vai crescer bastante. Precisamos trazer de volta pra 8 bits.
    # Aprox: Acc_max ~= 127 * 127 * 784 (pior caso teórico)
    # Queremos mapear o range útil de volta para [-128, 127]
    
    # Heurística: Vamos observar a magnitude típica da saída simulada em float
    raw_output = np.dot(x_test_norm, weights_float) + bias_float
    max_out = np.max(np.abs(raw_output))
    if max_out == 0: max_out = 1.0
    
    # A relação real é: Out_int = Out_float / (scale_w * scale_x)
    # PPU faz: (Acc * mult) >> shift
    # Queremos que (Acc * mult >> shift) ~= Out_float / scale_total
    
    # Simplificação robusta para teste:
    # Vamos calibrar o shift para que o maior valor do dataset de teste caiba em ~100 (dentro de 127)
    # Acc_int_max estimativo
    sim_acc = np.dot(X_int, W_int) + B_int
    max_acc_abs = np.max(np.abs(sim_acc))
    
    # Queremos reduzir max_acc_abs para ~100
    target = 100.0
    ratio = max_acc_abs / target
    
    # Encontrar mult/shift tal que (mult / 2^shift) ~= 1/ratio
    # Vamos fixar mult=100 e achar o shift
    # 100 / 2^shift = 100 / max_acc_abs -> 2^shift = max_acc_abs
    if max_acc_abs < 1: max_acc_abs = 1
    ppu_shift = int(math.ceil(math.log2(max_acc_abs / target * 1.5))) # 1.5 margem seg
    if ppu_shift < 0: ppu_shift = 0
    ppu_mult = 1 # Usando shift puro geralmente é mais seguro pra evitar overflow na multiplicação intermediária se acc for gigante
    
    # Refinando com mult para precisão
    # scale_factor = 1 / ratio
    # mult * 2^-shift = scale_factor
    # mult = scale_factor * 2^shift
    scale_factor = target / max_acc_abs
    ppu_shift = 16 # Fixa shift num valor alto para ter precisão no mult
    ppu_mult = int(round(scale_factor * (1 << ppu_shift)))
    
    # Clamp mult to 16-bit unsigned (assumindo que HW suporta)
    # Se o HW suportar apenas mult pequeno, ajuste aqui.
    # No test_npu_top vimos mult até 255 ok? Vamos limitar a 8 bits se for o caso.
    while ppu_mult > 255:
        ppu_mult >>= 1
        ppu_shift -= 1
        
    if ppu_mult < 1: ppu_mult = 1
    if ppu_shift < 0: ppu_shift = 0
    
    test_utils.log_info(f"Calibration: MaxAcc={max_acc_abs} -> Mult={ppu_mult}, Shift={ppu_shift}")
    
    return W_int, B_int, X_int, y_test_sub, ppu_mult, ppu_shift

# ==============================================================================
# TESTE PRINCIPAL
# ==============================================================================

@cocotb.test()
async def test_npu_mnist_inference(dut):
    test_utils.log_header("TESTE NPU: MNIST (Trained Model Check)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    
    # Preparar Modelo e Dados
    W_int, B_int, X_int, y_true, ppu_mult, ppu_shift = train_and_quantize_model()
    
    NUM_SAMPLES = 5 # Testar 5 amostras
    
    # Configurar NPU
    q_cfg = (0 << 8) | (ppu_shift & 0x1F)
    await mmio_write(dut, REG_QUANT_CFG, q_cfg)
    await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
    
    test_utils.log_info(f"Iniciando inferência em {NUM_SAMPLES} imagens...")

    match_count = 0
    real_match_count = 0

    for img_idx in range(NUM_SAMPLES):
        x_vec = X_int[img_idx]
        hw_scores = np.zeros(10, dtype=int)
        
        # --- TILING LOOP ---
        for col_start in range(0, NUM_LABELS, COLS):
            col_end = min(col_start + COLS, NUM_LABELS)
            current_chunk_size = col_end - col_start
            
            # Carregar Bias
            for i in range(current_chunk_size):
                await mmio_write(dut, REG_BIAS_BASE + (i*4), B_int[col_start + i])
            for i in range(current_chunk_size, 4):
                await mmio_write(dut, REG_BIAS_BASE + (i*4), 0)

            # Clear
            await mmio_write(dut, REG_CTRL, CTRL_ACC_CLEAR)
            await mmio_write(dut, REG_CTRL, 0)
            
            # SYSTOLIC FEED
            for k in range(INPUT_SIZE):
                vec_a = [x_vec[k], 0, 0, 0]
                w_row_slice = W_int[k, col_start:col_end]
                vec_w = [0]*4
                for idx, w_val in enumerate(w_row_slice):
                    vec_w[idx] = w_val
                
                await mmio_write(dut, REG_WRITE_A, pack_int8(vec_a))
                await mmio_write(dut, REG_WRITE_W, pack_int8(vec_w))
            
            # Wait
            for _ in range(60): await RisingEdge(dut.clk)
            
            # Dump
            await mmio_write(dut, REG_CTRL, CTRL_ACC_DUMP)
            results = []
            for _ in range(4):
                while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                    await RisingEdge(dut.clk)
                results.append(unpack_int8(await mmio_read(dut, REG_READ_OUT)))
            await mmio_write(dut, REG_CTRL, 0)

            valid_row = results[3] 
            hw_scores[col_start : col_end] = valid_row[:current_chunk_size]

        # --- Validação ---
        
        npu_pred = np.argmax(hw_scores)
        
        # Referência Python (Simulação do Hardware)
        ref_dot = np.dot(x_vec, W_int) + B_int
        ref_proc = (ref_dot * ppu_mult) 
        # Simula shift com arredondamento
        round_add = (1 << (ppu_shift - 1)) if ppu_shift > 0 else 0
        ref_proc = np.floor((ref_proc + round_add) >> ppu_shift).astype(int)
        ref_proc = np.clip(ref_proc, -128, 127)
        ref_pred = np.argmax(ref_proc)
        
        true_label = y_true[img_idx]

        msg = f"Img {img_idx}: Real={true_label} | NPU={npu_pred} (Ref={ref_pred})"
        
        # Checa consistência HW vs SW
        hw_ok = (npu_pred == ref_pred)
        # Checa acerto Real
        real_ok = (npu_pred == true_label)
        
        if real_ok:
            test_utils.log_success(f"{msg} [ACERTOU]")
            real_match_count += 1
        else:
            test_utils.log_warning(f"{msg} [ERROU]")

        if hw_ok: match_count += 1

    test_utils.log_header("RESULTADO FINAL")
    test_utils.log_info(f"Consistência HW/Ref: {match_count}/{NUM_SAMPLES}")
    test_utils.log_success(f"Acurácia Real: {real_match_count}/{NUM_SAMPLES} (Modelo Treinado)")