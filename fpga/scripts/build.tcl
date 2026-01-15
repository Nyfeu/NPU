# fpga/build.tcl (Atualizado/Simplificado)

# Captura argumentos (Top Entity e Part)
if { $argc != 2 } {
    puts "Uso: vivado -mode batch -source build.tcl -tclargs <top_entity> <part>"
    exit 1
}
set topEntity [lindex $argv 0]
set targetPart [lindex $argv 1]

# Configura projeto em memória
create_project -in_memory -part $targetPart

# --- LENDO ARQUIVOS ---

# Package
read_vhdl "pkg/npu_pkg.vhd"

# Common & RTL
read_vhdl [glob rtl/common/*.vhd]
read_vhdl [glob rtl/core/*.vhd]
read_vhdl [glob rtl/ppu/*.vhd]
read_vhdl "rtl/npu_top.vhd"

# FPGA Tester (HIL Wrapper)
read_vhdl [glob rtl/fpga_tester/*.vhd]

# Constraints
read_xdc "fpga/constraints/pins.xdc"

# --- FLUXO DE COMPILAÇÃO ---
synth_design -top $topEntity -part $targetPart -flatten_hierarchy rebuilt
opt_design
place_design
route_design

# --- GERAR BITSTREAM ---
write_bitstream -force "build/${topEntity}.bit"

exit