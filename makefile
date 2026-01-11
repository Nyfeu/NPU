# ==============================================================================
# NPU Project - Main Makefile
# ==============================================================================

# Diretórios Principais
PROJECT_ROOT := $(shell pwd)
RTL_DIR      := $(PROJECT_ROOT)/rtl
TB_DIR       := $(PROJECT_ROOT)/sim
BUILD_DIR    := $(PROJECT_ROOT)/build

# Configurações Padrão
SIM           ?= ghdl
TOPLEVEL_LANG ?= vhdl

# Utiliza PHONY targets para evitar conflitos com arquivos do sistema
.PHONY: all help cocotb view clean

# Target padrão: Mostra o banner de ajuda
all: help

# ------------------------------------------------------------------------------
# Target: Help (Banner)
# ------------------------------------------------------------------------------

help:
	@echo " "
	@echo " "
	@echo "      ███╗   ██╗██████╗ ██╗   ██╗ "
	@echo "      ████╗  ██║██╔══██╗██║   ██║ "
	@echo "      ██╔██╗ ██║██████╔╝██║   ██║ "
	@echo "      ██║╚██╗██║██╔═══╝ ██║   ██║ "
	@echo "      ██║ ╚████║██║     ╚██████╔╝ "
	@echo "      ╚═╝  ╚═══╝╚═╝      ╚═════╝  "
	@echo " "
	@echo "============================================================================================"
	@echo "           NPU BUILD SYSTEM                      "
	@echo "============================================================================================"
	@echo " "
	@echo " 🧠 PROJECT OVERVIEW"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "  
	@echo "   Target       : Neural Processing Unit (NPU)"
	@echo "   Architecture : Systolic Array Accelerator"
	@echo "   Tooling      : Make + GHDL + Cocotb + GTKWave"
	@echo " "
	@echo " "
	@echo " 🧪 SIMULATION & VERIFICATION"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make cocotb TOP=<top> TEST=<test>        Rodar simulação Cocotb do módulo especificado"
	@echo "   make view TEST=<test>                    Abrir formas de onda (VCD) no GTKWave"
	@echo " "
	@echo " "
	@echo " 📦 BUILD & HOUSEKEEPING"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make                                     Mostrar este menu de ajuda"
	@echo "   make clean                               Remover artefatos de build e simulação"
	@echo " "
	@echo " "
	@echo " 📌 EXAMPLES"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make cocotb TOP=systolic_array TEST=test_array"
	@echo "   make view TEST=test_array"
	@echo " "
	@echo " "
	@echo "============================================================================================"
	@echo " "


# ------------------------------------------------------------------------------
# Target: Cocotb (Simulação)
# ------------------------------------------------------------------------------

# Mapeia as variáveis (TOP, TEST) para as variáveis do Cocotb

cocotb:
ifndef TOP
	$(error Erro: Defina TOP=<nome_entidade>)
endif
ifndef TEST
	$(error Erro: Defina TEST=<nome_arquivo_python>)
endif
	@mkdir -p $(BUILD_DIR)
	
	@echo " "
	@echo "======================================================================"
	@echo " "
	@echo ">>> 🧪 COCOTB - Iniciando Testes Automatizados"
	@echo " "
	@echo "======================================================================"
	@echo " "
	@echo ">>> 🏗️  Top Level :  $(TOP)"
	@echo ">>> 📂 Testbench :  $(TEST).py"
	@echo " "
	@echo "======================================================================"
	@echo " "
	@export COCOTB_ANSI_OUTPUT=1; \
    export COCOTB_RESULTS_FILE=$(BUILD_DIR)/results.xml; \
	PYTHONPATH=$(TB_DIR) $(MAKE) -s -f $(shell cocotb-config --makefiles)/Makefile.sim \
		TOPLEVEL=$(TOP) \
		MODULE=$(TEST) \
		VHDL_SOURCES="$(shell find $(RTL_DIR) -name '*.vhd')" \
		SIM_BUILD=$(BUILD_DIR) \
		SIM_ARGS="--vcd=$(BUILD_DIR)/$(TEST).vcd" \
		SIM=$(SIM) \
		TOPLEVEL_LANG=$(TOPLEVEL_LANG) \
		2>&1 | grep -v "vpi_iterate returned NULL"

	@echo " "
	@echo ">>> ✅ Teste concluído"
	@echo ">>> 🌊 Ondas: $(BUILD_DIR)/$(TEST).vcd"

# ------------------------------------------------------------------------------
# Target: View (Ondas)
# ------------------------------------------------------------------------------

view:
ifndef TEST
	$(error Erro: Defina TEST=<nome_arquivo_python>)
endif
	@echo ">>> 📊 Abrindo GTKWave..."
	@if [ -f $(BUILD_DIR)/$(TEST).vcd ]; then \
		gtkwave $(BUILD_DIR)/$(TEST).vcd > /dev/null 2>&1 & \
	else \
		echo ">>> ❌ Erro: Onda não encontrada."; \
	fi

# ------------------------------------------------------------------------------
# Target: Clean
# ------------------------------------------------------------------------------

clean:
	@rm -rf $(BUILD_DIR) results.xml __pycache__
	@rm -rf $(TB_DIR)/__pycache__
	@echo ">>> 🧹 Limpeza concluída."