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
-- Data     : [19/01/2026]
--
-------------------------------------------------------------------------------------------------------------   
--
-- >>> Mapa de Memória (Offsets)
-- 
-- 0x00 (RW): CONTROL CSR
--            Bit 0: EN_RELU     (1 = Ativa ReLU, 0 = Pass-through linear)
--            Bit 1: [RESERVED]
--            Bit 2: ACC_CLEAR   (1 = Início do bloco de Tiling: Zera e sobrescreve acumulador)
--            Bit 3: ACC_DUMP    (1 = Fim do bloco de Tiling: Envia resultado acumulado para PPU)
--
-- 0x04 (RW): QUANT_CFG (Bits 0-4: Shift, Bits 8-15: Zero Point)
-- 0x08 (RW): QUANT_MULT (32 bits - Multiplicador da PPU)
--
-- 0x0C (RO): STATUS CSR
--            Bit 0: Input FIFO Full
--            Bit 1: Weight FIFO Full
--            Bit 2: Output FIFO Empty
--            Bit 3: Output FIFO Valid (Tem dado para ler)
--
-- 0x10 (WO): WRITE_WEIGHT_FIFO (Entrada de Pesos)
-- 0x14 (WO): WRITE_INPUT_FIFO  (Entrada de Ativações)
-- 0x18 (RO): READ_OUTPUT_FIFO  (Saída de Resultados)
--
-- 0x20+:     BIAS Registers (0x20=Col0, 0x24=Col1, 0x28=Col2, 0x2C=Col3...)
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
        FIFO_DEPTH  : integer := 64                              -- Profundidade dos Buffers FIFO

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
        data_o      : out std_logic_vector(31 downto 0)          -- Dado indo para a CPU

        -----------------------------------------------------------------------------------------------------

    );
end entity npu_top;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_top is

    -- Sinais de Controle do Barramento ---------------------------------------------------------------------

    signal reg_addr       : integer range 0 to 255;
    signal s_ack          : std_logic;

    -- Registradores de Configuração (CSRs) -----------------------------------------------------------------

    signal r_en_relu      : std_logic := '0';
    signal r_quant_shift  : std_logic_vector(4 downto 0) := (others => '0');
    signal r_quant_zero   : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
    signal r_quant_mult   : std_logic_vector(QUANT_W-1 downto 0) := (others => '0');
    signal r_bias_vec     : std_logic_vector((COLS*ACC_W)-1 downto 0) := (others => '0');
    signal r_acc_clear    : std_logic := '0';
    signal r_acc_dump     : std_logic := '0';

    -- Interfaces das FIFOs ---------------------------------------------------------------------------------
    
    -- Weight FIFO ---

    signal wfifo_w_valid, wfifo_w_ready : std_logic;
    signal wfifo_r_valid, wfifo_r_ready : std_logic;
    signal wfifo_r_data                 : std_logic_vector((COLS*DATA_W)-1 downto 0);
    
    -- Input Act FIFO ---

    signal ififo_w_valid, ififo_w_ready : std_logic;
    signal ififo_r_valid, ififo_r_ready : std_logic;
    signal ififo_r_data                 : std_logic_vector((ROWS*DATA_W)-1 downto 0);

    -- Output FIFO ---

    signal ofifo_w_valid, ofifo_w_ready : std_logic;
    signal ofifo_r_valid, ofifo_r_ready : std_logic;
    signal ofifo_w_data, ofifo_r_data   : std_logic_vector(31 downto 0);
    signal pop_out                      : std_logic;

    -- Sinal de Reset Interno -------------------------------------------------------------------------------

    signal s_soft_rst_n      : std_logic;

    -- Sinais CORE / PPU ------------------------------------------------------------------------------------

    signal core_valid_in     : std_logic;
    signal core_valid_out    : std_logic;
    signal core_accs         : std_logic_vector((COLS*ACC_W)-1 downto 0);
    signal ppu_valid_vec     : std_logic_vector(0 to COLS-1);
    signal ppu_data_vec      : std_logic_vector((COLS*DATA_W)-1 downto 0);

    ---------------------------------------------------------------------------------------------------------

begin

    ---------------------------------------------------------------------------------------------------------
    -- DECODIFICAÇÃO DE ENDEREÇO
    ---------------------------------------------------------------------------------------------------------

    reg_addr <= to_integer(unsigned(addr_i(7 downto 0)));

    ---------------------------------------------------------------------------------------------------------
    -- Reset Interno
    ---------------------------------------------------------------------------------------------------------

    s_soft_rst_n <= rst_n and (not r_acc_clear);

    ---------------------------------------------------------------------------------------------------------
    -- PROCESSO MMIO
    ---------------------------------------------------------------------------------------------------------

    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                rdy_o <= '0';
                s_ack <= '0';
                data_o <= (others => '0');
                wfifo_w_valid <= '0';
                ififo_w_valid <= '0';
                pop_out <= '0';
            else
                wfifo_w_valid <= '0';
                ififo_w_valid <= '0';
                pop_out <= '0';

                if vld_i = '1' then
                    rdy_o <= '1';
                    if s_ack = '0' then
                        s_ack <= '1';

                        if we_i = '1' then
                            case reg_addr is
                                when 16#00# =>
                                    r_en_relu   <= data_i(0);
                                    r_acc_clear <= data_i(2);
                                    r_acc_dump  <= data_i(3);
                                when 16#04# =>
                                    r_quant_shift <= data_i(4 downto 0);
                                    r_quant_zero  <= data_i(15 downto 8);
                                when 16#08# =>
                                    r_quant_mult <= data_i;
                                when 16#10# =>
                                    wfifo_w_valid <= '1';
                                when 16#14# =>
                                    ififo_w_valid <= '1';
                                when 16#20# =>
                                    r_bias_vec(31 downto 0) <= data_i;
                                when 16#24# =>
                                    r_bias_vec(63 downto 32) <= data_i;
                                when 16#28# =>
                                    r_bias_vec(95 downto 64) <= data_i;
                                when 16#2C# =>
                                    r_bias_vec(127 downto 96) <= data_i;
                                when others => null;
                            end case;
                        else
                            case reg_addr is
                                when 16#0C# =>
                                    data_o(0) <= not ififo_w_ready;
                                    data_o(1) <= not wfifo_w_ready;
                                    data_o(2) <= not ofifo_r_valid;
                                    data_o(3) <= ofifo_r_valid;
                                when 16#18# =>
                                    data_o <= ofifo_r_data;
                                    pop_out <= '1';
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
    -- BUFFERIZAÇÃO (FIFOS)
    ---------------------------------------------------------------------------------------------------------
    
    -- Weight FIFO
    u_wfifo : entity work.fifo_sync
        generic map (DATA_W => COLS*DATA_W, DEPTH => FIFO_DEPTH)
        port map (clk, s_soft_rst_n, wfifo_w_valid, wfifo_w_ready, data_i, wfifo_r_valid, wfifo_r_ready, wfifo_r_data);

    -- Input Act FIFO
    u_ififo : entity work.fifo_sync
        generic map (DATA_W => ROWS*DATA_W, DEPTH => FIFO_DEPTH)
        port map (clk, s_soft_rst_n, ififo_w_valid, ififo_w_ready, data_i, ififo_r_valid, ififo_r_ready, ififo_r_data);

    -- Output FIFO
    -- O sinal ofifo_r_ready (POP) agora vem do processo síncrono principal
    u_ofifo : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (clk, s_soft_rst_n, ofifo_w_valid, ofifo_w_ready, ofifo_w_data, ofifo_r_valid, pop_out, ofifo_r_data);


    ---------------------------------------------------------------------------------------------------------
    -- CONTROLE DE FLUXO 
    ---------------------------------------------------------------------------------------------------------
    
    core_valid_in <= wfifo_r_valid and ififo_r_valid;
    wfifo_r_ready <= core_valid_in;
    ififo_r_ready <= core_valid_in;

    ---------------------------------------------------------------------------------------------------------
    -- NPU CORE & PPUs
    ---------------------------------------------------------------------------------------------------------

    u_core : entity work.npu_core
        generic map (ROWS => ROWS, COLS => COLS, DATA_W => DATA_W, ACC_W => ACC_W)
        port map (
            clk           => clk,
            rst_n         => rst_n, 
            acc_clear     => r_acc_clear,
            acc_dump      => r_acc_dump,
            valid_in      => core_valid_in,
            input_weights => wfifo_r_data,
            input_acts    => ififo_r_data,
            output_accs   => core_accs,
            valid_out     => core_valid_out
        );

    -- PPU Instance Generation ------------------------------------------------------------------------------

    GEN_PPU : for i in 0 to COLS-1 generate
        u_ppu : entity work.post_process
            port map (
                clk         => clk,
                rst_n       => rst_n,
                valid_in    => core_valid_out,
                acc_in      => core_accs((i+1)*ACC_W-1 downto i*ACC_W),
                bias_in     => r_bias_vec((i+1)*ACC_W-1 downto i*ACC_W),
                quant_mult  => r_quant_mult,
                quant_shift => r_quant_shift,
                zero_point  => r_quant_zero,
                en_relu     => r_en_relu,
                valid_out   => ppu_valid_vec(i),
                data_out    => ppu_data_vec((i+1)*DATA_W-1 downto i*DATA_W)
            );
    end generate;

    -- Output Packing (Assumindo 4 colunas de 8 bits = 32 bits)

    ofifo_w_valid <= ppu_valid_vec(0);
    ofifo_w_data  <= std_logic_vector(resize(unsigned(ppu_data_vec), 32));

    ---------------------------------------------------------------------------------------------------------
    
end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------