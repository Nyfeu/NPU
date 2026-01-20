------------------------------------------------------------------------------------------------------------------
-- 
-- File: command_processor.vhd
-- 
--  ██████╗ ██████╗ ███╗   ███╗███╗   ███╗ █████╗ ███╗   ██╗██████╗ 
-- ██╔════╝██╔═══██╗████╗ ████║████╗ ████║██╔══██╗████╗  ██║██╔══██╗
-- ██║     ██║   ██║██╔████╔██║██╔████╔██║███████║██╔██╗ ██║██║  ██║
-- ██║     ██║   ██║██║╚██╔╝██║██║╚██╔╝██║██╔══██║██║╚██╗██║██║  ██║
-- ╚██████╗╚██████╔╝██║ ╚═╝ ██║██║ ╚═╝ ██║██║  ██║██║ ╚████║██████╔╝
--  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝  
-- 
-- Descrição : Módulo Controlador UART (TX + RX)
-- 
-- Autor     : [André Maiolini]
-- Data      : [20/01/2026]    
--
------------------------------------------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-------------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do Processador de Comandos
-------------------------------------------------------------------------------------------------------------------

entity command_processor is

    port (

        -- Sinais de controle (sincronismo)
        clk         : in  std_logic;
        rst_n       : in  std_logic;

        -- UART Interface
        uart_rx_valid   : in  std_logic;
        uart_rx_data    : in  std_logic_vector(7 downto 0);
        uart_tx_ready   : in  std_logic;
        uart_tx_valid   : out std_logic;
        uart_tx_data    : out std_logic_vector(7 downto 0);

        -- Master Bus Interface (Conecta na NPU)
        npu_rdy_i       : in  std_logic;
        npu_data_i      : in  std_logic_vector(31 downto 0); 
        npu_vld_o       : out std_logic;
        npu_we_o        : out std_logic;
        npu_addr_o      : out std_logic_vector(31 downto 0);
        npu_data_o      : out std_logic_vector(31 downto 0)  

    );

end command_processor;

-------------------------------------------------------------------------------------------------------------------
-- Arquitetura: Implementação comportamental da interface do Processador de Comandos
-------------------------------------------------------------------------------------------------------------------

architecture rtl of command_processor is

   type t_state is (
        IDLE,
        GET_OPCODE,
        GET_ADDR,
        GET_DATA,
        EXECUTE_TRANSACTION,
        WAIT_ACK,
        SEND_RESPONSE,
        WAIT_TX_DONE
    );

    signal state : t_state := IDLE;

    signal r_opcode   : std_logic_vector(7 downto 0);
    signal r_addr     : std_logic_vector(31 downto 0);
    signal r_data_in  : std_logic_vector(31 downto 0);
    signal r_data_out : std_logic_vector(31 downto 0);
    signal r_byte_cnt : integer range 0 to 3;


begin
    
    process(clk, rst_n)
    begin
        if rst_n = '0' then
            state         <= IDLE;
            uart_tx_valid <= '0';
            uart_tx_data  <= (others => '0');
            npu_vld_o     <= '0';
            npu_we_o      <= '0';
            npu_addr_o    <= (others => '0');
            npu_data_o    <= (others => '0');
            r_addr        <= (others => '0');
            r_data_in     <= (others => '0');
            r_opcode      <= (others => '0');
            r_byte_cnt    <= 0;

        elsif rising_edge(clk) then

            -- defaults
            uart_tx_valid <= '0';
            npu_vld_o     <= '0';
            npu_we_o      <= '0';

            case state is

                when IDLE =>
                    if uart_rx_valid = '1' then
                        r_opcode <= uart_rx_data;
                        r_byte_cnt <= 3;
                        r_addr <= (others => '0');
                        state <= GET_ADDR;
                    end if;

                -- Recebe 4 bytes de endereço
                when GET_ADDR =>
                    if uart_rx_valid = '1' then
                        r_addr <= r_addr(23 downto 0) & uart_rx_data;
                        if r_byte_cnt = 0 then
                            if r_opcode = x"01" then
                                r_byte_cnt <= 3;
                                r_data_in <= (others => '0');
                                state <= GET_DATA;
                            else
                                state <= EXECUTE_TRANSACTION;
                            end if;
                        else
                            r_byte_cnt <= r_byte_cnt - 1;
                        end if;
                    end if;

                -- Recebe 4 bytes de dados (WRITE)
                when GET_DATA =>
                    if uart_rx_valid = '1' then
                        r_data_in <= r_data_in(23 downto 0) & uart_rx_data;
                        if r_byte_cnt = 0 then
                            state <= EXECUTE_TRANSACTION;
                        else
                            r_byte_cnt <= r_byte_cnt - 1;
                        end if;
                    end if;

                -- Pulso de transação
                when EXECUTE_TRANSACTION =>
                    npu_addr_o <= r_addr;
                    npu_data_o <= r_data_in;
                    npu_vld_o  <= '1';

                    if r_opcode = x"01" then
                        npu_we_o <= '1';
                    else
                        npu_we_o <= '0';
                    end if;

                    state <= WAIT_ACK;

                when WAIT_ACK =>
                    if npu_rdy_i = '1' then
                        if r_opcode = x"02" then
                            r_data_out <= npu_data_i;
                            r_byte_cnt <= 3;
                            state <= SEND_RESPONSE;
                        else
                            state <= IDLE;
                        end if;
                    end if;

                when SEND_RESPONSE =>
                    if uart_tx_ready = '1' then
                        uart_tx_valid <= '1';
                        case r_byte_cnt is
                            when 3 => uart_tx_data <= r_data_out(31 downto 24);
                            when 2 => uart_tx_data <= r_data_out(23 downto 16);
                            when 1 => uart_tx_data <= r_data_out(15 downto 8);
                            when 0 => uart_tx_data <= r_data_out(7 downto 0);
                            when others => null;
                        end case;
                        state <= WAIT_TX_DONE;
                    end if;

                when WAIT_TX_DONE =>
                    if uart_tx_ready = '1' then
                        if r_byte_cnt = 0 then
                            state <= IDLE;
                        else
                            r_byte_cnt <= r_byte_cnt - 1;
                            state <= SEND_RESPONSE;
                        end if;
                    end if;

                when others =>
                    state <= IDLE;

            end case;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------------

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------------