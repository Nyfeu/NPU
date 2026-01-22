------------------------------------------------------------------------------------------------------------------
-- 
-- File: ram_dual.vhd
--
-- ██████╗  █████╗ ███╗   ███╗
-- ██╔══██╗██╔══██╗████╗ ████║
-- ██████╔╝███████║██╔████╔██║
-- ██╔══██╗██╔══██║██║╚██╔╝██║
-- ██║  ██║██║  ██║██║ ╚═╝ ██║
-- ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
--  
-- Descrição : RAM de Porta Dupla Simples (Inferência de BRAM)
--             Porta A: Escrita (Usada pelo DMA/CPU)
--             Porta B: Leitura (Usada pela NPU Core)
-- 
-- Autor     : [André Maiolini]
-- Data      : [21/01/2026]    
--
------------------------------------------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-------------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface da Dual Port RAM
-------------------------------------------------------------------------------------------------------------------

entity ram_dual is

    generic (

        DATA_W : integer := 32;
        DEPTH  : integer := 1024 -- 4KB conforme roadmap

    );

    port (

        -- Sincronização (clock)
        clk      : in  std_logic;
        
        -- Porta de Escrita (DMA)
        wr_en    : in  std_logic;
        wr_addr  : in  std_logic_vector(31 downto 0);
        wr_data  : in  std_logic_vector(DATA_W-1 downto 0);
        
        -- Porta de Leitura (NPU)
        rd_addr  : in  std_logic_vector(31 downto 0);
        rd_data  : out std_logic_vector(DATA_W-1 downto 0)

    );

end entity;

-------------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação da Dual Port RAM
-------------------------------------------------------------------------------------------------------------------

architecture rtl of ram_dual is

    -- Função para calcular log2 para dimensionar o array
    function log2_ceil(val : integer) return integer is
        variable res : integer := 0;
        variable tmp : integer := 1;
    begin
        if val <= 1 then return 1; end if;
        while tmp < val loop
            tmp := tmp * 2;
            res := res + 1;
        end loop;
        return res;
    end function;

    constant ADDR_BITS : integer := log2_ceil(DEPTH);
    type mem_t is array (0 to DEPTH-1) of std_logic_vector(DATA_W-1 downto 0);
    signal ram : mem_t := (others => (others => '0'));

begin

    process(clk)
    begin

        if rising_edge(clk) then
        
            -- Escrita Síncrona
            if wr_en = '1' then
                ram(to_integer(unsigned(wr_addr(ADDR_BITS-1 downto 0)))) <= wr_data;
            end if;
            
            -- Leitura Síncrona
            rd_data <= ram(to_integer(unsigned(rd_addr(ADDR_BITS-1 downto 0))));
        
        end if;

    end process;

end architecture;

-------------------------------------------------------------------------------------------------------------------