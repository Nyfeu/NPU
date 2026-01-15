-------------------------------------------------------------------------------------------------------------
-- 
-- File: uart_controller .vhd
-- 
-- ██╗   ██╗ █████╗ ██████╗ ████████╗
-- ██║   ██║██╔══██╗██╔══██╗╚══██╔══╝
-- ██║   ██║███████║██████╔╝   ██║   
-- ██║   ██║██╔══██║██╔══██╗   ██║   
-- ╚██████╔╝██║  ██║██║  ██║   ██║   
--  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
-- 
-- Descrição : Módulo Controlador UART (TX + RX)
--
-- Autor    : [André Maiolini]
-- Data     : [13/01/2026]
--
-------------------------------------------------------------------------------------------------------------  

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-------------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do Controlador UART
-------------------------------------------------------------------------------------------------------------------

entity uart_controller  is

    generic (

        CLK_FREQ    : integer := 100_000_000;           -- Clock da Nexys 4 (100 MHz)
        BAUD_RATE   : integer := 115_200                -- Baud rate (115200 bps)

    );

    port (

        -- Sinais de controle (sincronismo)

        clk         : in  std_logic;
        rst         : in  std_logic;
        
        -- Interface UART Física
        uart_rx     : in  std_logic;
        uart_tx     : out std_logic;
        
        -- Interface Lógica 
        tx_data     : in  std_logic_vector(7 downto 0); -- Dado para enviar
        tx_start    : in  std_logic;                    -- Pulso para iniciar envio
        tx_busy     : out std_logic;                    -- '1' se estiver enviando
        rx_data     : out std_logic_vector(7 downto 0); -- Dado recebido
        rx_dv       : out std_logic                     -- Pulso '1' quando dado é válido
    
    );

end uart_controller ;

-------------------------------------------------------------------------------------------------------------------
-- Arquitetura: Implementação comportamental da interface do Controlador UART
-------------------------------------------------------------------------------------------------------------------

architecture rtl of uart_controller  is

    -- Calculo de ciclos de clock por bit UART
    -- Para 100MHz e 115200: 100.000.000 / 115.200 = ~868 ciclos
    constant CLKS_PER_BIT : integer := CLK_FREQ / BAUD_RATE;

    -- Sinais para TX
    type tx_states is (TX_IDLE, TX_START_BIT, TX_DATA_BITS, TX_STOP_BIT);
    signal tx_state : tx_states := TX_IDLE;
    signal tx_cnt   : integer range 0 to CLKS_PER_BIT := 0;
    signal tx_idx   : integer range 0 to 7 := 0;
    signal tx_reg   : std_logic_vector(7 downto 0) := (others => '0');

    -- Sinais para RX
    type rx_states is (RX_IDLE, RX_START_BIT, RX_DATA_BITS, RX_STOP_BIT);
    signal rx_state : rx_states := RX_IDLE;
    signal rx_cnt   : integer range 0 to CLKS_PER_BIT := 0;
    signal rx_idx   : integer range 0 to 7 := 0;
    signal rx_reg   : std_logic_vector(7 downto 0) := (others => '0');
    
    -- Sinais de sincronização para entrada assíncrona RX
    signal rx_sync_1, rx_sync_2 : std_logic := '1';

begin

    -- =========================================================================
    -- PROCESSO DE SINCRONIZAÇÃO (Evita metaestabilidade no pino RX)
    -- =========================================================================
    process(clk)
    begin
        if rising_edge(clk) then
            rx_sync_1 <= uart_rx;
            rx_sync_2 <= rx_sync_1;
        end if;
    end process;

    -- =========================================================================
    -- PROCESSO RX (Receptor)
    -- =========================================================================
    process(clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                rx_state <= RX_IDLE;
                rx_dv    <= '0';
                rx_data  <= (others => '0');
                rx_cnt   <= 0;
                rx_idx   <= 0;
            else
                case rx_state is
                    when RX_IDLE =>
                        rx_dv <= '0';
                        rx_cnt <= 0;
                        rx_idx <= 0;
                        -- Detecta borda de descida (Start Bit = 0)
                        if rx_sync_2 = '0' then
                            rx_state <= RX_START_BIT;
                        end if;

                    when RX_START_BIT =>
                        -- Espera metade do tempo do bit para amostrar no meio
                        if rx_cnt = (CLKS_PER_BIT - 1) / 2 then
                            if rx_sync_2 = '0' then -- Confirma se ainda é Start Bit
                                rx_cnt <= 0;
                                rx_state <= RX_DATA_BITS;
                            else
                                rx_state <= RX_IDLE; -- Ruído falso
                            end if;
                        else
                            rx_cnt <= rx_cnt + 1;
                        end if;

                    when RX_DATA_BITS =>
                        if rx_cnt < CLKS_PER_BIT - 1 then
                            rx_cnt <= rx_cnt + 1;
                        else
                            rx_cnt <= 0;
                            rx_reg(rx_idx) <= rx_sync_2; -- Amostra o bit
                            
                            if rx_idx < 7 then
                                rx_idx <= rx_idx + 1;
                            else
                                rx_idx <= 0;
                                rx_state <= RX_STOP_BIT;
                            end if;
                        end if;

                    when RX_STOP_BIT =>
                        if rx_cnt < CLKS_PER_BIT - 1 then
                            rx_cnt <= rx_cnt + 1;
                        else
                            rx_dv   <= '1';        -- Pulso de dado válido
                            rx_data <= rx_reg;     -- Atualiza saída
                            rx_state <= RX_IDLE;
                        end if;
                end case;
            end if;
        end if;
    end process;

    -- =========================================================================
    -- PROCESSO TX (Transmissor)
    -- =========================================================================
    process(clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                tx_state <= TX_IDLE;
                tx_cnt   <= 0;
                tx_idx   <= 0;
                tx_reg   <= (others => '0');
                uart_tx  <= '1'; -- Linha Idle é High
                tx_busy  <= '0';
            else
                case tx_state is
                    when TX_IDLE =>
                        uart_tx <= '1';
                        tx_cnt  <= 0;
                        tx_idx  <= 0;
                        
                        if tx_start = '1' then
                            tx_reg   <= tx_data;
                            tx_busy  <= '1';
                            tx_state <= TX_START_BIT;
                        else
                            tx_busy <= '0';
                        end if;

                    when TX_START_BIT =>
                        uart_tx <= '0'; -- Start Bit é Low
                        if tx_cnt < CLKS_PER_BIT - 1 then
                            tx_cnt <= tx_cnt + 1;
                        else
                            tx_cnt <= 0;
                            tx_state <= TX_DATA_BITS;
                        end if;

                    when TX_DATA_BITS =>
                        uart_tx <= tx_reg(tx_idx); -- Envia LSB primeiro
                        
                        if tx_cnt < CLKS_PER_BIT - 1 then
                            tx_cnt <= tx_cnt + 1;
                        else
                            tx_cnt <= 0;
                            if tx_idx < 7 then
                                tx_idx <= tx_idx + 1;
                            else
                                tx_idx <= 0;
                                tx_state <= TX_STOP_BIT;
                            end if;
                        end if;

                    when TX_STOP_BIT =>
                        uart_tx <= '1'; -- Stop Bit é High
                        if tx_cnt < CLKS_PER_BIT - 1 then
                            tx_cnt <= tx_cnt + 1;
                        else
                            tx_state <= TX_IDLE;
                            tx_busy  <= '0';
                        end if;
                    
                end case;
            end if;
        end if;
    end process;

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------------