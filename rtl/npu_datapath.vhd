-------------------------------------------------------------------------------------------------------------
--
-- File: npu_datapath.vhd
-- 
-- ██████╗  █████╗ ████████╗ █████╗ ██████╗  █████╗ ████████╗██╗  ██╗
-- ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██║  ██║
-- ██║  ██║███████║   ██║   ███████║██████╔╝███████║   ██║   ███████║
-- ██║  ██║██╔══██║   ██║   ██╔══██║██╔═══╝ ██╔══██║   ██║   ██╔══██║
-- ██████╔╝██║  ██║   ██║   ██║  ██║██║     ██║  ██║   ██║   ██║  ██║
-- ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝                                                               
--
-- Descrição: NPU - Datapath (RAMs, Core, PPU, FIFO)
--
-- Autor    : [André Maiolini]
-- Data     : [21/01/2026]
--
-------------------------------------------------------------------------------------------------------------

library ieee;                                                    -- Biblioteca padrão IEEE
use ieee.std_logic_1164.all;                                     -- Tipos de lógica digital
use ieee.numeric_std.all;                                        -- Tipos numéricos (signed, unsigned)
use work.npu_pkg.all;                                            -- Pacote de definições do NPU

-------------------------------------------------------------------------------------------------------------
-- ENTIDADE: Definição da interface do caminho de dados
-------------------------------------------------------------------------------------------------------------

entity npu_datapath is

    generic (
    
        ROWS        : integer := 4;                              -- Quantidade de Linhas do Array Sistólico
        COLS        : integer := 4;                              -- Quantidade de Colunas do Array Sistólico
        ACC_W       : integer := 32;                             -- Largura do Acumulador de Entrada
        DATA_W      : integer := 8;                              -- Largura do Dado de Saída
        QUANT_W     : integer := 32;                             -- Largura dos Parâmetros de Quantização
        FIFO_DEPTH  : integer := 2048                            -- Define o tamanho da RAM (4KB = 1024 * 32b)
    
    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk                 : in  std_logic;
        rst_n               : in  std_logic;

        -----------------------------------------------------------------------------------------------------
        -- Controle de Memória (Escrita - MMIO)
        -----------------------------------------------------------------------------------------------------

        wgt_we              : in  std_logic;
        inp_we              : in  std_logic;
        w_data              : in  std_logic_vector(31 downto 0);
        wgt_wr_ptr          : in  unsigned(31 downto 0);
        inp_wr_ptr          : in  unsigned(31 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Controle de Memória (Leitura - Controller)
        -----------------------------------------------------------------------------------------------------

        wgt_rd_ptr          : in  unsigned(31 downto 0);
        inp_rd_ptr          : in  unsigned(31 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Controle do Core
        -----------------------------------------------------------------------------------------------------

        ctl_acc_clear       : in  std_logic;
        ctl_acc_dump        : in  std_logic;
        ctl_valid_in        : in  std_logic;                     -- Sincronizado com leitura RAM

        -----------------------------------------------------------------------------------------------------
        -- Configurações PPU
        -----------------------------------------------------------------------------------------------------

        cfg_relu            : in  std_logic;
        cfg_quant_sh        : in  std_logic_vector(4 downto 0);
        cfg_quant_zo        : in  std_logic_vector(DATA_W-1 downto 0);
        cfg_quant_mul       : in  std_logic_vector(QUANT_W-1 downto 0);
        cfg_bias_vec        : in  std_logic_vector((COLS*ACC_W)-1 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Saída FIFO
        -----------------------------------------------------------------------------------------------------

        fifo_pop            : in  std_logic;
        fifo_r_valid        : out std_logic;
        fifo_r_data         : out std_logic_vector(31 downto 0);
        fifo_ready_feedback : out std_logic
    
        -----------------------------------------------------------------------------------------------------
    
    );

end entity npu_datapath;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação estrutural do caminho de dados
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_datapath is

    -- Controle de Memória ----------------------------------------------------------------------------------

    signal wgt_ram_rdata    : std_logic_vector(31 downto 0);
    signal inp_ram_rdata    : std_logic_vector(31 downto 0);
    signal wgt_wr_addr_calc : std_logic_vector(31 downto 0);
    signal wgt_rd_addr_calc : std_logic_vector(31 downto 0);
    signal inp_wr_addr_calc : std_logic_vector(31 downto 0);
    signal inp_rd_addr_calc : std_logic_vector(31 downto 0);

    -- Sinais CORE / PPU ------------------------------------------------------------------------------------

    signal core_valid_out   : std_logic;
    signal core_accs        : std_logic_vector((COLS*ACC_W)-1 downto 0);
    signal ppu_valid_vec    : std_logic_vector(0 to COLS-1);
    signal ppu_data_vec     : std_logic_vector((COLS*DATA_W)-1 downto 0);

    -- FIFO -------------------------------------------------------------------------------------------------

    signal ofifo_w_valid, ofifo_w_ready : std_logic;
    signal ofifo_w_data     : std_logic_vector(31 downto 0);
    signal s_fifo_rst_n     : std_logic;

    ---------------------------------------------------------------------------------------------------------

begin

    ---------------------------------------------------------------------------------------------------------
    -- Memórias (Weights & Inputs)
    ---------------------------------------------------------------------------------------------------------
    
    wgt_wr_addr_calc <= std_logic_vector(wgt_wr_ptr - 1);
    wgt_rd_addr_calc <= std_logic_vector(wgt_rd_ptr - 1);

    u_ram_w : entity work.ram_dual
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk,
            wr_en => wgt_we, 
            wr_addr => wgt_wr_addr_calc,
            wr_data => w_data,
            rd_addr => wgt_rd_addr_calc,
            rd_data => wgt_ram_rdata
        );

    inp_wr_addr_calc <= std_logic_vector(inp_wr_ptr - 1);
    inp_rd_addr_calc <= std_logic_vector(inp_rd_ptr - 1);

    u_ram_i : entity work.ram_dual
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk,
            wr_en => inp_we, 
            wr_addr => inp_wr_addr_calc, 
            wr_data => w_data,
            rd_addr => inp_rd_addr_calc, 
            rd_data => inp_ram_rdata
        );

    ---------------------------------------------------------------------------------------------------------
    -- Core Sistólico
    ---------------------------------------------------------------------------------------------------------

    u_core : entity work.npu_core
        generic map (ROWS => ROWS, COLS => COLS, DATA_W => DATA_W, ACC_W => ACC_W)
        port map (
            clk           => clk,
            rst_n         => rst_n, 
            acc_clear     => ctl_acc_clear,
            acc_dump      => ctl_acc_dump,
            valid_in      => ctl_valid_in,
            input_weights => wgt_ram_rdata,
            input_acts    => inp_ram_rdata,
            output_accs   => core_accs,
            valid_out     => core_valid_out
        );

    ---------------------------------------------------------------------------------------------------------
    -- Post Processing Units (PPU)
    ---------------------------------------------------------------------------------------------------------

    GEN_PPU : for i in 0 to COLS-1 generate
        u_ppu : entity work.post_process
            port map (
                clk         => clk,
                rst_n       => rst_n,
                valid_in    => core_valid_out,
                acc_in      => core_accs((i+1)*ACC_W-1 downto i*ACC_W),
                bias_in     => cfg_bias_vec((i+1)*ACC_W-1 downto i*ACC_W),
                quant_mult  => cfg_quant_mul,
                quant_shift => cfg_quant_sh,
                zero_point  => cfg_quant_zo,
                en_relu     => cfg_relu,
                valid_out   => ppu_valid_vec(i),
                data_out    => ppu_data_vec((i+1)*DATA_W-1 downto i*DATA_W)
            );
    end generate;

    ---------------------------------------------------------------------------------------------------------
    -- Output FIFO
    ---------------------------------------------------------------------------------------------------------

    ofifo_w_valid <= ppu_valid_vec(0); 
    ofifo_w_data  <= std_logic_vector(resize(unsigned(ppu_data_vec), 32));

    -- Exportando o sinal de ready (backpressure)
    -- Se '0', FIFO cheia, Controller deve pausar.
    fifo_ready_feedback <= ofifo_w_ready;
    
    -- Reset da FIFO deve ocorrer apenas se houver CLEAR. No modo Tiling, mantém.
    s_fifo_rst_n  <= rst_n and not ctl_acc_clear;

    u_ofifo : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => 64) 
        port map (
            clk => clk, rst_n => s_fifo_rst_n,
            w_valid => ofifo_w_valid, w_ready => ofifo_w_ready, w_data => ofifo_w_data,
            r_valid => fifo_r_valid, r_ready => fifo_pop, r_data => fifo_r_data
        );

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------