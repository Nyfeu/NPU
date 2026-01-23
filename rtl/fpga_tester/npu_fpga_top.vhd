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
-- Descrição: Wrapper atualizado para suportar a NPU
--
-- Autor    : [André Maiolini]
-- Data     : [23/01/2026]
--
-------------------------------------------------------------------------------------------------------------  

library ieee;
use ieee.std_logic_1164.ALL;

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do wrapper FPGA para a NPU
-------------------------------------------------------------------------------------------------------------

entity npu_fpga_top is
    
    generic (
        CLK_FREQ    : integer := 100000000; 
        BAUD_RATE   : integer := 921_600
    );
    
    port ( 
        clk         : in  std_logic;
        rst         : in  std_logic; -- Botão da Nexys (Ativo Alto)
        uart_rx     : in  std_logic;
        uart_tx     : out std_logic;
        leds        : out std_logic_vector(3 downto 0)
    );

end npu_fpga_top;

-------------------------------------------------------------------------------------------------------------
-- Arquitetura: Implementação comportamental do wrapper FPGA para a NPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_fpga_top is

    -- Sinal de RESET Interno (Ativo Baixo)
    signal s_rst_n    : std_logic;

    -- Sinais UART (Interface com Command Processor)
    signal s_rx_valid : std_logic;
    signal s_rx_data  : std_logic_vector(7 downto 0);
    signal s_tx_ready : std_logic;
    signal s_tx_valid : std_logic;
    signal s_tx_data  : std_logic_vector(7 downto 0);
    signal s_uart_tx_busy : std_logic;

    -- Sinais NPU (Barramento Interno)
    signal s_npu_vld, s_npu_rdy, s_npu_we : std_logic;
    signal s_npu_addr : std_logic_vector(31 downto 0);
    signal s_npu_wdata, s_npu_rdata : std_logic_vector(31 downto 0);

    -- Extensores de pulso para o LED
    signal rx_blink_cnt : integer range 0 to 10000000 := 0;
    signal rx_led_reg   : std_logic := '0';

begin

    s_rst_n <= not rst;
    s_tx_ready <= not s_uart_tx_busy;

    -- =========================================================
    -- DEBUG LEDS (Mantidos inalterados)
    -- =========================================================
    leds(0) <= s_rst_n;

    process(clk) begin
        if rising_edge(clk) then
            if s_rx_valid = '1' then
                rx_blink_cnt <= 10000000;
                rx_led_reg <= '1';
            elsif rx_blink_cnt > 0 then
                rx_blink_cnt <= rx_blink_cnt - 1;
            else
                rx_led_reg <= '0';
            end if;
        end if;
    end process;
    leds(1) <= rx_led_reg;

    leds(2) <= s_npu_vld; -- Acende quando o Command Processor fala com a NPU
    leds(3) <= s_npu_rdy; -- Acende quando a NPU está pronta/respondendo

    -- =========================================================
    -- INSTÂNCIAS
    -- =========================================================
    
    -- Controlador UART 
    u_uart : entity work.uart_controller
        generic map ( 
            CLK_FREQ  => CLK_FREQ, 
            BAUD_RATE => BAUD_RATE 
        )
        port map (
            clk       => clk, 
            rst       => rst, 
            uart_rx   => uart_rx, 
            uart_tx   => uart_tx,
            tx_data   => s_tx_data, 
            tx_start  => s_tx_valid, 
            tx_busy   => s_uart_tx_busy,
            rx_data   => s_rx_data, 
            rx_dv     => s_rx_valid
        );

    -- Processador de Comandos
    u_cmd_proc : entity work.command_processor
        port map (
            clk           => clk, 
            rst_n         => s_rst_n,
            uart_rx_valid => s_rx_valid, 
            uart_rx_data  => s_rx_data,
            uart_tx_ready => s_tx_ready, 
            uart_tx_valid => s_tx_valid, 
            uart_tx_data  => s_tx_data,
            npu_rdy_i     => s_npu_rdy, 
            npu_data_i    => s_npu_rdata,
            npu_vld_o     => s_npu_vld, 
            npu_we_o      => s_npu_we, 
            npu_addr_o    => s_npu_addr, 
            npu_data_o    => s_npu_wdata
        );

    -- NPU TOP 
    u_npu : entity work.npu_top
        generic map ( 
            ROWS       => 4, 
            COLS       => 4, 
            ACC_W      => 32, 
            DATA_W     => 8, 
            QUANT_W    => 32, 
            FIFO_DEPTH => 2048 
        )
        port map (
            clk     => clk, 
            rst_n   => s_rst_n,
            
            -- Nova Interface de MMIO
            vld_i   => s_npu_vld,
            rdy_o   => s_npu_rdy,
            we_i    => s_npu_we,
            addr_i  => s_npu_addr,
            data_i  => s_npu_wdata,
            data_o  => s_npu_rdata
        );

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------