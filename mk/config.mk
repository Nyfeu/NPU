# Ferramentas de Simulação (Nativas Linux/WSL)
GHDL    := ghdl

# Detecção de Ambiente (WSL vs Linux Nativo)
ifdef WSL_DISTRO_NAME
    VIVADO := cmd.exe /c vivado.bat
    PYTHON := python.exe
else
    VIVADO := vivado
    PYTHON := python3
endif

# Flags GHDL
GHDL_FLAGS := --std=08 --ieee=synopsys

# Flags Vivado (Modo Batch)
VIVADO_FLAGS := -mode batch -notrace -nojournal -log build/vivado.log

# Diretórios
RTL_DIR   := rtl
PKG_DIR   := pkg
SIM_DIR   := sim
FPGA_DIR  := fpga
SW_DIR    := sw
BUILD_DIR := build