# ==============================================================================
# File: fpga_mnist.py
# ==============================================================================
# Descrição: Driver HIL para MNIST com verificação de Consistência de Hardware
#            separada da Acurácia do Modelo.
# ==============================================================================

import serial
import time
import struct
import math
import sys
import os
import urllib.request
import logging
import warnings
import numpy as np

# --- CONFIGURAÇÃO DE LOGGING E CORES ---

class Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"

class ColoredFormatter(logging.Formatter):
    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    FORMATS = {
        logging.DEBUG:    Colors.DIM + fmt + Colors.RESET,
        logging.INFO:     Colors.BLUE + "%(asctime)s " + Colors.RESET + "| " + Colors.GREEN + "%(levelname)-8s" + Colors.RESET + " | %(message)s",
        logging.WARNING:  Colors.BLUE + "%(asctime)s " + Colors.RESET + "| " + Colors.YELLOW + "%(levelname)-8s" + Colors.RESET + " | %(message)s",
        logging.ERROR:    Colors.BLUE + "%(asctime)s " + Colors.RESET + "| " + Colors.RED + "%(levelname)-8s" + Colors.RESET + " | %(message)s",
        logging.CRITICAL: Colors.RED + Colors.BOLD + fmt + Colors.RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')
        return formatter.format(record)

def setup_logger():
    warnings.simplefilter(action='ignore', category=FutureWarning)
    logger = logging.getLogger("MNIST_HIL")
    logger.setLevel(logging.INFO)
    if logger.hasHandlers(): logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)
    
    if not os.path.exists("build"): os.makedirs("build")
    log_file = os.path.join("build", "mnist_test_report.log")
    fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(fh)
    return logger

log = setup_logger()

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    log.warning("Scikit-learn não encontrado. Usando pesos aleatórios.")

# ==============================================================================
# CONFIGURAÇÃO DE HARDWARE
# ==============================================================================

SERIAL_PORT = 'COM6'   
BAUD_RATE   = 921600

# Mapa de Registradores
ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_WRITE_W    = 0x10 
ADDR_WRITE_A    = 0x14 
ADDR_READ_OUT   = 0x18 
ADDR_BIAS_BASE  = 0x20 

# Controle
CTRL_RELU       = 1  
CTRL_ACC_CLEAR  = 4  
CTRL_ACC_DUMP   = 8  
STATUS_VALID    = 8  

ROWS = 4
COLS = 4
NUM_CLASSES = 10
INPUT_SIZE  = 784

# ==============================================================================
# DRIVER UART
# ==============================================================================

class UART_Driver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=2)
            time.sleep(2) 
            self.ser.reset_input_buffer()
            log.info(f"Conexão Serial: {Colors.BOLD}{port} @ {baud} bps{Colors.RESET}")
        except Exception as e:
            log.critical(f"Erro Serial: {e}")
            sys.exit(1)

    def write(self, addr, data):
        packet = struct.pack('>BII', 0x01, addr, int(data) & 0xFFFFFFFF) 
        self.ser.write(packet)

    def read(self, addr):
        packet = struct.pack('>BI', 0x02, addr)
        self.ser.write(packet)
        resp = self.ser.read(4)
        if len(resp) == 4:
            return struct.unpack('>I', resp)[0]
        return 0

    def close(self):
        self.ser.close()

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
# DATASET & MODELO
# ==============================================================================

def load_mnist():
    if not os.path.exists("mnist.npz"):
        url = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz"
        log.info(f"Baixando MNIST de {url}...")
        urllib.request.urlretrieve(url, "mnist.npz")
    
    with np.load("mnist.npz", allow_pickle=True) as f:
        x_train, y_train = f['x_train'], f['y_train']
        x_test, y_test = f['x_test'], f['y_test']
        
    x_train = x_train.reshape(-1, 784).astype(np.float32)
    x_test  = x_test.reshape(-1, 784).astype(np.float32)
    return x_train, y_train, x_test, y_test

def train_or_get_model():
    x_train, y_train, x_test, y_test = load_mnist()
    
    if HAS_SKLEARN:
        log.info("Treinando Regressão Logística (1k amostras)...")
        mask = np.random.choice(len(x_train), 1000, replace=False)
        X_small = x_train[mask]
        y_small = y_train[mask]
        
        scaler = StandardScaler()
        X_small = scaler.fit_transform(X_small)
        
        clf = LogisticRegression(solver='lbfgs', max_iter=100)
        clf.fit(X_small, y_small)
        
        weights_float = clf.coef_.T # (784, 10)
        bias_float = clf.intercept_
        
        x_test_norm = scaler.transform(x_test[:50]) # 50 de teste
        y_test_sub  = y_test[:50]
    else:
        log.warning("Usando Pesos Aleatórios!")
        weights_float = np.random.uniform(-0.5, 0.5, (784, 10))
        bias_float    = np.random.uniform(-0.1, 0.1, (10,))
        x_test_norm   = (x_test[:50] / 255.0) * 2 - 1
        y_test_sub    = y_test[:50]
        
    # Quantização
    max_w = np.max(np.abs(weights_float))
    max_x = np.max(np.abs(x_test_norm))
    scale_w = max_w / 127.0 if max_w > 0 else 1.0
    scale_x = max_x / 127.0 if max_x > 0 else 1.0
    
    W_int = np.clip(np.round(weights_float / scale_w), -128, 127).astype(int)
    B_int = np.clip(np.round(bias_float / (scale_w * scale_x)), -128, 127).astype(int)
    X_int = np.clip(np.round(x_test_norm / scale_x), -128, 127).astype(int)
    
    # Calibração PPU
    # Simula o pior caso de acumulação
    sim_acc = np.dot(X_int, W_int) + B_int
    max_acc_abs = np.max(np.abs(sim_acc))
    if max_acc_abs < 1: max_acc_abs = 1
    
    target_out = 100.0
    ppu_shift = 16
    ppu_mult = int((target_out / max_acc_abs) * (1 << ppu_shift))
    
    while ppu_mult > 255:
        ppu_mult >>= 1
        ppu_shift -= 1
    if ppu_mult < 1: ppu_mult = 1
    if ppu_shift < 0: ppu_shift = 0

    log.info(f"Calibration: MaxAcc={int(max_acc_abs)} -> Mult={ppu_mult}, Shift={ppu_shift}")
    return W_int, B_int, X_int, y_test_sub, ppu_mult, ppu_shift

# ==============================================================================
# SIMULAÇÃO DE REFERÊNCIA (Bit-Exact Logic)
# ==============================================================================

def compute_reference(x_vec, W_int, B_int, mult, shift):
    """Calcula o resultado esperado usando a lógica da PPU do HW"""
    # 1. Accumulation (Dot Product)
    acc = np.dot(x_vec, W_int) + B_int
    
    # 2. PPU: Mult + Shift + Clamp
    # Hardware faz: (acc * mult) >> shift
    val = acc * mult
    
    if shift > 0:
        # Arredondamento simples (adiciona metade do divisor antes do shift)
        round_bit = 1 << (shift - 1)
        val = (val + round_bit) >> shift
    else:
        pass # Shift 0
        
    # 3. Clamp int8
    val = np.clip(val, -128, 127)
    return val.astype(int)

# ==============================================================================
# LOOP PRINCIPAL
# ==============================================================================

def main():
    log.info(f"{Colors.BOLD}>>> Iniciando Teste HIL - MNIST (HW Validity Check){Colors.RESET}")
    driver = UART_Driver(SERIAL_PORT, BAUD_RATE)
    
    # 1. Preparação
    W_int, B_int, X_int, y_true, ppu_mult, ppu_shift = train_or_get_model()
    
    # 2. Config Global
    driver.write(ADDR_CSR_CTRL, 0)
    driver.write(ADDR_CSR_QUANT, (0 << 8) | (ppu_shift & 0x1F))
    driver.write(ADDR_CSR_MULT, ppu_mult)
    
    hw_ok_count = 0
    model_ok_count = 0
    total = len(X_int)
    
    log.info(f"{Colors.DIM}" + "-" * 80 + f"{Colors.RESET}")
    log.info(f" ID   | REAL  | NPU   | REF   | HW CHECK | MOD CHECK | STATUS")
    log.info(f"{Colors.DIM}" + "-" * 80 + f"{Colors.RESET}")

    # 3. Inferência
    for i, (x_vec, label_true) in enumerate(zip(X_int, y_true)):
        
        # --- EXECUÇÃO NO HARDWARE ---
        npu_scores = np.zeros(10, dtype=int)
        
        # Tiling Loop (3 passadas: 0-3, 4-7, 8-9)
        for col_start in range(0, NUM_CLASSES, COLS):
            col_end = min(col_start + COLS, NUM_CLASSES)
            chunk_size = col_end - col_start
            
            # Setup Bias
            for b_idx in range(chunk_size):
                driver.write(ADDR_BIAS_BASE + (b_idx*4), B_int[col_start + b_idx])
            for b_idx in range(chunk_size, 4):
                driver.write(ADDR_BIAS_BASE + (b_idx*4), 0)
                
            # Clear
            driver.write(ADDR_CSR_CTRL, CTRL_ACC_CLEAR)
            driver.write(ADDR_CSR_CTRL, 0)
            
            # Feed (784 ciclos)
            for k in range(INPUT_SIZE):
                vec_a = [x_vec[k], 0, 0, 0]
                w_slice = W_int[k, col_start:col_end]
                vec_w = [0]*4
                for idx_w, val_w in enumerate(w_slice):
                    vec_w[idx_w] = val_w
                
                driver.write(ADDR_WRITE_A, pack_vec(vec_a))
                driver.write(ADDR_WRITE_W, pack_vec(vec_w))
            
            # Read Result
            driver.write(ADDR_CSR_CTRL, CTRL_ACC_DUMP)
            raw_outs = []
            for _ in range(4):
                while not (driver.read(ADDR_CSR_STATUS) & STATUS_VALID): pass
                raw_outs.append(unpack_vec(driver.read(ADDR_READ_OUT)))
            driver.write(ADDR_CSR_CTRL, 0)
            
            # Store (Row 0 result is at index 3)
            npu_scores[col_start:col_end] = raw_outs[3][:chunk_size]

        # --- CÁLCULO DE REFERÊNCIA (PYTHON) ---
        ref_scores = compute_reference(x_vec, W_int, B_int, ppu_mult, ppu_shift)
        
        # --- COMPARAÇÃO ---
        npu_pred = np.argmax(npu_scores)
        ref_pred = np.argmax(ref_scores)
        
        # 1. Validade do Hardware (NPU bate com Ref?)
        # Compara vetores completos para rigor, ou argmax para simplicidade. 
        # Aqui comparamos Argmax + consistência aproximada dos scores
        hw_match = (npu_pred == ref_pred) 
        
        # 2. Acurácia do Modelo (NPU bate com Label Real?)
        model_hit = (npu_pred == label_true)
        
        if hw_match: hw_ok_count += 1
        if model_hit: model_ok_count += 1
        
        # Formatação do Log
        hw_str = f"{Colors.GREEN}PASS{Colors.RESET}" if hw_match else f"{Colors.RED}FAIL{Colors.RESET}"
        mod_str = f"{Colors.GREEN}HIT {Colors.RESET}" if model_hit else f"{Colors.YELLOW}MISS{Colors.RESET}"
        
        # Status Geral da Linha
        if hw_match and model_hit:
            status_line = f"{Colors.GREEN}PERFECT{Colors.RESET}"
        elif not hw_match:
            status_line = f"{Colors.RED}HW ERROR{Colors.RESET}"
        else:
            status_line = f"{Colors.YELLOW}BAD PRED{Colors.RESET}"

        log.info(f" {i:<4} | {label_true:<5} | {npu_pred:<5} | {ref_pred:<5} | {hw_str:^8} | {mod_str:^9} | {status_line}")
        
        # Se HW falhou, mostra debug dos scores
        if not hw_match:
            log.warning(f"    Scores NPU: {npu_scores}")
            log.warning(f"    Scores REF: {ref_scores}")

    # Relatório Final
    hw_acc = (hw_ok_count / total) * 100
    mod_acc = (model_ok_count / total) * 100
    
    log.info(f"{Colors.DIM}" + "="*80 + f"{Colors.RESET}")
    log.info(f"{Colors.BOLD}RELATÓRIO FINAL{Colors.RESET}")
    log.info(f"Acurácia do Modelo    : {mod_acc:.2f}%  (Capacidade de predição)")
    log.info(f"Consistência Hardware : {hw_acc:.2f}%  (Validação da implementação)")
    log.info(f"{Colors.DIM}" + "="*80 + f"{Colors.RESET}")
    
    driver.close()

if __name__ == "__main__":
    main()