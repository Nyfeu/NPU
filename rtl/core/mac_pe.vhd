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
        load_weight : in  std_logic;                      -- Flag de controle para carregar novo peso

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

    -- Sinal intermediário para o produto multiplicativo ----------------------------------------------------

    signal mult_result : signed(2*DATA_WIDTH-1 downto 0); -- Resultado da multiplicação (32 bits assinados)

    ---------------------------------------------------------------------------------------------------------

begin 

    -- Deslocamento dos dados dos registradores para as saídas ----------------------------------------------

    act_out <= act_reg;                                   -- Saída da ativação
    weight_out <= weight_reg;                             -- Saída do peso
    acc_out <= acc_reg;                                   -- Saída do acumulador

    -- Cálculo do produto multiplicativo --------------------------------------------------------------------

    mult_result <= weight_reg * act_in;

    -- Processo síncrono para atualização dos registradores -------------------------------------------------

    process(clk)
    begin

        if rising_edge(clk) then
        
            if rst_n = '0' then

                -- Reset síncrono: zera todos os registradores
                weight_reg <= (others => '0');
                act_reg    <= (others => '0');
                acc_reg    <= (others => '0');

                -- NOTA: isso estabele um estado inicial conhecido para os registradores
                -- evitando valores residuais indesejados.

            else

                -- Atualização do registrador de peso se load_weight estiver ativo

                if load_weight = '1' then

                    weight_reg <= weight_in;
                    act_reg    <= (others => '0');
                    acc_reg    <= (others => '0');
                
                    -- NOTA: ao carregar um novo peso, a ativação devem 
                    -- permanecer zeradas.

                else 

                    -- Pipeline Horizontal: Passa o dado atual para o vizinho (atraso de 1 ciclo) -----------

                    act_reg <= act_in;

                    -- Pipeline Vertical: Soma + Multiplicação ----------------------------------------------

                    acc_reg <= acc_in + resize(mult_result, ACC_WIDTH);

                    -----------------------------------------------------------------------------------------

                end if;

            end if;

        end if;

    end process;

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------