# ==============================================================================
# File: test_post_process.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
from test_utils import *

# ==============================================================================
# HELPERS DE CONVERSÃO
# ==============================================================================

def to_signed32(val):
    """Converte inteiro Python para 32-bit signed (simula overflow se precisar)"""
    val = val & 0xFFFFFFFF
    if val & 0x80000000:
        val -= 0x100000000
    return val

def from_signed8(val):
    """Lê valor de 8-bit do Cocotb e converte para int Python assinado"""
    try: val = int(val)
    except: return 0
    val = val & 0xFF
    if val & 0x80:
        val -= 0x100
    return val

# ==============================================================================
# MODELO DE REFERÊNCIA (Bit-Exact com o Hardware)
# ==============================================================================

class PPUReference:
    @staticmethod
    def compute(acc, bias, mult, shift, zero_point, en_relu):
        # 1. Bias Add
        val = acc + bias
        
        # 2. Scaling (Mult)
        # O hardware usa 32x32 -> 64 bits. Python lida com isso nativamente.
        val = val * mult
        
        # 3. Shift & Rounding
        # Lógica: round_bit = 1 << (shift - 1)
        if shift > 0:
            round_bit = 1 << (shift - 1)
            val = (val + round_bit) >> shift
        
        # 4. Zero Point Add
        val = val + zero_point
        
        # 5. ReLU
        if en_relu and val < 0:
            val = 0
            
        # 6. Clamping (Saturação Int8: -128 a 127)
        if val > 127: val = 127
        if val < -128: val = -128
            
        return val

# ==============================================================================
# SCOREBOARD
# ==============================================================================

class Scoreboard:
    def __init__(self):
        self.queue = []
        self.errors = 0
        
    def add_expected(self, val):
        self.queue.append(val)
        
    def check(self, received):
        if not self.queue:
            log_error(f"Dado inesperado recebido: {received}")
            self.errors += 1
            return
            
        expected = self.queue.pop(0)
        if received != expected:
            self.errors += 1
            log_error("MISMATCH!")
            log_error(f"  Esperado: {expected}")
            log_error(f"  Recebido: {received}")

# ==============================================================================
# SETUP
# ==============================================================================

async def setup_dut(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.acc_in.value = 0
    dut.bias_in.value = 0
    dut.quant_mult.value = 0
    dut.quant_shift.value = 0
    dut.zero_point.value = 0
    dut.en_relu.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

async def monitor_output(dut, sb):
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if dut.valid_out.value == 1:
            val = from_signed8(dut.data_out.value)
            sb.check(val)

# ==============================================================================
# TESTES
# ==============================================================================

@cocotb.test()
async def test_01_identity_check(dut):
    
    # Teste 1: Identidade (Pass-Through)
    # Configura Mult=1, Shift=0, Bias=0. O dado deve passar quase inalterado
    # (exceto pela saturação de 8 bits).
    
    log_header("TESTE 1: IDENTIDADE & SATURAÇÃO BÁSICA")
    await setup_dut(dut)
    sb = Scoreboard()
    cocotb.start_soon(monitor_output(dut, sb))
    
    # Parâmetros de Identidade
    dut.bias_in.value = 0
    dut.quant_mult.value = 1
    dut.quant_shift.value = 0
    dut.zero_point.value = 0
    dut.en_relu.value = 0

    # Vetores: Dentro do range, Acima (Overflow), Abaixo (Underflow)
    inputs = [0, 10, -10, 100, 127, -128, 200, -200, 1000]
    
    for val in inputs:
        # Golden Model
        expected = PPUReference.compute(val, 0, 1, 0, 0, False)
        sb.add_expected(expected)
        
        # Drive
        dut.valid_in.value = 1
        dut.acc_in.value = val
        await RisingEdge(dut.clk)

    dut.valid_in.value = 0
    for _ in range(10): await RisingEdge(dut.clk) # Espera pipeline
    
    if sb.errors == 0: log_success("Pass-Through OK.")
    else: assert False, f"{sb.errors} erros."

@cocotb.test()
async def test_02_relu_logic(dut):
    
    # Teste 2: Lógica ReLU
    # Verifica se números negativos são zerados quando en_relu=1.
    
    log_header("TESTE 2: FUNÇÃO RELU")
    await setup_dut(dut)
    sb = Scoreboard()
    cocotb.start_soon(monitor_output(dut, sb))
    
    dut.quant_mult.value = 1
    dut.en_relu.value = 1 # ATIVADO
    
    inputs = [50, -50, 0, -1, 1]
    
    for val in inputs:
        expected = PPUReference.compute(val, 0, 1, 0, 0, True)
        sb.add_expected(expected)
        
        dut.valid_in.value = 1
        dut.acc_in.value = val
        await RisingEdge(dut.clk)
        
    dut.valid_in.value = 0
    for _ in range(10): await RisingEdge(dut.clk)
    
    if sb.errors == 0: log_success("ReLU Logic OK.")
    else: assert False

@cocotb.test()
async def test_03_quantization_math(dut):
    
    # Teste 3: Quantização Real (Scaling + Shifting + Rounding)
    # Simula um cenário real de rede neural onde o acumulador é grande
    # e precisamos reduzir para 8 bits.
    
    log_header("TESTE 3: MATEMÁTICA DE QUANTIZAÇÃO")
    await setup_dut(dut)
    sb = Scoreboard()
    cocotb.start_soon(monitor_output(dut, sb))
    
    # Cenário: Dividir por aprox 256 (Shift 8) e multiplicar por 1.5 (Mult convertida)
    # Vamos usar valores aleatórios para estressar