-------------------------------------------------------------------------------------------------------------
--
-- File: mac_pe.vhd
--
-- ███╗   ███╗ █████╗  ██████╗    ██████╗ ███████╗
-- ████╗ ████║██╔══██╗██╔════╝    ██╔══██╗██╔════╝
-- ██╔████╔██║███████║██║         ██████╔╝█████╗  
-- ██║╚██╔╝██║██╔══██║██║         ██╔═══╝ ██╔══╝  
-- ██║ ╚═╝ ██║██║  ██║╚██████╗    ██║     ███████╗
-- ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝    ╚═╝     ╚══════╝
--
-- Descrição: Neural Processing Unit (NPU) - MAC Processing Element (PE)
--
-- Autor    : [André Maiolini]
-- Data     : [11/01/2026]
--
-------------------------------------------------------------------------------------------------------------
                                               

library ieee;                  -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;   -- Tipos de lógica digital
use ieee.numeric_std.all;      -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;          -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do MAC Processing Element (PE)
-------------------------------------------------------------------------------------------------------------

entity mac_pe is 

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk         : in  std_logic;                      -- Sinal de clock
        rst_n       : in  std_logic;                      -- Sinal de reset síncrono local (ativo baixo)
        
        -- Controle OS (Output Stationary)

        clear_acc   : in  std_logic;                      -- Zera o acumulador interno
        drain_output: in  std_logic;                      -- 1: Desloca dados (Shift Vertical), 0: Calcula

        -----------------------------------------------------------------------------------------------------
        -- Entradas de Dados
        -----------------------------------------------------------------------------------------------------

        weight_in  : in  npu_data_t;                      -- Entrada de peso (8 bits assinados)
        act_in     : in  npu_data_t;                      -- Entrada de ativação (8 bits assinados)
        acc_in     : in  npu_acc_t;                       -- Entrada de acumulador (32 bits assinados)

        -----------------------------------------------------------------------------------------------------
        -- Saídas de Dados
        -----------------------------------------------------------------------------------------------------

        weight_out : out npu_data_t;                      -- Saída de peso (8 bits assinados)
        act_out    : out npu_data_t;                      -- Saída de ativação (8 bits assinados)
        acc_out    : out npu_acc_t                        -- Saída de acumulador (32 bits assinados)

        -----------------------------------------------------------------------------------------------------

    );

end entity mac_pe;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Imeplementação comportamental do MAC Processing Element (PE)
-------------------------------------------------------------------------------------------------------------

architecture rtl of mac_pe is

    -- Registradores internos para armazenar peso, ativação e acumulador ------------------------------------

    signal weight_reg : npu_data_t := (others => '0');    -- Registro de peso
    signal act_reg    : npu_data_t := (others => '0');    -- Registro de ativação
    signal acc_reg    : npu_acc_t  := (others => '0');    -- Registro de acumulador

    ---------------------------------------------------------------------------------------------------------

begin 

    -- Deslocamento dos dados dos registradores para as saídas ----------------------------------------------

    act_out    <= act_reg;                                -- Saída da ativação
    weight_out <= weight_reg;                             -- Saída do peso
    acc_out    <= acc_reg;                                -- Saída do acumulador

    -- Processo Síncrono ------------------------------------------------------------------------------------

    process(clk)
    begin

        if rising_edge(clk) then
            if rst_n = '0' then
                weight_reg <= (others => '0');
                act_reg    <= (others => '0');
                acc_reg    <= (others => '0');
            else

                -- 1. Pipeline de Dados (Systolic Flow)
                -- Os dados de entrada são passados para os registradores de saída
                -- para serem consumidos pelos vizinhos no próximo ciclo.

                weight_reg <= weight_in;
                act_reg    <= act_in;

                -- 2. Lógica do Acumulador (Output Stationary)
                if clear_acc = '1' then

                    -- Reset do acumulador para nova inferência
                    acc_reg <= (others => '0');
                
                elsif drain_output = '1' then

                    -- Modo DRAIN: Comporta-se como um shift-register vertical.
                    -- Pega o dado do PE de cima (acc_in) e passa para baixo.
                    acc_reg <= acc_in;

                    
                else

                    -- Modo COMPUTAÇÃO: MAC (Multiply-Accumulate)
                    -- Acumula sobre si mesmo.
                    -- Usamos weight_in/act_in direto para minimizar latência de captura.
                    acc_reg <= acc_reg + resize(weight_in * act_in, ACC_WIDTH);
                    
                end if;

            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------