# ==============================================================================
# File: tb/test_fifo_sync.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from test_utils import *

# Configuração
DEPTH = 16
DATA_W = 8

@cocotb.test()
async def test_fifo_logic(dut):
    log_header("TESTE FIFO SYNC (READY/VALID)")
    
    # 1. Setup
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.w_valid.value = 0
    dut.w_data.value = 0
    dut.r_ready.value = 0
    
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    log_info("Reset liberado.")

    # --------------------------------------------------------------------------
    # CENÁRIO 1: Escrita e Leitura Básica (Sequencial)
    # --------------------------------------------------------------------------
    log_info(">>> Cenário 1: Write 1 -> Read 1")
    
    # Escreve o valor 42
    dut.w_valid.value = 1
    dut.w_data.value = 42
    await RisingEdge(dut.clk)
    
    # Tira o valid (parou de escrever)
    dut.w_valid.value = 0
    
    await Timer(1, unit='ns') 
    
    # Verifica se a FIFO diz que tem dados
    if dut.r_valid.value != 1:
        log_error("FIFO deveria estar com r_valid=1")
        assert False
    
    # Lê o dado
    received = int(dut.r_data.value)
    if received != 42:
        log_error(f"Dado incorreto. Esp: 42, Rec: {received}")
        assert False
    
    # Confirma a leitura (POP)
    dut.r_ready.value = 1
    await RisingEdge(dut.clk)
    dut.r_ready.value = 0
    
    # Verifica se esvaziou
    await Timer(1, unit='ns')
    if dut.r_valid.value != 0:
        log_error("FIFO deveria estar vazia (r_valid=0)")
        assert False
        
    log_success("Teste Básico OK.")

    # --------------------------------------------------------------------------
    # CENÁRIO 2: Encher a FIFO (Full Flag Test)
    # --------------------------------------------------------------------------
    log_info(f">>> Cenário 2: Enchendo a FIFO ({DEPTH} itens)")
    
    expected_data = []
    
    # Escreve até encher
    for i in range(DEPTH):
        val = i + 10
        expected_data.append(val)
        
        dut.w_valid.value = 1
        dut.w_data.value = val
        
        # Verifica se antes de escrever ela dizia que podia
        if dut.w_ready.value == 0:
            log_error(f"FIFO disse FULL antes da hora (item {i})")
            assert False
            
        await RisingEdge(dut.clk)

    dut.w_valid.value = 0
    await Timer(1, unit='ns')
    
    # Agora deve estar cheia
    if dut.w_ready.value == 1:
        log_error("FIFO deveria estar CHEIA (w_ready=0), mas aceita dados.")
        assert False
    
    log_success("FIFO encheu corretamente.")

    # --------------------------------------------------------------------------
    # CENÁRIO 3: Esvaziar a FIFO (Drain Test)
    # --------------------------------------------------------------------------
    log_info(">>> Cenário 3: Esvaziando a FIFO")
    
    for i in range(DEPTH):

        await Timer(1, unit='ns') 

        if dut.r_valid.value == 0:
            log_error(f"FIFO indicou vazia cedo demais (item {i})")
            assert False
            
        # Confere dado (sem dar pop ainda)
        rec = int(dut.r_data.value)
        exp = expected_data[i]
        
        if rec != exp:
            log_error(f"Erro de Ordem FIFO. Esp: {exp}, Rec: {rec}")
            assert False
            
        # Dá o POP
        dut.r_ready.value = 1
        await RisingEdge(dut.clk)
        
        # Pausa aleatória na leitura (para testar se o dado segura)
        dut.r_ready.value = 0
        await RisingEdge(dut.clk)

    await Timer(1, unit='ns')
    if dut.r_valid.value == 1:
        log_error("FIFO deveria estar VAZIA após ler tudo.")
        assert False
        
    log_success("FIFO esvaziou corretamente.")

    # --------------------------------------------------------------------------
    # CENÁRIO 4: Leitura e Escrita Simultânea (Throughput)
    # --------------------------------------------------------------------------
    log_info(">>> Cenário 4: R/W Simultâneo")
    
    # Enche metade
    for i in range(5):
        dut.w_valid.value = 1
        dut.w_data.value = i + 100
        await RisingEdge(dut.clk)
    
    # Agora escreve 200 e lê (o 100) no mesmo ciclo
    dut.w_valid.value = 1
    dut.w_data.value = 200
    dut.r_ready.value = 1 # Vai ler o 100
    
    await RisingEdge(dut.clk)
    dut.w_valid.value = 0
    dut.r_ready.value = 0
    
    # O próximo a sair deve ser 101
    await Timer(1, unit='ns')
    if int(dut.r_data.value) != 101:
         log_error(f"Erro no ponteiro após R/W simultâneo. Leu: {int(dut.r_data.value)}")
         assert False

    log_success("R/W Simultâneo OK.")