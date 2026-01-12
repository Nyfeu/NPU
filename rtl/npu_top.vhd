-------------------------------------------------------------------------------------------------------------
--
-- File: npu_top.vhd
-- 
-- ███╗   ██╗██████╗ ██╗   ██╗
-- ████╗  ██║██╔══██╗██║   ██║
-- ██╔██╗ ██║██████╔╝██║   ██║
-- ██║╚██╗██║██╔═══╝ ██║   ██║
-- ██║ ╚████║██║     ╚██████╔╝
-- ╚═╝  ╚═══╝╚═╝      ╚═════╝ 
--
-- Descrição: Neural Processing Unit (NPU) - TOP-LEVEL (IP)
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
-- ENTIDADE: Definição da interface da NPU
-------------------------------------------------------------------------------------------------------------

entity npu_top is

    generic (

        ROWS       : integer := 4;                               -- Quantidade de Linhas do Array Sistólico
        COLS       : integer := 4;                               -- Quantidade de Colunas do Array Sistólico
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
        -- Interface com o Controlador 
        -----------------------------------------------------------------------------------------------------
        
        load_weight   : in  std_logic;
        valid_in      : in  std_logic;
        input_weights : in  std_logic_vector((COLS * DATA_W)-1 downto 0);
        input_acts    : in  std_logic_vector((ROWS * DATA_W)-1 downto 0);
        
        -----------------------------------------------------------------------------------------------------
        -- Interface de Configuração (PPU) - CSRs (Control & Status Registers) virtuais
        -----------------------------------------------------------------------------------------------------

        bias_in       : in  std_logic_vector((COLS * ACC_W)-1 downto 0);
        quant_mult    : in  std_logic_vector(QUANT_W-1 downto 0);
        quant_shift   : in  std_logic_vector(4 downto 0);
        zero_point    : in  std_logic_vector(DATA_W-1 downto 0);
        en_relu       : in  std_logic;

        -----------------------------------------------------------------------------------------------------
        -- Saída Final do IP
        -----------------------------------------------------------------------------------------------------

        valid_out     : out std_logic;
        output_data   : out std_logic_vector((COLS * DATA_W)-1 downto 0)

        -----------------------------------------------------------------------------------------------------

    );

end entity npu_top;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU
-------------------------------------------------------------------------------------------------------------

architecture struct of npu_top is

    -- Sinais de Ligação Core -> PPU
    signal core_valid_out : std_logic;
    signal core_accs      : std_logic_vector((COLS * ACC_W)-1 downto 0);
    
    -- Sinais de Validação dos PPUs
    signal ppu_valid_vec  : std_logic_vector(0 to COLS-1);

begin

    -- Instância do NPU CORE --------------------------------------------------------------------------------

    u_npu_core : entity work.npu_core
        generic map (
            ROWS   => ROWS,
            COLS   => COLS,
            DATA_W => DATA_W,
            ACC_W  => ACC_W
        )
        port map (
            clk           => clk,
            rst_n         => rst_n,
            load_weight   => load_weight,
            valid_in      => valid_in,
            input_weights => input_weights,
            input_acts    => input_acts,
            valid_out     => core_valid_out,
            output_accs   => core_accs
        );

    -- Instância dos PPUs (Pós-Processamento Paralelo) ------------------------------------------------------

    GEN_PPUS: for i in 0 to COLS-1 generate
    begin

        u_ppu : entity work.post_process
            generic map (
                ACC_W   => ACC_W,
                DATA_W  => DATA_W,
                QUANT_W => QUANT_W
            )
            port map (
                clk         => clk,
                rst_n       => rst_n,
                valid_in    => core_valid_out, -- Acionado quando o Core termina
                
                -- Fatiamento dos dados do Core
                acc_in      => core_accs((i+1)*ACC_W-1 downto i*ACC_W),
                
                -- Fatiamento do Bias (Um por coluna)
                bias_in     => bias_in((i+1)*ACC_W-1 downto i*ACC_W),
                
                -- Parâmetros Globais
                quant_mult  => quant_mult,
                quant_shift => quant_shift,
                zero_point  => zero_point,
                en_relu     => en_relu,
                
                -- Saídas
                valid_out   => ppu_valid_vec(i),
                data_out    => output_data((i+1)*DATA_W-1 downto i*DATA_W)
            );

    end generate;

    -- O IP só entrega o dado quando o Pós-Processamento termina
    valid_out <= ppu_valid_vec(0);

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------