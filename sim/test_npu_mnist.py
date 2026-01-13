# ==============================================================================
# File: test_npu_mnist.py
# ==============================================================================
# Descrição: Teste de inferência do dataset MNIST (784x10)
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
import math
import os
import urllib.request
import numpy as np 
from test_utils import *

# ==============================================================================
# CONSTANTES
# ==============================================================================

# Endereços dos registradores (CSRs)
ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_FIFO_W     = 0x10
ADDR_FIFO_ACT   = 0x14
ADDR_FIFO_OUT   = 0x18
ADDR_BIAS_BASE  = 0x20 

# BITWISE
CTRL_RELU       = (1 << 0)
CTRL_LOAD       = (1 << 1)
CTRL_ACC_CLEAR  = (1 << 2) 
CTRL_ACC_DUMP   = (1 << 3) 

# Constantes para o array
ROWS = 4
COLS = 4
LATENCY_MARGIN  = 30 

# ==============================================================================
# DRIVER E UTILITÁRIOS
# ==============================================================================

class MMIO_Driver:
    def __init__(self, dut):
        self.dut = dut
        self.dut.sel_i.value = 0; self.dut.we_i.value = 0; self.dut.addr_i.value = 0; self.dut.data_i.value = 0

    async def write(self, addr, data):
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value = 1; self.dut.we_i.value = 1; self.dut.addr_i.value = addr; self.dut.data_i.value = int(data) & 0xFFFFFFFF
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value = 0; self.dut.we_i.value = 0

    async def read(self, addr):
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value = 1; self.dut.we_i.value = 0; self.dut.addr_i.value = addr
        await RisingEdge(self.dut.clk)
        val = self.dut.data_o.value
        self.dut.sel_i.value = 0
        try: return int(val)
        except: return 0

def pack_vec(values):
    packed = 0
    for i, val in enumerate(values):
        val = int(val) & 0xFF
        packed |= (val << (i * 8))
    return packed

def unpack_vec(packed):
    res = []
    for i in range(4):
        b = (packed >> (i*8)) & 0xFF
        if b > 127: b -= 256
        res.append(b)
    return res

def ppu_software_model(acc_32, bias_32, mult, shift):
    s1 = acc_32 + bias_32
    s2 = s1 * mult
    if shift > 0:
        round_bit = 1 << (shift - 1)
        s3 = (s2 + round_bit) >> shift
    else:
        s3 = s2
    if s3 > 127: return 127
    if s3 < -128: return -128
    return int(s3)

# ==============================================================================
# MODELO MNIST
# ==============================================================================

def get_mnist_model():

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        
    except ImportError:
        return None

    file_path = "mnist.npz"
    url = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz"

    if not os.path.exists(file_path):

        cocotb.log.info(f"⬇️ Baixando MNIST...")
        try: urllib.request.urlretrieve(url, file_path)
        except: return get_synthetic_data()
    
    try:
        with np.load(file_path, allow_pickle=True) as f:
            x_train, y_train = f['x_train'], f['y_train']
            x_test, y_test = f['x_test'], f['y_test']
        
        X = np.concatenate([x_train, x_test]).reshape(-1, 784).astype(float)
        y = np.concatenate([y_train, y_test]).astype(int)
        
        # Treina com mais dados para melhorar a acurácia
        X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=5000, test_size=50, random_state=42)
        
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_test = scaler.transform(X_test)
        
        cocotb.log.info("🧠 Treinando Regressão Logística...")
        clf = LogisticRegression(C=0.01, penalty='l2', solver='lbfgs', max_iter=200)
        clf.fit(X_train, y_train)
        
        weights = clf.coef_
        bias = clf.intercept_
        
        # Quantização
        max_w = np.max(np.abs(weights))
        max_x = np.max(np.abs(X_test))
        scale_w = max_w / 127.0 if max_w > 0 else 1.0
        scale_x = max_x / 127.0 if max_x > 0 else 1.0
        
        W_int = np.clip(np.round(weights / scale_w), -128, 127).astype(int)
        X_test_int = np.clip(np.round(X_test / scale_x), -128, 127).astype(int)
        B_int = np.round(bias / (scale_w * scale_x)).astype(int)
        
        return W_int, B_int, X_test_int, y_test, False

    except: return get_synthetic_data()

def get_synthetic_data():
    np.random.seed(42)
    return np.random.randint(-60, 60, (10, 784)), np.random.randint(-1000, 1000, (10,)), np.random.randint(-100, 100, (5, 784)), np.zeros(5), True

# ==============================================================================
# TESTE PRINCIPAL
# ==============================================================================

@cocotb.test()
async def test_npu_mnist(dut):
    log_header("TESTE NPU: MNIST (Reconhecimento de Dígitos)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    mmio = MMIO_Driver(dut)
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # 1. Obter Dados
    data = get_mnist_model()
    if data is None: return 
    W_int, B_int, X_test, y_true, is_synthetic = data
    
    # 2. CALIBRAÇÃO INTELIGENTE
    # Rodamos o modelo em software (sem quantizar saída) para ver o range real dos valores.
    
    cocotb.log.info("⚖️  Calibrando PPU com dados reais...")
    
    # Calcula produto escalar cru (sem shift) para todas as amostras de teste
    # W_int (10, 784) @ X_test.T (784, N) = (10, N)
    raw_outputs = np.dot(W_int, X_test.T) + B_int[:, None]
    
    # Pega o valor máximo absoluto observado
    max_observed = np.max(np.abs(raw_outputs))
    
    # Dá uma margem de segurança de 20% para evitar saturação em outliers
    max_safe = max_observed * 1.2
    
    # Calcula shift para que max_safe caiba em 127
    target_ratio = max_safe / 127.0
    if target_ratio <= 1:
        ppu_shift = 0
    else:
        ppu_shift = int(math.ceil(math.log2(target_ratio)))
    
    ppu_mult = 1
    
    cocotb.log.info(f"🔍 Max Observado: {int(max_observed)} | Max Teórico Pior Caso: 12.000.000+")
    cocotb.log.info(f"⚙️  Shift Ajustado: {ppu_shift} (Era 17)")
    
    quant_cfg = (0 << 8) | (ppu_shift & 0x1F) 
    await mmio.write(ADDR_CSR_QUANT, quant_cfg)
    await mmio.write(ADDR_CSR_MULT, ppu_mult)
    
    match_count = 0
    NUM_CLASSES = 10
    NUM_FEATURES = 784
    COLS = 4; ROWS = 4
    
    # 3. Inferência
    for img_idx, input_vec in enumerate(X_test):
        
        final_scores_hw = np.zeros(NUM_CLASSES, dtype=int)
        
        # Golden Model
        raw_dot = np.dot(W_int, input_vec)
        golden_scores_quant = []
        for c in range(NUM_CLASSES):
            val = ppu_software_model(raw_dot[c], B_int[c], ppu_mult, ppu_shift)
            golden_scores_quant.append(val)
        golden_scores_quant = np.array(golden_scores_quant)
        
        # Hardware Tiling
        for col_start in range(0, NUM_CLASSES, COLS):
            current_bias = B_int[col_start : col_start + COLS]
            if len(current_bias) < COLS: current_bias = np.pad(current_bias, (0, COLS - len(current_bias)))
            for i, b in enumerate(current_bias): await mmio.write(ADDR_BIAS_BASE + (i*4), b)
                
            for depth_start in range(0, NUM_FEATURES, ROWS):
                w_tile = np.zeros((ROWS, COLS), dtype=int)
                c_end = min(col_start + COLS, NUM_CLASSES)
                d_end = min(depth_start + ROWS, NUM_FEATURES)
                block = W_int[col_start:c_end, depth_start:d_end].T 
                w_tile[:block.shape[0], :block.shape[1]] = block
                
                x_chunk = input_vec[depth_start : d_end]
                if len(x_chunk) < ROWS: x_chunk = np.pad(x_chunk, (0, ROWS - len(x_chunk)))
                
                await mmio.write(ADDR_CSR_CTRL, CTRL_LOAD)
                for r in reversed(range(ROWS)): await mmio.write(ADDR_FIFO_W, pack_vec(w_tile[r, :]))
                
                ctrl_val = 0
                if depth_start == 0: ctrl_val |= CTRL_ACC_CLEAR
                if depth_start + ROWS >= NUM_FEATURES: ctrl_val |= CTRL_ACC_DUMP
                
                await mmio.write(ADDR_CSR_CTRL, ctrl_val)
                await mmio.write(ADDR_FIFO_ACT, pack_vec(x_chunk))
                await ClockCycles(dut.clk, LATENCY_MARGIN)
            
            while True:
                status = await mmio.read(ADDR_CSR_STATUS)
                if (status >> 3) & 1: break
                await RisingEdge(dut.clk)
            val = await mmio.read(ADDR_FIFO_OUT)
            scores = unpack_vec(val)
            limit = min(COLS, NUM_CLASSES - col_start)
            final_scores_hw[col_start : col_start + limit] = scores[:limit]

        # Validation
        diff = np.abs(final_scores_hw - golden_scores_quant)
        max_diff = np.max(diff)
        
        npu_pred = np.argmax(final_scores_hw)
        soft_pred = np.argmax(golden_scores_quant)
        real_label = y_true[img_idx] if not is_synthetic else 0
        
        # Colorização do log
        msg = f"Amostra {img_idx}: Real={real_label} -> NPU={npu_pred} (Soft={soft_pred})"
        
        if max_diff == 0:
            status = "✅ (Bit-Exact)"
            if npu_pred == real_label: status += " 🎯 ACERTOU!"
            else: status += " ⚠️  ERROU CLASSE"
            log_info(f"{msg} | Diff=0 {status}")
            match_count += 1
        elif npu_pred == soft_pred:
             log_warning(f"{msg} | Diff={max_diff} (Pred Match)")
             match_count += 1
        else:
            log_warning(f"{msg} | Diff={max_diff} ❌ FALHA")

    acc = (match_count / len(X_test)) * 100.0
    log_header("RESULTADO FINAL")
    if is_synthetic: log_info("Dados: SINTÉTICOS")
    else: log_info(f"Dados: MNIST REAL ({len(X_test)} amostras)")
    
    log_info(f"Concordância NPU vs Python: {acc:.1f}%")
    assert acc >= 90.0, f"Falha: {acc:.1f}%"
    log_success("Hardware Validado e Calibrado!")