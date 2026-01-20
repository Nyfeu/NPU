# ==============================================================================
# File: test_npu_core.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
import random
from test_utils import *

# ==============================================================================
# File: NPU/sim/core/test_npu_core.py
# ==============================================================================
# Descrição: Testbench para o NPU Core (Output Stationary).
#            Verifica a integração completa: Buffers de Skew + Systolic Array.
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
from test_utils import *

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
ROWS = 4
COLS = 4
DATA_WIDTH = 8
ACC_WIDTH = 32

# ==============================================================================
# HELPERS
# ==============================================================================

def pack_vector(values, width):
    """Empacota lista de inteiros em um sinal VHDL."""
    packed = 0
    mask = (1 << width) - 1
    for i, val in enumerate(values):
        val = int(val) & mask
        packed |= (val << (i * width))
    return packed

def unpack_vector(packed_val, width, count):
    """Desempacota sinal VHDL para lista de inteiros."""
    unpacked = []
    try:
        val_int = packed_val.to_signed()
    except:
        val_int = 0
    mask = (1 << width) - 1
    for i in range(count):
        raw = (val_int >> (i * width)) & mask
        if raw & (1 << (width - 1)): raw -= (1 << width)
        unpacked.append(raw)
    return unpacked

async def reset_dut(dut):
    """Reset e inicialização de sinais."""
    dut.rst_n.value = 0
    dut.acc_clear.value = 0
    dut.acc_dump.value = 0
    dut.valid_in.value = 0
    dut.input_weights.value = 0
    dut.input_acts.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

# ==============================================================================
# TESTE 1: INTEGRAÇÃO BÁSICA (Matriz Identidade)
# ==============================================================================
@cocotb.test()
async def test_core_identity(dut):
    log_header("TESTE CORE: IDENTIDADE 4x4")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # 1. Definir Matrizes (A=I, B=I)
    # K=4 (Profundidade)
    A = [[1 if i==j else 0 for j in range(4)] for i in range(4)]
    B = [[1 if i==j else 0 for j in range(4)] for i in range(4)]
    
    # 2. Iniciar Processamento
    # Limpa acumuladores
    dut.acc_clear.value = 1
    await RisingEdge(dut.clk)
    dut.acc_clear.value = 0
    
    log_info(">>> Enviando Dados (Ciclo a Ciclo)...")
    
    # Loop pela dimensão K (Profundidade da multiplicação)
    # A NPU espera receber A[:, k] e B[k, :] simultaneamente
    K_DIM = 4
    for k in range(K_DIM):
        dut.valid_in.value = 1
        
        # Fatia de Ativações: Coluna k da matriz A
        col_A = [A[row][k] for row in range(ROWS)]
        
        # Fatia de Pesos: Linha k da matriz B
        row_B = [B[k][col] for col in range(COLS)]
        
        dut.input_acts.value = pack_vector(col_A, DATA_WIDTH)
        dut.input_weights.value = pack_vector(row_B, DATA_WIDTH)
        
        await RisingEdge(dut.clk)

    # Desliga entrada e espera o Pipeline processar
    dut.valid_in.value = 0
    dut.input_acts.value = 0
    dut.input_weights.value = 0
    
    # Latência: Skew Entrada (Max 4) + Array (4) + Margem
    # Como não temos sinal de "Done", esperamos um tempo seguro
    log_info(">>> Aguardando propagação no Array...")
    for _ in range(15):
        await RisingEdge(dut.clk)
        
    # 3. Drenagem (Readout)
    log_info(">>> Drenando Resultados...")
    dut.acc_dump.value = 1
    
    captured_rows = []
    
    # Leitura Bottom-Up (Igual ao Systolic Array)
    for i in range(ROWS):
        await Timer(1, unit="ns")
        packed = dut.output_accs.value
        vec = unpack_vector(packed, ACC_WIDTH, COLS)
        captured_rows.append(vec)
        await RisingEdge(dut.clk)
        
    dut.acc_dump.value = 0
    
    log_info(f"Saída Capturada: {captured_rows}")

    # 4. Validação
    # Sai Row 3, depois Row 2...
    expected_rows = [
        [0, 0, 0, 1], # Row 3
        [0, 0, 1, 0], # Row 2
        [0, 1, 0, 0], # Row 1
        [1, 0, 0, 0]  # Row 0
    ]
    
    for i in range(4):
        if captured_rows[i] != expected_rows[i]:
            log_error(f"Erro Row {3-i}. Esperado {expected_rows[i]}, Lido {captured_rows[i]}")
            assert False
            
    log_success("Sucesso! Core processou Identidade corretamente com Buffers de Skew.")

# ==============================================================================
# TESTE 2: FUZZING (Matrizes Retangulares)
# ==============================================================================
@cocotb.test()
async def test_core_fuzzing(dut):
    log_header("TESTE CORE: FUZZING (4x8 * 8x4)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    
    # 1. Dados Aleatórios
    K_DIM = 8 # Profundidade maior para testar fluxo contínuo
    A = [[random.randint(-5, 5) for _ in range(K_DIM)] for _ in range(ROWS)]
    B = [[random.randint(-5, 5) for _ in range(COLS)] for _ in range(K_DIM)]
    
    # Golden Model
    C_ref = [[0]*COLS for _ in range(ROWS)]
    for r in range(ROWS):
        for c in range(COLS):
            C_ref[r][c] = sum(A[r][k] * B[k][c] for k in range(K_DIM))
            
    # 2. Execução
    dut.acc_clear.value = 1
    await RisingEdge(dut.clk)
    dut.acc_clear.value = 0
    
    for k in range(K_DIM):
        dut.valid_in.value = 1
        col_A = [A[r][k] for r in range(ROWS)]
        row_B = [B[k][c] for c in range(COLS)]
        
        dut.input_acts.value = pack_vector(col_A, DATA_WIDTH)
        dut.input_weights.value = pack_vector(row_B, DATA_WIDTH)
        await RisingEdge(dut.clk)
        
    dut.valid_in.value = 0
    
    # Espera cálculo terminar (K + Latency)
    for _ in range(K_DIM + ROWS + COLS + 5):
        await RisingEdge(dut.clk)
        
    # 3. Readout
    dut.acc_dump.value = 1
    hw_rows = []
    for _ in range(ROWS):
        await Timer(1, unit="ns")
        packed = dut.output_accs.value
        hw_rows.append(unpack_vector(packed, ACC_WIDTH, COLS))
        await RisingEdge(dut.clk)
    
    # 4. Validar
    for i in range(ROWS):
        hw_val = hw_rows[i]
        ref_val = C_ref[(ROWS-1)-i] # Mapeamento Bottom-Up
        
        if hw_val != ref_val:
            log_error(f"Erro Row {(ROWS-1)-i}. Ref: {ref_val}, HW: {hw_val}")
            assert False
            
    log_success(f"Fuzzing OK! Multiplicação 4x{K_DIM}x4 passou.")