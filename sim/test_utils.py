# ==============================================================================
# File: test_utils.py
# ==============================================================================
#
# >>> Descrição: Módulo Compartilhado de Utilidades para Testes da ALU
#       Este módulo centraliza tudo que é COMUM entre diferentes testbenches:
#       - Configuração de logging e cores
#       - Constantes de operação
#       - Funções auxiliares
#
# ==============================================================================

import cocotb
from cocotb.triggers import Timer
import logging

# ==============================================================================
# CONFIGURAÇÃO DE LOGGING E VISUAL
# ==============================================================================

# Suprime logs irrelevantes do GHDL/GPI
logging.getLogger("gpi").setLevel(logging.ERROR)

class Colors:
    """Códigos ANSI para colorir o terminal"""
    HEADER  = '\033[96m'  # Ciano
    SUCCESS = '\033[92m'  # Verde
    INFO    = '\033[94m'  # Azul
    WARNING = '\033[93m'  # Amarelo
    FAIL    = '\033[91m'  # Vermelho
    ENDC    = '\033[0m'   # Reset
    BOLD    = '\033[1m'   # Negrito

def log_header(msg):
    """Loga um cabeçalho de seção"""
    cocotb.log.info(f"\n{Colors.HEADER}{Colors.BOLD}>>> {msg}{Colors.ENDC}")

def log_info(msg):
    """Loga uma informação geral"""
    cocotb.log.info(f"{Colors.INFO}ℹ️  {msg}{Colors.ENDC}")

def log_success(msg):
    """Loga uma mensagem de sucesso"""
    cocotb.log.info(f"{Colors.SUCCESS}✅ {msg}{Colors.ENDC}")

def log_warning(msg):
    """Loga um aviso"""
    cocotb.log.warning(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")

def log_error(msg):
    """Loga um erro"""
    cocotb.log.error(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")

def log_console(msg):
    """Loga uma mensagem de console"""
    cocotb.log.info(f"{Colors.INFO}📺 CONSOLE: {msg}{Colors.ENDC}")

def log_int(msg):
    """Loga um valor inteiro (número) no console"""
    cocotb.log.info(f"{Colors.INFO}🔢 INT: {msg}{Colors.ENDC}")

# ==============================================================================
# CONSTANTES - Códigos de Operação da ALU
# ==============================================================================

ALU_ADD  = 0b0000  # Adição: 10 + 32 = 42
ALU_SUB  = 0b1000  # Subtração: 10 - 32 = -22
ALU_SLL  = 0b0001  # Shift Left Lógico: move bits para esquerda (multiplica por 2)
ALU_SLT  = 0b0010  # Set Less Than (comparação com sinal)
ALU_SLTU = 0b0011  # Set Less Than Unsigned (comparação sem sinal)
ALU_XOR  = 0b0100  # OU Exclusivo: operação lógica
ALU_SRL  = 0b0101  # Shift Right Lógico: move bits para direita (divide por 2)
ALU_SRA  = 0b1101  # Shift Right Aritmético: shift direita preservando sinal
ALU_OR   = 0b0110  # OU lógico
ALU_AND  = 0b0111  # E lógico

def alu_name(alu_op):
    """Retorna o nome da operação ALU dado o código"""
    names = {
        ALU_ADD: "ADD", ALU_SUB: "SUB", ALU_SLL: "SLL",
        ALU_SLT: "SLT", ALU_SLTU: "SLTU", ALU_XOR: "XOR",
        ALU_SRL: "SRL", ALU_SRA: "SRA", ALU_OR: "OR",
        ALU_AND: "AND"
    }
    return names.get(alu_op, "UNKNOWN")

# ==============================================================================
# CONSTANTES - Códigos de Operação para CONTROL
# ==============================================================================

OP_R_TYPE = 0x33   # R-Type
OP_I_TYPE = 0x13   # I-Type
OP_LOAD   = 0x03   # Load
OP_STORE  = 0x23   # Store
OP_BRANCH = 0x63   # Branch
OP_JAL    = 0x6F   # Jump and Link
OP_JALR   = 0x67   # Jump and Link Register
OP_LUI    = 0x37   # Load Upper Immediate
OP_AUIPC  = 0x17   # Add Upper Immediate to PC

# ==============================================================================
# CONVERSÃO E DADOS
# ==============================================================================

def to_signed(val, bits=32):
    """Converte int para signed (complemento de 2)"""
    val = val & ((1 << bits) - 1)
    if val & (1 << (bits - 1)):
        val -= (1 << bits)
    return val

def to_unsigned(val, bits=32):
    """Garante que o valor seja tratado como unsigned"""
    return val & ((1 << bits) - 1)

def int_to_char(val):
    """Tenta converter int para char seguro para print"""
    try:
        c = chr(val & 0xFF)
        return c if c.isprintable() or c == '\n' else '.'
    except:
        return '.'
    
def sign_extend(value, bits):
    """Realiza extensão de sinal de um valor de 'bits' largura para 32 bits"""
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)

# ==============================================================================
# SINCRONIZAÇÃO DE SINAIS
# ==============================================================================

async def settle():
    """Aguarda um passo de tempo para propagação de sinais"""
    await Timer(1, unit="ns")

# ==============================================================================