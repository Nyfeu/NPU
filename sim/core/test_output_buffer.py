# ==============================================================================
# File: test_output_buffer.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from test_utils import *

# Configurações
COLS = 4
ACC_WIDTH = 32

# Helpers
def pack_acc_vector(values):
    packed = 0
    for i, val in enumerate(values):
        mask = (1 << ACC_WIDTH) - 1
        packed |= ((val & mask) << (i * ACC_WIDTH))
    return packed

def unpack_acc_vector(packed_val):
    try:
        val_int = int(packed_val)
    except ValueError:
        val_int = 0
    unpacked = []
    mask = (1 << ACC_WIDTH) - 1
    for i in range(COLS):
        raw = (val_int >> (i * ACC_WIDTH)) & mask
        if raw & (1 << (ACC_WIDTH - 1)): raw -= (1 << ACC_WIDTH)
        unpacked.append(raw)
    return unpacked

@cocotb.test()
async def test_output_deskew(dut):
    log_header("TESTE OUTPUT BUFFER (DESKEW)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # 1. Reset Robusto
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.data_in.value = 0
    
    # Configura para modo Pass-Through (Não acumular, apenas alinhar e sair)
    dut.acc_clear.value = 1 
    dut.acc_dump.value  = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    # 2. Injetar Sequência Diagonal
    # Queremos: [10, 20, 30, 40]
    target = [10, 20, 30, 40]
    
    log_info("Injetando dados...")
    dut.valid_in.value = 1
    
    # Envia os dados escalonados:
    # T=0: Col 0 envia 10 (as outras enviam 0)
    # T=1: Col 1 envia 20 (as outras enviam 0)
    # ...
    for t in range(COLS):
        vec = [0] * COLS
        vec[t] = target[t]
        dut.data_in.value = pack_acc_vector(vec)
        await RisingEdge(dut.clk)
        
    dut.valid_in.value = 0
    dut.data_in.value = 0

    # 3. Esperar Saída
    # O pipeline tem uma latência intrínseca para alinhar o maior atraso.
    # Esperamos até valid_out subir.
    
    cycles = 0
    while dut.valid_out.value == 0:
        await RisingEdge(dut.clk)
        cycles += 1
        if cycles > 10:
            log_error("Timeout esperando valid_out")
            assert False

    # 4. Verificar
    res = unpack_acc_vector(dut.data_out.value)
    log_info(f"Saída: {res}")
    
    if res == target:
        log_success("Sucesso! Deskew funcionou.")
    else:
        log_error(f"Falha. Esperado {target}, Recebido {res}")
        assert False

@cocotb.test()
async def test_valid_signal_delay(dut):
    log_header("TESTE VALID SIGNAL")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.acc_clear.value = 1 
    dut.acc_dump.value  = 1
    
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk) # Garante reset solto
    
    # Pulso único
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    
    # Espera subir
    latency = 0
    for _ in range(10):
        if dut.valid_out.value == 1:
            break
        await RisingEdge(dut.clk)
        latency += 1
        
    log_info(f"Latência medida: {latency} ciclos")
    
    if dut.valid_out.value == 1:
        log_success("Sinal Valid propagou corretamente.")
    else:
        log_error("Sinal Valid nunca subiu.")
        assert False