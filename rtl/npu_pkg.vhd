library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package npu_pkg is

    -- =========================================================================
    -- 1. Constantes Globais de Configuração
    -- =========================================================================
    
    -- Largura dos dados de entrada (Pixels e Pesos)
    constant DATA_WIDTH : integer := 8;
    
    -- Largura do acumulador (Somas parciais)
    -- Deve ser maior que DATA_WIDTH para evitar overflow imediato
    constant ACC_WIDTH  : integer := 32;

    -- =========================================================================
    -- 2. Definição de Tipos Padrão
    -- =========================================================================
    
    -- Tipo para dados e pesos (Signed 8-bit)
    subtype npu_data_t is signed(DATA_WIDTH-1 downto 0);
    
    -- Tipo para acumulação (Signed 32-bit)
    subtype npu_acc_t is signed(ACC_WIDTH-1 downto 0);

end package npu_pkg;
