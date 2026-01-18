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
--
-- >>> Mapa de Memória (Offsets)
-- 
-- 0x00 (RW): CONTROL CSR
--            Bit 0: EN_RELU   (1 = Ativa ReLU, 0 = Pass-through linear)
--            Bit 1: LOAD_MODE (1 = Dados em 0x10 carregam pesos, 0 = Modo Inferência)
--            Bit 2: ACC_CLEAR (1 = Início do bloco de Tiling: Zera e sobrescreve acumulador)
--            Bit 3: ACC_DUMP  (1 = Fim do bloco de Tiling: Envia resultado acumulado para PPU)
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
-- 0x10 (WO): WRITE_WEIGHT_FIFO (Entrada de Pesos - Use quando LOAD_MODE=1)
-- 0x14 (WO): WRITE_INPUT_FIFO  (Entrada de Ativações - Use quando LOAD_MODE=0)
-- 0x18 (RO): READ_OUTPUT_FIFO  (Saída de Resultados - Leitura remove da fila)
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

    signal reg_addr       : integer;

    -- Flag de Acknowledge ----------------------------------------------------------------------------------

    signal s_ack          : std_logic;

    -- Registradores de Configuração (CSRs) -----------------------------------------------------------------

    signal r_en_relu      : std_logic := '0';
    signal r_load_mode    : std_logic := '0'; 
    signal r_quant_shift  : std_logic_vector(4 downto 0) := (others => '0');
    signal r_quant_zero   : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
    signal r_quant_mult   : std_logic_vector(QUANT_W-1 downto 0) := (others => '0');
    signal r_bias_vec     : std_logic_vector((COLS * ACC_W)-1 downto 0) := (others => '0');
    signal r_acc_clear    : std_logic := '0';
    signal r_acc_dump     : std_logic := '0';

    -- Interfaces das FIFOs ---------------------------------------------------------------------------------
    
    -- Weight FIFO ---

    signal wfifo_w_valid, wfifo_w_ready : std_logic;
    signal wfifo_r_valid, wfifo_r_ready : std_logic; 
    signal wfifo_r_data  : std_logic_vector(31 downto 0);
    
    -- Input Act FIFO ---

    signal ififo_w_valid, ififo_w_ready : std_logic;
    signal ififo_r_valid, ififo_r_ready : std_logic;
    signal ififo_r_data  : std_logic_vector(31 downto 0);

    -- Output FIFO ---

    signal ofifo_w_valid, ofifo_w_ready : std_logic;
    signal ofifo_r_valid, ofifo_r_ready : std_logic;
    signal ofifo_w_data  : std_logic_vector(31 downto 0);
    signal ofifo_r_data  : std_logic_vector(31 downto 0);
    signal s_read_fifo_pop  : std_logic;

    -- Sinais Internos do Core NPU --------------------------------------------------------------------------

    signal core_valid_in    : std_logic;
    signal core_load_weight : std_logic;
    signal core_valid_out   : std_logic;
    signal core_output_data : std_logic_vector((COLS * DATA_W)-1 downto 0);
    
    -- Sinais Intermediários (Core -> PPU) ------------------------------------------------------------------

    signal core_accs        : std_logic_vector((COLS * ACC_W)-1 downto 0);
    signal ppu_valid_vec    : std_logic_vector(0 to COLS-1);
    signal core_to_ppu_valid: std_logic;

    ---------------------------------------------------------------------------------------------------------

begin

    ---------------------------------------------------------------------------------------------------------
    -- 1. DECODIFICAÇÃO DE ENDEREÇO E ESCRITA (MMIO)
    ---------------------------------------------------------------------------------------------------------

    -- Endereço simplificado
    reg_addr <= to_integer(unsigned(addr_i(7 downto 0)));

    -- Lógica da interface MMIO síncrona
    process(clk, rst_n)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                rdy_o         <= '0';
                s_ack         <= '0';
                data_o        <= (others => '0');
                
                -- Reset Registers
                r_en_relu     <= '0';
                r_load_mode   <= '0';
                r_quant_shift <= (others => '0');
                r_quant_zero  <= (others => '0');
                r_quant_mult  <= (others => '0');
                r_bias_vec    <= (others => '0');
                r_acc_clear   <= '0';
                r_acc_dump    <= '0';
                
                -- Reset Control Signals
                wfifo_w_valid   <= '0';
                ififo_w_valid   <= '0';
                s_read_fifo_pop <= '0';

            else
                -- Defaults (Pulsos de 1 ciclo)
                rdy_o           <= '0';
                wfifo_w_valid   <= '0';
                ififo_w_valid   <= '0';
                s_read_fifo_pop <= '0';
                
                -- Limpa o bus de dados (boa prática)
                data_o          <= (others => '0');

                -- Lógica de Handshake
                if vld_i = '1' then
                    
                    -- Se ainda não demos ACK nesta transação:
                    if s_ack = '0' then
                        rdy_o <= '1'; -- Responde no próximo ciclo
                        s_ack <= '1'; -- Marca que já atendemos

                        -- === ESCRITA ===
                        if we_i = '1' then
                            case reg_addr is
                                when 16#00# => -- Control
                                    r_en_relu   <= data_i(0);
                                    r_load_mode <= data_i(1);
                                    r_acc_clear <= data_i(2);
                                    r_acc_dump  <= data_i(3);

                                when 16#04# => -- Quant Config
                                    r_quant_shift <= data_i(4 downto 0);
                                    r_quant_zero  <= data_i(15 downto 8);

                                when 16#08# => r_quant_mult <= data_i;

                                -- FIFOs (Gera pulso único de escrita)
                                when 16#10# => wfifo_w_valid <= '1'; -- Write Weight
                                when 16#14# => ififo_w_valid <= '1'; -- Write Input

                                -- Bias
                                when 16#20# => r_bias_vec(31 downto 0)   <= data_i;
                                when 16#24# => r_bias_vec(63 downto 32)  <= data_i;
                                when 16#28# => r_bias_vec(95 downto 64)  <= data_i;
                                when 16#2C# => r_bias_vec(127 downto 96) <= data_i;
                                
                                when others => null;
                            end case;

                        -- === LEITURA ===
                        else
                            case reg_addr is
                                when 16#00# => -- Control
                                    data_o(0) <= r_en_relu;
                                    data_o(1) <= r_load_mode;
                                    data_o(2) <= r_acc_clear;
                                    data_o(3) <= r_acc_dump;

                                when 16#04# => -- Quant
                                    data_o(4 downto 0)  <= r_quant_shift;
                                    data_o(15 downto 8) <= r_quant_zero;

                                when 16#08# => data_o <= r_quant_mult;

                                when 16#0C# => -- STATUS
                                    data_o(0) <= not ififo_w_ready; -- Input Full?
                                    data_o(1) <= not wfifo_w_ready; -- Weight Full?
                                    data_o(2) <= not ofifo_r_valid; -- Output Empty?
                                    data_o(3) <= ofifo_r_valid;     -- Output Has Data?

                                when 16#18# => -- READ OUTPUT FIFO
                                    data_o <= ofifo_r_data;
                                    s_read_fifo_pop <= '1'; -- Consome o dado da fila (POP)

                                when 16#20# => data_o <= r_bias_vec(31 downto 0);
                                when 16#24# => data_o <= r_bias_vec(63 downto 32);
                                when 16#28# => data_o <= r_bias_vec(95 downto 64);
                                when 16#2C# => data_o <= r_bias_vec(127 downto 96);
                                
                                when others => data_o <= (others => '0');
                            end case;
                        end if;
                    
                    else
                        -- Se vld ainda é 1, mas ack já é 1:
                        -- Mantemos rdy_o em 0 para forçar o Master a baixar o valid.
                        -- Não fazemos nada (proteção contra double-write).
                        null;
                    end if;
                else
                    -- Master baixou o valid, podemos resetar o ack para a próxima
                    s_ack <= '0';
                end if;
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------
    -- 2. BUFFERIZAÇÃO (FIFOS)
    ---------------------------------------------------------------------------------------------------------
    
    -- Weight FIFO
    u_fifo_weights : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk, rst_n => rst_n,
            w_valid => wfifo_w_valid, w_ready => wfifo_w_ready, w_data => data_i,
            r_valid => wfifo_r_valid, r_ready => wfifo_r_ready, r_data => wfifo_r_data
        );

    -- Input Act FIFO
    u_fifo_acts : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk, rst_n => rst_n,
            w_valid => ififo_w_valid, w_ready => ififo_w_ready, w_data => data_i,
            r_valid => ififo_r_valid, r_ready => ififo_r_ready, r_data => ififo_r_data
        );

    -- Output FIFO
    -- O sinal ofifo_r_ready (POP) agora vem do processo síncrono principal
    ofifo_r_ready <= s_read_fifo_pop;

    u_fifo_out : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk, rst_n => rst_n,
            w_valid => ofifo_w_valid, w_ready => ofifo_w_ready, w_data => ofifo_w_data,
            r_valid => ofifo_r_valid, r_ready => ofifo_r_ready, r_data => ofifo_r_data
        );

    ---------------------------------------------------------------------------------------------------------
    -- 3. CONTROLE DE FLUXO (AUTO-POP)
    ---------------------------------------------------------------------------------------------------------
    
    -- Lógica: Se a FIFO tem dados (valid) E a NPU está no modo correto, consumimos (ready)
    
    -- Controle de Pesos
    wfifo_r_ready    <= '1' when (wfifo_r_valid = '1' and r_load_mode = '1') else '0';
    core_load_weight <= wfifo_r_ready;

    -- Controle de Ativações
    ififo_r_ready    <= '1' when (ififo_r_valid = '1' and r_load_mode = '0') else '0';
    core_valid_in    <= ififo_r_ready;

    ---------------------------------------------------------------------------------------------------------
    -- 4. NPU CORE & PPUs
    ---------------------------------------------------------------------------------------------------------

    u_npu_core : entity work.npu_core
        generic map (ROWS => ROWS, COLS => COLS, DATA_W => DATA_W, ACC_W => ACC_W)
        port map (
            clk           => clk,
            rst_n         => rst_n,
            acc_clear     => r_acc_clear,
            acc_dump      => r_acc_dump,
            load_weight   => core_load_weight,
            valid_in      => core_valid_in,
            input_weights => wfifo_r_data,
            input_acts    => ififo_r_data,
            valid_out     => core_to_ppu_valid,
            output_accs   => core_accs
        );

    -- PPU Instance Generation ------------------------------------------------------------------------------

    GEN_PPUS: for i in 0 to COLS-1 generate
    begin
        u_ppu : entity work.post_process
            generic map (ACC_W => ACC_W, DATA_W => DATA_W, QUANT_W => QUANT_W)
            port map (
                clk         => clk,
                rst_n       => rst_n,
                valid_in    => core_to_ppu_valid,
                acc_in      => core_accs((i+1)*ACC_W-1 downto i*ACC_W),
                bias_in     => r_bias_vec((i+1)*ACC_W-1 downto i*ACC_W),
                quant_mult  => r_quant_mult,
                quant_shift => r_quant_shift,
                zero_point  => r_quant_zero,
                en_relu     => r_en_relu,
                valid_out   => ppu_valid_vec(i),
                data_out    => core_output_data((i+1)*DATA_W-1 downto i*DATA_W)
            );
    end generate;

    -- Output Packing (Assumindo 4 colunas de 8 bits = 32 bits)

    ofifo_w_valid <= ppu_valid_vec(0);
    ofifo_w_data  <= std_logic_vector(resize(unsigned(core_output_data), 32));

    ---------------------------------------------------------------------------------------------------------
    
end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------