# ==============================================================================
# File: test_input_buffer.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from test_utils import *

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
ROWS = 4
DATA_WIDTH = 8

# ==============================================================================
# HELPERS (Empacotamento)
# ==============================================================================
def pack_vector(values):
    packed = 0
    for i, val in enumerate(values):
        mask = (1 << DATA_WIDTH) - 1
        val_masked = val & mask
        packed |= (val_masked << (i * DATA_WIDTH))
    return packed

def unpack_vector(packed_val):
    unpacked = []
    mask = (1 << DATA_WIDTH) - 1
    
    val_int = int(packed_val) # Garante inteiro

    for i in range(ROWS):
        raw_val = (val_int >> (i * DATA_WIDTH)) & mask
        # Converter para Signed 8-bit
        if raw_val & (1 << (DATA_WIDTH - 1)):
            raw_val -= (1 << DATA_WIDTH)
        unpacked.append(raw_val)
    return unpacked

# ==============================================================================
# TESTE 1: VERIFICAÇÃO DE SKEW (ATRASO TRIANGULAR)
# ==============================================================================
@cocotb.test()
async def test_buffer_skew(dut):
    
    # Injeta um único vetor e verifica se cada linha sai no tempo correto.
    # Linha 0: Atraso 0
    # Linha 1: Atraso 1
    # [...]
    
    log_header("TESTE 1: VERIFICAÇÃO DE SKEW")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # 1. Reset Síncrono
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.data_in.value = 0
    
    await RisingEdge(dut.clk) # Borda para capturar o reset
    dut.rst_n.value = 1       # Libera reset
    await RisingEdge(dut.clk) 

    # 2. Injetar Vetor de Teste: [10, 20, 30, 40]
    test_vec = [10, 20, 30, 40]
    log_info(f"Injetando vetor: {test_vec}")

    dut.valid_in.value = 1
    dut.data_in.value = pack_vector(test_vec)
    
    # Ciclo T0: O hardware processa a entrada
    await RisingEdge(dut.clk) 

    # 3. Remover Entrada (Voltar a injetar zeros/inválido)
    dut.valid_in.value = 0
    dut.data_in.value = 0

    # 4. Verificar Saídas Ciclo a Ciclo
    # Esperamos que os valores apareçam em escadinha.
    
    # --- Ciclo T1 (Imediato para Linha 0) ---
    # O Cocotb lê o estado atual (logo após a borda do T0)
    out = unpack_vector(dut.data_out.value)
    log_info(f"Saída T+0: {out}")
    
    # Linha 0 deve ter o dado (10). As outras ainda devem ser 0 (reset).
    if out[0] != 10: assert False, f"Erro Linha 0! Esperado 10, veio {out[0]}"
    if out[1] != 0:  assert False, "Erro Linha 1! Deveria ser 0 ainda."

    # --- Ciclo T2 ---
    await RisingEdge(dut.clk)
    out = unpack_vector(dut.data_out.value)
    log_info(f"Saída T+1: {out}")
    
    if out[1] != 20: assert False, f"Erro Linha 1! Esperado 20, veio {out[1]}"
    if out[0] != 0:  assert False, "Erro Linha 0! Deveria ser 0 (bolha)."

    # --- Ciclo T3 ---
    await RisingEdge(dut.clk)
    out = unpack_vector(dut.data_out.value)
    log_info(f"Saída T+2: {out}")
    if out[2] != 30: assert False, f"Erro Linha 2! Esperado 30, veio {out[2]}"

    # --- Ciclo T4 ---
    await RisingEdge(dut.clk)
    out = unpack_vector(dut.data_out.value)
    log_info(f"Saída T+3: {out}")
    if out[3] != 40: assert False, f"Erro Linha 3! Esperado 40, veio {out[3]}"

    log_success("Skew Triangular verificado com sucesso.")


# ==============================================================================
# TESTE 2: VALID FLAG (INJEÇÃO DE BOLHAS)
# ==============================================================================
@cocotb.test()
async def test_buffer_valid_logic(dut):
    
    # Verifica se valid_in='0' força a entrada de zeros, ignorando data_in.
    
    log_header("TESTE 2: LÓGICA DE VALID_IN")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    # Reset
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # Tentar injetar LIXO com valid=0
    dut.valid_in.value = 0
    dut.data_in.value = pack_vector([99, 99, 99, 99]) # Lixo
    
    await RisingEdge(dut.clk) # Processa T0
    
    # Verificar Linha 0 (que é direta)
    out = unpack_vector(dut.data_out.value)
    if out[0] != 0:
        log_error(f"Falha! valid_in=0 mas passou dado: {out[0]}")
        assert False
    else:
        log_success("valid_in=0 bloqueou a entrada corretamente (Bolha Inserida).")


# ==============================================================================
# TESTE 3: STREAM CONTÍNUO (PIPELINE CHEIO)
# ==============================================================================
@cocotb.test()
async def test_buffer_stream(dut):
    
    # Envia vetores consecutivos: V1=[1,1..], V2=[2,2..], V3=[3,3..]
    # Verifica se a saída forma a diagonal correta.
    
    log_header("TESTE 3: STREAM CONTÍNUO")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # Sequência de entrada
    inputs = [
        [1, 1, 1, 1],
        [2, 2, 2, 2],
        [3, 3, 3, 3],
        [4, 4, 4, 4]
    ]
    
    log_info("Injetando stream contínuo...")
    
    # Loop de Injeção e Captura
    captured = []
    
    # Rodar por tempo suficiente para tudo sair (4 inputs + 4 latencia)
    for t in range(10):
        # 1. Escrever Entrada
        if t < len(inputs):
            dut.valid_in.value = 1
            dut.data_in.value = pack_vector(inputs[t])
        else:
            dut.valid_in.value = 0 # Padding
            
        await RisingEdge(dut.clk)
        
        # 2. Ler Saída (Resultado do processamento da borda anterior)
        out = unpack_vector(dut.data_out.value)
        captured.append(out)
        # log_info(f"T={t}: {out}")

    # Validação Cruzada:
    # Saída esperada na linha R no tempo T deve ser igual à Entrada[T-R][R]
    
    for t, out_vec in enumerate(captured):
        for r in range(ROWS):
            # Qual vetor de entrada deveria estar saindo na linha 'r' neste tempo 't'?
            input_idx = t - r
            
            expected_val = 0
            if 0 <= input_idx < len(inputs):
                expected_val = inputs[input_idx][r]
            
            if out_vec[r] != expected_val:
                log_error(f"Erro no Tempo {t}, Linha {r}.")
                log_error(f"  Esperado: {expected_val} (do Input {input_idx})")
                log_error(f"  Obtido:   {out_vec[r]}")
                assert False

    log_success("Stream processado corretamente! Diagonal formada.")