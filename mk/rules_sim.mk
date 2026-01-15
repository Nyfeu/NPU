# Regras de Simulação (Cocotb)

TOPLEVEL ?= $(if $(TOP),$(TOP),npu_top)
MODULE   ?= $(if $(TEST),$(TEST),test_npu_top)

# Simulador padrão
SIM ?= ghdl

# Configurações de Path e Ambiente
export PYTHONPATH := $(CURDIR)/sim:$(CURDIR)/sim/core:$(CURDIR)/sim/ppu:$(CURDIR)/sim/common:$(PYTHONPATH)
export PYTHONUNBUFFERED := 1
export COCOTB_ANSI_OUTPUT := 1
export COCOTB_RESULTS_FILE := $(BUILD_DIR)/results.xml

# Usar bash para suportar pipefail
SHELL := /bin/bash

.PHONY: cocotb view sim_mnist sim_iris clean_sim

cocotb:
	@echo ""
	@echo "=========================================================================================="
	@echo " 🧪 COCOTB SIMULATION"
	@echo "=========================================================================================="
	@echo " 🔹 TOPLEVEL  : $(TOPLEVEL)"
	@echo " 🔹 MODULE    : $(MODULE)"
	@echo " 🔹 SIMULATOR : $(SIM)"
	@echo "=========================================================================================="
	@echo ""
	@mkdir -p $(BUILD_DIR)
	@set -o pipefail; \
	$(MAKE) -s --no-print-directory -f $(shell cocotb-config --makefiles)/Makefile.sim \
		VHDL_SOURCES="$(ALL_VHDL_SRCS)" \
		TOPLEVEL=$(TOPLEVEL) \
		MODULE=$(MODULE) \
		SIM=$(SIM) \
		SIM_ARGS="--vcd=$(BUILD_DIR)/$(MODULE).vcd" \
		WAVES=1 \
		2>&1 | grep --line-buffered -v "vpi_iterate returned NULL"

view:
	@echo ">>> [VIEW] Abrindo GTKWave para $(MODULE).vcd..."
	@gtkwave $(BUILD_DIR)/$(MODULE).vcd > /dev/null 2>&1 &

sim_mnist:
	@$(MAKE) -s cocotb TOP=npu_top TEST=test_npu_mnist

sim_iris:
	@$(MAKE) -s cocotb TOP=npu_top TEST=test_npu_iris

clean_sim:
	@echo ">>> [CLEAN] Removendo arquivos de simulação..."
	@rm -rf sim_build $(BUILD_DIR) *.vcd *.ghw results.xml