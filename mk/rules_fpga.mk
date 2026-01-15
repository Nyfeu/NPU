# Regras para FPGA (Vivado) e Hardware-in-the-Loop (HIL)

PROJECT_NAME := npu_project
TOP_ENTITY   := npu_fpga_top
PART         := xc7a100tcsg324-1
BITSTREAM    := $(BUILD_DIR)/$(TOP_ENTITY).bit

.PHONY: fpga fpga_bit fpga_prog clean_fpga hil hil_mnist hil_iris

# ------------------------------------------------------------------------------
# Fluxo Inteligente (Gera apenas se necessário + Programa)
# ------------------------------------------------------------------------------
fpga:
	@echo ">>> [FPGA] Verificando Bitstream..."
	@if [ ! -f $(BITSTREAM) ]; then \
		echo ">>> ⚠️  Bitstream não encontrado em $(BITSTREAM)."; \
		echo ">>> 🔨 Iniciando Síntese (Isso pode demorar)..."; \
		$(MAKE) fpga_bit; \
	else \
		echo ">>> ✅ Bitstream encontrado. Pulando síntese."; \
	fi
	@echo ">>> 🔌 Programando Placa..."
	$(MAKE) fpga_prog

# ------------------------------------------------------------------------------
# Etapas Individuais
# ------------------------------------------------------------------------------

# Gera o Bitstream (Sempre força a execução do Vivado se chamado diretamente)
fpga_bit:
	@echo ">>> [FPGA] Gerando Bitstream..."
	@mkdir -p $(BUILD_DIR)
	$(VIVADO) $(VIVADO_FLAGS) -source $(FPGA_DIR)/scripts/build.tcl -tclargs $(TOP_ENTITY) $(PART)
	@if [ -f clockInfo.txt ]; then mv clockInfo.txt $(BUILD_DIR)/; fi
	@if [ -f vivado.log ]; then mv vivado.log $(BUILD_DIR)/; fi
	@if [ -f vivado.jou ]; then mv vivado.jou $(BUILD_DIR)/; fi

# Apenas Programa (Assume que o bitstream existe)
fpga_prog:
	@echo ">>> [FPGA] Programando a placa..."
	$(VIVADO) $(VIVADO_FLAGS) -source $(FPGA_DIR)/scripts/program.tcl
	@if [ -f vivado.log ]; then mv vivado.log $(BUILD_DIR)/prog_vivado.log; fi
	@if [ -f vivado.jou ]; then mv vivado.jou $(BUILD_DIR)/prog_vivado.jou; fi

# ------------------------------------------------------------------------------
# Hardware-in-the-Loop (HIL)
# ------------------------------------------------------------------------------
# Uso: make hil TEST=fpga_mnist
hil:
	@echo ">>> [HIL] Rodando Driver Python: $(TEST)..."
	@if [ -z "$(TEST)" ]; then \
		echo ">>> ❌ ERRO: Defina o teste. Ex: make hil TEST=fpga_mnist"; \
		exit 1; \
	fi
	@# Executa o script python dentro da pasta sw/
	$(PYTHON) $(SW_DIR)/$(TEST).py

# Atalhos
hil_mnist:
	$(MAKE) hil TEST=fpga_mnist

hil_iris:
	$(MAKE) hil TEST=fpga_iris

# ------------------------------------------------------------------------------
# Limpeza
# ------------------------------------------------------------------------------
clean_fpga:
	@echo ">>> [CLEAN] Limpando arquivos do Vivado..."
	@rm -rf .Xil usage_statistics_webtalk.html usage_statistics_webtalk.xml
	@rm -rf $(BUILD_DIR) vivado*.log vivado*.jou