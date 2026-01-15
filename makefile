# ==============================================================================
# NPU Project Makefile
# ==============================================================================

# Configurações básicas (Variáveis apenas)
include mk/config.mk
include mk/sources.mk

# Forçar o Help como padrão
.DEFAULT_GOAL := help

# Includes de Regras (Contêm targets)
include mk/rules_sim.mk
include mk/rules_fpga.mk

# Target Help (Onde está o banner)
.PHONY: all help clean

all: help

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
	@echo "   Tooling      : Make + GHDL + Cocotb + GTKWave + Vivado"
	@echo " "
	@echo " "
	@echo " 🧪 SIMULATION & VERIFICATION"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make cocotb TOP=<top> TEST=<test>        Rodar simulação Cocotb"
	@echo "   make view TEST=<test>                    Abrir ondas no GTKWave"
	@echo "   make sim_mnist                           Atalho: Simulação do MNIST"
	@echo "   make sim_iris                            Atalho: Simulação do IRIS"
	@echo " "
	@echo " "
	@echo " 🛠️  FPGA WORKFLOW (Inteligente)"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make fpga                                Verificar bitstream, gerar se necessário e programar"
	@echo "   make fpga_bit                            Forçar geração do Bitstream (Vivado)"
	@echo "   make fpga_prog                           Apenas programar (sem check)"
	@echo " "
	@echo " "
	@echo " 🐍 HARDWARE-IN-THE-LOOP (HIL)"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make hil TEST=<script>                   Rodar script Python da pasta sw/"
	@echo "   make hil_mnist                           Atalho: Rodar HIL do MNIST"
	@echo "   make hil_iris                            Atalho: Rodar HIL do IRIS"
	@echo " "
	@echo " "
	@echo " 📦 HOUSEKEEPING"
	@echo " ──────────────────────────────────────────────────────────────────────────────────────────"
	@echo " "
	@echo "   make clean                               Limpar tudo"
	@echo " "
	@echo " "
	@echo "============================================================================================"
	@echo " "

clean: clean_sim clean_fpga
	@echo ">>> Limpeza Concluída."