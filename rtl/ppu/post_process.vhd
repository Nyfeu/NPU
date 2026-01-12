-------------------------------------------------------------------------------------------------------------
--
-- File: post_process.vhd
--
-- ██████╗ ██████╗ ██╗   ██╗
-- ██╔══██╗██╔══██╗██║   ██║
-- ██████╔╝██████╔╝██║   ██║
-- ██╔═══╝ ██╔═══╝ ██║   ██║
-- ██║     ██║     ╚██████╔╝
-- ╚═╝     ╚═╝      ╚═════╝ 
-- 
-- Descrição: Neural Processing Unit (NPU) - Post-Process Unit (PPU)
--
-- Autor    : [André Maiolini]
-- Data     : [12/01/2026]
-- 
-------------------------------------------------------------------------------------------------------------

library ieee;                                                    -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                     -- Tipos de lógica digital
use ieee.numeric_std.all;                                        -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;                                            -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface da PPU
-------------------------------------------------------------------------------------------------------------

entity post_process is

    generic (

        ACC_W       : integer := 32;                             -- Largura do Acumulador de Entrada
        DATA_W      : integer := 8;                              -- Largura do Dado de Saída
        QUANT_W     : integer := 32                              -- Largura dos Parâmetros de Quantização

    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk         : in  std_logic;                             -- Clock do sistema
        rst_n       : in  std_logic;                             -- Reset síncrono (ativo em nível baixo)

        -----------------------------------------------------------------------------------------------------
        -- Entradas 
        -----------------------------------------------------------------------------------------------------

        valid_in    : in  std_logic;                             -- Indica que os dados de entrada são válidos neste ciclo
        acc_in      : in  std_logic_vector(ACC_W-1 downto 0);    -- Acumulador bruto (32-bit) vindo do Systolic Array
        bias_in     : in  std_logic_vector(ACC_W-1 downto 0);    -- Valor de Viés (Bias) a ser somado ao acumulador
        quant_mult  : in  std_logic_vector(QUANT_W-1 downto 0);  -- Fator multiplicativo de escala (Ponto Fixo)
        quant_shift : in  std_logic_vector(4 downto 0);          -- Quantidade de bits para deslocar à direita (Divisão por 2^N)
        zero_point  : in  std_logic_vector(DATA_W-1 downto 0);   -- Offset do Ponto Zero para ajustar a saída (Int8 assimétrico)
        en_relu     : in  std_logic;                             -- Habilita função de ativação ReLU (Zera valores negativos)

        -----------------------------------------------------------------------------------------------------
        -- Saídas 
        -----------------------------------------------------------------------------------------------------

        valid_out   : out std_logic;                             -- Indica que o dado processado está pronto na saída
        data_out    : out std_logic_vector(DATA_W-1 downto 0)    -- Dado final processado e quantizado (8-bit)

        -----------------------------------------------------------------------------------------------------

    );
end entity post_process;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da PPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of post_process is

    -- Constantes para Saturação Dinâmica

    constant MAX_OUT_VAL : integer := (2**(DATA_W-1)) - 1;
    constant MIN_OUT_VAL : integer := -(2**(DATA_W-1));

    -- Largura do Produto (Soma das larguras dos operandos)

    constant PROD_W : integer := ACC_W + QUANT_W;
    
    -- PIPELINE ---------------------------------------------------------------------------------------------

    -- Calcula: Output_int8 = CLAMP (ReLU((Acc_32+Bias_32)*Mult_32 / 2^Shift + ZeroPoint_8))

    -- Estágio 1 (Bias Addition) ----------------------------------------------------------------------------

    signal s1_sum        : signed(ACC_W-1 downto 0) := (others => '0');
    signal s1_valid      : std_logic := '0';
    
    -- Estágio 2 (FP MULT) ----------------------------------------------------------------------------------

    signal s2_prod       : signed(PROD_W-1 downto 0) := (others => '0');
    signal s2_valid      : std_logic := '0';

    -- Estágio 3 (Volta para ACC_W pois o shift deve trazer para uma faixa representável) -------------------

    signal s3_shifted    : signed(ACC_W-1 downto 0) := (others => '0');
    signal s3_valid      : std_logic := '0';
    
    -- Pipeline de Parâmetros -------------------------------------------------------------------------------

    signal p1_quant_mult : signed(QUANT_W-1 downto 0) := (others => '0');
    signal p1_quant_shift: unsigned(4 downto 0) := (others => '0');
    signal p1_zero_point : signed(DATA_W downto 0) := (others => '0');         -- +1 bit para sinal 
    signal p1_relu       : std_logic := '0';
    
    signal p2_quant_shift: unsigned(4 downto 0) := (others => '0');
    signal p2_zero_point : signed(DATA_W downto 0) := (others => '0');
    signal p2_relu       : std_logic := '0';
    
    signal p3_zero_point : signed(DATA_W downto 0) := (others => '0');
    signal p3_relu       : std_logic := '0';

    ---------------------------------------------------------------------------------------------------------

begin

    process(clk, rst_n)

        -- Variáveis precisam ter tamanho suficiente para operações intermediárias
        variable v_round_bit : signed(PROD_W-1 downto 0);
        variable v_shifted   : signed(PROD_W-1 downto 0);
        variable v_final_int : signed(ACC_W-1 downto 0);

    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                s1_valid  <= '0';
                s2_valid  <= '0';
                s3_valid  <= '0';
                valid_out <= '0';
                data_out  <= (others => '0');
                
                s1_sum <= (others => '0');
                s2_prod <= (others => '0');
                s3_shifted <= (others => '0');
                
            else
                
                -- ==========================================================================================
                -- ESTÁGIO 1: BIAS ADD
                -- ==========================================================================================

                s1_sum         <= signed(acc_in) + signed(bias_in);
                s1_valid       <= valid_in;
                p1_quant_mult  <= signed(quant_mult);
                p1_quant_shift <= unsigned(quant_shift);

                -- Expande Zero Point uint para signed positivo
                p1_zero_point  <= resize(signed(zero_point), DATA_W + 1);
                p1_relu        <= en_relu;

                -- ==========================================================================================
                -- ESTÁGIO 2: SCALING
                -- ==========================================================================================

                s2_prod        <= s1_sum * p1_quant_mult;
                s2_valid       <= s1_valid;
                p2_quant_shift <= p1_quant_shift;
                p2_zero_point  <= p1_zero_point;
                p2_relu        <= p1_relu;

                -- ==========================================================================================
                -- ESTÁGIO 3: SHIFT & ROUNDING
                -- ==========================================================================================

                if to_integer(p2_quant_shift) > 0 then
                    v_round_bit := to_signed(1, PROD_W) sll (to_integer(p2_quant_shift) - 1);
                else
                    v_round_bit := (others => '0');
                end if;

                v_shifted := shift_right(s2_prod + v_round_bit, to_integer(p2_quant_shift));
                
                -- Trunca-se para ACC_W (assumindo que o scaling trouxe o valor de volta)

                s3_shifted    <= v_shifted(ACC_W-1 downto 0);
                s3_valid      <= s2_valid;
                p3_zero_point <= p2_zero_point;
                p3_relu       <= p2_relu;

                -- ==========================================================================================
                -- ESTÁGIO 4: ZERO POINT & CLAMPING (DINÂMICO)
                -- ==========================================================================================

                v_final_int := s3_shifted + resize(p3_zero_point, ACC_W);

                -- ReLU

                if p3_relu = '1' and v_final_int < 0 then
                    v_final_int := (others => '0');
                end if;

                -- Saturação Dinâmica baseada nos Generics

                if v_final_int > MAX_OUT_VAL then
                    data_out <= std_logic_vector(to_signed(MAX_OUT_VAL, DATA_W));
                elsif v_final_int < MIN_OUT_VAL then
                    data_out <= std_logic_vector(to_signed(MIN_OUT_VAL, DATA_W));
                else
                    data_out <= std_logic_vector(v_final_int(DATA_W-1 downto 0));
                end if;

                valid_out <= s3_valid;

            end if;
            
        end if;

    end process;

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------