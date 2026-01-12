-------------------------------------------------------------------------------------------------------------
--
-- File: npu_top.vhd
-- 
-- ███╗   ██╗██████╗ ██╗   ██╗
-- ████╗  ██║██╔══██╗██║   ██║
-- ██╔██╗ ██║██████╔╝██║   ██║
-- ██║╚██╗██║██╔═══╝ ██║   ██║
-- ██║ ╚████║██║     ╚██████╔╝
-- ╚═╝  ╚═══╝╚═╝      ╚═════╝ 
--
-- Descrição: Neural Processing Unit (NPU) - Interconexão Top-Level
--
-- Autor    : [André Maiolini]
-- Data     : [12/01/2026]
--
-------------------------------------------------------------------------------------------------------------   

library ieee;                                                -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                 -- Tipos de lógica digital
use ieee.numeric_std.all;                                    -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;                                        -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface da NPU Top-Level
-------------------------------------------------------------------------------------------------------------

entity npu_top is

    generic (

        ROWS       : integer := 4;                           -- Número de Linhas (Altura)
        COLS       : integer := 4;                           -- Número de Colunas (Largura)
        DATA_W     : integer := DATA_WIDTH;                  -- Largura dos Dados
        ACC_W      : integer := ACC_WIDTH                    -- Largura dos Acumuladores

    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk         : in  std_logic;                         -- Sinal de clock
        rst_n       : in  std_logic;                         -- Sinal de reset síncrono local (ativo baixo)
        
        -----------------------------------------------------------------------------------------------------
        -- Controle
        -----------------------------------------------------------------------------------------------------

        load_weight   : in  std_logic;                       -- Sinal para carregar pesos no Array Sistólico
        valid_in      : in  std_logic;                       -- Sinal de validade dos dados de entrada
        
        -----------------------------------------------------------------------------------------------------
        -- Dados
        -----------------------------------------------------------------------------------------------------

        -- Pesos de entrada (vetor empacotado): Largura = COLS * 8 bits
        input_weights : in  std_logic_vector((COLS * DATA_W)-1 downto 0);

        -- Ativações de entrada (vetor empacotado): Largura = ROWS * 8 bits
        input_acts    : in  std_logic_vector((ROWS * DATA_W)-1 downto 0);
        
        -----------------------------------------------------------------------------------------------------
        -- Saída
        -----------------------------------------------------------------------------------------------------

        -- Acumuladores de saída (vetor empacotado): Largura = COLS * 16 bits
        output_accs   : out std_logic_vector((COLS * ACC_W)-1 downto 0);

        -- Sinal de validade dos dados de saída
        valid_out     : out std_logic

        -----------------------------------------------------------------------------------------------------

    );

end entity npu_top;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU Top-Level
-------------------------------------------------------------------------------------------------------------

architecture struct of npu_top is

    -- Sinais de Interconexão -------------------------------------------------------------------------------

    signal acts_skewed     : std_logic_vector((ROWS * DATA_W)-1 downto 0);
    signal raw_accs        : std_logic_vector((COLS * ACC_W)-1 downto 0);
    signal valid_to_outbuf : std_logic;

    -- Pipeline de Valid ------------------------------------------------------------------------------------
    
    -- Profundidade exata = ROWS (Latência vertical do Array)

    signal valid_delay_line : std_logic_vector(0 to ROWS-1);

    ---------------------------------------------------------------------------------------------------------

begin

    -- INPUT BUFFER -----------------------------------------------------------------------------------------

    u_input_buffer : entity work.input_buffer
        generic map ( ROWS => ROWS, DATA_W => DATA_W )
        port map (
            clk      => clk,
            rst_n    => rst_n,
            valid_in => valid_in,
            data_in  => input_acts,
            data_out => acts_skewed
        );

    -- SYSTOLIC ARRAY ---------------------------------------------------------------------------------------

    u_systolic_array : entity work.systolic_array
        generic map ( ROWS => ROWS, COLS => COLS, DATA_W => DATA_W, ACC_W => ACC_W )
        port map (
            clk           => clk,
            rst_n         => rst_n,
            load_weight   => load_weight,
            input_weights => input_weights,
            input_acts    => acts_skewed,
            output_accs   => raw_accs
        );

    -- PIPELINE DE VALID ------------------------------------------------------------------------------------

    -- Garante que o sinal valid se propague na mesma velocidade que a onda de dados

    process(clk, rst_n)
    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                -- Reset síncrono (ativo baixo)
                valid_delay_line <= (others => '0');

            else

                -- Shift Register usando concatenação (Mais limpo e seguro)
                -- Entrada na esquerda (0), shift para a direita
                valid_delay_line <= valid_in & valid_delay_line(0 to ROWS-2);

            end if;

        end if;

    end process;

    -- A saída do pipeline é o último estágio
    valid_to_outbuf <= valid_delay_line(ROWS-1);

    -- OUTPUT BUFFER ----------------------------------------------------------------------------------------

    u_output_buffer : entity work.output_buffer
        generic map ( COLS => COLS, ACC_W => ACC_W )
        port map (
            clk       => clk,
            rst_n     => rst_n,
            valid_in  => valid_to_outbuf,
            data_in   => raw_accs,
            data_out  => output_accs,
            valid_out => valid_out
        );

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------