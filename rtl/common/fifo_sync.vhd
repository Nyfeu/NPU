-------------------------------------------------------------------------------------------------------------
--
-- File: fifo_sync.vhd
--
-- ███████╗██╗███████╗ ██████╗ 
-- ██╔════╝██║██╔════╝██╔═══██╗
-- █████╗  ██║█████╗  ██║   ██║
-- ██╔══╝  ██║██╔══╝  ██║   ██║
-- ██║     ██║██║     ╚██████╔╝
-- ╚═╝     ╚═╝╚═╝      ╚═════╝ 
--
-- Autor    : [André Maiolini]
-- Data     : [12/01/2026]
-- 
-------------------------------------------------------------------------------------------------------------

library ieee;                                                    -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                     -- Tipos de lógica digital
use ieee.numeric_std.all;                                        -- Tipos numéricos (signed, unsigned)

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do buffer FIFO
----------------------------------------------------------------------------------------------------

entity fifo_sync is

    generic (

        DATA_W : integer := 8;   -- Largura dos dados
        DEPTH  : integer := 16   -- Profundidade da Fila (número de slots)
    
    );

    port (

        clk       : in  std_logic;
        rst_n     : in  std_logic;

        -- Interface de Escrita (Quem manda dados para a FIFO)
        w_valid   : in  std_logic; -- "Tenho dado para gravar"
        w_ready   : out std_logic; -- "Posso aceitar gravação" (Not Full)
        w_data    : in  std_logic_vector(DATA_W-1 downto 0);

        -- Interface de Leitura (Quem consome dados da FIFO)
        r_valid   : out std_logic; -- "Tenho dado para ler" (Not Empty)
        r_ready   : in  std_logic; -- "Já li/consumi o dado"
        r_data    : out std_logic_vector(DATA_W-1 downto 0);
        
        -- Status (Opcional, útil para debug ou CSRs)
        count     : out std_logic_vector(31 downto 0) -- Quantos itens tem na fila
    
    );

end entity fifo_sync;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental do buffer FIFO
----------------------------------------------------------------------------------------------------

architecture rtl of fifo_sync is

    -- Memória da FIFO (Inferida como Block RAM ou Distributed RAM)
    type mem_t is array (0 to DEPTH-1) of std_logic_vector(DATA_W-1 downto 0);
    signal mem : mem_t := (others => (others => '0'));

    -- Ponteiros
    signal head : integer range 0 to DEPTH-1 := 0; -- Onde escrever (Write Pointer)
    signal tail : integer range 0 to DEPTH-1 := 0; -- Onde ler (Read Pointer)
    
    -- Contador de ocupação
    signal count_i : integer range 0 to DEPTH := 0;
    
    -- Flags Internas
    signal full_i  : std_logic;
    signal empty_i : std_logic;

begin

    -- Lógica de Flags
    full_i  <= '1' when count_i = DEPTH else '0';
    empty_i <= '1' when count_i = 0     else '0';

    -- Saídas de Controle
    w_ready <= not full_i;  -- Pronto para escrever se não estiver cheia
    r_valid <= not empty_i; -- Dado válido para leitura se não estiver vazia
    
    -- Saída de Count
    count <= std_logic_vector(to_unsigned(count_i, 32));

    -- O dado na saída é sempre o que está apontado pelo Tail
    r_data <= mem(tail);

    -- Processo Principal
    process(clk, rst_n)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                head    <= 0;
                tail    <= 0;
                count_i <= 0;
            else
                -- Lógica de Escrita
                -- Se o produtor quer escrever (Valid) E temos espaço (Ready/!Full)
                if (w_valid = '1' and full_i = '0') then
                    mem(head) <= w_data;
                    
                    if head = DEPTH-1 then
                        head <= 0;
                    else
                        head <= head + 1;
                    end if;
                end if;

                -- Lógica de Leitura
                -- Se o consumidor aceitou o dado (Ready) E tinhamos dado (Valid/!Empty)
                if (r_ready = '1' and empty_i = '0') then
                    if tail = DEPTH-1 then
                        tail <= 0;
                    else
                        tail <= tail + 1;
                    end if;
                end if;

                -- Atualização do Contador (Ocupação)
                if (w_valid = '1' and full_i = '0') and (r_ready = '1' and empty_i = '0') then
                    -- Escreveu e Leu ao mesmo tempo: Contagem não muda
                    count_i <= count_i;
                elsif (w_valid = '1' and full_i = '0') then
                    -- Só escreveu
                    count_i <= count_i + 1;
                elsif (r_ready = '1' and empty_i = '0') then
                    -- Só leu
                    count_i <= count_i - 1;
                end if;
                
            end if;
        end if;
    end process;

end architecture; -- rtl

----------------------------------------------------------------------------------------------------