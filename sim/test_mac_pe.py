# ==============================================================================
# File: tb/test_mac_pe.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import random
from test_utils import *

# Constantes baseadas no npu_pkg (8 bits dados, 32 bits acc)
MIN_DATA = -128
MAX_DATA = 127
MIN_ACC  = -2147483648
MAX_ACC  = 2147483647

async def reset_dut(dut):
    """Helper para resetar o DUT"""
    dut.rst_n.value = 0
    dut.load_weight.value = 0
    dut.weight_in.value = 0
    dut.act_in.value = 0
    dut.acc_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

# ==============================================================================
# TESTE 1: FUNCIONALIDADE BÁSICA (Reset e Carga)
# ==============================================================================
@cocotb.test()
async def test_01_loading(dut):
    
    # Verifica o Reset e o Carregamento de Pesos (Weight Stationary).
    
    log_header("TESTE 1: RESET E CARGA DE PESOS")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # 1. Carregar Peso Positivo
    TEST_WEIGHT = 42
    dut.load_weight.value = 1
    dut.weight_in.value = TEST_WEIGHT
    await RisingEdge(dut.clk) 
    
    # 2. Verificar Propagação 
    await RisingEdge(dut.clk)
    
    read_weight = dut.weight_out.value.to_signed()
    if read_weight == TEST_WEIGHT:
        log_success(f"Peso {TEST_WEIGHT} carregado com sucesso.")
    else:
        log_error(f"Erro Carga. Esperado {TEST_WEIGHT}, lido {read_weight}")
        assert False

    # 3. Verificar Retenção (Weight Stationary)
    dut.load_weight.value = 0
    dut.weight_in.value = 0 
    await RisingEdge(dut.clk)
    
    read_weight = dut.weight_out.value.to_signed()
    if read_weight == TEST_WEIGHT:
        log_success("Peso retido corretamente.")
    else:
        log_error("Peso foi perdido após desativar load_weight!")
        assert False

# ==============================================================================
# TESTE 2: CASOS DE BORDA (Zeros, Máximos e Mínimos)
# ==============================================================================
@cocotb.test()
async def test_02_edge_cases(dut):
    
    # Verifica limites matemáticos: Zero, Max Positivo, Max Negativo.
    
    log_header("TESTE 2: CASOS DE BORDA")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # Lista de Casos de Teste (Tuplas: Peso, Ativação, Acumulador Entrada)
    test_cases = [
        # (Weight, Act, Acc_In)
        (0,        100,  50),         # Multiplicação por Zero (Peso)
        (50,       0,    50),         # Multiplicação por Zero (Input)
        (1,        1,    MAX_ACC-1),  # Limite do Acumulador
        (MAX_DATA, 1,    0),          # Max Positivo
        (MIN_DATA, 1,    0),          # Max Negativo (-128)
        (-1,       -1,   0),          # Menos com Menos (deve dar +1)
        (MAX_DATA, MAX_DATA, 0)       # Max * Max (127*127 = 16129)
    ]

    for w, act, acc in test_cases:

        # 1. Carregar Peso
        dut.load_weight.value = 1
        dut.weight_in.value = w
        await RisingEdge(dut.clk)

        # 2. Executar
        dut.load_weight.value = 0
        dut.act_in.value = act
        dut.acc_in.value = acc
        await RisingEdge(dut.clk)

        # 3. Verificar (Lembrando da latência de 1 ciclo do Acc_out)
        await RisingEdge(dut.clk)
        
        result = dut.acc_out.value.to_signed()
        expected = acc + (w * act)
        
        # Clamp para simular overflow de 32 bits 
        if expected > MAX_ACC: expected -= (2**32)
        if expected < MIN_ACC: expected += (2**32)

        if result == expected:
            log_success(f"PASS: {acc} + ({w} * {act}) = {result}")
        else:
            log_error(f"FAIL: {acc} + ({w} * {act}). Esperado {expected}, Veio {result}")
            assert False

# ==============================================================================
# TESTE 3: FUZZING (Stress Test Aleatório)
# ==============================================================================
@cocotb.test()
async def test_03_fuzzing(dut):
    
    # Injeta centenas de valores aleatórios e compara com modelo em Python.
    
    log_header("TESTE 3: FUZZING (RANDOMIZED)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    NUM_SAMPLES = 100
    
    for i in range(NUM_SAMPLES):
        # 1. Gera valores aleatórios dentro do range de 8 bits / 32 bits
        w = random.randint(MIN_DATA, MAX_DATA)
        act = random.randint(MIN_DATA, MAX_DATA)
        acc = random.randint(-1000000, 1000000) 

        # 2. Carrega Peso
        dut.load_weight.value = 1
        dut.weight_in.value = w
        await RisingEdge(dut.clk)

        # 3. Executa
        dut.load_weight.value = 0
        dut.act_in.value = act
        dut.acc_in.value = acc
        await RisingEdge(dut.clk)

        # 4. Verifica
        await RisingEdge(dut.clk)
        
        hw_result = dut.acc_out.value.to_signed()
        sw_model = acc + (w * act)

        if hw_result != sw_model:
            log_error(f"ERRO DE FUZZING na iteração {i}!")
            log_int(f"Entradas: W={w}, Act={act}, Acc={acc}")
            log_int(f"Hardware: {hw_result}")
            log_int(f"Esperado: {sw_model}")
            assert False
            
    log_success(f"Sucesso! {NUM_SAMPLES} vetores aleatórios verificados sem erros. 🚀")