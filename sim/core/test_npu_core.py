# ==============================================================================
# File: test_npu_core.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly
import random
from test_utils import *

# ==============================================================================
# Configurações 
# ==============================================================================

ROWS = 4
COLS = 4
DATA_WIDTH = 8
ACC_WIDTH = 32

MIN_VAL = -128
MAX_VAL = 127

# ==============================================================================
# CLASSES E FUNÇÕES AUXILIARES (REUTILIZÁVEIS)
# ==============================================================================

def pack_vec(values):
    """ Empacota lista de inteiros para sinal lógico. """
    packed = 0
    mask = (1 << DATA_WIDTH) - 1
    for i, val in enumerate(values):
        val_masked = val & mask
        packed |= (val_masked << (i * DATA_WIDTH))
    return packed

def unpack_vec(packed_val):
    """ Desempacota sinal lógico para lista de inteiros (com sinal). """
    try: val_int = int(packed_val)
    except ValueError: return [0] * COLS
    unpacked = []
    mask = (1 << ACC_WIDTH) - 1
    for i in range(COLS):
        raw = (val_int >> (i * ACC_WIDTH)) & mask
        if raw & (1 << (ACC_WIDTH - 1)): raw -= (1 << ACC_WIDTH)
        unpacked.append(raw)
    return unpacked

class ReferenceModel:
    """ Modelo Dourado (Golden Model) """
    @staticmethod
    def compute(W, X):
        res = []
        for c in range(COLS):
            acc = 0
            for r in range(ROWS):
                acc += X[r] * W[r][c]
            res.append(acc)
        return res

class Scoreboard:
    """ Gerencia a comparação de resultados """
    def __init__(self, log_prefix="[SB]"):
        self.queue = []
        self.errors = 0
        self.prefix = log_prefix

    def add_expected(self, vec):
        self.queue.append(vec)

    def check(self, received):
        if not self.queue:
            log_error(f"{self.prefix} Erro Crítico: Dado recebido sem expectativa -> {received}")
            self.errors += 1
            return

        expected = self.queue.pop(0)
        if received != expected:
            self.errors += 1
            log_error(f"{self.prefix} FALHA DE DADOS")
            log_error(f"   Esperado: {expected}")
            log_error(f"   Recebido: {received}")

# ==============================================================================
# SETUP HELPERS
# ==============================================================================

async def setup_npu(dut):
    """ Inicializa Clock e Reset """
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.load_weight.value = 0
    dut.input_weights.value = 0
    dut.input_acts.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

async def load_weights(dut, weights_matrix):
    """ Carrega uma matriz de pesos na NPU """
    dut.load_weight.value = 1
    # Carrega de baixo para cima (Linha 3 -> Linha 0)
    for r in range(ROWS-1, -1, -1):
        dut.input_weights.value = pack_vec(weights_matrix[r])
        await RisingEdge(dut.clk)
    dut.load_weight.value = 0
    await RisingEdge(dut.clk)

async def monitor_output(dut, scoreboard):
    """ Processo contínuo que captura saídas válidas """
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if dut.valid_out.value == 1:
            raw = dut.output_accs.value
            vec = unpack_vec(raw)
            scoreboard.check(vec)

# ==============================================================================
# TESTES INDIVIDUAIS
# ==============================================================================

@cocotb.test()
async def test_01_basic_sanity(dut):
    
    # TESTE 1: Sanity Check (Integridade Básica)
    # Carrega Matriz Identidade e verifica se a saída é igual à entrada.
    # Objetivo: Garantir que o caminho de dados está desobstruído.
    
    log_header("TESTE 1: BASIC SANITY (Identidade)")
    await setup_npu(dut)
    sb = Scoreboard("[Sanity]")

    # 1. Matriz Identidade
    # 1 0 0 0
    # 0 1 0 0 ...
    W = [[1 if r == c else 0 for c in range(COLS)] for r in range(ROWS)]
    await load_weights(dut, W)

    # 2. Inicia Monitor
    monitor = cocotb.start_soon(monitor_output(dut, sb))

    # 3. Vetores de Teste Simples
    test_vectors = [
        [10, 20, 30, 40],
        [1, 1, 1, 1],
        [0, 0, 0, 0]
    ]

    log_info("Injetando vetores básicos...")
    for vec in test_vectors:
        # Golden Model
        expected = ReferenceModel.compute(W, vec) # Deve ser igual a 'vec'
        sb.add_expected(expected)

        # Drive
        dut.valid_in.value = 1
        dut.input_acts.value = pack_vec(vec)
        await RisingEdge(dut.clk)
    
    dut.valid_in.value = 0

    # 4. Wait & Check
    for _ in range(50): 
        if not sb.queue: break
        await RisingEdge(dut.clk)
    
    monitor.cancel()
    
    if sb.errors == 0 and not sb.queue:
        log_success("Teste de Sanidade: APROVADO.")
    else:
        log_error(f"Teste de Sanidade: FALHOU com {sb.errors} erros.")
        assert False

@cocotb.test()
async def test_02_corner_cases(dut):
    
    # TESTE 2: Corner Cases (Limites Numéricos)
    # Testa valores máximos, mínimos e zeros para garantir que não há overflow incorreto
    # ou problemas de sinal (signed arithmetic).
    
    log_header("TESTE 2: CORNER CASES")
    await setup_npu(dut)
    sb = Scoreboard("[Corner]")

    # 1. Pesos Mistos (Positivos e Negativos)
    W = [[random.randint(-10, 10) for _ in range(COLS)] for _ in range(ROWS)]
    await load_weights(dut, W)
    monitor = cocotb.start_soon(monitor_output(dut, sb))

    # 2. Casos Extremos
    corner_vectors = [
        [MAX_VAL] * ROWS,    # [127, 127, 127, 127] -> Stress Máximo Positivo
        [MIN_VAL] * ROWS,    # [-128, -128...] -> Stress Máximo Negativo
        [0] * ROWS,          # Zeros -> Limpeza
        [1, -1, 1, -1],      # Alternância de bits/sinal
        [0, MAX_VAL, 0, MIN_VAL]
    ]

    log_info(f"Testando {len(corner_vectors)} vetores de canto...")

    for vec in corner_vectors:
        sb.add_expected(ReferenceModel.compute(W, vec))
        
        dut.valid_in.value = 1
        dut.input_acts.value = pack_vec(vec)
        await RisingEdge(dut.clk)

    dut.valid_in.value = 0
    
    # Wait & Check
    for _ in range(50): 
        if not sb.queue: break
        await RisingEdge(dut.clk)
    
    monitor.cancel()
    
    if sb.errors == 0:
        log_success("Teste de Corner Cases: APROVADO.")
    else:
        assert False, f"Falha nos Casos de Canto ({sb.errors} erros)"

@cocotb.test()
async def test_03_stress_random(dut):
    
    # TESTE 3: Stress Test (Fuzzing com Backpressure)
    # Injeta uma grande quantidade de vetores aleatórios e insere "pausas" (bubbles)
    # aleatórias no sinal 'valid_in' para testar a robustez do pipeline de controle.
    
    log_header("TESTE 3: STRESS RANDOM & BACKPRESSURE")
    await setup_npu(dut)
    sb = Scoreboard("[Stress]")

    # 1. Pesos Totalmente Aleatórios
    W = [[random.randint(MIN_VAL, MAX_VAL) for _ in range(COLS)] for _ in range(ROWS)]
    await load_weights(dut, W)
    monitor = cocotb.start_soon(monitor_output(dut, sb))

    NUM_VECS = 200
    log_info(f"Iniciando fuzzing com {NUM_VECS} vetores e pausas aleatórias...")

    for i in range(NUM_VECS):
        # Gera entrada
        vec = [random.randint(MIN_VAL, MAX_VAL) for _ in range(ROWS)]
        
        # Registra expectativa
        sb.add_expected(ReferenceModel.compute(W, vec))

        # Envia dado
        dut.valid_in.value = 1
        dut.input_acts.value = pack_vec(vec)
        await RisingEdge(dut.clk)

        # INJEÇÃO DE CAOS: Pausa aleatória (Backpressure simulado)
        # Simula o processador não enviando dados por alguns ciclos
        if random.random() < 0.3: # 30% de chance de pausa
            dut.valid_in.value = 0
            dut.input_acts.value = 0
            
            pause_duration = random.randint(1, 4)
            for _ in range(pause_duration):
                await RisingEdge(dut.clk)

    dut.valid_in.value = 0
    
    # Wait for drain (timeout maior pois temos muitos dados)
    timeout = 0
    while sb.queue and timeout < 1000:
        await RisingEdge(dut.clk)
        timeout += 1

    monitor.cancel()

    if sb.errors == 0 and not sb.queue:
        log_success(f"Teste de Stress ({NUM_VECS} vecs): APROVADO.")
    elif sb.queue:
        log_error(f"Timeout: {len(sb.queue)} vetores não saíram da NPU.")
        assert False
    else:
        assert False, f"Falha no Stress Test ({sb.errors} erros)"