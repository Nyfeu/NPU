# ==============================================================================
# File: fpga_mnist.py
# Descrição: Driver HIL para Reconhecimento de Digitos (MNIST)
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

# --- CONFIGURAÇÃO DE LOGGING E CORES ---

# Códigos ANSI para cores no terminal
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

# Formatter Customizado para o Console (Colorido)
class ColoredFormatter(logging.Formatter):
    # Formato: [HORA] [NIVEL] Mensagem
    # Ex: 19:30:01 | INFO    | Mensagem...
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

# Setup do Logger
def setup_logger():
    # Suprime FutureWarnings
    warnings.simplefilter(action='ignore', category=FutureWarning)
    
    logger = logging.getLogger("FPGA_HIL")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.hasHandlers():
        logger.handlers.clear()

    # Handler 1: Console 
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)

    # Handler 2: Arquivo (Texto auditoria)
    log_file = os.path.join("build", "hil_test_report.log") 
    fh = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    fh.setLevel(logging.INFO)
    plain_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
    fh.setFormatter(plain_formatter)
    logger.addHandler(fh)

    return logger

log = setup_logger()

try:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
except ImportError:
    log.error("Dependências ausentes. Execute: pip install numpy scikit-learn pyserial")
    sys.exit(1)

# ==============================================================================
# CONFIGURAÇÃO DE HARDWARE
# ==============================================================================

SERIAL_PORT = 'COM6'  
BAUD_RATE   = 921600
TEST_SIZE   = 50      

# Mapa de Memória NPU
ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_FIFO_W     = 0x10
ADDR_FIFO_ACT   = 0x14
ADDR_FIFO_OUT   = 0x18
ADDR_BIAS_BASE  = 0x20 

# Flags
CTRL_RELU       = (1 << 0)
CTRL_LOAD       = (1 << 1)
CTRL_ACC_CLEAR  = (1 << 2) 
CTRL_ACC_DUMP   = (1 << 3) 

ROWS = 4
COLS = 4

# ==============================================================================
# CLASSES E UTILITÁRIOS
# ==============================================================================

class UART_Driver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=1)
            time.sleep(2) # Estabilidade pós-reset
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
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
        return None
            
    def close(self):
        self.ser.close()
        log.info("Conexão Serial encerrada.")

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

def get_mnist_data(n_tests=100):
    file_path = "mnist.npz"
    url = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz"

    if not os.path.exists(file_path):
        log.info("Baixando dataset MNIST...")
        try: urllib.request.urlretrieve(url, file_path)
        except Exception as e:
            log.error(f"Erro no download: {e}")
            return None
    
    with np.load(file_path, allow_pickle=True) as f:
        x_train, y_train = f['x_train'], f['y_train']
        x_test, y_test = f['x_test'], f['y_test']
    
    # Reduz dataset para treinamento rápido do modelo de referência
    X = np.concatenate([x_train, x_test]).reshape(-1, 784).astype(float)
    y = np.concatenate([y_train, y_test]).astype(int)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=2000, test_size=n_tests, random_state=42)
    
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)
    
    log.info("Treinando modelo de referência (LogisticRegression)...")
    clf = LogisticRegression(C=0.01, solver='lbfgs', max_iter=100)
    clf.fit(X_train, y_train)
    
    # Quantização
    weights = clf.coef_
    bias = clf.intercept_
    
    max_w = np.max(np.abs(weights))
    max_x = np.max(np.abs(X_test))
    scale_w = max_w / 127.0 if max_w > 0 else 1.0
    scale_x = max_x / 127.0 if max_x > 0 else 1.0
    
    W_int = np.clip(np.round(weights / scale_w), -128, 127).astype(int)
    X_test_int = np.clip(np.round(X_test / scale_x), -128, 127).astype(int)
    B_int = np.round(bias / (scale_w * scale_x)).astype(int)
    
    return W_int, B_int, X_test_int, y_test

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    log.info(f"{Colors.BOLD}>>> Iniciando Suite de Testes HIL - MNIST{Colors.RESET}")
    driver = UART_Driver(SERIAL_PORT, BAUD_RATE)
    
    # Preparação
    data = get_mnist_data(n_tests=TEST_SIZE)
    if data is None: return
    W_int, B_int, X_test, y_true = data
    
    # Calibração
    log.info("Calculando parâmetros de quantização (PPU)...")
    raw_outputs = np.dot(W_int, X_test.T) + B_int[:, None]
    max_observed = np.max(np.abs(raw_outputs)) * 1.2 
    
    target_ratio = max_observed / 127.0
    ppu_shift = int(math.ceil(math.log2(target_ratio))) if target_ratio > 1 else 0
    ppu_mult = 1
    
    log.info(f"Configuração PPU -> Mult: {ppu_mult}, Shift: {ppu_shift}")
    
    # Configuração Inicial FPGA
    driver.write(ADDR_CSR_QUANT, (0 << 8) | (ppu_shift & 0x1F))
    driver.write(ADDR_CSR_MULT, ppu_mult)
    driver.write(ADDR_CSR_CTRL, 0)

    # Loop de Inferência
    NUM_CLASSES = 10
    NUM_FEATURES = 784
    correct_count = 0
    total_time = 0
    
    # Cabeçalho da Tabela
    log.info(f"{Colors.DIM}" + "-" * 65 + f"{Colors.RESET}")
    header = f"{'ID':<5} | {'REAL':<5} | {'PRED':<5} | {'CONF':<8} | {'TIME(s)':<8} | {'STATUS'}"
    log.info(f"{Colors.BOLD}{header}{Colors.RESET}")
    log.info(f"{Colors.DIM}" + "-" * 65 + f"{Colors.RESET}")
    
    for img_idx, input_vec in enumerate(X_test):
        final_scores = np.zeros(NUM_CLASSES, dtype=int)
        start_time = time.time()
        
        # --- INICIO DA INFERÊNCIA NO HARDWARE ---

        for col_start in range(0, NUM_CLASSES, COLS):
            # Envia Bias
            current_bias = B_int[col_start : col_start + COLS]
            if len(current_bias) < COLS: 
                current_bias = np.pad(current_bias, (0, COLS - len(current_bias)))
            for i, b in enumerate(current_bias):
                driver.write(ADDR_BIAS_BASE + (i*4), b)
            
            # Loop Profundidade
            for depth_start in range(0, NUM_FEATURES, ROWS):
                c_end = min(col_start + COLS, NUM_CLASSES)
                d_end = min(depth_start + ROWS, NUM_FEATURES)
                
                # Pesos e Entrada
                block = W_int[col_start:c_end, depth_start:d_end].T
                w_tile = np.zeros((ROWS, COLS), dtype=int)
                w_tile[:block.shape[0], :block.shape[1]] = block
                
                x_chunk = input_vec[depth_start : d_end]
                if len(x_chunk) < ROWS: 
                    x_chunk = np.pad(x_chunk, (0, ROWS - len(x_chunk)))
                
                # Carga
                driver.write(ADDR_CSR_CTRL, CTRL_LOAD)
                for r in reversed(range(ROWS)):
                    driver.write(ADDR_FIFO_W, pack_vec(w_tile[r, :]))
                
                # Controle
                ctrl_val = 0
                if depth_start == 0: ctrl_val |= CTRL_ACC_CLEAR
                if depth_start + ROWS >= NUM_FEATURES: ctrl_val |= CTRL_ACC_DUMP
                
                driver.write(ADDR_CSR_CTRL, ctrl_val)
                driver.write(ADDR_FIFO_ACT, pack_vec(x_chunk))
            
            # Polling
            while True:
                status = driver.read(ADDR_CSR_STATUS)
                if status and ((status >> 3) & 1): break
            
            val = driver.read(ADDR_FIFO_OUT)
            scores = unpack_vec(val)
            limit = min(COLS, NUM_CLASSES - col_start)
            final_scores[col_start : col_start + limit] = scores[:limit]

        # --- FIM DA INFERÊNCIA ---

        elapsed = time.time() - start_time
        total_time += elapsed
        
        pred = np.argmax(final_scores)
        score_val = final_scores[pred]
        real = y_true[img_idx]
        
        is_correct = (pred == real)
        
        # FORMATAÇÃO DA LINHA 
        if is_correct:
            correct_count += 1
            status_str = f"{Colors.GREEN}OK{Colors.RESET}"
            row_color = "" 
            log_level = logging.INFO
        else:
            status_str = f"{Colors.RED}FAIL{Colors.RESET}"
            row_color = Colors.YELLOW 
            log_level = logging.WARNING
            
        # Monta a linha
        # ID | REAL | PRED | CONF | TIME | STATUS
        row_str = (f"{row_color}{img_idx+1:<5}{Colors.RESET} | "
                   f"{real:<5} | "
                   f"{row_color}{pred:<5}{Colors.RESET} | "
                   f"{score_val:<8} | "
                   f"{elapsed:<8.2f} | "
                   f"{status_str}")
        
        log.log(log_level, row_str)

    # Relatório Final
    acc = (correct_count / len(X_test)) * 100
    avg_time = total_time / len(X_test)
    
    # Cor do relatório final baseada na acurácia
    final_color = Colors.GREEN if acc >= 90.0 else Colors.RED
    
    log.info(f"{Colors.DIM}" + "="*65 + f"{Colors.RESET}")
    log.info(f"{Colors.BOLD}RELATÓRIO FINAL DE VALIDAÇÃO (HIL){Colors.RESET}")
    log.info(f"Total Amostras  : {len(X_test)}")
    log.info(f"Acertos         : {correct_count}")
    log.info(f"Erros           : {len(X_test) - correct_count}")
    log.info(f"Acurácia        : {final_color}{acc:.2f}%{Colors.RESET}")
    log.info(f"{Colors.DIM}" + "-" * 30 + f"{Colors.RESET}")
    log.info(f"Tempo Total     : {total_time:.2f} s")
    log.info(f"Tempo Médio/Img : {avg_time:.2f} s")
    log.info(f"{Colors.DIM}" + "="*65 + f"{Colors.RESET}")
    
    driver.close()

if __name__ == "__main__":
    main()