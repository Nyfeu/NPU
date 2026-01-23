-------------------------------------------------------------------------------------------------------------
--
-- File: npu_register_file.vhd
-- 
-- ██████╗ ███████╗ ██████╗         ███████╗██╗██╗     ███████╗
-- ██╔══██╗██╔════╝██╔════╝         ██╔════╝██║██║     ██╔════╝
-- ██████╔╝█████╗  ██║  ███╗        █████╗  ██║██║     █████╗  
-- ██╔══██╗██╔══╝  ██║   ██║        ██╔══╝  ██║██║     ██╔══╝  
-- ██║  ██║███████╗╚██████╔╝███████╗██║     ██║███████╗███████╗
-- ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝     ╚═╝╚══════╝╚══════╝                                                         
--
-- Descrição: NPU - Register File & MMIO Decoder
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
-- ENTIDADE: Definição da interface do banco de registradores
-------------------------------------------------------------------------------------------------------------

entity npu_register_file is

    generic (
        
        ACC_W       : integer := 32;                             -- Largura do Acumulador de Entrada
        DATA_W      : integer := 8;                              -- Largura do Dado de Saída
        QUANT_W     : integer := 32;                             -- Largura dos Parâmetros de Quantização
        COLS        : integer := 4                               -- Quantidade de Colunas do Array Sistólico
    
    );

    port (

        -----------------------------------------------------------------------------------------------------
        -- Sinais de Controle e Sincronização
        -----------------------------------------------------------------------------------------------------

        clk           : in  std_logic;
        rst_n         : in  std_logic;

        -----------------------------------------------------------------------------------------------------
        -- Interface MMIO 
        -----------------------------------------------------------------------------------------------------

        vld_i         : in  std_logic;
        rdy_o         : out std_logic;
        we_i          : in  std_logic;
        addr_i        : in  std_logic_vector(31 downto 0);
        data_i        : in  std_logic_vector(31 downto 0);
        data_o        : out std_logic_vector(31 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Interface com Controller (Status & Comandos)
        -----------------------------------------------------------------------------------------------------

        sts_busy      : in  std_logic;
        sts_done      : in  std_logic;
        cmd_start     : out std_logic;
        cmd_clear     : out std_logic;
        cmd_no_drain  : out std_logic;
        cmd_rst_w     : out std_logic; -- Reset Read Ptr Weights
        cmd_rst_i     : out std_logic; -- Reset Read Ptr Inputs

        -----------------------------------------------------------------------------------------------------
        -- Interface com Datapath (FIFO Read)
        -----------------------------------------------------------------------------------------------------

        fifo_r_valid  : in  std_logic;
        fifo_r_data   : in  std_logic_vector(31 downto 0);
        fifo_pop      : out std_logic;

        -----------------------------------------------------------------------------------------------------
        -- Interface com Datapath (RAM Write Control)
        -----------------------------------------------------------------------------------------------------

        ram_w_data    : out std_logic_vector(31 downto 0); -- Pass-through
        wgt_we        : out std_logic;
        inp_we        : out std_logic;
        wgt_wr_ptr    : out unsigned(31 downto 0);
        inp_wr_ptr    : out unsigned(31 downto 0);

        -----------------------------------------------------------------------------------------------------
        -- Configurações Exportadas
        -----------------------------------------------------------------------------------------------------

        cfg_run_size  : out unsigned(31 downto 0);
        cfg_relu      : out std_logic;
        cfg_quant_sh  : out std_logic_vector(4 downto 0);
        cfg_quant_zo  : out std_logic_vector(DATA_W-1 downto 0);
        cfg_quant_mul : out std_logic_vector(QUANT_W-1 downto 0);
        cfg_bias_vec  : out std_logic_vector((COLS*ACC_W)-1 downto 0)

        -----------------------------------------------------------------------------------------------------

    );

end entity npu_register_file;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental do banco de registradores
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_register_file is

    -- Sinais para Mapeamento -------------------------------------------------------------------------------

    signal s_ack        : std_logic := '0';

    -- Registradores Internos -------------------------------------------------------------------------------

    signal r_run_size    : unsigned(31 downto 0) := (others => '0');
    signal r_wgt_wr_ptr  : unsigned(31 downto 0) := (others => '0');
    signal r_inp_wr_ptr  : unsigned(31 downto 0) := (others => '0');
    
    -- Configs ----------------------------------------------------------------------------------------------

    signal r_en_relu     : std_logic := '0';
    signal r_quant_shift : std_logic_vector(4 downto 0) := (others => '0');
    signal r_quant_zero  : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
    signal r_quant_mult  : std_logic_vector(QUANT_W-1 downto 0) := (others => '0');
    signal r_bias_vec    : std_logic_vector((COLS*ACC_W)-1 downto 0) := (others => '0');

    -- Comandos (Pulsos ou Níveis) --------------------------------------------------------------------------

    signal s_cmd_start   : std_logic := '0';
    signal s_acc_clear   : std_logic := '0';

    ---------------------------------------------------------------------------------------------------------

begin

    -- Wiring outputs ---------------------------------------------------------------------------------------

    cfg_run_size  <= r_run_size;
    cfg_relu      <= r_en_relu;
    cfg_quant_sh  <= r_quant_shift;
    cfg_quant_zo  <= r_quant_zero;
    cfg_quant_mul <= r_quant_mult;
    cfg_bias_vec  <= r_bias_vec;
    wgt_wr_ptr    <= r_wgt_wr_ptr;
    inp_wr_ptr    <= r_inp_wr_ptr;
    ram_w_data    <= data_i; 
    cmd_start     <= s_cmd_start;
    cmd_clear     <= s_acc_clear;

    process(clk)

        variable v_addr_idx : integer range 0 to 255 := 0;

    begin

        if rising_edge(clk) then

            if rst_n = '0' then

                rdy_o <= '0';
                s_ack <= '0';
                data_o <= (others => '0');
                
                r_wgt_wr_ptr <= (others => '0');
                r_inp_wr_ptr <= (others => '0');
                
                wgt_we <= '0';
                inp_we <= '0';
                fifo_pop <= '0';
                
                s_cmd_start <= '0';
                s_acc_clear <= '0';
                cmd_no_drain <= '0';
                cmd_rst_w <= '0';
                cmd_rst_i <= '0';

                r_en_relu <= '0';

            else

                -- LÓGICA DE OPERAÇÃO NORMAL
                if not is_x(addr_i(7 downto 0)) then
                    v_addr_idx := to_integer(unsigned(addr_i(7 downto 0)));
                end if;

                -- Defaults (Strobes)
                wgt_we <= '0';
                inp_we <= '0';
                fifo_pop <= '0';
                s_cmd_start <= '0'; 

                -- Auto-clear do sinal de clear (dura 1 ciclo de ack)
                if s_ack = '1' then 
                    s_acc_clear <= '0'; 
                end if;

                -- Handshake MMIO
                if vld_i = '1' then
                    rdy_o <= '1';
                    
                    if s_ack = '0' then
                        s_ack <= '1';
                        
                        -------------------------------------------------------------------------------------
                        -- ESCRITA (MMIO)
                        -- Só é aceita se a NPU estiver IDLE
                        -------------------------------------------------------------------------------------

                        if we_i = '1' and sts_busy = '0' then
                            case v_addr_idx is
                                -- [0x04] CMD
                                when 16#04# => 
                                    -- Bit 0: Global Pointers Reset (DMA Write Ptrs) 
                                    if data_i(0) = '1' then 
                                        r_wgt_wr_ptr <= (others => '0');
                                        r_inp_wr_ptr <= (others => '0');
                                    end if;
                                    -- Bit 6: Reset apenas Wgt Write Ptr (NOVO)
                                    if data_i(6) = '1' then 
                                        r_wgt_wr_ptr <= (others => '0');
                                    end if;
                                    -- Bit 7: Reset apenas Inp Write Ptr (NOVO)
                                    if data_i(7) = '1' then 
                                        r_inp_wr_ptr <= (others => '0');
                                    end if;
                                    -- Bit 2: ACC_CLEAR
                                    s_acc_clear <= data_i(2);
                                    -- Bit 1: START
                                    if data_i(1) = '1' then
                                        s_cmd_start <= '1';
                                        cmd_no_drain <= data_i(3);
                                        cmd_rst_w <= data_i(4); -- Reset Read Ptr Weights (to Controller)
                                        cmd_rst_i <= data_i(5); -- Reset Read Ptr Inputs (to Controller)
                                    end if;
                                
                                -- [0x08] CONFIG
                                when 16#08# => r_run_size <= unsigned(data_i);
                                
                                -- [0x10] W_PORT (Auto-Inc)
                                when 16#10# =>
                                    wgt_we <= '1';
                                    r_wgt_wr_ptr <= r_wgt_wr_ptr + 1;

                                -- [0x14] I_PORT (Auto-Inc)
                                when 16#14# =>
                                    inp_we <= '1';
                                    r_inp_wr_ptr <= r_inp_wr_ptr + 1;

                                -- Configurações Estáticas
                                when 16#40# => -- QUANT_CFG
                                    r_quant_shift <= data_i(4 downto 0);
                                    r_quant_zero  <= data_i(15 downto 8);
                                when 16#44# => r_quant_mult <= data_i;
                                when 16#48# => r_en_relu <= data_i(0);
                                
                                -- Bias
                                when 16#80# => r_bias_vec(31 downto 0)   <= data_i;
                                when 16#84# => r_bias_vec(63 downto 32)  <= data_i;
                                when 16#88# => r_bias_vec(95 downto 64)  <= data_i;
                                when 16#8C# => r_bias_vec(127 downto 96) <= data_i;
                                when others => null;
                            end case;
                        
                        -------------------------------------------------------------------------------------
                        -- LEITURA (MMIO)
                        -------------------------------------------------------------------------------------

                        else
                            case v_addr_idx is
                                -- [0x00] STATUS
                                when 16#00# =>
                                    data_o <= (0 => sts_busy, 1 => sts_done, 3 => fifo_r_valid, others => '0');
                                -- [0x18] OUT_DATA
                                when 16#18# =>
                                    data_o <= fifo_r_data;
                                    fifo_pop <= '1';
                                when others => 
                                    data_o <= (others => '0');
                            end case;
                        end if;
                    end if;

                else
                    rdy_o <= '0';
                    s_ack <= '0';
                end if;

            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------

end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------