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
-- Data     : [21/01/2026]
--
------------------------------------------------------------------------------------------------------------- 
--
-- >>> Mapa de Memória (Offsets)
-- 
-- Base (Controle DMA/FSM)
--
--  0x00 : STATUS (RO) [0=Busy, 1=Done]
--  0x04 : CMD    (WO) 
--
--   - Bit[0]: RST_DMA_PTRS (Zera ponteiros de escrita - Nova Carga)
--   - Bit[1]: START        (Inicia a execução)
--   - Bit[2]: ACC_CLEAR    (1=Limpa Array antes de rodar, 0=Acumula/ACC_NO_CLEAR)
--   - Bit[3]: ACC_NO_DRAIN (1=Mantém resultado no Array/Tiling, 0=Salva na FIFO)
--   - Bit[4]: RST_W_RD     (1=Zera ponteiro leitura Pesos, 0=Continua de onde parou)
--   - Bit[5]: RST_I_RD     (1=Zera ponteiro leitura Inputs, 0=Continua de onde parou)
--   - Bit[6]: RST_WR_W     (1=Zera ponteiro de escrita Pesos, 0=Continua de onde parou)
--   - Bit[7]: RST_WR_I     (1=Zera ponteiro de escrita Inputs, 0=Continua de onde parou)
--
--  0x08 : CONFIG (RW) [Tamanho do Tile / Ciclos]
--  0x10 : W_PORT (WO) [Porta de Pesos - Fixed Dest]
--  0x14 : I_PORT (WO) [Porta de Inputs - Fixed Dest]
--  0x18 : O_DATA (RO) [Leitura de Saída]
--
-- Configuração Estática 
-- 
--  0x40 : QUANT_CFG
--  0x44 : QUANT_MULT
--  0x48 : CONTROL_FLAGS (ReLU, etc)
--  0x80+: BIAS
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

        clk         : in  std_logic;                             -- Clock do sistema
        rst_n       : in  std_logic;                             -- Reset síncrono (ativo em nível baixo)

        -----------------------------------------------------------------------------------------------------
        -- Interface para Mapeamento em Memória (MMIO)
        -----------------------------------------------------------------------------------------------------

        vld_i       : in  std_logic;                             -- Valid
        rdy_o       : out std_logic;                             -- Ready
        we_i        : in  std_logic;                             -- 1=Write, 0=Read
        addr_i      : in  std_logic_vector(31 downto 0);         -- Endereço
        data_i      : in  std_logic_vector(31 downto 0);         -- Dado vindo da CPU
        data_o      : out std_logic_vector(31 downto 0);         -- Dado indo para a CPU

        -----------------------------------------------------------------------------------------------------
        -- Interface para Interrupção (IRQ)
        -----------------------------------------------------------------------------------------------------

        irq_done_o  : out std_logic

        -----------------------------------------------------------------------------------------------------

    );

end entity npu_top;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_top is

    -- Register File <-> Controller -------------------------------------------------------------------------

    signal s_cmd_start           : std_logic := '0';
    signal s_cmd_no_drain        : std_logic := '0';
    signal s_cmd_rst_w           : std_logic := '0';
    signal s_cmd_rst_i           : std_logic := '0';
    signal s_sts_busy            : std_logic := '0';
    signal s_sts_done            : std_logic := '0';
    signal s_cfg_run_size        : unsigned(31 downto 0) := (others => '0');

    -- Register File <-> Datapath ---------------------------------------------------------------------------

    signal s_cmd_clear           : std_logic := '0';
    signal s_ram_w_data          : std_logic_vector(31 downto 0) := (others => '0');
    signal s_wgt_we              : std_logic := '0';
    signal s_inp_we              : std_logic := '0';
    signal s_wgt_wr_ptr          : unsigned(31 downto 0) := (others => '0');
    signal s_inp_wr_ptr          : unsigned(31 downto 0) := (others => '0');
    signal s_fifo_pop            : std_logic := '0';
    signal s_fifo_r_valid        : std_logic := '0';
    signal s_fifo_r_data         : std_logic_vector(31 downto 0) := (others => '0');

    -- Config Signals ---------------------------------------------------------------------------------------

    signal s_cfg_relu            : std_logic := '0';
    signal s_cfg_quant_sh        : std_logic_vector(4 downto 0) := (others => '0');
    signal s_cfg_quant_zo        : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
    signal s_cfg_quant_mul       : std_logic_vector(QUANT_W-1 downto 0) := (others => '0');
    signal s_cfg_bias_vec        : std_logic_vector((COLS*ACC_W)-1 downto 0) := (others => '0');

    -- Controller <-> Datapath ------------------------------------------------------------------------------

    signal s_wgt_rd_ptr          : unsigned(31 downto 0) := (others => '0');
    signal s_inp_rd_ptr          : unsigned(31 downto 0) := (others => '0');
    signal s_ctl_acc_dump        : std_logic := '0';
    signal s_ctl_core_vld        : std_logic := '0';
    signal s_fifo_ready_feedback : std_logic := '1';

    -- Sinal Auxiliar para Edge Detector --------------------------------------------------------------------

    signal r_done_dly            : std_logic := '0';

    ---------------------------------------------------------------------------------------------------------

begin

    -- ========================================================================
    -- DETECTOR DE BORDA DA INTERRUPÇÃO
    -- ========================================================================
    -- Gera um pulso de 1 ciclo quando 's_sts_done' transita de 0 para 1.
    
    process(clk)
    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                r_done_dly <= '0';
                irq_done_o <= '0';

            else

                r_done_dly <= s_sts_done; -- Guarda estado anterior

                -- Rising Edge Detection
                if (s_sts_done = '1' and r_done_dly = '0') then
                    irq_done_o <= '1'; -- Pulso!
                else
                    irq_done_o <= '0';
                end if;
                
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------
    -- Instância: Register File & MMIO
    ---------------------------------------------------------------------------------------------------------

    u_reg_file : entity work.npu_register_file
        generic map (
            ACC_W         => ACC_W, 
            DATA_W        => DATA_W, 
            QUANT_W       => QUANT_W, 
            COLS          => COLS
        )
        port map (
            
            -- Sinais de Controle e Sincronismo
            clk           => clk, 
            rst_n         => rst_n,

            -- Memory Mapped I/O (MMIO)
            vld_i         => vld_i, 
            rdy_o         => rdy_o, 
            we_i          => we_i, 
            addr_i        => addr_i, 
            data_i        => data_i, 
            data_o        => data_o,

            -- Controller Interface
            sts_busy      => s_sts_busy, 
            sts_done      => s_sts_done,
            cmd_start     => s_cmd_start, 
            cmd_clear     => s_cmd_clear, 
            cmd_no_drain  => s_cmd_no_drain,
            cmd_rst_w     => s_cmd_rst_w, 
            cmd_rst_i     => s_cmd_rst_i,

            -- Datapath Interface
            fifo_r_valid  => s_fifo_r_valid, 
            fifo_r_data   => s_fifo_r_data, 
            fifo_pop      => s_fifo_pop,
            ram_w_data    => s_ram_w_data, 
            wgt_we        => s_wgt_we, 
            inp_we        => s_inp_we, 
            wgt_wr_ptr    => s_wgt_wr_ptr, 
            inp_wr_ptr    => s_inp_wr_ptr,

            -- Configs Interface
            cfg_run_size  => s_cfg_run_size, 
            cfg_relu      => s_cfg_relu, 
            cfg_quant_sh  => s_cfg_quant_sh, 
            cfg_quant_zo  => s_cfg_quant_zo, 
            cfg_quant_mul => s_cfg_quant_mul, 
            cfg_bias_vec  => s_cfg_bias_vec

        );

    ---------------------------------------------------------------------------------------------------------
    -- Instância: Controller (FSM)
    ---------------------------------------------------------------------------------------------------------

    u_controller : entity work.npu_controller
        generic map (
            ROWS          => ROWS, 
            COLS          => COLS
        )
        port map (

            -- Sinais de Controle e Sincronismo
            clk           => clk, 
            rst_n         => rst_n,

            -- RegFile Interface
            cmd_start     => s_cmd_start, 
            cmd_no_drain  => s_cmd_no_drain,
            cmd_rst_w     => s_cmd_rst_w, 
            cmd_rst_i     => s_cmd_rst_i,
            cfg_run_size  => s_cfg_run_size,
            
            -- System Interface
            sts_busy      => s_sts_busy, 
            sts_done      => s_sts_done,

            -- Datapath Interface
            wgt_rd_ptr    => s_wgt_rd_ptr, 
            inp_rd_ptr    => s_inp_rd_ptr,
            ctl_ram_re    => open,                                -- Usado internamente para gerar core_vld
            ctl_core_vld  => s_ctl_core_vld, 
            ctl_acc_dump  => s_ctl_acc_dump,

            -- Backpressure (STALL)
            fifo_ready_i => s_fifo_ready_feedback

        );

    ---------------------------------------------------------------------------------------------------------
    -- Instância: Datapath (RAMs, Core, FIFO)
    ---------------------------------------------------------------------------------------------------------

    u_datapath : entity work.npu_datapath
        generic map (
            ROWS          => ROWS, 
            COLS          => COLS, 
            ACC_W         => ACC_W, 
            DATA_W        => DATA_W, 
            QUANT_W       => QUANT_W, 
            FIFO_DEPTH    => FIFO_DEPTH
        )
        port map (

            clk                 => clk, 
            rst_n               => rst_n,

            -- Write Side (RegFile)
            wgt_we              => s_wgt_we, 
            inp_we              => s_inp_we, 
            w_data              => s_ram_w_data,
            wgt_wr_ptr          => s_wgt_wr_ptr, 
            inp_wr_ptr          => s_inp_wr_ptr,

            -- Read Side (Controller)
            wgt_rd_ptr          => s_wgt_rd_ptr, 
            inp_rd_ptr          => s_inp_rd_ptr,
            ctl_acc_clear       => s_cmd_clear, 
            ctl_acc_dump        => s_ctl_acc_dump, 
            ctl_valid_in        => s_ctl_core_vld,

            -- Configs
            cfg_relu            => s_cfg_relu, 
            cfg_quant_sh        => s_cfg_quant_sh, 
            cfg_quant_zo        => s_cfg_quant_zo, 
            cfg_quant_mul       => s_cfg_quant_mul, 
            cfg_bias_vec        => s_cfg_bias_vec,
            
            -- FIFO
            fifo_pop            => s_fifo_pop, 
            fifo_r_valid        => s_fifo_r_valid, 
            fifo_r_data         => s_fifo_r_data,
            fifo_ready_feedback => s_fifo_ready_feedback
        
        );

    ---------------------------------------------------------------------------------------------------------

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------