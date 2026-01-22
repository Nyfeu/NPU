# ==============================================================================
# File: test_npu_mnist.py
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
    from sklearn.preprocessing import MinMaxScaler
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

NUM_TEST_SAMPLES = 50   
INPUT_DIM        = 784  # 28x28 pixels

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
# MODELAGEM DE SOFTWARE (PPU)
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
        for k in range(len(x_vec)):
            acc += x_vec[k] * W_mat[k][col]
        final_val = model_ppu(acc, B_vec[col], mult, shift)
        scores.append(final_val)
    return scores

# ==============================================================================
# PREPARAÇÃO ML (ALTA PERFORMANCE)
# ==============================================================================

def get_mnist_model():
    if not HAS_SKLEARN: return None

    test_utils.log_info("Carregando MNIST Dataset...")
    try:
        mnist = datasets.fetch_openml('mnist_784', version=1, cache=True, as_frame=False)
    except Exception as e:
        test_utils.log_error(f"Erro ao baixar MNIST: {e}")
        return None

    X_raw = mnist.data
    y_raw = mnist.target.astype(int)

    # 1. Filtro: Classes 0, 1, 2, 3
    mask = y_raw < 4
    X_filt = X_raw[mask]
    y_filt = y_raw[mask]

    # 2. Split 
    X_train, X_test, y_train, y_test = train_test_split(
        X_filt, y_filt, train_size=10000, test_size=NUM_TEST_SAMPLES, random_state=42, stratify=y_filt
    )

    # 3. Escalonamento ALTO CONTRASTE (-1 a 1)
    # Isso força o input a usar todo o range do int8 (-128 a 127)
    # Preto vira -128, Branco vira 127. Muito melhor para a NPU "ver" o dígito.
    scaler = MinMaxScaler(feature_range=(-1, 1))
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    test_utils.log_info(f"Treinando Modelo (10k amostras, alto contraste)...")
    # C=1.0 (Menor regularização) permite pesos maiores, facilitando quantização
    clf = LogisticRegression(random_state=42, C=1.0, solver='lbfgs', max_iter=2000)
    clf.fit(X_train, y_train)

    # 4. Quantização
    weights_pad = np.zeros((INPUT_DIM, 4))
    weights_pad[:, :4] = clf.coef_.T
    bias_pad = np.zeros(4)
    bias_pad[:4] = clf.intercept_

    # Escala para int8
    max_w = np.max(np.abs(weights_pad))
    max_x = np.max(np.abs(X_test)) # Deve ser 1.0 agora

    scale_w = 127.0 / max_w if max_w > 0 else 1.0
    scale_x = 127.0 / max_x if max_x > 0 else 1.0

    W_int = np.round(weights_pad * scale_w).astype(int)
    W_int = np.clip(W_int, -128, 127)
    
    B_int = np.round(bias_pad * scale_w * scale_x).astype(int)
    
    X_test_int = np.round(X_test * scale_x).astype(int)
    X_test_int = np.clip(X_test_int, -128, 127)

    # 5. CALIBRAÇÃO PPU
    test_utils.log_info("Calibrando PPU...")
    raw_acc = np.dot(X_test_int, W_int) + B_int
    max_acc_abs = np.max(np.abs(raw_acc))
    if max_acc_abs == 0: max_acc_abs = 1
    
    # Target output range +/- 100
    target_output = 100.0
    ppu_shift = 16 
    scale_factor = target_output / max_acc_abs
    ppu_mult = int(round(scale_factor * (1 << ppu_shift)))
    if ppu_mult < 1: ppu_mult = 1
    
    return W_int, B_int, X_test_int, y_test, ppu_mult, ppu_shift

# ==============================================================================
# TESTE PRINCIPAL
# ==============================================================================

@cocotb.test()
async def test_npu_mnist_inference(dut):
    test_utils.log_header("TESTE MNIST")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    if not HAS_SKLEARN: 
        test_utils.log_error("Bibliotecas ML ausentes.")
        return

    # Preparação
    data_pack = get_mnist_model()
    if data_pack is None: return
    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = data_pack

    # Inicialização HW
    await reset_dut(dut)
    test_utils.log_info(f"Configuração: {INPUT_DIM} Inputs")
    test_utils.log_info(f"CALIBRAÇÃO: [Mult={ppu_mult} | Shift={ppu_shift}]")
    test_utils.log_info(f"Iniciando simulação de {len(X_test)} imagens...")

    # Config Global
    await mmio_write(dut, REG_QUANT_CFG, (0 << 8) | (ppu_shift & 0x1F))
    await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
    for i, b in enumerate(B_int):
        await mmio_write(dut, REG_BIAS_BASE + (i*4), b)

    correct_preds = 0
    hw_sw_matches = 0
    K_DIM = INPUT_DIM

    # Loop de Inferência
    for idx, (x_vec, label_true) in enumerate(zip(X_test, y_true)):
        
        # 1. HARD RESET
        await reset_dut(dut)
        
        # Reconfiguração
        await mmio_write(dut, REG_QUANT_CFG, (0 << 8) | (ppu_shift & 0x1F))
        await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
        for i, b in enumerate(B_int):
            await mmio_write(dut, REG_BIAS_BASE + (i*4), b)

        # 2. Referência SW
        expected_scores = compute_expected_scores(x_vec, W_int, B_int, ppu_mult, ppu_shift)

        # 3. Carga HW
        await mmio_write(dut, REG_CMD, CMD_RST_PTRS)
        for k in range(K_DIM):
            col_A = [x_vec[k], 0, 0, 0] 
            row_B = W_int[k, :]         
            await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
            await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))
            
        # 4. Execução HW
        await mmio_write(dut, REG_CONFIG, K_DIM)
        await mmio_write(dut, REG_CMD, CMD_START)
        
        for _ in range(5000): 
            if (await mmio_read(dut, REG_STATUS) & STATUS_DONE): break
            await RisingEdge(dut.clk)

        # 5. Leitura HW
        results = []
        for _ in range(4):
            while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                await RisingEdge(dut.clk)
            val = await mmio_read(dut, REG_READ_OUT)
            results.append(unpack_int8(val))
        
        results.reverse()
        hw_scores = results[0]

        # 6. Validação 
        diff = [abs(h - s) for h, s in zip(hw_scores, expected_scores)]
        is_hw_valid = max(diff) <= 2
        
        hw_pred = np.argmax(hw_scores)
        is_pred_correct = (hw_pred == label_true)

        if is_hw_valid: hw_sw_matches += 1
        if is_pred_correct: correct_preds += 1

        # Logs
        if idx > 0 and idx % 10 == 0:
            test_utils.log_info(f"Progresso: {idx}/{len(X_test)} imagens...")

        if not is_hw_valid:
            test_utils.log_error(f"[HW FAIL] Img {idx} | Ref: {expected_scores} | HW: {hw_scores} | Diff: {diff}")
        elif not is_pred_correct:
            test_utils.log_warning(f"[MODEL MISS] Img {idx} | Real: {label_true} | Pred: {hw_pred}")

    # Relatório Final
    acc_model = (correct_preds / len(X_test)) * 100.0
    hw_reliability = (hw_sw_matches / len(X_test)) * 100.0
    
    test_utils.log_header(f"RESULTADO FINAL: Acurácia {acc_model:.2f}%")

    # Validação Final
    if hw_reliability < 100.0:
        test_utils.log_error(f"Fidelidade do Hardware: {hw_reliability:.2f}% (FALHA)")
        assert False, "Hardware instável."
    else:
        test_utils.log_info("Fidelidade do Hardware: 100%")

    # Meta de Acurácia: >90%
    if acc_model < 90.0:
        test_utils.log_warning(f"Acurácia {acc_model:.2f}% está abaixo de 90%.")
        assert False, "Modelo impreciso."
    else:
        test_utils.log_success("SUCESSO: Hardware Fiel e Modelo Preciso!")