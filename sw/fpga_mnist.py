# ==============================================================================
# File: fpga_mnist.py
# ==============================================================================

import serial
import time
import struct
import sys
import os
import urllib.request
import numpy as np
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÃO DE HARDWARE
# ==============================================================================

SERIAL_PORT = 'COM6'  
BAUD_RATE   = 921600

# Mapa de Registradores
REG_STATUS     = 0x00
REG_CMD        = 0x04
REG_CONFIG     = 0x08
REG_WRITE_W    = 0x10 
REG_WRITE_A    = 0x14 
REG_READ_OUT   = 0x18 
REG_QUANT_CFG  = 0x40
REG_QUANT_MULT = 0x44
REG_BIAS_BASE  = 0x80

# Flags
STATUS_DONE      = (1 << 1)
STATUS_OUT_VALID = (1 << 3)

# Bits de Comando
CMD_RST_DMA_PTRS = (1 << 0)
CMD_START        = (1 << 1)
CMD_ACC_CLEAR    = (1 << 2)
CMD_RST_W_RD     = (1 << 4)
CMD_RST_I_RD     = (1 << 5)
CMD_RST_WR_W     = (1 << 6)
CMD_RST_WR_I     = (1 << 7)

# ==============================================================================
# LOGGING SYSTEM
# ==============================================================================
class Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    GREY    = "\033[90m"

def get_timestamp(): 
    return datetime.now().strftime('%H:%M:%S')

def log_info(msg):    
    print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.CYAN}[INFO]{Colors.RESET}    {msg}")

def log_success(msg): 
    print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.GREEN}[PASS]{Colors.RESET}    {msg}")

def log_error(msg):   
    print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.RED}[FAIL]{Colors.RESET}    {msg}")

def log_header(msg):  
    print(f"\n{Colors.YELLOW}{'='*85}\n {msg}\n{'='*85}{Colors.RESET}")

# ==============================================================================
# DRIVER NPU (MAX SPEED)
# ==============================================================================
class NPUDriver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=2.0)
            self.ser.reset_input_buffer()
            log_success(f"FPGA Conectada: {port} @ {baud} bps")
        except Exception as e:
            log_error(f"Erro Serial: {e}")
            sys.exit(1)

    def close(self): self.ser.close()

    def write_reg(self, addr, data):
        self.ser.write(struct.pack('>B I I', 0x01, addr, int(data) & 0xFFFFFFFF))

    def read_reg(self, addr):
        self.ser.write(struct.pack('>B I', 0x02, addr))
        resp = self.ser.read(4)
        return struct.unpack('>I', resp)[0] if len(resp) == 4 else 0

    def wait_done(self):
        while not (self.read_reg(REG_STATUS) & STATUS_DONE): pass

    def read_results(self):
        res = []
        for _ in range(4):
            while not (self.read_reg(REG_STATUS) & STATUS_OUT_VALID): pass
            val = self.read_reg(REG_READ_OUT)
            res.append(self.unpack_int8(val))
            self.read_reg(REG_STATUS) 
        return res[::-1] 

    def pack_int8(self, v): 
        return ((int(v[0]) & 0xFF)) | \
               ((int(v[1]) & 0xFF) << 8) | \
               ((int(v[2]) & 0xFF) << 16) | \
               ((int(v[3]) & 0xFF) << 24)
    
    def unpack_int8(self, p):
        return [(p >> (i*8) & 0xFF) - 256 if (p >> (i*8) & 0xFF) & 0x80 else (p >> (i*8) & 0xFF) for i in range(4)]

# ==============================================================================
# DATASET & MODELO (MNIST)
# ==============================================================================
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler, MinMaxScaler
except ImportError: sys.exit("Instale sklearn")

def load_mnist():
    if not os.path.exists("mnist.npz"):
        url = "https://storage.googleapis.com/tensorflow/tf-keras-datasets/mnist.npz"
        log_info("Baixando MNIST...")
        urllib.request.urlretrieve(url, "mnist.npz")
    
    with np.load("mnist.npz", allow_pickle=True) as f:
        x_train, y_train = f['x_train'], f['y_train']
        x_test, y_test = f['x_test'], f['y_test']
        
    x_train = x_train.reshape(-1, 784).astype(np.float32)
    x_test  = x_test.reshape(-1, 784).astype(np.float32)
    return x_train, y_train, x_test, y_test

def get_quantized_model():
    log_info("Treinando Modelo (Regressão Logística)...")
    x_train, y_train, x_test, y_test = load_mnist()
    
    mask = np.random.choice(len(x_train), 2000, replace=False)
    X_small, y_small = x_train[mask], y_train[mask]
    
    scaler = MinMaxScaler(feature_range=(-1, 1))
    X_small = scaler.fit_transform(X_small)
    
    clf = LogisticRegression(solver='lbfgs', max_iter=500)
    clf.fit(X_small, y_small)
    
    x_test_norm = scaler.transform(x_test[:50])
    y_test_sub  = y_test[:50]
    
    max_w = np.max(np.abs(clf.coef_))
    scale_w = 127.0 / max_w
    scale_x = 127.0 
    
    W_float = clf.coef_.T 
    B_float = clf.intercept_
    
    W_int = np.clip(np.round(W_float * scale_w), -128, 127).astype(int)
    X_int = np.clip(np.round(x_test_norm * scale_x), -128, 127).astype(int)
    B_int = np.clip(np.round(B_float * scale_w * scale_x), -100000, 100000).astype(int)
    
    log_info("Calibrando Quantização PPU...")
    sim_acc = np.dot(X_int, W_int) + B_int
    max_acc_real = np.max(np.abs(sim_acc))
    
    target_acc = max_acc_real * 1.1 
    best_shift = 16
    target_mult = (127.0 / target_acc) * (1 << best_shift)
    best_mult = int(round(target_mult))
    if best_mult < 1: best_mult = 1
    
    log_info(f"PPU Config: Mult={best_mult}, Shift={best_shift} (MaxAcc={max_acc_real:.0f})")
    
    return W_int, B_int, X_int, y_test_sub, best_mult, best_shift

# ==============================================================================
# GOLDEN MODEL
# ==============================================================================
def model_ppu(acc, bias, mult, shift):
    val = (acc + bias) * mult
    if shift > 0: val = (val + (1 << (shift - 1))) >> shift
    return max(-128, min(127, int(val)))

def compute_golden_tile(x_vec, w_tile, b_tile, mult, shift):
    scores = []
    for col in range(w_tile.shape[1]):
        acc = np.dot(x_vec, w_tile[:, col])
        scores.append(model_ppu(acc, b_tile[col], mult, shift))
    return scores

# ==============================================================================
# MAIN
# ==============================================================================
def main():

    print("\n")
    print(f"\n{Colors.CYAN}  ███╗   ███╗███╗   ██╗██╗███████╗████████╗{Colors.RESET}")
    print(f"{Colors.CYAN}  ████╗ ████║████╗  ██║██║██╔════╝╚══██╔══╝{Colors.RESET}")
    print(f"{Colors.CYAN}  ██╔████╔██║██╔██╗ ██║██║███████╗   ██║   {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║╚██╔╝██║██║╚██╗██║██║╚════██║   ██║   {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║ ╚═╝ ██║██║ ╚████║██║███████║   ██║   {Colors.RESET}")
    print(f"{Colors.CYAN}  ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝   ╚═╝   {Colors.RESET}")
    print("\n")                          

    driver = NPUDriver(SERIAL_PORT, BAUD_RATE)
    
    try:
        W_int, B_int, X_int, y_true, q_mult, q_shift = get_quantized_model()
        K_DIM = 784 
        
        driver.write_reg(REG_QUANT_MULT, q_mult)
        driver.write_reg(REG_QUANT_CFG, q_shift)
        
        log_header(f"VALIDAÇÃO MNIST ({len(X_int)} Amostras) - MODO TILING")
        print(f"{Colors.DIM}{'-'*85}{Colors.RESET}")
        print(f" {'ID':<4} | {'REAL':<4} | {'HW':<4} | {'SW':<4} | {'HW OK?':<8} | {'ACC OK?':<8} | {'LATÊNCIA'}")
        print(f"{Colors.DIM}{'-'*85}{Colors.RESET}")

        stats = {'hw_match': 0, 'acc': 0, 'total': len(X_int)}
        total_time = 0

        for idx, (x_vec, label) in enumerate(zip(X_int, y_true)):
            start_t = time.time()
            
            # Reset Geral
            driver.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
            
            # 1. Carrega INPUT (Uma única vez!)
            # Isso envia 784 * 4 bytes = ~3KB pela serial
            for k in range(K_DIM):
                driver.write_reg(REG_WRITE_A, driver.pack_int8([x_vec[k], 0, 0, 0]))

            hw_scores = []
            
            # 2. Processa por Lotes (Classes 0-3, 4-7, 8-9)
            # Reusa o input carregado acima, trocando apenas os pesos
            for chunk_start in [0, 4, 8]:
                chunk_end = min(chunk_start + 4, 10)
                chunk_size = chunk_end - chunk_start
                
                # Bias
                for b in range(chunk_size):
                    driver.write_reg(REG_BIAS_BASE + b*4, int(B_int[chunk_start+b]))
                for b in range(chunk_size, 4):
                    driver.write_reg(REG_BIAS_BASE + b*4, 0)
                
                # Reset apenas ponteiro de Escrita de Pesos
                driver.write_reg(REG_CMD, CMD_RST_WR_W) 
                
                # Carga Pesos
                for k in range(K_DIM):
                    w_row = W_int[k, chunk_start:chunk_end]
                    w_padded = np.zeros(4, dtype=int)
                    if len(w_row) > 0: w_padded[:len(w_row)] = w_row
                    driver.write_reg(REG_WRITE_W, driver.pack_int8(w_padded))
                
                # Dispara NPU (Resetando ponteiros de LEITURA para ler do início)
                driver.write_reg(REG_CONFIG, K_DIM)
                driver.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
                driver.wait_done()
                
                res = driver.read_results()
                hw_scores.extend(res[0][:chunk_size])
            
            elapsed = (time.time() - start_t) * 1000
            total_time += elapsed
            
            # Validação
            sw_scores = compute_golden_tile(x_vec, W_int, B_int, q_mult, q_shift)
            hw_pred = np.argmax(hw_scores)
            sw_pred = np.argmax(sw_scores)
            
            is_match = (list(hw_scores) == list(sw_scores))
            is_correct = (hw_pred == label)
            
            if is_match: stats['hw_match'] += 1
            if is_correct: stats['acc'] += 1
            
            match_str = f"{Colors.GREEN}YES{Colors.RESET}" if is_match else f"{Colors.RED}NO{Colors.RESET}"
            acc_str   = f"{Colors.GREEN}YES{Colors.RESET}" if is_correct else f"{Colors.RED}NO{Colors.RESET}"
            
            print(f" {idx:<4} | {label:<4} | {Colors.BOLD}{hw_pred:<4}{Colors.RESET} | {sw_pred:<4} | {match_str:<17} | {acc_str:<17} | {elapsed:.0f}ms")

        # Relatório Final
        hw_pct = (stats['hw_match'] / stats['total']) * 100
        acc_pct = (stats['acc'] / stats['total']) * 100
        avg_lat = total_time/len(X_int)
        
        print(f"\n{Colors.YELLOW}{'='*85}")
        print(f" RELATÓRIO FINAL (MNIST)")
        print(f"{'='*85}{Colors.RESET}")
        print(f" Consistência HW (Bit-Exact) : {Colors.BOLD}{hw_pct:>6.2f}%{Colors.RESET}")
        print(f" Acurácia do Modelo          : {Colors.BOLD}{acc_pct:>6.2f}%{Colors.RESET}")
        print(f" Latência Média              : {Colors.CYAN}{avg_lat:>6.0f} ms{Colors.RESET}")
        print(f"{Colors.YELLOW}{'='*85}{Colors.RESET}")

    except KeyboardInterrupt:
        print("\n 🛑 Cancelado pelo usuário!")
    finally:
        driver.close()

if __name__ == "__main__":
    main()