# ==============================================================================
# File: fpga_iris.py
# ==============================================================================
# Descrição: Driver HIL para Iris Dataset 
# ==============================================================================

import serial
import time
import struct
import math
import sys
import os
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
    logger = logging.getLogger("IRIS_HIL")
    logger.setLevel(logging.INFO)
    if logger.hasHandlers(): logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)
    
    log_file = os.path.join("build", "iris_test_report.log")
    fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(fh)
    return logger

log = setup_logger()

try:
    from sklearn import datasets
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
except ImportError:
    log.critical("SKLEARN ausente. Instale: pip install scikit-learn numpy")
    sys.exit(1)

# ==============================================================================
# CONFIGURAÇÃO DE HARDWARE
# ==============================================================================

SERIAL_PORT = 'COM6'  
BAUD_RATE   = 921600

ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_FIFO_W     = 0x10
ADDR_FIFO_ACT   = 0x14
ADDR_FIFO_OUT   = 0x18
ADDR_BIAS_BASE  = 0x20 

CTRL_RELU       = 1  
CTRL_LOAD       = 2  
CTRL_ACC_CLEAR  = 4  
CTRL_ACC_DUMP   = 8  

ROWS = 4
COLS = 4

# ==============================================================================
# CLASSES E UTILITÁRIOS
# ==============================================================================

class UART_Driver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=2)
            time.sleep(2) 
            self.ser.reset_input_buffer()
            log.info(f"Conexão Serial estabelecida: {Colors.BOLD}{port} @ {baud} bps{Colors.RESET}")
        except Exception as e:
            log.critical(f"Falha na conexão serial: {e}")
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
        else:
            log.warning(f"Timeout lendo addr {hex(addr)}")
            return 0

    def close(self):
        self.ser.close()
        log.info("Conexão Serial encerrada.")

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
    log.info("Treinando modelo LogisticRegression no dataset Iris...")
    iris = datasets.load_iris()
    X = iris.data; y = iris.target
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)
    
    clf = LogisticRegression(random_state=0, C=1.0)
    clf.fit(X_train, y_train)
    
    # Adaptação para NPU 4x4
    # Iris tem 3 classes -> Precisamos de 3 neurônios (colunas)
    # A NPU tem 4 colunas. A quarta coluna será preenchida com zeros (padding).
    weights_pad = np.zeros((4,4))
    
    # clf.coef_ é (3, 4). Transpomos para (4, 3) para mapear Features nas Linhas e Classes nas Colunas.
    weights_core = clf.coef_.T 
    weights_pad[:, :3] = weights_core 
    
    bias_pad = np.zeros(4)
    bias_pad[:3] = clf.intercept_
    
    # Quantização
    max_w = np.max(np.abs(weights_pad))
    max_x = np.max(np.abs(X_test))
    scale_w = max_w / 127.0 if max_w > 0 else 1.0
    scale_x = max_x / 127.0 if max_x > 0 else 1.0
    
    W_int = quantize_matrix(weights_pad, scale_w)
    B_int = quantize_bias(bias_pad, scale_w, scale_x)
    X_test_int = quantize_matrix(X_test, scale_x)
    
    # Calibração PPU (Estimativa conservadora)
    max_acc_val = (127 * 127 * ROWS) + np.max(np.abs(B_int))
    ppu_mult = 120 
    target_ratio = (max_acc_val * ppu_mult) / 127.0
    ppu_shift = int(math.ceil(math.log2(target_ratio))) if target_ratio > 1 else 0
    if ppu_shift > 31: ppu_shift = 31
    
    log.info(f"Parâmetros de Quantização: Mult={ppu_mult}, Shift={ppu_shift}")
    return W_int, B_int, X_test_int, y_test, ppu_mult, ppu_shift

# ==============================================================================
# MAIN TEST LOOP
# ==============================================================================

def main():
    log.info(f"{Colors.BOLD}>>> Iniciando Suite de Testes HIL - IRIS{Colors.RESET}")
    driver = UART_Driver(SERIAL_PORT, BAUD_RATE)
    
    # Preparação
    data = get_iris_model()
    if data is None: return
    W_int, B_int, X_test, y_true, ppu_mult, ppu_shift = data

    # Configuração NPU
    log.info("Configurando NPU (PPU, Bias, Pesos)...")
    driver.write(ADDR_CSR_CTRL, 0)
    driver.write(ADDR_CSR_QUANT, (0 << 8) | (ppu_shift & 0x1F))
    driver.write(ADDR_CSR_MULT, ppu_mult)

    # Envia Bias
    for i, b in enumerate(B_int):
        driver.write(ADDR_BIAS_BASE + (i*4), b)

    # Envia Pesos
    driver.write(ADDR_CSR_CTRL, CTRL_LOAD) 
    for r in reversed(range(ROWS)):
        packed = pack_vec(W_int[r, :])
        driver.write(ADDR_FIFO_W, packed)

    # Inferência
    log.info("Iniciando Inferência...")
    
    # Configura modo de execução (Clear antes, Dump depois)
    # Como Iris cabe em um único passo, podemos deixar fixo.
    driver.write(ADDR_CSR_CTRL, CTRL_ACC_CLEAR | CTRL_ACC_DUMP)
    
    correct_count = 0
    total_time = 0
    
    # Cabeçalho da Tabela
    log.info(f"{Colors.DIM}" + "-" * 65 + f"{Colors.RESET}")
    header = f"{'ID':<5} | {'REAL':<5} | {'PRED':<5} | {'SCORES (Cls 0,1,2)':<25} | {'STATUS'}"
    log.info(f"{Colors.BOLD}{header}{Colors.RESET}")
    log.info(f"{Colors.DIM}" + "-" * 65 + f"{Colors.RESET}")
    
    for idx, (x_vec, y_real) in enumerate(zip(X_test, y_true)):
        start_time = time.time()
        
        # Envia Entrada
        driver.write(ADDR_FIFO_ACT, pack_vec(x_vec))
        
        # Polling
        while True:
            status = driver.read(ADDR_CSR_STATUS)
            if (status >> 3) & 1: break
        
        # Lê Resultado
        res_packed = driver.read(ADDR_FIFO_OUT)
        scores = unpack_vec(res_packed)
        
        # Analisa Tempo
        elapsed = time.time() - start_time
        total_time += elapsed
        
        # Classificação (Ignora o 4° valor que é padding)
        pred = np.argmax(scores[:3])
        is_correct = (pred == y_real)
        
        if is_correct:
            correct_count += 1
            status_str = f"{Colors.GREEN}OK{Colors.RESET}"
            row_color = ""
            log_level = logging.INFO
        else:
            status_str = f"{Colors.RED}FAIL{Colors.RESET}"
            row_color = Colors.YELLOW
            log_level = logging.WARNING
            
        scores_str = f"[{scores[0]:>3}, {scores[1]:>3}, {scores[2]:>3}]"
        
        # Log da linha
        row_str = (f"{row_color}{idx+1:<5}{Colors.RESET} | "
                   f"{y_real:<5} | "
                   f"{row_color}{pred:<5}{Colors.RESET} | "
                   f"{scores_str:<25} | "
                   f"{status_str}")
        log.log(log_level, row_str)

    # 4. Relatório Final
    acc = (correct_count / len(X_test)) * 100
    avg_time = (total_time / len(X_test)) * 1000 # em ms
    final_color = Colors.GREEN if acc >= 90.0 else Colors.RED
    
    log.info(f"{Colors.DIM}" + "="*65 + f"{Colors.RESET}")
    log.info(f"{Colors.BOLD}RELATÓRIO FINAL DE VALIDAÇÃO (IRIS){Colors.RESET}")
    log.info(f"Total Amostras  : {len(X_test)}")
    log.info(f"Acertos         : {correct_count}")
    log.info(f"Erros           : {len(X_test) - correct_count}")
    log.info(f"Acurácia        : {final_color}{acc:.2f}%{Colors.RESET}")
    log.info("-" * 30)
    log.info(f"Tempo Médio/Img : {avg_time:.2f} ms") 
    log.info(f"{Colors.DIM}" + "="*65 + f"{Colors.RESET}")
    
    driver.close()

if __name__ == "__main__":
    main()