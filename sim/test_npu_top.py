# ==============================================================================
# File: test_npu_top.py
# ==============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
import random
from test_utils import *

# ==============================================================================
# CONSTANTES
# ==============================================================================

# Endereços dos registradores CSRs
ADDR_CSR_CTRL   = 0x00
ADDR_CSR_QUANT  = 0x04
ADDR_CSR_MULT   = 0x08
ADDR_CSR_STATUS = 0x0C
ADDR_FIFO_W     = 0x10
ADDR_FIFO_ACT   = 0x14
ADDR_FIFO_OUT   = 0x18
ADDR_BIAS_BASE  = 0x20 

# Bits de Controle
CTRL_RELU       = 1  # Bit 0
CTRL_LOAD       = 2  # Bit 1
CTRL_ACC_CLEAR  = 4  # Bit 2: Zera acumulador (Início de bloco)
CTRL_ACC_DUMP   = 8  # Bit 3: Envia resultado (Fim de bloco)

# Tamanho do array sistólico
ROWS = 4
COLS = 4

# ==============================================================================
# DRIVER MMIO
# ==============================================================================

class MMIO_Driver:

    def __init__(self, dut):
        self.dut = dut
        self.dut.sel_i.value  = 0
        self.dut.we_i.value   = 0
        self.dut.addr_i.value = 0
        self.dut.data_i.value = 0

    async def write(self, addr, data):
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value  = 1
        self.dut.we_i.value   = 1
        self.dut.addr_i.value = addr
        self.dut.data_i.value = int(data) & 0xFFFFFFFF
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value  = 0
        self.dut.we_i.value   = 0

    async def read(self, addr):
        await RisingEdge(self.dut.clk)
        self.dut.sel_i.value  = 1
        self.dut.we_i.value   = 0
        self.dut.addr_i.value = addr
        await RisingEdge(self.dut.clk)
        val_obj = self.dut.data_o.value
        self.dut.sel_i.value  = 0
        try: return int(val_obj)
        except ValueError: return 0

# ==============================================================================
# HELPERS
# ==============================================================================

def pack_vec(values):
    packed = 0
    for i, val in enumerate(values):
        val = val & 0xFF
        packed |= (val << (i * 8))
    return packed

def unpack_vec(packed):
    res = []
    for i in range(4):
        b = (packed >> (i*8)) & 0xFF
        if b > 127: b -= 256
        res.append(b)
    return res

def clamp_int8(val):
    if val > 127: return 127
    if val < -128: return -128
    return val

# ==============================================================================
# GOLDEN MODEL
# ==============================================================================

def npu_golden_model(weights, inputs, biases, mult, shift, zp, relu):
    results = []
    for vec_in in inputs:
        row_res = []
        for c in range(COLS):
            acc = 0
            for r in range(ROWS):
                acc += vec_in[r] * weights[r][c]
            acc += biases[c]
            acc = acc * mult
            if shift > 0:
                round_bit = 1 << (shift - 1)
                acc = (acc + round_bit) >> shift
            acc += zp
            if relu and acc < 0: acc = 0
            row_res.append(clamp_int8(acc))
        results.append(row_res)
    return results

# ==============================================================================
# TESTE HEAVY STRESS (FULL DUPLEX)
# ==============================================================================

@cocotb.test()
async def test_npu_heavy_stress(dut):
    
    # Teste Robustez com Controle de Fluxo:
    # - Monitora Flags FIFO Full/Empty para evitar perda de dados.
    # - Alterna entre escrita e leitura dinamicamente.
    
    log_header("TESTE NPU: HEAVY STRESS (FULL DUPLEX)")
    
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    mmio = MMIO_Driver(dut)
    
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    
    NUM_EPOCHS = 50
    VEC_PER_EPOCH = 100 
    
    total_errors = 0
    total_vectors_processed = 0

    for epoch in range(NUM_EPOCHS):
        if epoch % 10 == 0: 
            log_info(f"--- Epoch {epoch+1}/{NUM_EPOCHS} ---")
        
        # 1. Config Randomization
        biases = [random.randint(-20000, 20000) for _ in range(COLS)]
        mult = random.randint(1, 30000) 
        if random.choice([True, False]): mult = -mult 
        shift = random.randint(0, 14)
        zp = random.randint(-50, 50)
        en_relu = random.choice([0, 1])

        # Write CSRs (Configuração Inicial)
        # Nota: Não precisamos de Clear/Dump aqui pois é configuração
        ctrl_val = en_relu # Apenas ReLU bit
        await mmio.write(ADDR_CSR_CTRL, ctrl_val) 
        
        quant_cfg = ((zp & 0xFF) << 8) | (shift & 0x1F)
        await mmio.write(ADDR_CSR_QUANT, quant_cfg)
        await mmio.write(ADDR_CSR_MULT, mult)
        for i, b in enumerate(biases):
            await mmio.write(ADDR_BIAS_BASE + (i*4), b)

        # 2. Weights Randomization
        W = [[random.randint(-128, 127) for _ in range(COLS)] for _ in range(ROWS)]
        
        # Ativa LOAD MODE (Bit 1) + Mantém ReLU
        await mmio.write(ADDR_CSR_CTRL, CTRL_LOAD | en_relu)
        
        for row in reversed(W):
            await mmio.write(ADDR_FIFO_W, pack_vec(row))
            
        # ---- Ativa Modo Inferência "Pass-Through" ---
        # LOAD_MODE = 0
        # ACC_CLEAR = 1 (Limpa acumulador a cada nova entrada)
        # ACC_DUMP  = 1 (Libera resultado imediatamente)
        ctrl_infer = en_relu | CTRL_ACC_CLEAR | CTRL_ACC_DUMP
        
        await mmio.write(ADDR_CSR_CTRL, ctrl_infer)
        # ------------------------------------------------------------
        
        # 3. Generate Inputs
        X = []
        X.append([127, 127, 127, 127])    
        X.append([-128, -128, -128, -128]) 
        X.append([0, 0, 0, 0])
        X.append([127, -128, 127, -128])
        for _ in range(VEC_PER_EPOCH):
            X.append([random.randint(-128, 127) for _ in range(ROWS)])
            
        total_vectors_processed += len(X)
        expected = npu_golden_model(W, X, biases, mult, shift, zp, en_relu)
        
        # 4. STREAMING LOOP 
        # ======================================================================
        sent_idx = 0
        received_data = []
        
        # Enquanto houver dados para enviar OU receber
        while len(received_data) < len(X):
            
            # Lê Status Register
            status = await mmio.read(ADDR_CSR_STATUS)
            
            in_full = (status >> 0) & 1
            out_rdy = (status >> 3) & 1
            
            did_work = False
            
            # Prioridade 1: Drenar Saída (Evitar Output FIFO Overflow)
            if out_rdy:
                val = await mmio.read(ADDR_FIFO_OUT)
                received_data.append(unpack_vec(val))
                did_work = True
                
            # Prioridade 2: Enviar Entrada (Se houver espaço)
            if sent_idx < len(X) and not in_full:
                await mmio.write(ADDR_FIFO_ACT, pack_vec(X[sent_idx]))
                sent_idx += 1
                did_work = True
            
            # Se não fez nada (FIFO cheia E sem saída), espera um pouco o HW processar
            if not did_work:
                await RisingEdge(dut.clk)
                
        # ======================================================================

        # Validação
        epoch_errors = 0
        for i, (rcv, exp) in enumerate(zip(received_data, expected)):
            if rcv != exp:
                epoch_errors += 1
                total_errors += 1
                if epoch_errors == 1: 
                    log_error(f"Falha Epoch {epoch} Vetor {i}")
                    log_error(f"  In: {X[i]} | Exp: {exp} | Rcv: {rcv}")
                    log_error(f"  Cfg: M={mult} S={shift} ZP={zp} B[0]={biases[0]}")

    if total_errors == 0:
        log_success(f"SUCESSO TOTAL: {total_vectors_processed} vetores validados.")
    else:
        log_error(f"FALHA: {total_errors} erros encontrados.")
        assert False