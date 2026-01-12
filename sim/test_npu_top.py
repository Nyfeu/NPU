# ==============================================================================
# File: tb/test_npu_top.py
# Descrição: Testbench de Integração para o NPU TOP LEVEL.
#            Verifica o fluxo completo: Entrada(Int8) -> Core(Int32) -> PPU -> Saída(Int8)
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
import random
from test_utils import *

# ==============================================================================
# CONFIGURAÇÕES (DEVEM BATER COM O VHDL)
# ==============================================================================
ROWS = 4
COLS = 4
DATA_WIDTH = 8   # Entrada/Saída do Top
ACC_WIDTH = 32   # Largura interna do Acumulador/Bias
QUANT_WIDTH = 32 # Largura do Multiplicador

# ==============================================================================
# MODELO DE REFERÊNCIA COMPLETO (GOLDEN MODEL)
# ==============================================================================
class NPUFullModel:
    @staticmethod
    def compute(weights, input_vec, bias_vec, mult, shift, zp, en_relu):
        """
        Simula o hardware bit-exact:
        1. Multiplicação Matricial (Systolic Array)
        2. Soma de Bias
        3. Scaling (Mult + Shift + Round)
        4. Zero Point + ReLU + Clamp
        """
        
        # 1. CORE: Matrix Multiply (Y = X * W)
        # ---------------------------------------------------
        core_accs = []
        for c in range(COLS):
            acc = 0
            for r in range(ROWS):
                acc += input_vec[r] * weights[r][c]
            core_accs.append(acc)

        # 2. PPU: Post-Processing
        # ---------------------------------------------------
        final_outputs = []
        for c, val in enumerate(core_accs):
            
            # A. Bias Add
            val = val + bias_vec[c]
            
            # B. Scaling (Fixed Point Mult)
            val = val * mult
            
            # C. Shift & Rounding (Round to Nearest)
            if shift > 0:
                round_bit = 1 << (shift - 1)
                val = (val + round_bit) >> shift
            
            # D. Zero Point Add
            val = val + zp
            
            # E. ReLU
            if en_relu and val < 0:
                val = 0
                
            # F. Clamping (Saturação Int8: -128 a 127)
            if val > 127: val = 127
            if val < -128: val = -128
            
            final_outputs.append(val)
            
        return final_outputs

# ==============================================================================
# HELPERS DE EMPACOTAMENTO
# ==============================================================================

def pack_weights(row_values):
    """ Empacota uma linha de pesos (Int8) """
    packed = 0
    mask = (1 << DATA_WIDTH) - 1
    for i, val in enumerate(row_values):
        val = val & mask
        packed |= (val << (i * DATA_WIDTH))
    return packed

def pack_inputs(vec_values):
    """ Empacota vetor de ativação (Int8) """
    return pack_weights(vec_values) # Mesma lógica

def pack_bias(bias_list):
    """ Empacota vetor de Bias (Int32) - Cuidado com a largura! """
    packed = 0
    mask = (1 << ACC_WIDTH) - 1
    for i, val in enumerate(bias_list):
        val = val & mask
        packed |= (val << (i * ACC_WIDTH))
    return packed

def unpack_output(packed_val):
    """ Desempacota saída (Int8) """
    try: val_int = int(packed_val)
    except: return [0] * COLS
    
    res = []
    mask = (1 << DATA_WIDTH) - 1
    for i in range(COLS):
        raw = (val_int >> (i * DATA_WIDTH)) & mask
        if raw & 0x80: raw -= 0x100 # Signed conversion
        res.append(raw)
    return res

# ==============================================================================
# TESTBENCH
# ==============================================================================

@cocotb.test()
async def test_npu_integration(dut):
    """
    Teste de Integração:
    1. Carrega pesos.
    2. Configura PPU com parâmetros não-triviais (Bias, Shift).
    3. Injeta dados e verifica se a saída bate com o modelo Python.
    """
    log_header("TESTE DE INTEGRAÇÃO NPU TOP (CORE + PPU)")
    
    # --- 1. Inicialização ---
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.load_weight.value = 0
    
    # Configuração Inicial Segura (Bypass)
    dut.bias_in.value = 0
    dut.quant_mult.value = 1
    dut.quant_shift.value = 0
    dut.zero_point.value = 0
    dut.en_relu.value = 0
    
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    log_info("Reset liberado.")

    # --- 2. Carga de Pesos (Weight Loading) ---
    # Vamos usar uma Matriz Diagonal com valor 2 para facilitar o debug mental
    # [[2,0,0,0], [0,2,0,0]...]
    # Assim, o resultado do Core será Entrada * 2
    
    weights = [[2 if r == c else 0 for c in range(COLS)] for r in range(ROWS)]
    
    dut.load_weight.value = 1
    for r in range(ROWS-1, -1, -1):
        dut.input_weights.value = pack_weights(weights[r])
        await RisingEdge(dut.clk)
    dut.load_weight.value = 0
    
    log_info("Pesos carregados (Diagonal x2).")

    # --- 3. Configuração do PPU (Cenário Realista) ---
    # Vamos testar:
    # - Bias: Somar valores diferentes por coluna
    # - Scaling: Multiplicar por 1 (mas via PPU) e dividir por 2 (Shift=1)
    # Resultado Esperado: ((Entrada * 2) + Bias) / 2
    
    bias_vec = [10, 20, -10, 0] # Bias por coluna
    mult = 1
    shift = 1 # Divisão por 2
    zp = 0
    relu = 1  # Ativar ReLU para cortar negativos
    
    dut.bias_in.value     = pack_bias(bias_vec)
    dut.quant_mult.value  = mult
    dut.quant_shift.value = shift
    dut.zero_point.value  = zp
    dut.en_relu.value     = relu
    
    log_info(f"Config PPU: Bias={bias_vec}, Shift={shift}, ReLU={relu}")

    # --- 4. Loop de Teste ---
    test_vectors = [
        [10, 10, 10, 10],   # Simples
        [0, 0, 0, 0],       # Zeros
        [-20, -20, -20, -20], # Negativos (Testar ReLU)
        [50, 50, 50, 50]    # Valores mais altos
    ]
    
    # Fila de espera para conferência
    expected_queue = []

    # Processo de Monitoramento
    async def monitor():
        idx = 0
        while idx < len(test_vectors):
            await RisingEdge(dut.clk)
            await ReadOnly()
            if dut.valid_out.value == 1:
                received = unpack_output(dut.output_data.value)
                expected = expected_queue[idx]
                
                if received == expected:
                    log_success(f"Vetor {idx} OK: Entrada={test_vectors[idx]} -> Saída={received}")
                else:
                    log_error(f"FALHA no Vetor {idx}:")
                    log_error(f"   Esperado: {expected}")
                    log_error(f"   Recebido: {received}")
                    assert False, "Mismatch de dados"
                idx += 1
    
    cocotb.start_soon(monitor())

    # Processo de Injeção (Driver)
    for vec in test_vectors:
        # Calcula o esperado (Python)
        exp = NPUFullModel.compute(weights, vec, bias_vec, mult, shift, zp, relu)
        expected_queue.append(exp)
        
        # Envia para o Hardware
        dut.valid_in.value = 1
        dut.input_acts.value = pack_inputs(vec)
        await RisingEdge(dut.clk)
        
    dut.valid_in.value = 0

    # Aguarda o fim do processamento
    for _ in range(50):
        if len(expected_queue) == 0: break # (Lógica simplificada, o monitor controla o idx)
        await RisingEdge(dut.clk)
        
    log_success("Teste de Integração Finalizado com Sucesso!")