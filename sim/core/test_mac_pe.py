# ==============================================================================
# File: test_mac_pe.py
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
    """Reseta o DUT para estado conhecido"""
    dut.rst_n.value = 0
    dut.clear_acc.value = 0
    dut.drain_output.value = 0
    dut.weight_in.value = 0
    dut.act_in.value = 0
    dut.acc_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

# ==============================================================================
# TESTE 1: ACUMULAÇÃO (OS)
# ==============================================================================
@cocotb.test()
async def test_01_accumulation(dut):
    log_header("TESTE 1: ACUMULAÇÃO (OS)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # 1. Limpar
    dut.clear_acc.value = 1
    await RisingEdge(dut.clk)
    dut.clear_acc.value = 0

    # 2. Sequência de MACs: 10 + 12 + 100 = 122
    ops = [(2, 5), (3, 4), (10, 10)]
    expected = 0
    
    for w, act in ops:
        dut.weight_in.value = w
        dut.act_in.value = act
        expected += (w * act)
        await RisingEdge(dut.clk) 

    # Espera propagação
    await Timer(1, unit="ns") 
    
    val = dut.acc_out.value.to_signed()
    
    if val == expected:
        log_success(f"OK: {val} == {expected}")
    else:
        log_error(f"FALHA: Esperado {expected}, Lido {val}")
        assert False

# ==============================================================================
# TESTE 2: DRENAGEM DE DADOS (Shift Vertical)
# ==============================================================================
@cocotb.test()
async def test_02_drain(dut):
    log_header("TESTE 2: DRENAGEM (DRAIN)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # 1. Sujar o acumulador
    dut.weight_in.value = 5
    dut.act_in.value = 10
    await RisingEdge(dut.clk) # acc = 50

    # 2. Ativar Drain
    dut.drain_output.value = 1
    dut.acc_in.value = 999 
    await RisingEdge(dut.clk) 

    # Espera propagação
    await Timer(1, unit="ns")
    
    val = dut.acc_out.value.to_signed()
    if val == 999:
        log_success("OK: Drain funcionou (999).")
    else:
        log_error(f"FALHA: Esperado 999, Lido {val}")
        assert False

# ==============================================================================
# TESTE 3: FUZZING (RANDOMIZED STRESS TEST)
# ==============================================================================
@cocotb.test()
async def test_03_fuzzing(dut):
    log_header("TESTE 3: FUZZING (Stress Test Aleatório)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    NUM_EPISODES = 5      # Quantas vezes vamos zerar e começar de novo
    STEPS_PER_EPISODE = 20 # Quantas acumulações por episódio

    for episode in range(NUM_EPISODES):
        
        # 1. Limpa o acumulador no início do episódio
        dut.clear_acc.value = 1
        await RisingEdge(dut.clk)
        dut.clear_acc.value = 0
        
        expected_acc = 0
        log_info(f"--- Episódio {episode+1}/{NUM_EPISODES} ---")

        for step in range(STEPS_PER_EPISODE):
            # Gera inputs aleatórios
            w = random.randint(MIN_DATA, MAX_DATA)
            act = random.randint(MIN_DATA, MAX_DATA)
            
            # Aplica no DUT
            dut.weight_in.value = w
            dut.act_in.value = act
            
            # Modelo Python (Referência)
            expected_acc += (w * act)
            
            # Emula Overflow de 32 bits (comportamento do VHDL)
            if expected_acc > MAX_ACC: 
                expected_acc -= (2**32)
            elif expected_acc < MIN_ACC:
                expected_acc += (2**32)

            await RisingEdge(dut.clk)
            
            # Verificação com atraso delta
            await Timer(1, unit="ns")
            
            hw_result = dut.acc_out.value.to_signed()
            
            if hw_result != expected_acc:
                log_error(f"ERRO FUZZING na iteração {step}!")
                log_info(f"Inputs: W={w}, Act={act}")
                log_info(f"Hardware: {hw_result}")
                log_info(f"Esperado: {expected_acc}")
                assert False

    log_success(f"Sucesso! {NUM_EPISODES*STEPS_PER_EPISODE} vetores aleatórios verificados.")