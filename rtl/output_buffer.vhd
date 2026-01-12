-------------------------------------------------------------------------------------------------------------
--
-- File: output_buffer.vhd
--
--  ██████╗ ██╗   ██╗████████╗██████╗ ██╗   ██╗████████╗
-- ██╔═══██╗██║   ██║╚══██╔══╝██╔══██╗██║   ██║╚══██╔══╝
-- ██║   ██║██║   ██║   ██║   ██████╔╝██║   ██║   ██║   
-- ██║   ██║██║   ██║   ██║   ██╔═══╝ ██║   ██║   ██║   
-- ╚██████╔╝╚██████╔╝   ██║   ██║     ╚██████╔╝   ██║   
--  ╚═════╝  ╚═════╝    ╚═╝   ╚═╝      ╚═════╝    ╚═╝                                                     
--
-- Descrição: Neural Processing Unit (NPU) - Output Buffer para Acumuladores (remove SKEW)
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
-- ENTIDADE: Definição da interface do Output Buffer
-------------------------------------------------------------------------------------------------------------

entity output_buffer is

    generic (

        COLS       : integer := 4;                           -- Largura da Matriz
        ACC_W      : integer := ACC_WIDTH                    -- Largura do Acumulador (32 bits)

    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk         : in  std_logic;                         -- Sinal de clock
        rst_n       : in  std_logic;                         -- Sinal de reset síncrono local (ativo baixo)
        
        -----------------------------------------------------------------------------------------------------
        -- Entradas 
        -----------------------------------------------------------------------------------------------------

        -- Controle de Validade da Entrada: '1' dados válidos, '0' ignora dados
        valid_in   : in  std_logic; 
        
        -- Entrada Inclinada (vem do array sistólico)
        data_in    : in  std_logic_vector((COLS * ACC_W)-1 downto 0);
        
        -----------------------------------------------------------------------------------------------------
        -- Saídas 
        -----------------------------------------------------------------------------------------------------

        -- Saída Linear (alinhada para memória/CPU)
        data_out   : out std_logic_vector((COLS * ACC_W)-1 downto 0);
        
        -- Flag de validade alinhada (indica quando o vetor completo está pronto)
        valid_out  : out std_logic

        -----------------------------------------------------------------------------------------------------

    );

end entity output_buffer;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental do Output Buffer
-------------------------------------------------------------------------------------------------------------

architecture rtl of output_buffer is

    -- Tipos Internos
    type acc_array_t is array (0 to COLS-1) of npu_acc_t;
    
    -- Inicialização com Zeros para evitar 'U' na simulação
    signal in_unpacked  : acc_array_t := (others => (others => '0'));
    signal out_unpacked : acc_array_t := (others => (others => '0'));

    -- Pipeline do Valid é um SIGNAL 
    signal valid_pipe   : std_logic_vector(0 to COLS-2) := (others => '0');

begin

    -- Desempacotar Entrada ---------------------------------------------------------------------------------

    process(data_in)
    begin
        for j in 0 to COLS-1 loop
            in_unpacked(j) <= signed(data_in((j+1)*ACC_W-1 downto j*ACC_W));
        end loop;
    end process;

    -- Gerar Linhas de Atraso Invertidas (Deskew) -----------------------------------------------------------
    
    GEN_COLS: for j in 0 to COLS-1 generate

        -- Constante local: Quanto atraso esta coluna precisa?
        -- Coluna 0 precisa esperar pela última. Coluna (COLS-1) não espera nada.
        constant DELAY_CYCLES : integer := (COLS - 1) - j;

    begin
        
        -- CASO 1: Sem Atraso (Última Coluna)
        -- --------------------------------------------------------------------------------------------------
        GEN_NO_DELAY: if DELAY_CYCLES = 0 generate
             out_unpacked(j) <= in_unpacked(j);
        end generate;

        -- CASO 2: Com Atraso (Colunas 0 até Penúltima)
        -- --------------------------------------------------------------------------------------------------
        GEN_DELAY: if DELAY_CYCLES > 0 generate
            
            type shift_reg_t is array (0 to DELAY_CYCLES-1) of npu_acc_t;
            signal shift_reg : shift_reg_t := (others => (others => '0'));
            
        begin

            process(clk, rst_n)
            begin

                if rising_edge(clk) then

                    if rst_n = '0' then

                        shift_reg <= (others => (others => '0'));

                    else

                        -- Shift Register Padrão
                        shift_reg(0) <= in_unpacked(j);
                        
                        if DELAY_CYCLES > 1 then
                            for k in 1 to DELAY_CYCLES-1 loop
                                shift_reg(k) <= shift_reg(k-1);
                            end loop;
                        end if;

                    end if;

                end if;

            end process;

            out_unpacked(j) <= shift_reg(DELAY_CYCLES-1);
            
        end generate;

    end generate GEN_COLS;


    -- Gerar Valid Out (Atraso total para alinhar o sinal de validade) --------------------------------------
    
    process(clk, rst_n)
    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                valid_pipe <= (others => '0');

            else

                valid_pipe(0) <= valid_in;
                for k in 1 to COLS-2 loop
                    valid_pipe(k) <= valid_pipe(k-1);
                end loop;

            end if;

        end if;

    end process;

    valid_out <= valid_pipe(COLS-2);

    -- Empacotar Saída --------------------------------------------------------------------------------------

    process(out_unpacked)
    begin
        for j in 0 to COLS-1 loop
            data_out((j+1)*ACC_W-1 downto j*ACC_W) <= std_logic_vector(out_unpacked(j));
        end loop;
    end process;

end architecture; -- rtl 

-------------------------------------------------------------------------------------------------------------