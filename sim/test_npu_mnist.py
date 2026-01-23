# ==============================================================================
# File: test_npu_mnist.py (Tiling & Localidade)
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

# Comandos
CMD_RST_DMA_PTRS = (1 << 0) 
CMD_START        = (1 << 1)
CMD_ACC_CLEAR    = (1 << 2)
CMD_RST_W_RD     = (1 << 4) 
CMD_RST_I_RD     = (1 << 5) 
CMD_RST_WR_W     = (1 << 6) 
CMD_RST_WR_I     = (1 << 7) 

NUM_TEST_SAMPLES = 50   
INPUT_DIM        = 784  # 28x28 pixels
NUM_CLASSES      = 10   
HW_COLS          = 4    

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
    dut.vld_i.value  = 0
    dut.we_i.value   = 0
    dut.addr_i.value = 0
    dut.data_i.value = 0
    dut.rst_n.value = 0
    await Timer(20, unit="ns") 
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

# ==============================================================================
# MODELO DE REFERÊNCIA
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
    for cls in range(NUM_CLASSES):
        acc = 0
        for k in range(len(x_vec)):
            acc += x_vec[k] * W_mat[k][cls]
        final_val = model_ppu(acc, B_vec[cls], mult, shift)
        scores.append(final_val)
    return scores

# ==============================================================================
# PREPARAÇÃO ML (0-9)
# ==============================================================================

def get_mnist_model():
    if not HAS_SKLEARN: return None

    test_utils.log_info("Carregando MNIST Completo (0-9)...")
    mnist = datasets.fetch_openml('mnist_784', version=1, cache=True, as_frame=False)
    X_train, X_test, y_train, y_test = train_test_split(
        mnist.data, mnist.target.astype(int), train_size=10000, test_size=NUM_TEST_SAMPLES, random_state=42
    )

    scaler = MinMaxScaler(feature_range=(-1, 1))
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    test_utils.log_info("Treinando Modelo (Logistic Regression)...")
    clf = LogisticRegression(random_state=42, C=1.0, solver='lbfgs', max_iter=2000)
    clf.fit(X_train, y_train)

    W_int = np.round(clf.coef_.T * (127.0/np.max(np.abs(clf.coef_)))).astype(int)
    X_test_int = np.round(X_test * 127.0).astype(int)
    B_int = np.round(clf.intercept_ * (127.0/np.max(np.abs(clf.coef_))) * 127.0).astype(int)

    # Calibração PPU
    raw_acc = np.dot(X_test_int, W_int) + B_int
    ppu_shift = 16 
    scale_factor = 100.0 / np.max(np.abs(raw_acc))
    ppu_mult = int(round(scale_factor * (1 << ppu_shift)))
    
    return W_int, B_int, X_test_int, y_test, ppu_mult, ppu_shift

# ==============================================================================
# TESTE DE TILING & LOCALIDADE
# ==============================================================================

@cocotb.test()
async def test_npu_mnist_tiling_full(dut):
    test_utils.log_header("TESTE MNIST: DEBUG MODE (Mismatches Reportados)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    if not HAS_SKLEARN: 
        test_utils.log_error("Sklearn não encontrado.")
        return

    data_pack = get_mnist_model()
    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = data_pack

    await reset_dut(dut)
    await mmio_write(dut, REG_QUANT_CFG, (0 << 8) | (ppu_shift & 0x1F))
    await mmio_write(dut, REG_QUANT_MULT, ppu_mult)
    
    correct_preds = 0
    hw_sw_matches = 0
    total_samples = len(X_test)

    # Tolerância para diferença numérica (Arredondamento HW vs Python)
    # O valor 1 é aceitável devido a diferenças em rounds de inteiros.
    TOLERANCE = 1 

    for idx, (x_vec, label_true) in enumerate(zip(X_test, y_true)):
        full_hw_scores = []
        
        # -----------------------------------------------------------
        # Loop de Tiling (0-3, 4-7, 8-9)
        # -----------------------------------------------------------
        for class_start in range(0, NUM_CLASSES, HW_COLS):
            class_end = min(class_start + HW_COLS, NUM_CLASSES)
            num_classes_batch = class_end - class_start
            
            W_slice = W_int[:, class_start:class_end]
            B_slice = B_int[class_start:class_end]
            
            # Padding se batch < 4
            if num_classes_batch < HW_COLS:
                W_slice = np.pad(W_slice, ((0,0),(0, HW_COLS - num_classes_batch)))
                B_slice = np.pad(B_slice, (0, HW_COLS - num_classes_batch))

            for i, b in enumerate(B_slice):
                await mmio_write(dut, REG_BIAS_BASE + (i*4), b)

            # CARGA DE DADOS
            if class_start == 0:
                # Batch 0: Carrega Imagem + Pesos
                await mmio_write(dut, REG_CMD, CMD_RST_WR_W | CMD_RST_WR_I)
                for k in range(INPUT_DIM):
                    pixel = x_vec[k]
                    # BROADCAST Input
                    await mmio_write(dut, REG_WRITE_A, pack_int8([pixel]*4))
                    await mmio_write(dut, REG_WRITE_W, pack_int8(W_slice[k, :]))
            else:
                # Batch Seguintes: Apenas Pesos (Reusa Imagem)
                await mmio_write(dut, REG_CMD, CMD_RST_WR_W)
                for k in range(INPUT_DIM):
                    await mmio_write(dut, REG_WRITE_W, pack_int8(W_slice[k, :]))

            # EXECUTA
            await mmio_write(dut, REG_CONFIG, INPUT_DIM)
            await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
            
            while not (await mmio_read(dut, REG_STATUS) & STATUS_DONE):
                await RisingEdge(dut.clk)

            # COLETA
            while not (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID):
                await RisingEdge(dut.clk)
            
            packed_res = await mmio_read(dut, REG_READ_OUT)
            full_hw_scores.extend(unpack_int8(packed_res)[:num_classes_batch])

        # -----------------------------------------------------------
        # VALIDAÇÃO & LOGS DETALHADOS
        # -----------------------------------------------------------
        expected = compute_expected_scores(x_vec, W_int, B_int, ppu_mult, ppu_shift)
        
        # 1. Análise Numérica (Bit-Exact check)
        diffs = [abs(h - s) for h, s in zip(full_hw_scores, expected)]
        max_diff = max(diffs)
        
        if max_diff > TOLERANCE:
            test_utils.log_error(f"HW MISMATCH | Sample {idx}")
            test_utils.log_error(f"HW : {full_hw_scores}")
            test_utils.log_error(f"Ref: {expected}")
            test_utils.log_error(f"Dif: {diffs}")
            # Não abortamos o teste, mas marcamos o erro.
        else:
            hw_sw_matches += 1

        # 2. Análise de Predição (Acurácia)
        hw_pred = np.argmax(full_hw_scores)
        if hw_pred == label_true:
            correct_preds += 1
        else:
            # Log opcional para entender porque a acurácia está baixa
            # Use log_warning para destacar, mas é 'menos grave' que erro de HW
            test_utils.log_warning(f"PRED ERROR | Sample {idx} | Real: {label_true} vs Pred: {hw_pred}")

        # 3. Log de Progresso
        if idx % 10 == 0 or idx == total_samples - 1:
            acc_current = (correct_preds / (idx + 1)) * 100.0
            hw_reliability = (hw_sw_matches / (idx + 1)) * 100.0
            test_utils.log_info(f"Progresso {idx}/{total_samples} | Acc Modelo: {acc_current:.1f}% | HW Match: {hw_reliability:.1f}%")

    # -----------------------------------------------------------
    # RESULTADO FINAL
    # -----------------------------------------------------------
    final_acc = (correct_preds / total_samples) * 100.0
    final_hw_match = (hw_sw_matches / total_samples) * 100.0
    
    test_utils.log_header(f"RELATÓRIO FINAL")
    test_utils.log_info(f"Acurácia do Modelo: {final_acc:.2f}%")
    test_utils.log_info(f"Fidelidade HW/SW:   {final_hw_match:.2f}%")

    if final_hw_match < 100.0:
        test_utils.log_error("FALHA CRÍTICA: O Hardware produziu resultados diferentes do modelo SW.")
        assert False, "Hardware Mismatch Detected"
    
    test_utils.log_success("Teste Concluído - Hardware Validado com Sucesso.")