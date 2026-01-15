# 📃 Modelo de Programação da NPU

## 1. Visão Geral
A NPU opera como um periférico mapeado em memória (MMIO) com comportamento de fluxo (stream). Devido à natureza de *pipeline* sistólico, **não há mecanismo de travamento (stall) automático do núcleo** caso a saída esteja cheia. O controle de fluxo deve ser gerenciado pelo Software ou DMA.

## 2. Mapa de Registradores (Base Address + Offset)

| Offset | Registrador | Acesso | Descrição |
| :--- | :--- | :--- | :--- |
| `0x00` | **CTRL** | RW | Configuração de modo e ativação. |
| `0x04` | **QUANT** | RW | Parâmetros de quantização (Shift, ZP). |
| `0x08` | **MULT** | RW | Multiplicador da PPU. |
| `0x0C` | **STATUS** | RO | Flags de estado das FIFOs. |
| `0x10` | **W_FIFO** | WO | Porta de entrada de Pesos. |
| `0x14` | **IN_FIFO** | WO | Porta de entrada de Ativações (Dados). |
| `0x18` | **OUT_FIFO** | RO | Porta de saída de Resultados. |

## 3. Perda de Dados (Data Loss)

### Problema
A NPU processa 1 vetor de entrada e gera 1 vetor de saída com latência fixa. Se a **Output FIFO** estiver cheia quando o resultado ficar pronto, o dado será **descartado** (Overflow).

### Solução: Janela Deslizante (Credit-Based Flow)
Para garantir integridade zero-loss, o driver deve garantir a invariante:
` (Vetores Enviados - Vetores Lidos) <= PROFUNDIDADE_FIFO_SAIDA `

A profundidade padrão da FIFO é **64**.

## 4. Bits de Status (Polling)

Use o registrador `STATUS (0x0C)` para decisões em tempo real:

* **Bit 0 (IN_FULL):** 
    * `1`: Pare de enviar dados.
    * `0`: Seguro para enviar.
* **Bit 3 (OUT_VALID):**
    * `1`: Dados disponíveis. Leia imediatamente para liberar espaço.
    * `0`: Buffer vazio.