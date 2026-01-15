-------------------------------------------------------------------------------------------------------------
--
-- File: npu_fpga_top.vhd
-- 
-- ███████╗██████╗  ██████╗  █████╗ 
-- ██╔════╝██╔══██╗██╔════╝ ██╔══██╗
-- █████╗  ██████╔╝██║  ███╗███████║
-- ██╔══╝  ██╔═══╝ ██║   ██║██╔══██║
-- ██║     ██║     ╚██████╔╝██║  ██║
-- ╚═╝     ╚═╝      ╚═════╝ ╚═╝  ╚═╝
--
-- Descrição: Neural Processing Unit (NPU) - TOP-LEVEL (IP) FPGA Hardware-in-the-Loop (HIL)
--
-- Autor    : [André Maiolini]
-- Data     : [14/01/2026]
--
-------------------------------------------------------------------------------------------------------------  

library ieee;
use ieee.std_logic_1164.ALL;

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do wrapper FPGA para a NPU
-------------------------------------------------------------------------------------------------------------

entity npu_fpga_top is

    port ( 
        CLK_i       : in  std_logic;
        Reset_i     : in  std_logic; -- Botão da Nexys (Ativo Alto)
        UART_RX_i   : in  std_logic;
        UART_TX_o   : out std_logic;
        LEDS_o      : out std_logic_vector(15 downto 0)
    );

end npu_fpga_top;

-------------------------------------------------------------------------------------------------------------
-- Arquitetura: Implementação comportamental do wrapper FPGA para a NPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_fpga_top is

    -- Reset Sincronizado e Invertido para NPU
    signal rst_n       : std_logic;

    -- UART Signals
    signal rx_data, tx_data : std_logic_vector(7 downto 0);
    signal rx_dv, tx_start, tx_busy : std_logic;

    -- Bus Signals (Processador -> NPU)
    signal bus_sel, bus_we : std_logic;
    signal bus_addr, bus_wdata, bus_rdata : std_logic_vector(31 downto 0);

begin

    rst_n <= not Reset_i; -- Inverte para NPU

    -- Debug: LEDs mostram os 16 bits baixos do barramento de dados (escrita ou leitura)
    -- Isso ajuda a ver se a NPU está recebendo/enviando algo
    LEDS_o <= bus_wdata(15 downto 0) when bus_we = '1' else bus_rdata(15 downto 0);

    -- UART Controller (Camada Física)
    UART_Phys : entity work.uart_controller
        generic map (CLK_FREQ => 100_000_000, BAUD_RATE => 921_600)
        port map (
            CLK => CLK_i, RST => Reset_i,
            UART_RX => UART_RX_i, UART_TX => UART_TX_o,
            TX_DATA => tx_data, TX_START => tx_start, TX_BUSY => tx_busy,
            RX_DATA => rx_data, RX_DV => rx_dv
        );

    -- Command Processor (Mestre do Barramento)
    CMD_Proc : entity work.command_processor
        port map (
            CLK => CLK_i, RST => rst_n, -- Usa reset negado internamente para consistência
            RX_DATA => rx_data, RX_DV => rx_dv,
            TX_DATA => tx_data, TX_START => tx_start, TX_BUSY => tx_busy,
            -- Interface Bus
            M_SEL => bus_sel, M_WE => bus_we,
            M_ADDR => bus_addr, M_WDATA => bus_wdata, M_RDATA => bus_rdata
        );

    -- NPU (Device)
    NPU_Inst : entity work.npu_top
        generic map (
            ROWS => 4, COLS => 4, ACC_W => 32, DATA_W => 8, QUANT_W => 32, FIFO_DEPTH => 64
        )
        port map (
            clk => CLK_i, rst_n => rst_n,
            sel_i => bus_sel, we_i => bus_we,
            addr_i => bus_addr, data_i => bus_wdata, data_o => bus_rdata
        );

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------