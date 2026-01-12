-------------------------------------------------------------------------------------------------------------
--
-- File: input_buffer.vhd
--
-- ██╗███╗   ██╗██████╗ ██╗   ██╗████████╗
-- ██║████╗  ██║██╔══██╗██║   ██║╚══██╔══╝
-- ██║██╔██╗ ██║██████╔╝██║   ██║   ██║   
-- ██║██║╚██╗██║██╔═══╝ ██║   ██║   ██║   
-- ██║██║ ╚████║██║     ╚██████╔╝   ██║   
-- ╚═╝╚═╝  ╚═══╝╚═╝      ╚═════╝    ╚═╝   
--
-- Descrição: Neural Processing Unit (NPU) - Input Buffer para Ativações (aplica SKEW)
--      Alinha temporalmente os dados de entrada para o formato de onda sistólica.
--
-- Autor    : [André Maiolini]
-- Data     : [11/01/2026]
--
-------------------------------------------------------------------------------------------------------------
                                               
library ieee;                                                -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                 -- Tipos de lógica digital
use ieee.numeric_std.all;                                    -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;                                        -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do Input Buffer
-------------------------------------------------------------------------------------------------------------

entity input_buffer is

    generic (

        ROWS       : integer := 4;                           -- Número de Linhas (Altura)
        DATA_W     : integer := DATA_WIDTH                   -- Largura dos Dados 

    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk         : in  std_logic;                         -- Sinal de clock
        rst_n       : in  std_logic;                         -- Sinal de reset síncrono local (ativo baixo)

        -----------------------------------------------------------------------------------------------------
        -- Entradas (Vetores Empacotados)
        -----------------------------------------------------------------------------------------------------

        -- Sinal de validade dos dados de entrada: '1' carrega dados, '0' injeta bolhas (zeros)

        valid_in     : in std_logic;                         

        -- Entrada linear de dados (ativações): Largura = ROWS * 8 bits

        data_in      : in  std_logic_vector((ROWS * DATA_W)-1 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Saídas (Vetores Empacotados)
        -----------------------------------------------------------------------------------------------------

        -- Saída com dados alinhados temporalmente (com SKEW): Largura = ROWS * 8 bits

        data_out   : out std_logic_vector((ROWS * DATA_W)-1 downto 0)                      

        -----------------------------------------------------------------------------------------------------

    );
end entity input_buffer;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental do Input Buffer
-------------------------------------------------------------------------------------------------------------

architecture rtl of input_buffer is

    -- Array auxiliar para facilitar indexação (Unpacked) ---------------------------------------------------

    type data_array_t is array (0 to ROWS-1) of npu_data_t;
    
    signal in_unpacked  : data_array_t := (others => (others => '0'));
    signal out_unpacked : data_array_t := (others => (others => '0'));

    ---------------------------------------------------------------------------------------------------------

begin 

    -- Desempacotar Entrada (std_logic_vector -> array of signed) -------------------------------------------

    process(data_in)
    begin
        for i in 0 to ROWS-1 loop
            in_unpacked(i) <= signed(data_in((i+1)*DATA_W-1 downto i*DATA_W));
        end loop;
    end process;

    -- Gerar Linhas de Atraso (Skew) ------------------------------------------------------------------------
    
    GEN_ROWS: for i in 0 to ROWS-1 generate
    begin
        
        -- CASO 1: Linha 0 (Sem atraso)
        -- --------------------------------------------------------------------------------------------------
        GEN_NO_DELAY: if i = 0 generate
            -- Se válido, passa o dado. Se não, passa zero.
            out_unpacked(i) <= in_unpacked(i) when (valid_in = '1') else (others => '0');
        end generate;

        -- CASO 2: Linhas 1 a N (Atraso de 'i' ciclos)
        -- --------------------------------------------------------------------------------------------------
        GEN_DELAY: if i > 0 generate

            -- Declaração local de sinais: Cria um registro exclusivo para esta iteração do loop
            -- O tamanho do array depende de 'i'. Ex: Linha 3 tem array de tamanho 3.

            type shift_reg_t is array (0 to i-1) of npu_data_t;
            signal shift_reg : shift_reg_t := (others => (others => '0'));

        begin
            
            process(clk, rst_n)
            begin
                
                if rising_edge(clk) then

                    if rst_n = '0' then

                        shift_reg <= (others => (others => '0'));

                    else 
                    
                        -- Entrada do Shift Register (Posição 0)
                        if valid_in = '1' then
                            shift_reg(0) <= in_unpacked(i);
                        else
                            shift_reg(0) <= (others => '0'); -- Injeta bolha
                        end if;

                        -- Deslocamento (Shift)
                        -- Só executa se o tamanho for maior que 1 (ex: Linha 2 em diante)
                        if i > 1 then
                            for k in 1 to i-1 loop
                                shift_reg(k) <= shift_reg(k-1);
                            end loop;
                        end if;

                    end if;
                    
                end if;

            end process;

            -- A saída desta linha é o último estágio do registro
            out_unpacked(i) <= shift_reg(i-1);

        end generate;

    end generate GEN_ROWS;


    -- Empacotar Saída (array of signed -> std_logic_vector) ------------------------------------------------
    
    process(out_unpacked)
    begin
        for i in 0 to ROWS-1 loop
            data_out((i+1)*DATA_W-1 downto i*DATA_W) <= std_logic_vector(out_unpacked(i));
        end loop;
    end process;

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------