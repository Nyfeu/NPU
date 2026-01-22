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
        data_o      : out std_logic_vector(31 downto 0)          -- Dado indo para a CPU

        -----------------------------------------------------------------------------------------------------

    );

end entity npu_top;

-------------------------------------------------------------------------------------------------------------
-- ARQUITETURA: Implementação comportamental da NPU
-------------------------------------------------------------------------------------------------------------

architecture rtl of npu_top is

    -- Constantes de Latência -------------------------------------------------------------------------------

    -- Latência da RAM (1) + Input Buffer (1) + Propagação Sistólica (ROWS+COLS)
    constant C_PIPE_LATENCY : integer := 1 + 1 + (ROWS + COLS);

    -- Tempo para DUMP (Shift out dos acumuladores = ROWS ciclos) + Margem PPU
    constant C_DUMP_LATENCY : integer := ROWS + 2;

    -- Sinais de Controle do Barramento ---------------------------------------------------------------------

    signal reg_addr       : integer range 0 to 255 := 0;
    signal s_ack          : std_logic := '0';

    -- Sinais da FSM e Controle -----------------------------------------------------------------------------

    type state_t is (IDLE, COMPUTE, DRAIN);
    signal state : state_t := IDLE;
    
    signal r_run_size     : unsigned(31 downto 0) := (others => '0');
    signal r_cycle_cnt    : unsigned(31 downto 0) := (others => '0');
    signal s_busy         : std_logic := '0';
    signal s_done         : std_logic := '0';

    -- Sinal para Controle de Tiling (Acumulação Parcial)
    -- 1 = Não faz Drain ao final (Tiling)
    signal r_no_drain     : std_logic := '0'; 

    -- Sinal Interno para Dados -----------------------------------------------------------------------------

    signal r_data_o       : std_logic_vector(31 downto 0) := (others => '0');

    -- Ponteiros (escrita DMA) ------------------------------------------------------------------------------

    signal wgt_wr_ptr     : unsigned(31 downto 0) := (others => '0');
    signal inp_wr_ptr     : unsigned(31 downto 0) := (others => '0');

    -- Pointers (leitura da FSM) ----------------------------------------------------------------------------

    signal wgt_rd_ptr     : unsigned(31 downto 0) := (others => '0');
    signal inp_rd_ptr     : unsigned(31 downto 0) := (others => '0');

    -- Sinais da RAM ----------------------------------------------------------------------------------------

    signal s_ram_read_en  : std_logic := '0';
    signal s_core_valid   : std_logic := '0';
    signal wgt_ram_we     : std_logic := '0';
    signal inp_ram_we     : std_logic := '0';
    signal wgt_ram_rdata  : std_logic_vector(31 downto 0) := (others => '0');
    signal inp_ram_rdata  : std_logic_vector(31 downto 0) := (others => '0');

    signal wgt_wr_addr_calc : std_logic_vector(31 downto 0);
    signal wgt_rd_addr_calc : std_logic_vector(31 downto 0);
    signal inp_wr_addr_calc : std_logic_vector(31 downto 0);
    signal inp_rd_addr_calc : std_logic_vector(31 downto 0);

    -- Registradores de Configuração (CSRs) -----------------------------------------------------------------

    signal r_en_relu      : std_logic := '0';
    signal r_quant_shift  : std_logic_vector(4 downto 0) := (others => '0');
    signal r_quant_zero   : std_logic_vector(DATA_W-1 downto 0) := (others => '0');
    signal r_quant_mult   : std_logic_vector(QUANT_W-1 downto 0) := (others => '0');
    signal r_bias_vec     : std_logic_vector((COLS*ACC_W)-1 downto 0) := (others => '0');

    -- Output FIFO ------------------------------------------------------------------------------------------

    signal ofifo_w_valid, ofifo_w_ready : std_logic := '0';
    signal ofifo_r_valid, ofifo_r_ready : std_logic := '0';
    signal ofifo_w_data, ofifo_r_data   : std_logic_vector(31 downto 0) := (others => '0');
    signal pop_out                      : std_logic := '0';
    signal s_fifo_rst_n                 : std_logic := '0';

    -- Sinais CORE / PPU ------------------------------------------------------------------------------------

    signal core_valid_out : std_logic := '0';
    signal core_accs      : std_logic_vector((COLS*ACC_W)-1 downto 0) := (others => '0');
    signal ppu_valid_vec  : std_logic_vector(0 to COLS-1) := (others => '0');
    signal ppu_data_vec   : std_logic_vector((COLS*DATA_W)-1 downto 0) := (others => '0');

    -- Reset Interno ----------------------------------------------------------------------------------------

    signal s_acc_clear    : std_logic := '0';
    signal s_acc_dump     : std_logic := '0';

    ---------------------------------------------------------------------------------------------------------

begin

    ---------------------------------------------------------------------------------------------------------
    -- Decodificação de Endereço
    ---------------------------------------------------------------------------------------------------------

    reg_addr <= to_integer(unsigned(addr_i(7 downto 0)));

    ---------------------------------------------------------------------------------------------------------
    -- Instância RAM 
    ---------------------------------------------------------------------------------------------------------

    -- RAM para os pesos (weights)

    wgt_wr_addr_calc <= std_logic_vector(wgt_wr_ptr - 1);
    wgt_rd_addr_calc <= std_logic_vector(wgt_rd_ptr - 1);

    u_ram_w : entity work.ram_dual
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk,
            wr_en => wgt_ram_we, 
            wr_addr => wgt_wr_addr_calc,
            wr_data => data_i,
            rd_addr => wgt_rd_addr_calc,
            rd_data => wgt_ram_rdata
        );

    -- RAM para os inputs (ativações)

    inp_wr_addr_calc <= std_logic_vector(inp_wr_ptr - 1);
    inp_rd_addr_calc <= std_logic_vector(inp_rd_ptr - 1);

    u_ram_i : entity work.ram_dual
        generic map (DATA_W => 32, DEPTH => FIFO_DEPTH)
        port map (
            clk => clk,
            wr_en => inp_ram_we, 
            wr_addr => inp_wr_addr_calc, 
            wr_data => data_i,
            rd_addr => inp_rd_addr_calc, 
            rd_data => inp_ram_rdata
        );

    ---------------------------------------------------------------------------------------------------------
    -- PROCESSO MMIO: POINTERS & CONFIG
    ---------------------------------------------------------------------------------------------------------

    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                rdy_o <= '0';
                s_ack <= '0';
                data_o <= (others => '0');
                wgt_wr_ptr <= (others => '0');
                inp_wr_ptr <= (others => '0');
                wgt_ram_we <= '0';
                inp_ram_we <= '0';
                pop_out <= '0';
                s_acc_clear <= '0';
                r_no_drain <= '0';
            else
                -- Defaults
                wgt_ram_we <= '0';
                inp_ram_we <= '0';
                pop_out    <= '0';

                -- Auto-clear do sinal de clear (dura 1 ciclo de ack)
                if s_ack = '1' then s_acc_clear <= '0'; end if;

                -- Handshake MMIO
                if vld_i = '1' then
                    rdy_o <= '1';
                    
                    if s_ack = '0' then
                        s_ack <= '1'; -- Registra o Ack para evitar múltiplas escritas no mesmo ciclo
                        
                        -- ESCRITA
                        if we_i = '1' then
                            case reg_addr is
                                -- [0x04] CMD
                                when 16#04# => 
                                    -- Bit 0: Reset Pointers (DMA)
                                    if data_i(0) = '1' then 
                                        wgt_wr_ptr <= (others => '0');
                                        inp_wr_ptr <= (others => '0');
                                    end if;

                                    -- Bit 2: ACC_CLEAR Explícito (Se '0' = ACC_NO_CLEAR)
                                    s_acc_clear <= data_i(2);

                                    -- Bit 1: START (Captura configurações de execução)
                                    if data_i(1) = '1' then
                                        -- Bit 3: NO_DRAIN (Tiling Mode)
                                        r_no_drain <= data_i(3);
                                        -- Nota: Bits 4 e 5 (Reset Reads) são tratados na FSM
                                    end if;
                                
                                -- [0x08] CONFIG
                                when 16#08# => r_run_size <= unsigned(data_i);
                                
                                -- [0x10] W_PORT (Auto-Inc)
                                when 16#10# =>
                                    wgt_ram_we <= '1';
                                    wgt_wr_ptr <= wgt_wr_ptr + 1;

                                -- [0x14] I_PORT (Auto-Inc)
                                when 16#14# =>
                                    inp_ram_we <= '1';
                                    inp_wr_ptr <= inp_wr_ptr + 1;

                                -- Configurações Estáticas
                                when 16#40# => -- QUANT_CFG
                                    r_quant_shift <= data_i(4 downto 0);
                                    r_quant_zero  <= data_i(15 downto 8);
                                when 16#44# => r_quant_mult <= data_i;
                                when 16#48# => r_en_relu <= data_i(0);
                                
                                -- Bias (Exemplo para 4 colunas)
                                when 16#80# => r_bias_vec(31 downto 0)   <= data_i;
                                when 16#84# => r_bias_vec(63 downto 32)  <= data_i;
                                when 16#88# => r_bias_vec(95 downto 64)  <= data_i;
                                when 16#8C# => r_bias_vec(127 downto 96) <= data_i;
                                when others => null;
                            end case;
                        
                        -- LEITURA
                        else
                            case reg_addr is
                                -- [0x00] STATUS
                                when 16#00# =>
                                    data_o <= (0 => s_busy, 1 => s_done, 3 => ofifo_r_valid, others => '0');
                                -- [0x18] OUT_DATA
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
    -- MICRO-SEQUENCIADOR (FSM)
    ---------------------------------------------------------------------------------------------------------
    
    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                state <= IDLE;
                wgt_rd_ptr <= (others => '0');
                inp_rd_ptr <= (others => '0');
                r_cycle_cnt <= (others => '0');
                s_ram_read_en <= '0';
                s_core_valid  <= '0';
                s_acc_dump  <= '0';
                s_busy <= '0';
                s_done <= '0';
            else
                -- Pipeline do Valid (Acompanha latência de 1 ciclo da BRAM)
                s_core_valid <= s_ram_read_en;

                case state is
                    when IDLE =>
                        s_busy <= '0';
                        s_ram_read_en <= '0';
                        s_acc_dump <= '0';
                        
                        -- Start Bit (Bit 1)
                        if vld_i='1' and we_i='1' and reg_addr=16#04# and data_i(1)='1' then
                            state <= COMPUTE;
                            s_busy <= '1';
                            s_done <= '0';
                            
                            r_cycle_cnt <= (others => '0');
                            
                            -- Controle de Reset dos Ponteiros de Leitura (Para Ping-Pong/Tiling)
                            -- Bit 4: Reset Weight Ptr?
                            if data_i(4) = '1' then wgt_rd_ptr <= (others => '0'); end if;
                            
                            -- Bit 5: Reset Input Ptr?
                            if data_i(5) = '1' then inp_rd_ptr <= (others => '0'); end if;
                        end if;

                    when COMPUTE =>
                        s_busy <= '1';
                        
                        -- Lógica 1: Controle de Leitura da RAM 
                        if r_cycle_cnt < r_run_size then
                            s_ram_read_en <= '1';
                            wgt_rd_ptr <= wgt_rd_ptr + 1;
                            inp_rd_ptr <= inp_rd_ptr + 1;
                        else
                            s_ram_read_en <= '0';
                        end if;

                        -- Lógica 2: Controle de Estado (Run + Latência de Propagação)
                        if r_cycle_cnt < (r_run_size + C_PIPE_LATENCY) then
                            r_cycle_cnt <= r_cycle_cnt + 1;
                        else
                            -- Pipeline esvaziou. Verificar se é Tiling ou Drain.
                            if r_no_drain = '1' then
                                -- MODO TILING: Acumula resultado, não limpa FIFO, volta IDLE
                                state <= IDLE;
                                s_done <= '1'; 
                            else
                                -- MODO FINAL: Hora de drenar resultados
                                state <= DRAIN;
                                r_cycle_cnt <= (others => '0');
                            end if;
                        end if;

                    when DRAIN =>
                        s_ram_read_en <= '0';
                        s_acc_dump <= '1';
                        
                        -- Espera o tempo exato para os dados saírem do Array + PPU
                        if r_cycle_cnt < C_DUMP_LATENCY then
                            r_cycle_cnt <= r_cycle_cnt + 1;
                        else
                            state <= IDLE;
                            s_done <= '1';
                            s_acc_dump <= '0';
                        end if;

                end case;
            end if;
        end if;
    end process;

    ---------------------------------------------------------------------------------------------------------
    -- NPU CORE, PPU & OUTPUT
    ---------------------------------------------------------------------------------------------------------

    u_core : entity work.npu_core
        generic map (ROWS => ROWS, COLS => COLS, DATA_W => DATA_W, ACC_W => ACC_W)
        port map (
            clk           => clk,
            rst_n         => rst_n, 
            acc_clear     => s_acc_clear,     -- Controlado pelo MMIO (Bit 2)
            acc_dump      => s_acc_dump,      -- Controlado pela FSM
            valid_in      => s_core_valid,    -- Vem do Pipeline FSM -> RAM -> Core
            input_weights => wgt_ram_rdata,   -- Sai direto da RAM
            input_acts    => inp_ram_rdata,   -- Sai direto da RAM
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

    -- Output FIFO ------------------------------------------------------------------------------------------

    ofifo_w_valid <= ppu_valid_vec(0); 
    ofifo_w_data  <= std_logic_vector(resize(unsigned(ppu_data_vec), 32));
    
    -- Reset da FIFO deve ocorrer apenas se houver CLEAR. No modo Tiling, mantém.
    s_fifo_rst_n  <= rst_n and not s_acc_clear;

    u_ofifo : entity work.fifo_sync
        generic map (DATA_W => 32, DEPTH => 64) 
        port map (
            clk => clk, rst_n => s_fifo_rst_n,
            w_valid => ofifo_w_valid, w_ready => ofifo_w_ready, w_data => ofifo_w_data,
            r_valid => ofifo_r_valid, r_ready => pop_out, r_data => ofifo_r_data
        );

    ---------------------------------------------------------------------------------------------------------
    
end architecture; -- rtl

-------------------------------------------------------------------------------------------------------------