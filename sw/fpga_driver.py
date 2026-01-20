import serial
import time
import struct
import random
import sys

# ==============================================================================
# CONFIGURAÇÃO DA PORTA SERIAL
# ==============================================================================
SERIAL_PORT = 'COM6'
BAUD_RATE   = 921600

# ==============================================================================
# MAPA DE REGISTRADORES
# ==============================================================================
REG_CTRL       = 0x00
REG_QUANT_CFG  = 0x04
REG_QUANT_MULT = 0x08
REG_STATUS     = 0x0C
REG_WRITE_W    = 0x10
REG_WRITE_A    = 0x14
REG_READ_OUT   = 0x18
REG_BIAS_BASE  = 0x20

STATUS_OUT_VALID = (1 << 3)

OP_WRITE = 0x01
OP_READ  = 0x02

# ==============================================================================
# DRIVER
# ==============================================================================
class NPUDriver:
    def __init__(self, port, baud):
        try:
            self.ser = serial.Serial(port, baud, timeout=2.0)
            print(f"✅ Conectado à FPGA em {port} @ {baud} bps")
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.5)
        except serial.SerialException as e:
            print(f"❌ Erro ao abrir serial: {e}")
            sys.exit(1)

    def close(self):
        self.ser.close()

    def write_reg(self, addr, data):
        data &= 0xFFFFFFFF
        packet = struct.pack('>B I I', OP_WRITE, addr, data)
        self.ser.write(packet)
        # Pequeno espaçamento para evitar overruns lógicos
        time.sleep(0.00005)

    def read_reg(self, addr):
        packet = struct.pack('>B I', OP_READ, addr)
        self.ser.write(packet)
        resp = self.ser.read(4)
        if len(resp) != 4:
            print(f"❌ Timeout lendo 0x{addr:02X}")
            return 0
        return struct.unpack('>I', resp)[0]

    # -----------------------------
    # Primitivas de alto nível
    # -----------------------------
    def clear_accumulators(self):
        self.write_reg(REG_CTRL, 0x04)
        time.sleep(0.001)
        self.write_reg(REG_CTRL, 0x00)
        time.sleep(0.001)

    def start_dump(self):
        self.write_reg(REG_CTRL, 0x08)
        time.sleep(0.0005)

    def stop_dump(self):
        self.write_reg(REG_CTRL, 0x00)
        time.sleep(0.0005)

# ==============================================================================
# UTILITÁRIOS
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

def model_ppu(acc, bias, mult, shift, zero, en_relu):
    v = (acc + bias) * mult
    if shift > 0:
        v = (v + (1 << (shift - 1))) >> shift
    v += zero
    if en_relu and v < 0:
        v = 0
    return max(-128, min(127, int(v)))

# ==============================================================================
# TESTES
# ==============================================================================
def test_identity(npu):
    print("\n=== TESTE IDENTIDADE ===")

    npu.write_reg(REG_QUANT_MULT, 1)
    npu.write_reg(REG_QUANT_CFG, 0)
    for i in range(4):
        npu.write_reg(REG_BIAS_BASE + i*4, 0)

    npu.clear_accumulators()

    for k in range(4):
        npu.write_reg(REG_WRITE_A, pack_int8([1 if r == k else 0 for r in range(4)]))
        npu.write_reg(REG_WRITE_W, pack_int8([1 if c == k else 0 for c in range(4)]))

    time.sleep(0.01)

    npu.start_dump()

    results = []
    for _ in range(4):
        while not (npu.read_reg(REG_STATUS) & STATUS_OUT_VALID):
            pass
        results.append(unpack_int8(npu.read_reg(REG_READ_OUT)))

    npu.stop_dump()

    for i, r in enumerate(results):
        print(f"Row {i}: {r}")

    success = (results == [[0,0,0,1],[0,0,1,0],[0,1,0,0],[1,0,0,0]])
    if not success:
        print("❌ Falha na Identidade! Verifique se os dados estão deslocados.")
    return success

def test_stress(npu, silent=False):
    # Gera parâmetros aleatórios
    q_mult  = random.randint(1, 10)
    q_shift = random.randint(0, 3)
    q_zero  = random.randint(-5, 5)
    bias    = [random.randint(-20, 20) for _ in range(4)]
    
    # Se não for silencioso, imprime configuração
    if not silent:
        print("\n=== TESTE STRESS ===")
        print(f"Mult={q_mult}, Shift={q_shift}, Zero={q_zero}")
        print(f"Bias={bias}")

    # Configura Hardware
    npu.write_reg(REG_QUANT_MULT, q_mult)
    npu.write_reg(REG_QUANT_CFG, ((q_zero & 0xFF) << 8) | q_shift)
    for i in range(4):
        npu.write_reg(REG_BIAS_BASE + i*4, bias[i])

    npu.clear_accumulators()

    # Gera Matrizes
    K = 8
    A = [[random.randint(-5,5) for _ in range(K)] for _ in range(4)]
    B = [[random.randint(-5,5) for _ in range(4)] for _ in range(K)]

    # Envia dados
    for k in range(K):
        npu.write_reg(REG_WRITE_A, pack_int8([A[r][k] for r in range(4)]))
        npu.write_reg(REG_WRITE_W, pack_int8([B[k][c] for c in range(4)]))

    time.sleep(0.01)

    # Lê Hardware
    npu.start_dump()
    hw = []
    for _ in range(4):
        while not (npu.read_reg(REG_STATUS) & STATUS_OUT_VALID):
            pass
        hw.append(unpack_int8(npu.read_reg(REG_READ_OUT)))
    npu.stop_dump()

    # Calcula Modelo (Golden)
    acc = [[sum(A[r][k]*B[k][c] for k in range(K)) for c in range(4)] for r in range(4)]
    golden = [[model_ppu(acc[r][c], bias[c], q_mult, q_shift, q_zero, False)
               for c in range(4)] for r in range(4)][::-1]

    match = (hw == golden)

    # Se falhar OU se não for modo silencioso, imprime detalhes
    if not match or not silent:
        if silent: # Se estava silencioso e falhou, precisamos imprimir o cabeçalho agora
            print(f"\n❌ FALHA NO TESTE STRESS")
            print(f"Mult={q_mult}, Shift={q_shift}, Zero={q_zero}")
            print(f"Bias={bias}")
        
        print("HW:")
        for r in hw: print(r)
        print("EXP:")
        for r in golden: print(r)

    return match

# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    npu = NPUDriver(SERIAL_PORT, BAUD_RATE)
    try:
        # 1. Teste de Identidade (Sanity Check)
        if test_identity(npu):
            print("\n✅ Identidade OK. Iniciando stress test massivo...")
            
            # 2. Loop de Stress (1000 iterações)
            TOTAL_TESTS = 1000
            failures = 0
            
            start_time = time.time()
            
            for i in range(TOTAL_TESTS):
                # silent=True para não floodar o terminal, exceto em erro
                if not test_stress(npu, silent=True):
                    print(f"❌ Erro detectado na iteração {i+1}")
                    failures += 1
                    # Opção: Parar no primeiro erro para debug
                    break 
                
                # Feedback de progresso a cada 50 testes
                if (i+1) % 50 == 0:
                    print(f"Progresso: {i+1}/{TOTAL_TESTS} testes concluídos...")
            
            end_time = time.time()
            duration = end_time - start_time
            
            print("\n" + "="*40)
            print(f"RESUMO FINAL")
            print("="*40)
            print(f"Testes Executados: {i+1}")
            print(f"Sucessos: {(i+1) - failures}")
            print(f"Falhas:   {failures}")
            print(f"Tempo:    {duration:.2f}s")
            
            if failures == 0:
                print("🏆 SUCESSO TOTAL! O Hardware está robusto.")
            else:
                print("⚠️  HOUVE FALHAS. Verifique o log acima.")
                
    finally:
        npu.close()