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
-- Data      : [13/01/2026]    
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
        rst         : in  std_logic;

        -- UART Interface
        rx_data     : in  std_logic_vector(7 downto 0);
        rx_dv       : in  std_logic;
        tx_data     : out std_logic_vector(7 downto 0);
        tx_start    : out std_logic;
        tx_busy     : in  std_logic;

        -- Master Bus Interface (Conecta na NPU)
        m_vld       : out std_logic;
        m_we        : out std_logic;
        m_addr      : out std_logic_vector(31 downto 0);
        m_wdata     : out std_logic_vector(31 downto 0);
        m_rdata     : in  std_logic_vector(31 downto 0);
        m_rdy       : in std_logic

    );

end command_processor;

-------------------------------------------------------------------------------------------------------------------
-- Arquitetura: Implementação comportamental da interface do Processador de Comandos
-------------------------------------------------------------------------------------------------------------------

architecture rtl of command_processor is

    type state_type is (
        IDLE, GET_ADDR, CHECK_OP, GET_DATA, 
        EXEC_WRITE,                                     -- Escreve no barramento
        EXEC_READ,                                      -- Configura endereço para leitura
        SEND_BYTE, WAIT_TX_START, WAIT_TX_DONE
    );

    signal state : state_type := IDLE;

    signal opcode_reg : std_logic_vector(7 downto 0);
    signal addr_reg   : std_logic_vector(31 downto 0);
    signal data_reg   : std_logic_vector(31 downto 0);  -- WDATA ou RDATA
    signal byte_cnt   : integer range 0 to 3 := 0;

begin
    
    -- Atribuição contínua para o barramento
    -- Só ativamos o SEL e WE nos estados apropriados para evitar escritas espúrias
    m_addr  <= addr_reg;
    m_wdata <= data_reg; -- O dado que recebemos da UART

    process(clk)
    begin
        if rising_edge(clk) then
            if rst = '0' then -- Reset Active Low (comum na sua NPU)
                state <= IDLE;
                m_vld <= '0';
                m_we  <= '0';
                tx_start <= '0';
            else
                -- Defaults
                tx_start <= '0';
                m_vld    <= '0';
                m_we     <= '0';

                case state is
                    when IDLE =>
                        byte_cnt <= 0;
                        if rx_dv = '1' then
                            opcode_reg <= rx_data;
                            state      <= GET_ADDR;
                        end if;

                    when GET_ADDR =>
                        if rx_dv = '1' then
                            addr_reg <= addr_reg(23 downto 0) & rx_data;
                            if byte_cnt = 3 then
                                byte_cnt <= 0;
                                state    <= CHECK_OP;
                            else
                                byte_cnt <= byte_cnt + 1;
                            end if;
                        end if;

                    when CHECK_OP =>
                        if opcode_reg = x"01" then      -- WRITE
                            state <= GET_DATA;
                        elsif opcode_reg = x"02" then   -- READ
                            state <= EXEC_READ;
                        else
                            state <= IDLE; 
                        end if;

                    when GET_DATA =>
                        if rx_dv = '1' then
                            data_reg <= data_reg(23 downto 0) & rx_data;
                            if byte_cnt = 3 then
                                state <= EXEC_WRITE;
                            else
                                byte_cnt <= byte_cnt + 1;
                            end if;
                        end if;

                    -- === INTERAÇÃO COM BARRAMENTO ===
                    
                    when EXEC_WRITE =>
                        -- Pulsa o barramento por 1 ciclo
                        m_vld <= '1';
                        m_we  <= '1';
                        -- Endereço e Dados já estão setados (signals)
                        if m_rdy = '1' then 
                            state <= IDLE;
                        end if;

                    when EXEC_READ =>
                        -- Configura barramento para leitura
                        m_vld <= '1';
                        m_we  <= '0';
                        -- Captura imediata ao receber Ready
                        if m_rdy = '1' then  
                            data_reg <= m_rdata;   -- Captura o dado VÁLIDO agora
                            byte_cnt <= 3;         -- Prepara contador para envio
                            state    <= SEND_BYTE; -- Vai direto para envio
                        end if;

                    -- === ENVIO DA RESPOSTA ===

                    when SEND_BYTE =>
                        case byte_cnt is
                            when 3 => tx_data <= data_reg(31 downto 24);
                            when 2 => tx_data <= data_reg(23 downto 16);
                            when 1 => tx_data <= data_reg(15 downto 8);
                            when 0 => tx_data <= data_reg(7 downto 0);
                        end case;
                        tx_start <= '1';
                        state    <= WAIT_TX_START;

                    when WAIT_tx_start =>
                        if tx_busy = '1' then state <= WAIT_TX_DONE; end if;

                    when WAIT_TX_DONE =>
                        if tx_busy = '0' then
                            if byte_cnt = 0 then state <= IDLE;
                            else byte_cnt <= byte_cnt - 1; state <= SEND_BYTE;
                            end if;
                        end if;
                end case;
            end if;
        end if;
    end process;
end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------------