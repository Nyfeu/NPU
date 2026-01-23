import serial
import time
import struct
import random
import sys
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
SERIAL_PORT = 'COM6'
BAUD_RATE   = 921600

# Cores ANSI
C_RESET  = "\033[0m"
C_RED    = "\033[91m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_CYAN   = "\033[96m"
C_GREY   = "\033[90m"

# ==============================================================================
# MAPA DE MEMÓRIA & CONSTANTES
# ==============================================================================
REG_STATUS     = 0x00
REG_CMD        = 0x04
REG_CONFIG     = 0x08
REG_WRITE_W    = 0x10 
REG_WRITE_A    = 0x14 
REG_READ_OUT   = 0x18 

REG_QUANT_CFG  = 0x40
REG_QUANT_MULT = 0x44
REG_FLAGS      = 0x48
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

OP_WRITE = 0x01
OP_READ  = 0x02

# ==============================================================================
# SISTEMA DE LOG PROFISSIONAL
# ==============================================================================
def get_time():
    return datetime.now().strftime("%H:%M:%S")

def log_info(msg):
    print(f"{C_GREY}[{get_time()}]{C_RESET} {C_CYAN}[INFO]{C_RESET}    {msg}")

def log_success(msg):
    print(f"{C_GREY}[{get_time()}]{C_RESET} {C_GREEN}[PASS]{C_RESET}    {msg}")

def log_error(msg):
    print(f"{C_GREY}[{get_time()}]{C_RESET} {C_RED}[FAIL]{C_RESET}    {msg}")

def log_warn(msg):
    print(f"{C_GREY}[{get_time()}]{C_RESET} {C_YELLOW}[WARN]{C_RESET}    {msg}")

def log_header(msg):
    print(f"\n{C_YELLOW}{'='*80}")
    print(f" {msg}")
    print(f"{'='*80}{C_RESET}")

def print_progress(iteration, total, prefix='Progresso:', suffix='', length=30):
    """
    Gera uma barra de progresso em linha única.
    Exemplo: [=====>          ] 35%
    """
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    
    if iteration == total:
        bar = '=' * filled_length 
    else:
        # O caractere '>' ou '#' na ponta
        bar = '=' * (filled_length - 1) + '>' if filled_length > 0 else ''
        
    empty = ' ' * (length - len(bar))
    
    # \r retorna o cursor para o início da linha
    sys.stdout.write(f'\r{C_GREY}[{get_time()}]{C_RESET} {C_YELLOW}[TEST]{C_RESET}    {prefix} [{bar}{empty}] {percent}% {suffix}')
    sys.stdout.flush()
    
    # Se completou, pula uma linha para não sobrescrever
    if iteration == total:
        print()

# ==============================================================================
# DRIVER
# ==============================================================================
class NPUDriver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=2.0)
            log_success(f"Link Serial Estabelecido: {port} @ {baud} bps")
            self.ser.reset_input_buffer()
        except serial.SerialException as e:
            log_error(f"Falha na conexão Serial: {e}")
            sys.exit(1)

    def close(self):
        self.ser.close()

    def write_reg(self, addr, data):
        data &= 0xFFFFFFFF
        packet = struct.pack('>B I I', OP_WRITE, addr, data)
        self.ser.write(packet)
        time.sleep(0.0001) 

    def read_reg(self, addr):
        packet = struct.pack('>B I', OP_READ, addr)
        self.ser.write(packet)
        resp = self.ser.read(4)
        if len(resp) != 4:
            log_error(f"Timeout no barramento (Addr: 0x{addr:02X})")
            return 0
        return struct.unpack('>I', resp)[0]

    def wait_for_done(self):
        while not (self.read_reg(REG_STATUS) & STATUS_DONE):
            pass

    def read_results(self):
        hw_results = []
        for _ in range(4):
            while not (self.read_reg(REG_STATUS) & STATUS_OUT_VALID):
                pass
            val = self.read_reg(REG_READ_OUT)
            hw_results.append(unpack_int8(val))
            self.read_reg(REG_STATUS) # Bus Toggling
        return hw_results[::-1]

# ==============================================================================
# HELPERS & GOLDEN MODEL
# ==============================================================================
def pack_int8(values):
    packed = 0
    for i, v in enumerate(values):
        packed |= ((v & 0xFF) << (i * 8))
    return packed

def unpack_int8(packed):
    out = []
    for i in range(4):
        b = (packed >> (i * 8)) & 0xFF
        out.append(b - 256 if b & 0x80 else b)
    return out

def clamp_int8(val):
    return max(-128, min(127, int(val)))

def model_ppu(acc, bias, mult, shift, zero, en_relu):
    val = acc + bias
    val = val * mult
    if shift > 0:
        val = (val + (1 << (shift - 1))) >> shift
    val += zero
    if en_relu and val < 0: val = 0
    return clamp_int8(val)

def compute_golden(A, B, bias, mult, shift, zero, K):
    acc = [[sum(A[r][k]*B[k][c] for k in range(K)) for c in range(4)] for r in range(4)]
    golden = [[model_ppu(acc[r][c], bias[c], mult, shift, zero, False)
               for c in range(4)] for r in range(4)]
    return golden

# ==============================================================================
# TESTES
# ==============================================================================
def test_sanity_check(npu):
    log_header("TESTE 1: SANITY CHECK (Identidade)")
    
    npu.write_reg(REG_QUANT_MULT, 1)
    npu.write_reg(REG_QUANT_CFG, 0)
    for i in range(4): npu.write_reg(REG_BIAS_BASE + i*4, 0)
    
    K_DIM = 4
    ident = [[1 if r==c else 0 for c in range(4)] for r in range(4)]
    
    npu.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
    for k in range(K_DIM):
        npu.write_reg(REG_WRITE_A, pack_int8([ident[r][k] for r in range(4)]))
        npu.write_reg(REG_WRITE_W, pack_int8([ident[k][c] for c in range(4)]))

    npu.write_reg(REG_CONFIG, K_DIM)
    npu.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
    npu.wait_for_done()
    
    hw = npu.read_results()
    
    if hw == ident:
        log_success("Matriz Identidade verificada com sucesso.")
        return True
    else:
        log_error(f"Falha Identidade.\nExp: {ident}\nGot: {hw}")
        return False

def test_corner_cases(npu):
    log_header("TESTE 2: CORNER CASES & LIMITES")
    
    cases = [
        {"name": "Saturação Positiva (+127)", "val": 10, "mult": 100, "bias": 0, "exp": 127},
        {"name": "Saturação Negativa (-128)", "val": -10, "mult": 100, "bias": 0, "exp": -128},
        {"name": "Zero Absoluto",             "val": 0, "mult": 55,  "bias": 0, "exp": 0},
        {"name": "Bias Dominance",            "val": 0, "mult": 1,   "bias": 50, "exp": 50},
    ]

    all_passed = True
    for case in cases:
        K_DIM = 4
        npu.write_reg(REG_QUANT_MULT, case["mult"])
        npu.write_reg(REG_QUANT_CFG, 0)
        for i in range(4): npu.write_reg(REG_BIAS_BASE + i*4, case["bias"])
        
        npu.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
        
        ident = [[1 if r==c else 0 for c in range(4)] for r in range(4)]
        val_mat = [[case["val"] for _ in range(K_DIM)] for _ in range(4)]
        
        for k in range(K_DIM):
            npu.write_reg(REG_WRITE_A, pack_int8([val_mat[r][k] for r in range(4)]))
            npu.write_reg(REG_WRITE_W, pack_int8([ident[k][c] for c in range(4)])) 
            
        npu.write_reg(REG_CONFIG, K_DIM)
        npu.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
        npu.wait_for_done()
        
        hw = npu.read_results()
        
        if hw[0][0] == case["exp"]:
            log_success(f"{case['name']:<25} | Resultado: {hw[0][0]}")
        else:
            log_error(f"{case['name']:<25} | Falha! Exp {case['exp']}, Got {hw[0][0]}")
            all_passed = False
            
    return all_passed

def test_backpressure(npu):
    log_header("TESTE 3: BACKPRESSURE (FIFO STALL)")
    log_info("Injetando latência artificial no host...")
    
    K_DIM = 16
    npu.write_reg(REG_QUANT_MULT, 1)
    npu.write_reg(REG_QUANT_CFG, 0)
    for i in range(4): npu.write_reg(REG_BIAS_BASE + i*4, 0)
    
    npu.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
    for k in range(K_DIM):
        npu.write_reg(REG_WRITE_A, pack_int8([1]*4))
        npu.write_reg(REG_WRITE_W, pack_int8([1]*4))
        
    npu.write_reg(REG_CONFIG, K_DIM)
    npu.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
    
    time.sleep(0.5) # Simula host travado
    
    hw = npu.read_results()
    
    if hw[0][0] == 16:
        log_success("FIFO gerenciou o backpressure corretamente.")
        return True
    else:
        log_error(f"Corrupção de dados por overflow/underflow. Lido: {hw[0][0]}")
        return False

def test_ultimate_stress(npu):
    log_header("TESTE 4: STRESS TEST RANDOMIZADO")
    
    ITERATIONS = 1000
    failures = 0
    
    log_info(f"Iniciando {ITERATIONS} ciclos de validação matemática...")
    
    for i in range(ITERATIONS):
        # Atualiza Barra de Progresso
        print_progress(i, ITERATIONS, prefix='Executando:', length=30)

        # 1. Parâmetros
        K_DIM   = random.randint(4, 32)
        mult    = random.randint(1, 5)
        bias    = [random.randint(-10, 10) for _ in range(4)]
        
        # 2. Config
        npu.write_reg(REG_QUANT_MULT, mult)
        npu.write_reg(REG_QUANT_CFG, 0)
        for b in range(4): npu.write_reg(REG_BIAS_BASE + b*4, bias[b])
        
        # 3. Dados
        A = [[random.randint(-5,5) for _ in range(K_DIM)] for _ in range(4)]
        B = [[random.randint(-5,5) for _ in range(4)] for _ in range(K_DIM)]
        
        # 4. Carga
        npu.write_reg(REG_CMD, CMD_RST_DMA_PTRS | CMD_RST_WR_W | CMD_RST_WR_I)
        for k in range(K_DIM):
            col_A = [A[r][k] for r in range(4)]
            row_B = [B[k][c] for c in range(4)]
            npu.write_reg(REG_WRITE_A, pack_int8(col_A))
            npu.write_reg(REG_WRITE_W, pack_int8(row_B))
            
        # 5. Execução
        npu.write_reg(REG_CONFIG, K_DIM)
        npu.write_reg(REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
        npu.wait_for_done()
        
        # 6. Validação
        hw = npu.read_results()
        golden = compute_golden(A, B, bias, mult, 0, 0, K_DIM)
        
        if hw != golden:
            failures += 1
            print() # Quebra a linha da barra de progresso
            log_error(f"Mismatch na iteração {i}: K={K_DIM}")
            break 
        
    # Finaliza a barra em 100%
    print_progress(ITERATIONS, ITERATIONS, prefix='Executando:', length=30)

    if failures == 0:
        log_success("Ciclos concluídos com integridade matemática perfeita.")
        return True
    else:
        return False

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    npu = NPUDriver(SERIAL_PORT, BAUD_RATE)
    try:
        print(f"\n{C_CYAN}  ███╗   ██╗██████╗ ██╗   ██╗    ██████╗ ██████╗ ██╗██╗   ██╗███████╗██████╗ {C_RESET}")
        print(f"{C_CYAN}  ████╗  ██║██╔══██╗██║   ██║    ██╔══██╗██╔══██╗██║██║   ██║██╔════╝██╔══██╗{C_RESET}")
        print(f"{C_CYAN}  ██╔██╗ ██║██████╔╝██║   ██║    ██║  ██║██████╔╝██║██║   ██║█████╗  ██████╔╝{C_RESET}")
        print(f"{C_CYAN}  ██║╚██╗██║██╔═══╝ ██║   ██║    ██║  ██║██╔══██╗██║╚██╗ ██╔╝██╔══╝  ██╔══██╗{C_RESET}")
        print(f"{C_CYAN}  ██║ ╚████║██║     ╚██████╔╝    ██████╔╝██║  ██║██║ ╚████╔╝ ███████╗██║  ██║{C_RESET}")
        print(f"{C_CYAN}  ╚═╝  ╚═══╝╚═╝      ╚═════╝     ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝{C_RESET}")
        
        steps = [
            test_sanity_check,
            test_corner_cases,
            test_backpressure,
            test_ultimate_stress
        ]
        
        all_ok = True
        for step in steps:
            if not step(npu):
                all_ok = False
                break
        
        log_header("RELATÓRIO DE QUALIFICAÇÃO")
        if all_ok:
            log_info(f"{C_GREEN}🏆 HARDWARE VALIDADO E OPERACIONAL.{C_RESET}")
        else:
            log_error(f"{C_CYAN}❌ FALHA CRÍTICA: REVISÃO DE HARDWARE NECESSÁRIA.{C_RESET}")
            
    except KeyboardInterrupt:
        print('\n')
        log_error("🛑 ABORTADO PELO USUÁRIO!")
    finally:
        npu.close()