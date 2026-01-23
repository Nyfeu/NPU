# ==============================================================================
# File: fpga_iris.py
# ==============================================================================

import serial
import time
import struct
import sys
import numpy as np
from datetime import datetime
import warnings

# ==============================================================================
# CONFIGURAÇÃO
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

STATUS_DONE      = (1 << 1)
STATUS_OUT_VALID = (1 << 3)

CMD_RST_DMA_PTRS = (1 << 0)
CMD_START        = (1 << 1)
CMD_ACC_CLEAR    = (1 << 2)
CMD_RST_W_RD     = (1 << 4)
CMD_RST_I_RD     = (1 << 5)
CMD_RST_WR_W     = (1 << 6)
CMD_RST_WR_I     = (1 << 7)

# ==============================================================================
# SISTEMA DE LOG E CORES
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

def get_timestamp(): return datetime.now().strftime('%H:%M:%S')

def log_info(msg):    print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.CYAN}[INFO]{Colors.RESET}    {msg}")
def log_success(msg): print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.GREEN}[PASS]{Colors.RESET}    {msg}")
def log_error(msg):   print(f"{Colors.GREY}[{get_timestamp()}]{Colors.RESET} {Colors.RED}[FAIL]{Colors.RESET}    {msg}")
def log_header(msg):  print(f"\n{Colors.YELLOW}{'='*80}\n {msg}\n{'='*80}{Colors.RESET}")

# ==============================================================================
# DRIVER NPU
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
        time.sleep(0.0001)

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
            self.read_reg(REG_STATUS) # Bus Toggling
        return res[::-1] # Row 0..3

    def pack_int8(self, v): 
        return sum(((int(x) & 0xFF) << (i*8)) for i, x in enumerate(v))
    
    def unpack_int8(self, p):
        return [(p >> (i*8) & 0xFF) - 256 if (p >> (i*8) & 0xFF) & 0x80 else (p >> (i*8) & 0xFF) for i in range(4)]

# ==============================================================================
# GOLDEN MODEL (SOFTWARE)
# ==============================================================================
def clamp_int8(val): return max(-128, min(127, int(val)))

def model_ppu(acc, bias, mult, shift):
    val = acc + bias
    val = val * mult
    if shift > 0: val = (val + (1 << (shift - 1))) >> shift
    return clamp_int8(val)

def compute_golden(input_vec_4, weights_4x4, bias_vec_4, mult, shift):
    sw_scores = []
    for cls_idx in range(4): # 4 colunas output (3 classes reais + 1 lixo)
        acc = sum(input_vec_4[k] * weights_4x4[k][cls_idx] for k in range(4))
        sw_scores.append(model_ppu(acc, bias_vec_4[cls_idx], mult, shift))
    return sw_scores

# ==============================================================================
# DATA SCIENCE
# ==============================================================================
try:
    from sklearn import datasets
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
except ImportError: sys.exit("Instale sklearn")

def get_quantized_model():
    log_info("Treinando Modelo...")
    iris = datasets.load_iris()
    X_train, X_test, y_train, y_test = train_test_split(iris.data, iris.target, test_size=0.3, random_state=42)
    
    scaler = StandardScaler().fit(X_train)
    X_test_scaled = scaler.transform(X_test)
    clf = LogisticRegression(random_state=0).fit(scaler.transform(X_train), y_train)
    
    # Mapping
    W_pad = np.zeros((4,4)); W_pad[:, :3] = clf.coef_.T 
    B_pad = np.zeros(4); B_pad[:3] = clf.intercept_
    
    # Quantization
    max_val = max(np.max(np.abs(W_pad)), np.max(np.abs(X_test_scaled)))
    scale = 127.0 / max_val
    W_int = np.round(W_pad * scale).astype(int)
    X_int = np.round(X_test_scaled * scale).astype(int)
    B_int = np.round(B_pad * scale * scale).astype(int)
    
    # Auto-Calibration
    max_acc_theor = (127 * 127 * 4) + np.max(np.abs(B_int))
    target_factor = 127.0 / max_acc_theor
    best_shift = 16
    best_mult = int(round(target_factor * (1 << best_shift)))
    if best_mult == 0: best_mult = 1
    
    log_info(f"Auto-Quantização: MaxAcc={max_acc_theor}, Mult={best_mult}, Shift={best_shift}")
    return W_int, B_int, X_int, y_test, best_mult, best_shift

# ==============================================================================
# MAIN
# ==============================================================================
def main():

    print('\n')
    print(f"\n{Colors.CYAN}  ██╗██████╗ ██╗███████╗    ██╗  ██╗██╗██╗     {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║██╔══██╗██║██╔════╝    ██║  ██║██║██║     {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║██████╔╝██║███████╗    ███████║██║██║     {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║██╔══██╗██║╚════██║    ██╔══██║██║██║     {Colors.RESET}")
    print(f"{Colors.CYAN}  ██║██║  ██║██║███████║    ██║  ██║██║███████╗{Colors.RESET}")
    print(f"{Colors.CYAN}  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝    ╚═╝  ╚═╝╚═╝╚══════╝{Colors.RESET}")
    print('\n')
    
    driver = NPUDriver(SERIAL_PORT, BAUD_RATE)
    
    try:
        W_int, B_int, X_test, y_true, q_mult, q_shift = get_quantized_model()
        K_DIM = 4

        log_header("CARGA DE PARÂMETROS")
        driver.write_reg(REG_QUANT_MULT, q_mult)
        driver.write_reg(REG_QUANT_CFG, q_shift)
        for i, b in enumerate(B_int): driver.write_reg(REG_BIAS_BASE + i*4, int(b))
        log_success("Pesos e Bias carregados.")

        log_header(f"VALIDAÇÃO CRUZADA HW/SW ({len(X_test)} Amostras)")
        
        # Cabeçalho da tabela perfeitamente alinhado
        print(f"{Colors.DIM}{'-'*85}{Colors.RESET}")
        print(f" {'ID':<4} | {'REAL':<4} | {'HW':<4} | {'SW':<4} | {'SCORES HW (Cls 0,1,2)':<22} | {'BIT-OK':<7} | {'ACC-OK'}")
        print(f"{Colors.DIM}{'-'*85}{Colors.RESET}")

        stats = {'hw_match': 0, 'acc': 0, 'total': len(X_test)}
        total_inf_time = 0
        
        for idx, (x_vec, y_real) in enumerate(zip(X_test, y_true)):
            t_start = time.time()
            
            # --- HARDWARE INFERENCE ---
            driver.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
            for k in range(K_DIM):
                driver.write_reg(REG_WRITE_A, driver.pack_int8([x_vec[k], 0, 0, 0]))
                driver.write_reg(REG_WRITE_W, driver.pack_int8(W_int[k]))
            
            driver.write_reg(REG_CONFIG, K_DIM)
            driver.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
            driver.wait_done()
            
            hw_out_all = driver.read_results()
            t_end = time.time()
            total_inf_time += (t_end - t_start)

            hw_scores = hw_out_all[0][:3]
            
            # --- SOFTWARE INFERENCE ---
            sw_scores_full = compute_golden(x_vec, W_int, B_int, q_mult, q_shift)
            sw_scores = sw_scores_full[:3]

            # --- CHECK ---
            hw_pred = np.argmax(hw_scores)
            sw_pred = np.argmax(sw_scores)
            
            hw_match = (list(hw_scores) == list(sw_scores))
            is_correct = (hw_pred == y_real)
            
            if hw_match: stats['hw_match'] += 1
            if is_correct: stats['acc'] += 1
            
            # Formatação 
            hw_str = "MATCH" if hw_match else "FAIL"
            hw_col = Colors.GREEN if hw_match else Colors.RED
            
            acc_str = "OK" if is_correct else "ERR"
            acc_col = Colors.GREEN if is_correct else Colors.RED
            
            # Scores formatados 
            sc_fmt = str(list(hw_scores))
            
            print(f" {idx:<4} | {y_real:<4} | {Colors.BOLD}{hw_pred:<4}{Colors.RESET} | {sw_pred:<4} | {sc_fmt:<22} | {hw_col}{hw_str:<7}{Colors.RESET} | {acc_col}{acc_str}{Colors.RESET}")

        # RELATÓRIO FINAL 
        acc_pct = (stats['acc'] / stats['total']) * 100
        hw_pct  = (stats['hw_match'] / stats['total']) * 100
        avg_lat = (total_inf_time / stats['total']) * 1000
        
        print(f"\n{Colors.YELLOW}{'='*40}")
        print(f" RELATÓRIO FINAL DE PERFORMANCE")
        print(f"{'='*40}{Colors.RESET}")
        print(f" Amostras Processadas : {stats['total']}")
        print(f" Validação Bit-Exact  : {Colors.BOLD}{hw_pct:>6.2f}%{Colors.RESET}")
        print(f" Acurácia do Modelo   : {Colors.BOLD}{acc_pct:>6.2f}%{Colors.RESET}")
        print(f" Latência Média (HIL) : {Colors.CYAN}{avg_lat:>6.2f} ms{Colors.RESET}")
        print(f"{Colors.YELLOW}{'='*40}{Colors.RESET}")
        
        print('\n')
        if hw_pct == 100.0:
            log_success("Hardware Aprovado.")
        else:
            log_error("Divergência HW/SW detectada!")

    except KeyboardInterrupt:
        print('\n')
        print("🛑 Cancelado pelo usuário!")
    finally:
        driver.close()

if __name__ == "__main__":
    main()