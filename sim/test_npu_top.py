# ==============================================================================
# File: test_npu_top.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ClockCycles
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

STATUS_BUSY      = (1 << 0)
STATUS_DONE      = (1 << 1)
STATUS_OUT_VALID = (1 << 3)

CMD_RST_DMA_PTRS = (1 << 0)
CMD_START        = (1 << 1)
CMD_ACC_CLEAR    = (1 << 2)
CMD_NO_DRAIN     = (1 << 3)
CMD_RST_W_RD     = (1 << 4)
CMD_RST_I_RD     = (1 << 5)

# ==============================================================================
# HELPERS
# ==============================================================================

def clamp_int8(val):
    if val > 127: return 127
    if val < -128: return -128
    return int(val)

def model_ppu(acc, bias, mult, shift, zero, en_relu):
    val = acc + bias
    val = val * mult
    if shift > 0:
        round_bit = 1 << (shift - 1)
        val = (val + round_bit) >> shift
    val = val + zero
    if en_relu and val < 0: val = 0
    return clamp_int8(val)

def pack_int8(values):
    packed = 0
    for i, val in enumerate(values):
        val_8bit = val & 0xFF
        packed |= (val_8bit << (i * 8))
    return packed

def unpack_int8(packed):
    values = []
    for i in range(4):
        raw = (packed >> (i * 8)) & 0xFF
        if raw & 0x80: raw -= 256
        values.append(raw)
    return values

# ==============================================================================
# DRIVERS MMIO
# ==============================================================================

async def mmio_write(dut, addr, data):
    dut.addr_i.value = addr
    dut.data_i.value = int(data)
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1: break
            
    dut.vld_i.value = 0
    dut.we_i.value  = 0
    dut.addr_i.value = 0 # Limpa bus
    dut.data_i.value = 0
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
    dut.addr_i.value = 0
    await RisingEdge(dut.clk) 
    return data

async def reset_dut(dut):
    # Inicialização segura para evitar Metavalues
    dut.vld_i.value  = 0
    dut.we_i.value   = 0
    dut.addr_i.value = 0
    dut.data_i.value = 0
    
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

async def npu_load_memory(dut, matrix_A, matrix_B, k_dim):
    await mmio_write(dut, REG_CMD, CMD_RST_DMA_PTRS)
    for k in range(k_dim):
        col_A = [matrix_A[r][k] for r in range(4)]
        row_B = matrix_B[k]
        await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
        await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))

async def npu_start(dut, run_size):
    await mmio_write(dut, REG_CONFIG, run_size)
    # Start + Reset Read Pointers + Clear Acc
    await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)

# ==============================================================================
# TESTES
# ==============================================================================

@cocotb.test()
async def test_top_identity_autonomous(dut):
    log_header("TESTE 1: IDENTIDADE (Verificação Básica)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    await mmio_write(dut, REG_QUANT_MULT, 1)
    await mmio_write(dut, REG_QUANT_CFG, 0)
    for i in range(4): await mmio_write(dut, REG_BIAS_BASE + (i*4), 0)
    
    k_dim = 4
    mat_A = [[1 if r==c else 0 for c in range(k_dim)] for r in range(4)]
    mat_B = [[1 if r==c else 0 for c in range(4)] for r in range(k_dim)]
    
    log_info("Carregando...")
    await npu_load_memory(dut, mat_A, mat_B, k_dim)
    
    log_info("Executando...")
    await npu_start(dut, k_dim)
    
    results = []
    for i in range(4):
        while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
            await RisingEdge(dut.clk)
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))

    results.reverse()
    if results == mat_A:
        log_success("Identidade OK!")
    else:
        log_error(f"Falha! {results}")
        assert False

@cocotb.test()
async def test_security_busy_lock(dut):
    log_header("TESTE 2: BUSY LOCK (Proteção contra Escrita)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # 1. Configuração Correta
    CORRECT_MULT = 1
    await mmio_write(dut, REG_QUANT_MULT, CORRECT_MULT)
    await mmio_write(dut, REG_QUANT_CFG, 0)
    
    # 2. Dados (Matriz Identidade)
    K_DIM = 64 # Run longo para dar tempo de "atacar"
    mat_A = [[10]*K_DIM for _ in range(4)] 
    mat_B = [[1]*4 for _ in range(K_DIM)] # Resultado deve ser 10*64 = 640 -> Clamped to 127
    
    await npu_load_memory(dut, mat_A, mat_B, K_DIM)
    
    # 3. Iniciar Execução
    log_info("Iniciando Run Longo...")
    await npu_start(dut, K_DIM)
    
    # 4. O ATAQUE!
    # Tentar mudar o Multiplicador para 0 enquanto BUSY
    # Se o Lock falhar, o resultado será 0. Se funcionar, será 127.
    await ClockCycles(dut.clk, 10) # Espera entrar em Compute
    
    busy_status = await mmio_read(dut, REG_STATUS)
    if not (busy_status & STATUS_BUSY):
        log_error("NPU deveria estar BUSY para o teste valer!")
    
    log_info("Tentando sobrescrever configuração durante execução...")
    await mmio_write(dut, REG_QUANT_MULT, 0) # <--- TENTATIVA DE SABOTAGEM
    
    # 5. Esperar terminar
    while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0:
        await ClockCycles(dut.clk, 10)
        
    # 6. Verificar Resultado
    results = []
    for _ in range(4):
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
    
    # Se o resultado for 0, o ataque funcionou (FALHA DE SEGURANÇA)
    # Se o resultado for 127, o ataque foi bloqueado (SUCESSO)
    sample_val = results[0][0]
    log_info(f"Valor lido: {sample_val} (Esperado: 127)")
    
    if sample_val == 0:
        log_error("FALHA: Configuração foi sobrescrita durante execução!")
        assert False
    elif sample_val == 127:
        log_success("SUCESSO: Escrita bloqueada pelo Busy Lock.")
    else:
        log_warning(f"Resultado inesperado: {sample_val}")

@cocotb.test()
async def test_output_backpressure(dut):
    log_header("TESTE 3: BACKPRESSURE (Leitura Tardia)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # Configuração Simples
    await mmio_write(dut, REG_QUANT_MULT, 1)
    await mmio_write(dut, REG_QUANT_CFG, 0)
    
    K_DIM = 4
    mat_A = [[5]*K_DIM for _ in range(4)]
    mat_B = [[1]*4 for _ in range(K_DIM)]
    # Resultado esperado: 5 * 4 = 20
    
    await npu_load_memory(dut, mat_A, mat_B, K_DIM)
    await npu_start(dut, K_DIM)
    
    log_info("NPU rodando... Simulando CPU lenta...")
    
    # Espera a NPU terminar internamente e ficar "travada" na FIFO
    # Se não houver backpressure/FIFO logic, os dados poderiam ser sobrescritos ou perdidos
    await ClockCycles(dut.clk, 500) 
    
    status = await mmio_read(dut, REG_STATUS)
    log_info(f"Status após espera: {bin(status)}")
    
    if not (status & STATUS_OUT_VALID):
        log_error("FALHA: FIFO vazia após espera (Dados perdidos?)")
        assert False
        
    # Ler agora
    results = []
    for _ in range(4):
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
    
    if results[0][0] == 20:
        log_success("SUCESSO: Dados preservados após espera (FIFO Backpressure OK).")
    else:
        log_error(f"FALHA: Dados corrompidos. Lido: {results[0][0]}")
        assert False