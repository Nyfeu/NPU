# ==============================================================================
# File: test_array.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
from test_utils import *

# ==============================================================================
# CONFIGURAÇÕES GERAIS
# ==============================================================================
ROWS = 4
COLS = 4
DATA_WIDTH = 8
ACC_WIDTH = 32

# ==============================================================================
# HELPERS: SKEW E EMPACOTAMENTO
# ==============================================================================

def prepare_os_inputs(matrix_act, matrix_w):
    """
    Prepara os streams de entrada aplicando o atraso (Skew) necessário para
    a arquitetura Output Stationary.
    
    Lógica Temporal:
      Para que o elemento A[row, k] encontre B[k, col] no PE(row, col):
      - A[row, k] deve entrar na linha 'row' no ciclo T = k + row
      - B[k, col] deve entrar na coluna 'col' no ciclo T = k + col
      
    Args:
        matrix_act (list): Matriz de Ativações (Entrada Esquerda) [ROWS][K]
        matrix_w   (list): Matriz de Pesos (Entrada Superior) [K][COLS]
        
    Returns:
        tuple: (stream_acts, stream_wgts) prontos para injeção ciclo a ciclo.
    """
    K_DEPTH = len(matrix_act[0]) # Dimensão comum da multiplicação (k)
    
    # O tempo total cobre a profundidade K + a latência de preenchimento do array
    total_cycles = K_DEPTH + max(ROWS, COLS) + 5
    
    stream_acts = []
    stream_wgts = []
    
    for t in range(total_cycles):
        # Construir vetor de Ativações para o ciclo atual (Coluna Vertical na borda Esq)
        current_act_col = []
        for r in range(ROWS):
            # Atraso triangular: linha 'r' atrasada por 'r' ciclos
            k = t - r
            if 0 <= k < K_DEPTH:
                val = matrix_act[r][k]
            else:
                val = 0 # Padding (Zeros)
            current_act_col.append(val)
        stream_acts.append(current_act_col)
        
        # Construir vetor de Pesos para o ciclo atual (Linha Horizontal na borda Sup)
        current_wgt_row = []
        for c in range(COLS):
            # Atraso triangular: coluna 'c' atrasada por 'c' ciclos
            k = t - c
            if 0 <= k < K_DEPTH:
                val = matrix_w[k][c]
            else:
                val = 0 # Padding (Zeros)
            current_wgt_row.append(val)
        stream_wgts.append(current_wgt_row)
            
    return stream_acts, stream_wgts

def pack_vector(values, width):
    """Empacota lista de inteiros em um único sinal std_logic_vector."""
    packed = 0
    mask = (1 << width) - 1
    for i, val in enumerate(values):
        val = int(val) & mask
        packed |= (val << (i * width))
    return packed

def unpack_vector(packed_val, width, count):
    """Desempacota sinal std_logic_vector para lista de inteiros (Signed)."""
    unpacked = []
    try:
        val_int = packed_val.to_signed()
    except:
        val_int = 0 # Trata 'X', 'U', 'Z' como 0
        
    mask = (1 << width) - 1
    for i in range(count):
        raw = (val_int >> (i * width)) & mask
        # Converte complemento de dois manualmente se necessário
        if raw & (1 << (width - 1)): 
            raw -= (1 << width)
        unpacked.append(raw)
    return unpacked

# ==============================================================================
# TESTE 1: MATRIZ IDENTIDADE (Validação Lógica Básica)
# ==============================================================================
@cocotb.test()
async def test_os_identity(dut):
    log_header("TESTE OS: IDENTIDADE 4x4")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    # --------------------------------------------------------------------------
    # Inicialização e Reset
    # --------------------------------------------------------------------------
    dut.rst_n.value = 0
    dut.clear_acc.value = 0
    dut.drain_output.value = 0
    dut.input_weights.value = 0
    dut.input_acts.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # --------------------------------------------------------------------------
    # Preparação dos Dados (A = I, B = I -> C = I)
    # --------------------------------------------------------------------------
    X = [[1 if i==j else 0 for j in range(4)] for i in range(4)]
    W = [[1 if i==j else 0 for j in range(4)] for i in range(4)]
    
    # Gera os streams com atrasos (Skew)
    s_acts, s_wgts = prepare_os_inputs(X, W)
    
    # --------------------------------------------------------------------------
    # Fase de Computação (Streaming)
    # --------------------------------------------------------------------------
    # Limpa acumuladores antes de começar
    dut.clear_acc.value = 1
    await RisingEdge(dut.clk)
    dut.clear_acc.value = 0
    
    log_info(">>> Iniciando Fase de Computação (Streaming)...")
    for t, (act_vec, wgt_vec) in enumerate(zip(s_acts, s_wgts)):
        dut.input_acts.value = pack_vector(act_vec, DATA_WIDTH)
        dut.input_weights.value = pack_vector(wgt_vec, DATA_WIDTH)
        await RisingEdge(dut.clk)
        
    # --------------------------------------------------------------------------
    # Fase de Drenagem (Drain Output)
    # --------------------------------------------------------------------------
    log_info(">>> Iniciando Fase de Drenagem (Shift Vertical)...")
    
    # Para a injeção de dados e ativa o modo Drain
    dut.input_acts.value = 0
    dut.input_weights.value = 0
    dut.drain_output.value = 1
    
    captured_results = []
    
    # IMPORTANTE: Ordem de Leitura "Bottom-Up"
    # No modo Drain, as colunas funcionam como shift-registers verticais.
    # - Ciclo 0 (Imediato): O dado da linha inferior (Row 3) já está na saída.
    # - Ciclo 1: Row 2 desce para a saída.
    # - ...
    
    for i in range(ROWS):
        # Passo A: Espera o sinal estabilizar (Delta Cycle)
        await Timer(1, unit="ns")
        
        # Passo B: Captura o valor presente na saída ANTES do clock bater
        packed = dut.output_accs.value
        vec = unpack_vector(packed, ACC_WIDTH, COLS)
        captured_results.append(vec)
        
        # Passo C: Avança o Clock (Realiza o Shift Vertical para trazer a próxima linha)
        await RisingEdge(dut.clk)

    log_info(f"Saída Capturada (Ordem: Row 3 -> Row 0): {captured_results}")
    
    # --------------------------------------------------------------------------
    # Verificação
    # --------------------------------------------------------------------------
    expected_rows = [
        [0, 0, 0, 1], # Row 3 (Fundo da matriz) sai primeiro
        [0, 0, 1, 0], # Row 2
        [0, 1, 0, 0], # Row 1
        [1, 0, 0, 0]  # Row 0 (Topo da matriz) sai por último
    ]
    
    errors = 0
    for i in range(4):
        if captured_results[i] != expected_rows[i]:
            log_error(f"Erro na captura {i} (Row Real {3-i}).")
            log_error(f"  Esperado: {expected_rows[i]}")
            log_error(f"  Lido:     {captured_results[i]}")
            errors += 1
            
    if errors == 0:
        log_success("Sucesso! Matriz Identidade processada e drenada corretamente.")
    else:
        assert False

# ==============================================================================
# TESTE 2: FUZZING (Stress Test Aleatório)
# ==============================================================================
@cocotb.test()
async def test_os_fuzzing(dut):
    log_header("TESTE OS: FUZZING 4x4 (Randomized)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    # Reset inicial
    dut.rst_n.value = 0
    dut.clear_acc.value = 0
    dut.drain_output.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # Gerar Matrizes Aleatórias
    # Testamos uma multiplicação (4xK) * (Kx4) -> (4x4)
    K_DIM = 8 
    A = [[random.randint(-5, 5) for _ in range(K_DIM)] for _ in range(ROWS)]
    B = [[random.randint(-5, 5) for _ in range(COLS)] for _ in range(K_DIM)]
    
    # Modelo de Referência (Cálculo em Python puro)
    C_ref = [[0]*COLS for _ in range(ROWS)]
    for r in range(ROWS):
        for c in range(COLS):
            val = sum(A[r][k] * B[k][c] for k in range(K_DIM))
            C_ref[r][c] = val
            
    # Executar no Hardware
    s_acts, s_wgts = prepare_os_inputs(A, B)
    
    dut.clear_acc.value = 1
    await RisingEdge(dut.clk)
    dut.clear_acc.value = 0
    
    for act, wgt in zip(s_acts, s_wgts):
        dut.input_acts.value = pack_vector(act, DATA_WIDTH)
        dut.input_weights.value = pack_vector(wgt, DATA_WIDTH)
        await RisingEdge(dut.clk)
        
    # Drenar Resultados
    dut.input_acts.value = 0
    dut.input_weights.value = 0
    dut.drain_output.value = 1
    
    res_hw = []
    for _ in range(ROWS):
        await Timer(1, unit="ns")
        packed = dut.output_accs.value
        res_hw.append(unpack_vector(packed, ACC_WIDTH, COLS))
        await RisingEdge(dut.clk)
        
    # Validar Resultados
    for i in range(ROWS):
        # Mapeia a leitura sequencial (0..3) para a linha da matriz (3..0)
        hw_row = res_hw[i]
        ref_row_idx = (ROWS - 1) - i
        expected = C_ref[ref_row_idx]
        
        if hw_row != expected:
            log_error(f"Erro na Linha {ref_row_idx} da matriz resultado.")
            log_error(f"  Esperado: {expected}")
            log_error(f"  Lido:     {hw_row}")
            assert False
            
    log_success(f"Fuzzing OK! Multiplicação 4x{K_DIM}x4 verificada com sucesso.")