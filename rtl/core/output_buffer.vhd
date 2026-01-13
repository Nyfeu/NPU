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
--      + Accumulator Bank (Tiling Support) 
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
        -- Controle de Tiling
        -----------------------------------------------------------------------------------------------------
        
        -- '1' = Primeiro tile (Sobrescreve), '0' = Tiles seguintes (Acumula)
        acc_clear   : in std_logic; 

        -- '1' = Último tile (Libera saída válida para PPU)
        acc_dump    : in std_logic; 

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
    
    -- Sinais de Deskew (Estágio 1)

    signal in_unpacked     : acc_array_t := (others => (others => '0'));
    signal out_deskewed    : acc_array_t := (others => (others => '0'));
    signal valid_deskewed  : std_logic;                                  

    -- Sinais do Accumulator Bank (Estágio 2)

    signal acc_regs        : acc_array_t := (others => (others => '0')); 
    signal valid_pipe      : std_logic_vector(0 to COLS-2) := (others => '0');

begin

    -- ======================================================================================================
    -- ESTÁGIO 1: DESKEW (Alinhamento Temporal)
    -- ======================================================================================================

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
        
        GEN_NO_DELAY: if DELAY_CYCLES = 0 generate

            out_deskewed(j) <= in_unpacked(j);

        end generate;

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

                        shift_reg(0) <= in_unpacked(j);

                        if DELAY_CYCLES > 1 then
                            for k in 1 to DELAY_CYCLES-1 loop
                                shift_reg(k) <= shift_reg(k-1);
                            end loop;
                        end if;

                    end if;

                end if;

            end process;

            out_deskewed(j) <= shift_reg(DELAY_CYCLES-1);

        end generate;

    end generate GEN_COLS;


    -- Alinhamento do Valid (Pipeline de Controle) ----------------------------------------------------------

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

    valid_deskewed <= valid_pipe(COLS-2);

    -- ======================================================================================================
    -- ESTÁGIO 2: ACCUMULATOR BANK (Soma sobre o tempo)
    -- ======================================================================================================

    process(clk, rst_n)
    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                acc_regs   <= (others => (others => '0'));
                valid_out  <= '0';

            else
                
                -- Padrão: Valid out é zero até que o Dump seja ativado
                valid_out <= '0';

                -- Só processamos se o dado vindo do array (já alinhado) for válido
                if valid_deskewed = '1' then
                    
                    for j in 0 to COLS-1 loop
                        if acc_clear = '1' then
                            -- INÍCIO DO TILE: Sobrescreve o acumulador com o novo dado
                            -- Isso descarta a soma anterior (que já deve ter sido lida)
                            acc_regs(j) <= out_deskewed(j);
                        else
                            -- MEIO DO TILE: Soma o novo dado ao acumulado
                            acc_regs(j) <= acc_regs(j) + out_deskewed(j);
                        end if;
                    end loop;

                    -- FIM DO TILE: Se o sinal de Dump estiver ativo, liberamos o dado para a PPU
                    if acc_dump = '1' then
                        valid_out <= '1';
                    end if;
                    
                end if;

            end if;

        end if;

    end process;

    -- ======================================================================================================
    -- SAÍDA FINAL
    -- ======================================================================================================

    -- Empacota o conteúdo dos registradores de acumulação para a saída
    -- Nota: Se acc_dump = '0', data_out ainda mostra o valor acumulando (spy), 
    -- mas valid_out = '0' impede a PPU de consumir.

    process(acc_regs)
    begin
        for j in 0 to COLS-1 loop
            data_out((j+1)*ACC_W-1 downto j*ACC_W) <= std_logic_vector(acc_regs(j));
        end loop;
    end process;

end architecture; -- rtl 

-------------------------------------------------------------------------------------------------------------