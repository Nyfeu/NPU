# ==============================================================================
# File: test_npu_iris.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import math
import test_utils 

# Imports ML
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
# CONSTANTES & MAPA DE REGISTRADORES
# ==============================================================================
REG_STATUS     = 0x00
REG_CMD        = 0x04
REG_CONFIG     = 0x08
REG_WRITE_W    = 0x10
REG_WRITE_A    = 0x14
REG_READ_OUT   = 0x18
REG_QUANT_CFG  = 0x40
REG_QUANT_MULT = 0x44
REG_BIAS_BASE  = 0x80

STATUS_DONE      = (1 << 1)
STATUS_OUT_VALID = (1 << 3)
CMD_RST_PTRS     = 0x01
CMD_START        = 0x02

# ==============================================================================
# HELPERS DE HARDWARE
# ==============================================================================

async def mmio_write(dut, addr, data):
    dut.addr_i.value = addr
    dut.data_i.value = int(data) & 0xFFFFFFFF
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1: break
    dut.vld_i.value = 0
    dut.we_i.value  = 0
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

# ==============================================================================
# MODELAGEM DE SOFTWARE
# ==============================================================================

def model_ppu(acc, bias, mult, shift, zero=0):
    val = acc + bias
    val = val * mult
    if shift > 0:
        round_bit = 1 << (shift - 1)
        val = (val + round_bit) >> shift
    val = val + zero
    if val > 127: return 127
    if val < -128: return -128
    return int(val)

def compute_expected_scores(x_vec, W_mat, B_vec, mult, shift):
    scores = []
    for col in range(4):
        acc = 0
        for k in range(4):
            acc += x_vec[k] * W_mat[k][col]
        final_val = model_ppu(acc, B_vec[col], mult, shift)
        scores.append(final_val)
    return scores

# ==============================================================================
# PREPARAÇÃO ML
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
        scale_w = 127.0 / max_w if max_w > 0 else 1.0
        scale_x = 127.0 / max_x if max_x > 0 else 1.0
        
        W_int = np.round(weights_pad * scale_w).astype(int)
        W_int = np.clip(W_int, -128, 127)
        B_int = np.round(bias_pad * scale_w * scale_x).astype(int)
        X_test_int = np.round(X_test * scale_x).astype(int)
        X_test_int = np.clip(X_test_int, -128, 127)
        
        max_possible_acc = (127 * 127 * 4) + np.max(np.abs(B_int))
        ppu_mult = 1
        ppu_shift = int(math.ceil(math.log2(max_possible_acc / 127.0)))
        if ppu_shift < 0: ppu_shift = 0
        
        return W_int, B_int, X_test_int, y_test, ppu_mult, ppu_shift
    return None

# ==============================================================================
# TESTE
# ==============================================================================

@cocotb.test()
async def test_npu_iris_inference_autonomous(dut):
    test_utils.log_header("TESTE IRIS: MODO ROBUSTO (Reset por Amostra)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    if not HAS_SKLEARN: 
        test_utils.log_error("SKLearn não encontrado. Pulando teste.")
        return

    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = get_iris_model()
    
    # Setup Inicial de Log
    test_utils.log_info(f"Configuração Carregada: Mult={ppu_mult}, Shift={ppu_shift}")
    test_utils.log_info(f"Iniciando inferência de {len(X_test)} amostras...")
    
    correct_preds = 0
    hw_sw_matches = 0
    K_DIM = 4 
    total_samples = len(X_test)
    
    # -------------------------------------------------------------------------
    # LOOP PRINCIPAL
    # -------------------------------------------------------------------------
    for idx, (x_vec, label_true) in enumerate(zip(X_test, y_true)):
        
        # 1. HARD RESET (A Cura para Dados Fantasmas)
        # Resetamos o HW a cada amostra para garantir que o FIFO esteja vazio.
        await reset_dut(dut)

        # 2. RECONFIGURAÇÃO (Obrigatória após Reset)
        await mmio_write(dut, REG_QUANT_CFG, (0 << 8) | (ppu_shift & 0x1F))
        await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
        for i, b in enumerate(B_int):
            await mmio_write(dut, REG_BIAS_BASE + (i*4), b)
        
        # 3. Referência SW
        expected_scores = compute_expected_scores(x_vec, W_int, B_int, ppu_mult, ppu_shift)
        
        # 4. Carga HW
        await mmio_write(dut, REG_CMD, CMD_RST_PTRS)
        for k in range(K_DIM):
            col_A = [x_vec[k], 0, 0, 0] 
            row_B = W_int[k, :]         
            await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
            await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))
            
        # 5. Execução
        await mmio_write(dut, REG_CONFIG, K_DIM)
        await mmio_write(dut, REG_CMD, CMD_START)
        
        for _ in range(2000):
            if (await mmio_read(dut, REG_STATUS) & STATUS_DONE): break
            await RisingEdge(dut.clk)
            
        # 6. Leitura
        results = []
        for _ in range(4):
            while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                await RisingEdge(dut.clk)
            val = await mmio_read(dut, REG_READ_OUT)
            results.append(unpack_int8(val))
            
        results.reverse()
        hw_scores = results[0] 
        
        # 7. Análise
        diff = [abs(h - s) for h, s in zip(hw_scores, expected_scores)]
        is_hw_valid = max(diff) <= 2
        hw_pred = np.argmax(hw_scores[:3])
        is_pred_correct = (hw_pred == label_true)
        
        if is_hw_valid: hw_sw_matches += 1
        if is_pred_correct: correct_preds += 1
        
        # Logs
        if idx > 0 and idx % (total_samples // 5) == 0:
            test_utils.log_info(f"Progresso: {idx}/{total_samples} amostras processadas...")

        if not is_hw_valid:
            test_utils.log_error(f"[HW FAIL] Amostra {idx} | Ref: {expected_scores} | HW: {hw_scores} | Diff: {diff}")
        elif not is_pred_correct:
            test_utils.log_warning(f"[MODEL MISS] Amostra {idx} | Label Real: {label_true} | Predito: {hw_pred}")

    acc_model = (correct_preds / total_samples) * 100.0
    hw_reliability = (hw_sw_matches / total_samples) * 100.0
    
    test_utils.log_header(f"RESULTADO FINAL: {acc_model:.2f}% de Acurácia")
    
    if hw_reliability < 100.0:
        test_utils.log_error(f"Fidelidade do Hardware: {hw_reliability:.2f}% (Houve divergências numéricas!)")
        assert False, "Falha na verificação numérica do Hardware."
    else:
        test_utils.log_info("Fidelidade do Hardware: 100%")

    if acc_model < 90.0:
        test_utils.log_warning(f"Acurácia do modelo ({acc_model:.2f}%) abaixo da meta de 90%.")
        assert False, "Critério de aceitação de ML não atingido."
    
    test_utils.log_success("Teste Iris Concluído com Sucesso!")