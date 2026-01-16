# ==============================================================================
# File: test_npu_iris.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import math
from test_utils import *

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
# CONSTANTES E DRIVER
# ==============================================================================

ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_FIFO_W     = 0x10
ADDR_FIFO_ACT   = 0x14
ADDR_FIFO_OUT   = 0x18
ADDR_BIAS_BASE  = 0x20 

CTRL_RELU       = 1  # Bit 0
CTRL_LOAD       = 2  # Bit 1
CTRL_ACC_CLEAR  = 4  # Bit 2
CTRL_ACC_DUMP   = 8  # Bit 3

ROWS = 4
COLS = 4

class MMIO_Driver:
    def __init__(self, dut):
        self.dut = dut
        # Inicializa sinais em '0'
        self.dut.vld_i.value = 0
        self.dut.we_i.value = 0
        self.dut.addr_i.value = 0
        self.dut.data_i.value = 0

    async def write(self, addr, data):
        # 1. Sinaliza a intenção de escrita (Valid)
        self.dut.vld_i.value = 1
        self.dut.we_i.value = 1
        self.dut.addr_i.value = addr
        self.dut.data_i.value = int(data) & 0xFFFFFFFF
        
        # 2. Espera pelo flanco de clock onde o READY da NPU é '1'
        while True:
            await RisingEdge(self.dut.clk)
            if self.dut.rdy_o.value == 1:
                break
        
        # 3. Finaliza a transação
        self.dut.vld_i.value = 0
        self.dut.we_i.value = 0

    async def read(self, addr):
        # 1. Sinaliza intenção de leitura
        self.dut.vld_i.value = 1
        self.dut.we_i.value = 0
        self.dut.addr_i.value = addr
        
        # 2. Espera o READY (dado pronto para ser capturado)
        while True:
            await RisingEdge(self.dut.clk)
            if self.dut.rdy_o.value == 1:
                # Captura o dado no mesmo ciclo que o Ready está alto
                val = self.dut.data_o.value
                break
        
        # 3. Finaliza
        self.dut.vld_i.value = 0
        try: return int(val)
        except: return 0

# ==============================================================================
# FUNÇÕES DE QUANTIZAÇÃO
# ==============================================================================

def quantize_matrix(matrix, scale):
    q = np.round(matrix / scale).astype(int)
    return np.clip(q, -128, 127)

def quantize_bias(bias, scale_w, scale_x):
    scale = scale_w * scale_x
    return np.round(bias / scale).astype(int)

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

# ==============================================================================
# PREPARAÇÃO DO MODELO
# ==============================================================================

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
    log_header("TESTE NPU: IRIS (LOG COMPLETO)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    mmio = MMIO_Driver(dut)
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # 1. Obter Modelo e Parâmetros
    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = get_iris_model()

    # 2. Configurar NPU
    # Inicialmente apenas configuração de PPU, sem ativar Tiling ainda
    await mmio.write(ADDR_CSR_CTRL, 0) 
    
    quant_cfg = (0 << 8) | (ppu_shift & 0x1F) 
    await mmio.write(ADDR_CSR_QUANT, quant_cfg)
    await mmio.write(ADDR_CSR_MULT, ppu_mult)
    
    # Carregar Bias
    for i, b in enumerate(B_int):
        await mmio.write(ADDR_BIAS_BASE + (i*4), b)
    
    log_success(f"Configuração: Mult={ppu_mult}, Shift={ppu_shift}")

    # 3. Carregar Pesos
    log_info("Carregando Pesos...")
    await mmio.write(ADDR_CSR_CTRL, CTRL_LOAD) # Load Mode
    for r in reversed(range(ROWS)):
        packed = pack_vec(W_int[r, :])
        await mmio.write(ADDR_FIFO_W, packed)
        
    # Ativar Modo Single-Batch (Clear + Dump) 
    # Como IRIS tem apenas 4 entradas, cabe tudo em uma passada.
    # Dizemos ao HW: "Zere o acumulador antes (CLEAR) e solte o resultado depois (DUMP)"
    ctrl_infer = CTRL_ACC_CLEAR | CTRL_ACC_DUMP
    await mmio.write(ADDR_CSR_CTRL, ctrl_infer)
    
    # 4. Inferência (Log de Tudo)
    log_info(f"Iniciando Inferência em {len(X_test)} amostras...")
    correct_preds = 0
    total_samples = len(X_test)
    BATCH_SIZE = 30
    
    sample_idx = 0 
    
    for i in range(0, total_samples, BATCH_SIZE):
        batch_X = X_test[i : i+BATCH_SIZE]
        batch_y = y_true[i : i+BATCH_SIZE]
        
        for x in batch_X:
            await mmio.write(ADDR_FIFO_ACT, pack_vec(x))
            
        for j, label_true in enumerate(batch_y):
            while True:
                status = await mmio.read(ADDR_CSR_STATUS)
                if (status >> 3) & 1: break
                await RisingEdge(dut.clk)
            
            val = await mmio.read(ADDR_FIFO_OUT)
            scores = unpack_vec(val)
            pred_label = np.argmax(scores[:3])
            
            is_correct = (pred_label == label_true)
            if is_correct: correct_preds += 1
                
            msg = f"Amostra {sample_idx:02d}: Scores={scores[:3]} | Pred={pred_label} | Real={label_true}"
            
            if not is_correct:
                log_warning(msg) # Amarelo para destacar o erro
            else:
                log_info(msg)    # Azul/Info para acertos
            
            sample_idx += 1

    # 5. Resultado
    acc = (correct_preds / total_samples) * 100.0
    log_header("RESULTADO FINAL")
    log_info(f"Acertos: {correct_preds}/{total_samples}")
    
    log_success(f"Acurácia da NPU: {acc:.2f}%")