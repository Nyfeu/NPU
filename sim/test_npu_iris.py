# ==============================================================================
# File: test_npu_iris.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import math
import test_utils 

# Imports ML (sklearn) =========================================================

try:
    import numpy as np
    from sklearn import datasets
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True

except ImportError:
    HAS_SKLEARN = False
    print("⚠️ SKLEARN não instalado.")

# ==============================================================================
# CONSTANTES (Atualizadas para NPU v2)
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

# ==============================================================================
# DRIVERS MMIO (Adaptado do test_npu_top.py)
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
    """Hard Reset: Garante estado limpo da NPU"""
    dut.rst_n.value = 0
    await Timer(20, unit="ns") 
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    for _ in range(5): await RisingEdge(dut.clk)

# ==============================================================================
# PREPARAÇÃO DO MODELO
# ==============================================================================

def quantize_matrix(matrix, scale):
    q = np.round(matrix / scale).astype(int)
    return np.clip(q, -128, 127)

def quantize_bias(bias, scale_w, scale_x):
    scale = scale_w * scale_x
    return np.round(bias / scale).astype(int)

def get_iris_model():
    if HAS_SKLEARN:
        iris = datasets.load_iris()
        X = iris.data; y = iris.target
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.5, random_state=42)
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_test = scaler.transform(X_test)
        
        clf = LogisticRegression(random_state=0, C=1.0)
        clf.fit(X_train, y_train)
        
        weights_pad = np.zeros((4,4))
        weights_pad[:, :3] = clf.coef_.T
        bias_pad = np.zeros(4)
        bias_pad[:3] = clf.intercept_
        
        max_w = np.max(np.abs(weights_pad))
        max_x = np.max(np.abs(X_test))
        scale_w = max_w / 127.0
        scale_x = max_x / 127.0
        
        W_int = quantize_matrix(weights_pad, scale_w)
        B_int = quantize_bias(bias_pad, scale_w, scale_x)
        X_test_int = quantize_matrix(X_test, scale_x)
        
        # Calibração Automática
        max_acc_val = (127 * 127 * ROWS) + np.max(np.abs(B_int))
        ppu_mult = 100
        target_ratio = (max_acc_val * ppu_mult) / 127.0
        ppu_shift = int(math.ceil(math.log2(target_ratio)))
        if ppu_shift < 0: ppu_shift = 0
        
        print(f"CALIBRAÇÃO: Max Acc={max_acc_val} -> Mult={ppu_mult}, Shift={ppu_shift}")
        return W_int, B_int, X_test_int, y_test, ppu_mult, ppu_shift
    else:
        return [[0]*4]*4, [0]*4, [[0]*4], [0], 1, 0

# ==============================================================================
# TESTE PRINCIPAL
# ==============================================================================

@cocotb.test()
async def test_npu_iris_inference(dut):
    test_utils.log_header("TESTE NPU: IRIS (Updated for Systolic Feed)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    
    # Obter Modelo e Parâmetros
    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = get_iris_model()

    # Configurar NPU
    # Quantização
    quant_cfg = (0 << 8) | (ppu_shift & 0x1F) 
    await mmio_write(dut, REG_QUANT_CFG, quant_cfg)
    await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
    
    # Carregar Bias
    for i, b in enumerate(B_int):
        await mmio_write(dut, REG_BIAS_BASE + (i*4), b)
    
    test_utils.log_success(f"Configuração: Mult={ppu_mult}, Shift={ppu_shift}")

    # Inferência
    test_utils.log_info(f"Iniciando Inferência em {len(X_test)} amostras...")
    correct_preds = 0
    total_samples = len(X_test)
    
    for sample_idx, (x, label_true) in enumerate(zip(X_test, y_true)):
        
        # Limpar Acumuladores antes de cada amostra
        await mmio_write(dut, REG_CTRL, CTRL_ACC_CLEAR)
        await mmio_write(dut, REG_CTRL, 0) # Retorna para Idle
        
        # Alimentação Sistólica (Systolic Feed)
        # Como a NPU agora espera alimentação simultânea de A e B:
        # Input 'x' (1x4) entra na Linha 0 da matriz A.
        # Pesos 'W' (4x4) entram na matriz B.
        for k in range(4):
            # Input Vector: Mapeado para Row 0 de A
            # col_A deve ter x[k] na posição 0, zeros nas outras linhas
            col_A = [x[k], 0, 0, 0]
            
            # Weight Matrix: Mapeada para B
            # row_B deve ser a linha k de W
            row_B = W_int[k, :] 
            
            await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
            await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))
            
        # Aguardar Processamento
        # Tempo fixo para propagação sistólica + PPU
        for _ in range(60): await RisingEdge(dut.clk)
        
        # Dump dos Resultados
        await mmio_write(dut, REG_CTRL, CTRL_ACC_DUMP)
        
        results = []
        for _ in range(4):
            tries = 0
            while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                await RisingEdge(dut.clk)
                tries += 1
                if tries > 200: break
            
            val = await mmio_read(dut, REG_READ_OUT)
            results.append(unpack_int8(val))
            
        await mmio_write(dut, REG_CTRL, 0) # Clear Ctrl
        
        # Processar Resultado
        # O hardware devolve de baixo pra cima (Row 3 -> Row 2 -> Row 1 -> Row 0).
        # results[0] = Row 3 ... results[3] = Row 0.
        # Como nosso input estava na Row 0, o resultado válido está em results[3].
        raw_scores = results[3] 
        pred_label = np.argmax(raw_scores[:3]) # IRIS tem 3 classes
        
        is_correct = (pred_label == label_true)
        if is_correct: correct_preds += 1
            
        msg = f"Amostra {sample_idx:02d}: Scores={raw_scores[:3]} | Pred={pred_label} | Real={label_true}"
        
        if not is_correct:
            test_utils.log_warning(msg)
        else:
            test_utils.log_info(msg)

    # Resultado Final
    acc = (correct_preds / total_samples) * 100.0
    test_utils.log_header("RESULTADO FINAL")
    test_utils.log_info(f"Acertos: {correct_preds}/{total_samples}")
    test_utils.log_success(f"Acurácia da NPU: {acc:.2f}%")