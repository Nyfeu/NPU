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
    
    # Simula a chegada 'inclinada' de dados e verifica se saem alinhados.
    
    log_header("TESTE OUTPUT BUFFER (DESKEW)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # 1. Reset
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    dut.data_in.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    # 2. Preparar Dados "Diagonais"
    # Queremos reconstruir o vetor [10, 20, 30, 40]
    target_vector = [10, 20, 30, 40]
    
    # Injetaremos ao longo de 4 ciclos (COLS)
    log_info("Injetando dados inclinados...")
    
    for t in range(COLS):
        # Em cada ciclo T, apenas a Coluna T recebe o dado válido.
        # As outras recebem 0 (ou lixo, mas usaremos 0 para clareza)
        
        current_input = [0] * COLS
        current_input[t] = target_vector[t] 
        
        dut.valid_in.value = 1 # Em um sistema real, o valid_in seria pulsado de acordo
        dut.data_in.value = pack_acc_vector(current_input)
        
        # log_info(f"Ciclo {t}: Injetando {current_input}")
        await RisingEdge(dut.clk)

    # 3. Esperar o alinhamento
    # A Coluna 0 precisa de COLS-1 ciclos de atraso.
    # Como injetamos a Coluna 0 no tempo T=0, ela deve sair no tempo T=(COLS-1).
    # A Coluna 3 foi injetada no tempo T=3. Ela tem atraso 0. Sai no tempo T=3.
    # Ou seja: TODOS devem sair juntos no ciclo após a última injeção.
    
    # Vamos ler o resultado IMEDIATAMENTE após o loop (que consumiu 4 ciclos)
    # Mas atenção à latência do registrador: leva 1 ciclo para o dado entrar no FF.
    
    # Vamos esperar mais 1 ciclo para garantir a leitura estável pós-pipeline
    # await RisingEdge(dut.clk) 

    # 4. Verificar Saída
    packed_out = dut.data_out.value
    output = unpack_acc_vector(packed_out)
    
    log_info(f"Saída Alinhada: {output}")
    
    if output == target_vector:
        log_success("Sucesso! O vetor foi reconstruído e alinhado.")
    else:
        log_error(f"Falha. Esperado {target_vector}, Obtido {output}")
        # Debug: Verificar atrasos individuais
        assert False

@cocotb.test()
async def test_valid_signal_delay(dut):
    
    # Verifica se o sinal valid_out sai junto com os dados alinhados.
    
    log_header("TESTE VALID SIGNAL")
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    
    dut.rst_n.value = 0
    dut.valid_in.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    # Pulso de Valid In no T=0
    dut.valid_in.value = 1
    await RisingEdge(dut.clk) # Edge 1 (Captura entrada)
    dut.valid_in.value = 0
    
    # O Valid Out deve ir para 1 após (COLS-1) ciclos de atraso
    LATENCY = COLS 
    
    # Loop de Silêncio: Verifica se permance 0 ANTES da latência completa
    # Se Latency=3, queremos verificar silêncio após Edge 1 e Edge 2.
    # Após Edge 3, já deve ser 1.
    for i in range(LATENCY - 1):
        if dut.valid_out.value == 1:
            log_error(f"Valid subiu cedo demais no ciclo intermediário {i}")
            assert False
        await RisingEdge(dut.clk)
        
    # Agora estamos após o último clock da latência. O sinal DEVE ser 1.
    if dut.valid_out.value == 1:
        log_success(f"Valid Out subiu corretamente no ciclo esperado ({LATENCY}).")
    else:
        log_error(f"Valid Out NÃO subiu após {LATENCY} ciclos! Valor atual: {dut.valid_out.value}")
        assert False