# ==============================================================================
# File: test_npu_top.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from test_utils import *
import random

# ==============================================================================
# CONSTANTES
# ==============================================================================

REG_STATUS     = 0x00
REG_CMD        = 0x04
REG_CONFIG     = 0x08
REG_WRITE_W    = 0x10
REG_WRITE_A    = 0x14
REG_READ_OUT   = 0x18
REG_QUANT_CFG  = 0x40
REG_QUANT_MULT = 0x44
REG_FLAGS      = 0x48
REG_BIAS_BASE  = 0x80

STATUS_DONE      = (1 << 1)
STATUS_OUT_VALID = (1 << 3)
CMD_RST_PTRS   = 0x01
CMD_START      = 0x02

# ==============================================================================
# HELPERS
# ==============================================================================

def log(msg, level="INFO"):
    cocotb.log.info(f"[{level}] {msg}")

def model_ppu(acc, bias, mult, shift, zero, en_relu):
    val = acc + bias
    val = val * mult
    if shift > 0:
        round_bit = 1 << (shift - 1)
        val = (val + round_bit) >> shift
    val = val + zero
    if en_relu and val < 0: val = 0
    if val > 127: return 127
    if val < -128: return -128
    return int(val)

def pack_int8(values):
    """Empacota 4 bytes em 1 int32 (Little Endian). Values[0] -> LSB"""
    packed = 0
    for i, val in enumerate(values):
        val_8bit = val & 0xFF
        packed |= (val_8bit << (i * 8))
    return packed

def unpack_int8(packed):
    """Desempacota 1 int32 em 4 bytes (com sinal)"""
    values = []
    for i in range(4):
        raw = (packed >> (i * 8)) & 0xFF
        if raw & 0x80: raw -= 256 # Conversão para sinalizado
        values.append(raw)
    return values

# ==============================================================================
# DRIVERS MMIO
# ==============================================================================

async def mmio_write(dut, addr, data):
    dut.addr_i.value = addr
    dut.data_i.value = data
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1: break
            
    dut.vld_i.value = 0
    dut.we_i.value  = 0
    await RisingEdge(dut.clk) 

async def mmio_read(dut, addr):
    dut.addr_i.value = addr
    dut.we_i.value   = 0
    dut.vld_i.value  = 1
    data = 0
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1:
            data = int(dut.data_o.value)
            break
    dut.vld_i.value = 0
    await RisingEdge(dut.clk) 
    return data

async def reset_dut(dut):
    dut.rst_n.value = 0
    await Timer(20, unit="ns") 
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def npu_load_memory(dut, matrix_A, matrix_B, k_dim):
    """
    matrix_A: Esperado no formato [Row][Col] (Python Lists)
    matrix_B: Esperado no formato [Row][Col] (Python Lists)
    
    Hardware Input Mapping:
    - Write A: Recebe COLUNAS de A (paralelismo espacial)
    - Write W: Recebe LINHAS de B (paralelismo espacial)
    """
    await mmio_write(dut, REG_CMD, CMD_RST_PTRS)
    
    for k in range(k_dim):
        # Pega a coluna k da matriz A (Input Acts)
        col_A = [matrix_A[r][k] for r in range(4)]
        # Pega a linha k da matriz B (Weights)
        row_B = matrix_B[k] 
        
        await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
        await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))

async def npu_run_and_wait(dut, run_size):
    await mmio_write(dut, REG_CONFIG, run_size)
    await mmio_write(dut, REG_CMD, CMD_START)
    
    for _ in range(2000): 
        status = await mmio_read(dut, REG_STATUS)
        if status & STATUS_DONE: return True
        await RisingEdge(dut.clk)
    return False

# ==============================================================================
# TESTES
# ==============================================================================

@cocotb.test()
async def test_top_identity_autonomous(dut):
    log_header("TESTE: IDENTIDADE (Modo Autônomo)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # Configs
    await mmio_write(dut, REG_QUANT_MULT, 1)
    await mmio_write(dut, REG_QUANT_CFG, 0)
    for i in range(4): await mmio_write(dut, REG_BIAS_BASE + (i*4), 0)
    
    k_dim = 4
    # Identidade 4x4
    mat_A = [[1 if r==c else 0 for c in range(k_dim)] for r in range(4)]
    mat_B = [[1 if r==c else 0 for c in range(4)] for r in range(k_dim)]
    
    log_info("Carregando BRAMs...")
    await npu_load_memory(dut, mat_A, mat_B, k_dim)
    
    log_info("Executando...")
    if not await npu_run_and_wait(dut, run_size=k_dim):
        assert False, "NPU Timeout"

    log_info("Lendo Resultados...")
    results = []
    for i in range(4):
        while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
            await RisingEdge(dut.clk)
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))

    results.reverse()

    expected = mat_A 
    
    if results == expected:
         log_success("SUCESSO: Identidade Verificada!")
    else:
         log_error(f"FALHA! Lido: {results} | Esperado: {expected}", "ERROR")
         assert results == expected

@cocotb.test()
async def test_top_fuzzing_autonomous(dut):
    log_header("TESTE: FUZZING (Buffer Completo)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    NUM_ROUNDS = 3
    for round_idx in range(NUM_ROUNDS):
        log_info(f"--- Round {round_idx+1} ---")
        await reset_dut(dut)
        
        q_mult  = random.randint(1, 10)
        q_shift = random.randint(0, 2)
        q_zero  = random.randint(-5, 5)
        bias_vec = [random.randint(-20, 20) for _ in range(4)]
        
        await mmio_write(dut, REG_QUANT_MULT, q_mult)
        await mmio_write(dut, REG_QUANT_CFG, ((q_zero & 0xFF) << 8) | (q_shift & 0x1F))
        for i in range(4): await mmio_write(dut, REG_BIAS_BASE + (i*4), bias_vec[i])

        K_DIM = 16 
        mat_A = [[random.randint(-5, 5) for _ in range(K_DIM)] for _ in range(4)]
        mat_B = [[random.randint(-5, 5) for _ in range(4)] for _ in range(K_DIM)]

        # Modelo de Referência (Python)
        acc_ref = [[0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                acc_ref[r][c] = sum(mat_A[r][k] * mat_B[k][c] for k in range(K_DIM))
        
        final_ref = [[0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                final_ref[r][c] = model_ppu(acc_ref[r][c], bias_vec[c], q_mult, q_shift, q_zero, False)

        await npu_load_memory(dut, mat_A, mat_B, K_DIM)
        await npu_run_and_wait(dut, run_size=K_DIM)
        
        results = []
        for _ in range(4):
            while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                await RisingEdge(dut.clk)
            results.append(unpack_int8(await mmio_read(dut, REG_READ_OUT)))
        
        results.reverse()

        # Verifica se o resultado bate (considerando ordem direta das linhas)
        if results == final_ref:
            log_success(f"Round {round_idx+1} OK")
        else:
            log_error(f"Round {round_idx+1} FAIL", "ERROR")
            log_warning(f"Ref: {final_ref}")
            log_warning(f"Got: {results}")
            assert False