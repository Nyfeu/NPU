open_hw_manager
connect_hw_server
open_hw_target

set_property PROGRAM.FILE {build/npu_fpga_top.bit} [get_hw_devices xc7a100t_0]
program_hw_devices [get_hw_devices xc7a100t_0]

close_hw_manager
exit