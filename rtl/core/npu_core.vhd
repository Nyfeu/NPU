-------------------------------------------------------------------------------------------------------------
--
-- File: npu_core.vhd
-- 
-- ███╗   ██╗██████╗ ██╗   ██╗
-- ████╗  ██║██╔══██╗██║   ██║
-- ██╔██╗ ██║██████╔╝██║   ██║
-- ██║╚██╗██║██╔═══╝ ██║   ██║
-- ██║ ╚████║██║     ╚██████╔╝
-- ╚═╝  ╚═══╝╚═╝      ╚═════╝ 
--
-- Descrição: Neural Processing Unit (NPU) - Interconexão CORE (Output Stationary)
--
-- Autor    : [André Maiolini]
-- Data     : [19/01/2026]
--
-------------------------------------------------------------------------------------------------------------   

library ieee;                                                -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                 -- Tipos de lógica digital
use ieee.numeric_std.all;                                    -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;                                        -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface da NPU CORE
-------------------------------------------------------------------------------------------------------------

entity npu_core is

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
        acc_clear   : in  std_logic;                         -- Limpa os acumuladores internos dos PEs
        acc_dump    : in  std_logic;                         -- Ativa o modo "Drain" (saída dos dados)
        
        -----------------------------------------------------------------------------------------------------
        -- Dados de Entrada (Streams)
        -----------------------------------------------------------------------------------------------------

        -- Valid de entrada (indica que input_acts e input_weights são validos neste ciclo)
        valid_in      : in  std_logic;                       

        -- Pesos fluem verticalmente (agora precisam de skew também)
        input_weights : in  std_logic_vector((COLS * DATA_W)-1 downto 0);

        -- Ativações fluem horizontalmente
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

end entity npu_core;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU CORE
-------------------------------------------------------------------------------------------------------------

architecture struct of npu_core is

    -- Sinais de Interconexão -------------------------------------------------------------------------------

    signal acts_skewed    : std_logic_vector((ROWS * DATA_W)-1 downto 0);
    signal weights_skewed : std_logic_vector((COLS * DATA_W)-1 downto 0);

    -- Sinais do Array --------------------------------------------------------------------------------------

    signal array_out_accs : std_logic_vector((COLS * ACC_W)-1 downto 0);

    ---------------------------------------------------------------------------------------------------------

begin

    -- INPUT BUFFER HORIZONTAL ------------------------------------------------------------------------------

    -- Aplica atrasos triangulares nas linhas de input_acts

    u_input_acts_buffer : entity work.input_buffer
        generic map ( 
            ROWS          => ROWS, -- Número de canais de skew (aqui são as linhas)
            DATA_W        => DATA_W 
        )
        port map (
            clk           => clk,
            rst_n         => rst_n,
            valid_in      => valid_in,
            data_in       => input_acts,
            data_out      => acts_skewed
        );

    -- INPUT BUFFER VERTICAL --------------------------------------------------------------------------------

    -- Aplica atrasos triangulares nas colunas de input_weights

    u_input_weights_buffer : entity work.input_buffer
        generic map ( 
            ROWS          => COLS, -- Para pesos, o número de canais é o número de COLUNAS
            DATA_W        => DATA_W 
        )
        port map (
            clk           => clk,
            rst_n         => rst_n,
            valid_in      => valid_in,
            data_in       => input_weights,
            data_out      => weights_skewed
        );

    -- SYSTOLIC ARRAY ---------------------------------------------------------------------------------------

    u_systolic_array : entity work.systolic_array
        generic map ( 
            ROWS          => ROWS, 
            COLS          => COLS, 
            DATA_W        => DATA_W, 
            ACC_W         => ACC_W 
        )
        port map (
            clk           => clk,
            rst_n         => rst_n,
            clear_acc     => acc_clear,
            drain_output  => acc_dump,
            input_weights => weights_skewed,
            input_acts    => acts_skewed,
            output_accs   => array_out_accs
        );

    -- Saída ------------------------------------------------------------------------------------------------

    -- No modo OS, a saída é válida enquanto estamos drenando (acc_dump = '1').
    
    output_accs <= array_out_accs;
    
    -- Como o Systolic Array (no modo Drain) já coloca o dado na saída combinacionalmente
    -- (baseado no registrador interno), o dado é válido no mesmo ciclo que acc_dump está alto.

    valid_out   <= acc_dump;

    ---------------------------------------------------------------------------------------------------------

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------