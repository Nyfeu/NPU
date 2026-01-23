# ==============================================================================
# File: test_npu_top.py (ULTIMATE STRESS EDITION)
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
import random
from test_utils import *

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
CMD_RST_WR_W     = (1 << 6)
CMD_RST_WR_I     = (1 << 7)

# ==============================================================================
# MODELO DE REFERÊNCIA
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

def compute_ref(mat_A, mat_B, k_dim, bias, mult, shift, zero, en_relu):
    acc_matrix = [[0]*4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            acc_matrix[r][c] = sum(mat_A[r][k] * mat_B[k][c] for k in range(k_dim))
            
    final_out = []
    for r in range(4):
        row_res = []
        for c in range(4):
            val = model_ppu(acc_matrix[r][c], bias[c], mult, shift, zero, en_relu)
            row_res.append(val)
        final_out.append(row_res)
    return final_out

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
    dut.data_i.value = int(data) & 0xFFFFFFFF
    dut.we_i.value   = 1
    dut.vld_i.value  = 1
    
    timeout = 1000
    while timeout > 0:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1: break
        timeout -= 1
            
    dut.vld_i.value = 0
    dut.we_i.value  = 0
    await RisingEdge(dut.clk) 

async def mmio_read(dut, addr):
    dut.addr_i.value = addr
    dut.we_i.value   = 0
    dut.vld_i.value  = 1
    
    data = 0
    timeout = 1000
    while timeout > 0:
        await RisingEdge(dut.clk)
        if dut.rdy_o.value == 1:
            data = int(dut.data_o.value)
            break
        timeout -= 1
    dut.vld_i.value = 0
    await RisingEdge(dut.clk) 
    return data

async def reset_dut(dut):
    dut.vld_i.value  = 0
    dut.we_i.value   = 0
    dut.addr_i.value = 0
    dut.data_i.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 10)

async def npu_setup_config(dut, mult, shift, zero, bias, en_relu=False):
    await mmio_write(dut, REG_QUANT_MULT, mult)
    await mmio_write(dut, REG_QUANT_CFG, ((zero & 0xFF) << 8) | (shift & 0x1F))
    await mmio_write(dut, REG_FLAGS, 1 if en_relu else 0)
    for i in range(4): await mmio_write(dut, REG_BIAS_BASE + (i*4), bias[i])

async def npu_load_data(dut, mat_A, mat_B, k_dim):
    await mmio_write(dut, REG_CMD, CMD_RST_DMA_PTRS)
    for k in range(k_dim):
        col_A = [mat_A[r][k] for r in range(4)]
        row_B = mat_B[k]
        await mmio_write(dut, REG_WRITE_A, pack_int8(col_A))
        await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))

# ==============================================================================
# TESTES DE TORTURA
# ==============================================================================

@cocotb.test()
async def test_corner_cases_from_hell(dut):
    """
    Testa limites matemáticos extremos:
    - Saturação máxima positiva
    - Saturação máxima negativa
    - Zeros
    - Overflow de acumulador
    """
    log_header("TESTE: CORNER CASES FROM HELL")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    corner_cases = [
        # Caso 1: Max Gain (Mult=255, Shift=0), Inputs Max -> Deve saturar em 127
        {
            "name": "MAX POSITIVE SATURATION",
            "A": 127, "B": 127, "bias": 1000, "mult": 255, "shift": 0, "zero": 0, "relu": False
        },
        # Caso 2: Max Negative (Mult=255), Bias Negativo -> Deve saturar em -128
        {
            "name": "MAX NEGATIVE SATURATION",
            "A": 127, "B": -128, "bias": -1000, "mult": 255, "shift": 0, "zero": 0, "relu": False
        },
        # Caso 3: Zeros limpos
        {
            "name": "ALL ZEROS",
            "A": 0, "B": 0, "bias": 0, "mult": 1, "shift": 0, "zero": 0, "relu": False
        },
        # Caso 4: Accumulator Stress (Muitos valores pequenos somando muito)
        # K=100, 10*10 = 100 por MAC -> 10.000 total no acc.
        {
            "name": "ACCUMULATOR STRESS",
            "A": 10, "B": 10, "bias": 0, "mult": 1, "shift": 0, "zero": 0, "relu": False
        }
    ]

    for case in corner_cases:
        log_info(f"Running: {case['name']}")
        K_DIM = 100
        mat_A = [[case["A"]]*K_DIM for _ in range(4)]
        mat_B = [[case["B"]]*4 for _ in range(K_DIM)]
        bias  = [case["bias"]]*4

        await npu_setup_config(dut, case["mult"], case["shift"], case["zero"], bias, case["relu"])
        await npu_load_data(dut, mat_A, mat_B, K_DIM)
        
        # Executa
        await mmio_write(dut, REG_CONFIG, K_DIM)
        await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
        
        while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0:
            await ClockCycles(dut.clk, 10)

        # Lê
        results = []
        for _ in range(4):
            val = await mmio_read(dut, REG_READ_OUT)
            results.append(unpack_int8(val))
        results.reverse()

        ref = compute_ref(mat_A, mat_B, K_DIM, bias, case["mult"], case["shift"], case["zero"], case["relu"])
        
        if results != ref:
            log_error(f"FALHA NO CASO {case['name']}")
            log_error(f"Esperado: {ref}")
            log_error(f"Obtido:   {results}")
            assert False
        else:
            log_success(f"{case['name']} - OK")


@cocotb.test()
async def test_chaos_monkey_mmio(dut):
    """
    Testa a resiliência do BUSY LOCK.
    Enquanto a NPU processa uma matriz grande, uma thread paralela
    tenta escrever lixo em registros críticos.
    """
    log_header("TESTE: CHAOS MONKEY (Busy Lock Stress)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    K_DIM = 128
    mat_A = [[1]*K_DIM for _ in range(4)]
    mat_B = [[1]*4 for _ in range(K_DIM)]
    bias = [0]*4
    
    # Configuração Inicial Correta
    await npu_setup_config(dut, mult=1, shift=0, zero=0, bias=bias)
    await npu_load_data(dut, mat_A, mat_B, K_DIM)

    # Inicia NPU
    log_info("Iniciando NPU...")
    await mmio_write(dut, REG_CONFIG, K_DIM)
    await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)

    # --- O MACACO DO CAOS ---
    async def chaos_monkey():
        for _ in range(50): # 50 tentativas de sabotagem
            target_reg = random.choice([REG_CONFIG, REG_QUANT_MULT, REG_WRITE_W, REG_CMD])
            garbage_data = random.randint(0, 0xFFFFFFFF)
            
            # Tenta escrever sem esperar handshake (fire and forget)
            dut.addr_i.value = target_reg
            dut.data_i.value = garbage_data
            dut.we_i.value = 1
            dut.vld_i.value = 1
            await RisingEdge(dut.clk)
            dut.vld_i.value = 0
            dut.we_i.value = 0
            
            await ClockCycles(dut.clk, random.randint(1, 5))

    # Roda o Chaos Monkey em paralelo
    chaos_task = cocotb.start_soon(chaos_monkey())

    # Espera NPU terminar
    while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0:
        await ClockCycles(dut.clk, 10)
    
    await chaos_task # Garante que o macaco parou

    # Verifica integridade
    results = []
    for _ in range(4):
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
    results.reverse()

    # Se K=128, A=1, B=1 -> Acc=128 -> Clamped to 127.
    # Se o macaco tivesse mudado o MULT para 0 ou o RUN_SIZE, daria erro.
    if results[0][0] == 127:
        log_success("Chaos Monkey falhou em quebrar a NPU! Lock funciona.")
    else:
        log_error(f"NPU foi sabotada! Resultado: {results[0][0]}")
        assert False


@cocotb.test()
async def test_backpressure_torture(dut):
    """
    Testa o BACKPRESSURE (Stall).
    Lê os resultados da FIFO com atrasos aleatórios e longos,
    forçando a FIFO a encher e o controlador a pausar o DRAIN.
    """
    log_header("TESTE: BACKPRESSURE TORTURE (Leitura Intermitente)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # Configuração
    await npu_setup_config(dut, mult=1, shift=0, zero=0, bias=[0]*4)
    
    K_DIM = 4
    # Matriz que gera valores conhecidos: Linha 0 -> 10, Linha 1 -> 20, etc.
    mat_A = [[(r+1)]*K_DIM for r in range(4)] # Linhas: 1, 2, 3, 4
    mat_B = [[10//K_DIM]*4 for _ in range(K_DIM)] # Colunas somam para dar scale
    # Na verdade, simplificando: A=1, B=1 -> Soma = K_DIM.
    # Vamos fazer: A = [[1..], [2..], [3..], [4..]], B = [[1..], ..]
    # Acc[r][c] = K_DIM * (r+1)
    
    await npu_load_data(dut, mat_A, [[1]*4]*K_DIM, K_DIM)
    
    log_info("Iniciando NPU...")
    await mmio_write(dut, REG_CONFIG, K_DIM)
    await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)

    log_info("Iniciando leitura lenta...")
    results = []
    
    # Precisamos ler 4 linhas
    for i in range(4):
        # Espera aleatória ANTES de tentar ler
        delay = random.randint(10, 200) # Delay grande
        await ClockCycles(dut.clk, delay)
        
        # Polling pelo Valid
        while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0:
            await RisingEdge(dut.clk)
            
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
        log_info(f"Leitura {i+1}/4 concluída após delay de {delay} ciclos.")

    results.reverse()
    
    expected = [[(r+1)*K_DIM]*4 for r in range(4)]
    
    if results == expected:
        log_success("Backpressure funcionou! Dados íntegros.")
    else:
        log_error(f"Falha no Backpressure. Lido: {results}, Esperado: {expected}")
        assert False


@cocotb.test()
async def test_consecutive_runs_no_reset(dut):
    """
    Testa múltiplas execuções consecutivas SEM reset de hardware (RST_N).
    Garante que a FSM limpa seus estados internos corretamente.
    """
    log_header("TESTE: 10 EXECUÇÕES CONSECUTIVAS (Sem Hard Reset)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut) # Reset inicial apenas

    for i in range(10):
        # Variamos o K a cada run para garantir que o contador limpa
        K_DIM = 4 + i 
        val_A = random.randint(1, 5)
        
        await npu_setup_config(dut, mult=1, shift=0, zero=0, bias=[0]*4)
        
        # Carga
        mat_A = [[val_A]*K_DIM for _ in range(4)]
        mat_B = [[1]*4 for _ in range(K_DIM)]
        await npu_load_data(dut, mat_A, mat_B, K_DIM)
        
        # Execução (Importante: CMD_ACC_CLEAR deve limpar o acumulador anterior)
        await mmio_write(dut, REG_CONFIG, K_DIM)
        await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
        
        # Espera
        while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0:
            await RisingEdge(dut.clk)
            
        # Leitura
        results = []
        for _ in range(4):
            val = await mmio_read(dut, REG_READ_OUT)
            results.append(unpack_int8(val))
        results.reverse()
        
        expected_val = val_A * K_DIM
        if results[0][0] != expected_val:
            log_error(f"Erro na execução {i+1}! Esperado {expected_val}, Lido {results[0][0]}")
            assert False
        
    log_success("10 execuções consecutivas passaram com sucesso.")

@cocotb.test()
async def test_locality_feature(dut):
    """
    Testa a reutilização de dados (Localidade).
    Cenário: Imagem (Input) constante, troca apenas os Pesos (Filtros).
    """
    log_header("TESTE: LOCALIDADE DE DADOS (Reuse Inputs)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    K_DIM = 4
    # Configuração Neutra
    await npu_setup_config(dut, mult=1, shift=0, zero=0, bias=[0]*4)

    # -------------------------------------------------------
    # PASSADA 1: Carrega TUDO (Input A, Peso A)
    # -------------------------------------------------------
    input_A = [[10]*K_DIM for _ in range(4)] # Inputs = 10
    weight_A = [[1]*4 for _ in range(K_DIM)] # Pesos = 1
    
    log_info("Passada 1: Carregando Input A e Peso A...")
    await npu_load_data(dut, input_A, weight_A, K_DIM)
    
    # Executa Passada 1
    await mmio_write(dut, REG_CONFIG, K_DIM)
    await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
    
    while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0: await RisingEdge(dut.clk)
    
    # Drena saída (para limpar FIFO, não precisamos validar agora)
    for _ in range(4): 
        while (await mmio_read(dut, REG_STATUS) & STATUS_OUT_VALID) == 0: await RisingEdge(dut.clk)
        await mmio_read(dut, REG_READ_OUT)

    # -------------------------------------------------------
    # PASSADA 2: Troca APENAS Pesos (Input A mantém, Peso B)
    # -------------------------------------------------------
    weight_B = [[2]*4 for _ in range(K_DIM)] # Pesos = 2
    
    log_info("Passada 2: Resetando APENAS ponteiro de Pesos...")
    # Zera ponteiro de escrita de Pesos (Bit 6), mas NÃO o de Inputs (Bit 7 ou 0)
    await mmio_write(dut, REG_CMD, CMD_RST_WR_W) 
    
    log_info("Carregando Peso B (Input A deve estar lá)...")
    for k in range(K_DIM):
        row_B = weight_B[k]
        # Escreve apenas na porta de Pesos!
        await mmio_write(dut, REG_WRITE_W, pack_int8(row_B))
        
    # Executa Passada 2 (Importante: Resetar ponteiros de LEITURA para ler do zero)
    await mmio_write(dut, REG_CMD, CMD_START | CMD_RST_W_RD | CMD_RST_I_RD | CMD_ACC_CLEAR)
    
    while (await mmio_read(dut, REG_STATUS) & STATUS_DONE) == 0: await RisingEdge(dut.clk)
    
    # Verifica Resultado: Input A (10) * Peso B (2) * K(4) = 80
    results = []
    for _ in range(4):
        val = await mmio_read(dut, REG_READ_OUT)
        results.append(unpack_int8(val))
    results.reverse()
    
    expected_val = 10 * 2 * 4 # = 80
    if results[0][0] == expected_val:
        log_success("SUCESSO: Dados de Input foram reutilizados corretamente!")
    else:
        log_error(f"FALHA: Esperado {expected_val}, Lido {results[0][0]}. (Input foi apagado?)")
        assert False