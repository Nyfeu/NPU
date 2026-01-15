## =============================================================================
## ARQUIVO: pins.xdc (Nexys 4 Original - Completo)
## =============================================================================

## 1. Clock Signal (100 MHz)
set_property -dict { PACKAGE_PIN E3    IOSTANDARD LVCMOS33 } [get_ports { CLK_i }]; 
create_clock -add -name sys_clk_pin -period 10.00 -waveform {0 5} [get_ports { CLK_i }];

## 2. Configurações de Voltagem
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

## 3. Reset (Botão Central - BTNC)
set_property -dict { PACKAGE_PIN E16   IOSTANDARD LVCMOS33 } [get_ports { Reset_i }];

## 4. USB-UART Interface
set_property -dict { PACKAGE_PIN C4    IOSTANDARD LVCMOS33 } [get_ports { UART_RX_i }];
set_property -dict { PACKAGE_PIN D4    IOSTANDARD LVCMOS33 } [get_ports { UART_TX_o }];

## 5. LEDs de Debug (Todos os 16 mapeados)
set_property -dict { PACKAGE_PIN T8    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[0] }];
set_property -dict { PACKAGE_PIN V9    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[1] }];
set_property -dict { PACKAGE_PIN R8    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[2] }];
set_property -dict { PACKAGE_PIN T6    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[3] }];
set_property -dict { PACKAGE_PIN T5    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[4] }];
set_property -dict { PACKAGE_PIN T4    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[5] }];
set_property -dict { PACKAGE_PIN U7    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[6] }];
set_property -dict { PACKAGE_PIN U6    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[7] }];
set_property -dict { PACKAGE_PIN V4    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[8] }];
set_property -dict { PACKAGE_PIN U3    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[9] }];
set_property -dict { PACKAGE_PIN V1    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[10] }];
set_property -dict { PACKAGE_PIN R1    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[11] }];
set_property -dict { PACKAGE_PIN P5    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[12] }];
set_property -dict { PACKAGE_PIN U1    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[13] }];
set_property -dict { PACKAGE_PIN R2    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[14] }];
set_property -dict { PACKAGE_PIN P2    IOSTANDARD LVCMOS33 } [get_ports { LEDS_o[15] }];