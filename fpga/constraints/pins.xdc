## =============================================================================
## ARQUIVO: pins.xdc (Nexys 4 Original - Completo)
## =============================================================================

## 1. Clock Signal (100 MHz)
set_property -dict { PACKAGE_PIN E3    IOSTANDARD LVCMOS33 } [get_ports { clk }]; 
create_clock -add -name sys_clk_pin -period 10.00 -waveform {0 5} [get_ports { clk }];

## 2. Configurações de Voltagem
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

## 3. Reset (Botão Central - BTNC)
set_property -dict { PACKAGE_PIN E16   IOSTANDARD LVCMOS33 } [get_ports { rst }];

## 4. USB-UART Interface
set_property -dict { PACKAGE_PIN C4    IOSTANDARD LVCMOS33 } [get_ports { uart_rx }];
set_property -dict { PACKAGE_PIN D4    IOSTANDARD LVCMOS33 } [get_ports { uart_tx }];

## 5. LEDs de Debug (Todos os 16 mapeados)
set_property -dict { PACKAGE_PIN T8    IOSTANDARD LVCMOS33 } [get_ports { leds[0] }];
set_property -dict { PACKAGE_PIN V9    IOSTANDARD LVCMOS33 } [get_ports { leds[1] }];
set_property -dict { PACKAGE_PIN R8    IOSTANDARD LVCMOS33 } [get_ports { leds[2] }];
set_property -dict { PACKAGE_PIN T6    IOSTANDARD LVCMOS33 } [get_ports { leds[3] }];
set_property -dict { PACKAGE_PIN T5    IOSTANDARD LVCMOS33 } [get_ports { leds[4] }];
set_property -dict { PACKAGE_PIN T4    IOSTANDARD LVCMOS33 } [get_ports { leds[5] }];
set_property -dict { PACKAGE_PIN U7    IOSTANDARD LVCMOS33 } [get_ports { leds[6] }];
set_property -dict { PACKAGE_PIN U6    IOSTANDARD LVCMOS33 } [get_ports { leds[7] }];
set_property -dict { PACKAGE_PIN V4    IOSTANDARD LVCMOS33 } [get_ports { leds[8] }];
set_property -dict { PACKAGE_PIN U3    IOSTANDARD LVCMOS33 } [get_ports { leds[9] }];
set_property -dict { PACKAGE_PIN V1    IOSTANDARD LVCMOS33 } [get_ports { leds[10] }];
set_property -dict { PACKAGE_PIN R1    IOSTANDARD LVCMOS33 } [get_ports { leds[11] }];
set_property -dict { PACKAGE_PIN P5    IOSTANDARD LVCMOS33 } [get_ports { leds[12] }];
set_property -dict { PACKAGE_PIN U1    IOSTANDARD LVCMOS33 } [get_ports { leds[13] }];
set_property -dict { PACKAGE_PIN R2    IOSTANDARD LVCMOS33 } [get_ports { leds[14] }];
set_property -dict { PACKAGE_PIN P2    IOSTANDARD LVCMOS33 } [get_ports { leds[15] }];