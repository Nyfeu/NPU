# Lista de Fontes VHDL

# Pacotes
VHDL_SRCS += $(PKG_DIR)/npu_pkg.vhd

# Common & Core
VHDL_SRCS += $(RTL_DIR)/common/fifo_sync.vhd
VHDL_SRCS += $(RTL_DIR)/common/ram_dual.vhd
VHDL_SRCS += $(RTL_DIR)/core/mac_pe.vhd
VHDL_SRCS += $(RTL_DIR)/core/systolic_array.vhd
VHDL_SRCS += $(RTL_DIR)/core/input_buffer.vhd
VHDL_SRCS += $(RTL_DIR)/core/npu_core.vhd
VHDL_SRCS += $(RTL_DIR)/ppu/post_process.vhd
VHDL_SRCS += $(RTL_DIR)/npu_controller.vhd
VHDL_SRCS += $(RTL_DIR)/npu_datapath.vhd
VHDL_SRCS += $(RTL_DIR)/npu_register_file.vhd
VHDL_SRCS += $(RTL_DIR)/npu_top.vhd

# FPGA Wrapper (Apenas usado no Vivado ou simulação do Top FPGA)
FPGA_SRCS += $(RTL_DIR)/fpga_tester/uart_controller.vhd
FPGA_SRCS += $(RTL_DIR)/fpga_tester/npu_fpga_top.vhd

# Lista completa combinada
ALL_VHDL_SRCS := $(VHDL_SRCS) $(FPGA_SRCS)