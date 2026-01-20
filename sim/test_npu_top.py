# ==============================================================================
# File: test_npu_top.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
import test_utils 

# ENDEREÇOS
REG_CTRL       = 0x00
REG_QUANT_CFG  = 0x04
REG_QUANT_MULT = 0x08
REG_STATUS     = 0x0C
REG_WRITE_W    = 0x10 
REG_WRITE_A    = 0x14 
REG_READ_OUT   = 0x18 
REG_BIAS_BASE  = 0x20

STATUS_OUT_VALID  = (1 << 3)

# ==============================================================================
# HELPERS
# ==============================================================================

def print_matrix_colored(matrix, name="Matrix"):
    """Imprime matriz usando o logger do test_utils"""
    test_utils.log_info(f"--- {name} ---")
    for row in matrix:
        row_str = " | ".join([f"{val:4d}" for val in row])
        cocotb.log.info(f"  [ {row_str} ]")

def model_ppu(acc, bias, mult, shift, zero, en_relu):
    """Modelo Python da PPU para validação do Fuzzing"""
    # 1. Bias
    val = acc + bias
    # 2. Mult (Fixed Point)
    val = val * mult
    # 3. Shift
    if shift > 0:
        round_bit = 1 << (shift - 1)
        val = (val + round_bit) >> shift
    # 4. Zero Point
    val = val + zero
    # 5. ReLU
    if en_relu and val < 0:
        val = 0
    # 6. Clamp (Int8)
    if val > 127: return 127
    if val < -128: return -128
    return int(val)

# ==============================================================================
# DRIVERS MMIO (COM FIX DE TIMING REFORÇADO)
# ==============================================================================

async def mmio_write(dut, addr, data):
    dut.addr_i.value = addr
    dut.data_i.value = data
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    while True:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1:
            break
    dut.vld_i.value = 0
    dut.we_i.value  = 0
    await RisingEdge(dut.clk) 
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
    await RisingEdge(dut.clk)
    return data

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

async def reset_dut(dut):
    """Hard Reset: Garante estado limpo da NPU"""
    dut.rst_n.value = 0
    await Timer(20, unit="ns") 
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    for _ in range(5): await RisingEdge(dut.clk)

# ==============================================================================
# TESTES
# ==============================================================================

@cocotb.test()
async def test_top_identity(dut):
    test_utils.log_header("TESTE: IDENTIDADE 4x4 (No Quantization)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    await mmio_write(dut, REG_QUANT_MULT, 1)
    await mmio_write(dut, REG_QUANT_CFG, 0)
    for i in range(4): await mmio_write(dut, REG_BIAS_BASE + (i*4), 0)
    
    await mmio_write(dut, REG_CTRL, 0x04) 
    await mmio_write(dut, REG_CTRL, 0x00)

    for k in range(4):
        col_A = [1 if r==k else 0 for r in range(4)]
        row_B = [1 if c==k else 0 for c in range(4)]
        await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
        await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))

    test_utils.log_info("Aguardando processamento...")
    for _ in range(40): await RisingEdge(dut.clk)

    await mmio_write(dut, REG_CTRL, 0x08) # Dump
    
    results = []
    for i in range(4):
        # Timeout safety para evitar travar se não houver dados
        timeout = 0
        while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
            await RisingEdge(dut.clk)
            timeout += 1
            if timeout > 100:
                test_utils.log_error("Timeout esperando STATUS_OUT_VALID")
                break
        
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
    
    await mmio_write(dut, REG_CTRL, 0x00)

    expected = [[0,0,0,1], [0,0,1,0], [0,1,0,0], [1,0,0,0]]
    
    if results == expected:
        test_utils.log_success("Identidade Verificada com Sucesso!")
    else:
        test_utils.log_error(f"Falha! Esp: {expected}, Lido: {results}")
        assert False

@cocotb.test()
async def test_top_fuzzing(dut):
    test_utils.log_header("TESTE: FUZZING (Random Inputs + Quantization)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    NUM_ROUNDS = 5

    for round_idx in range(NUM_ROUNDS):
        test_utils.log_info(f"--- Fuzz Round {round_idx+1}/{NUM_ROUNDS} ---")
        
        # HARD RESET: A única forma garantida de limpar acumuladores se o Soft Clear falhar
        await reset_dut(dut)
        
        # Randomizar Configuração
        q_mult  = random.randint(1, 20)
        q_shift = random.randint(0, 4)
        q_zero  = random.randint(-5, 5)
        
        cfg_val = ((q_zero & 0xFF) << 8) | (q_shift & 0x1F)
        
        await mmio_write(dut, REG_QUANT_MULT, q_mult)
        await mmio_write(dut, REG_QUANT_CFG, cfg_val)
        
        bias_vec = [random.randint(-50, 50) for _ in range(4)]
        for i in range(4):
            await mmio_write(dut, REG_BIAS_BASE + (i*4), bias_vec[i])

        test_utils.log_info(f"Config: Mult={q_mult}, Shift={q_shift}, Zero={q_zero}, Bias={bias_vec}")

        # Randomizar Matrizes
        K_DIM = 8
        A = [[random.randint(-10, 10) for _ in range(K_DIM)] for _ in range(4)]
        B = [[random.randint(-10, 10) for _ in range(4)] for _ in range(K_DIM)]

        # Calcular Referência (Python)
        acc_ref = [[0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                acc_ref[r][c] = sum(A[r][k] * B[k][c] for k in range(K_DIM))

        final_ref = [[0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                final_ref[r][c] = model_ppu(acc_ref[r][c], bias_vec[c], q_mult, q_shift, q_zero, False)

        # Inverter referência (Hardware lê de baixo pra cima: Row3...Row0)
        final_ref_ordered = final_ref[::-1]

        # Executar Hardware
        for k in range(K_DIM):
            col_A = [A[r][k] for r in range(4)]
            row_B = [B[k][c] for c in range(4)]
            await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
            await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))

        for _ in range(60): await RisingEdge(dut.clk)

        await mmio_write(dut, REG_CTRL, 0x08) # Dump
        
        results = []
        for _ in range(4):
            # Polling com timeout
            tries = 0
            while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
                await RisingEdge(dut.clk)
                tries += 1
                if tries > 200: break # Evita loop infinito se HW travar
            
            results.append(unpack_int8(await mmio_read(dut, REG_READ_OUT)))
        
        await mmio_write(dut, REG_CTRL, 0x00)

        # Comparar
        if results == final_ref_ordered:
            test_utils.log_success(f"Round {round_idx+1} OK")
        else:
            test_utils.log_error(f"Round {round_idx+1} FAIL")
            print_matrix_colored(final_ref_ordered, "Esperado")
            print_matrix_colored(results, "Lido")
            assert False