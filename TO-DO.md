# NPU Project - Roadmap & Specifications

Este documento rastreia o progresso do desenvolvimento da NPU e define as especificações técnicas para cada componente.

## 📋 Roadmap (TO-DO List)

### Fase 1: Infraestrutura e Definições
- [x] Criar estrutura de diretórios (`rtl/`, `sim/`, `build/`).
- [x] Configurar `makefile` principal e scripts de suporte.
- [x] Definir `npu_pkg.vhd` (Pacote de constantes e tipos globais).

### Fase 2: O Coração (MAC PE)
- [x] **Design:** Implementar `mac_pe.vhd` (Processing Element).
- [x] **Verificação:** Criar `test_mac_pe.py` (Teste unitário).
- [x] **Simulação:** Validar comportamento de *Weight Stationary* e Pipeline.

### Fase 3: A Arquitetura (Systolic Array)
- [x] **Design:** Implementar `systolic_array.vhd` (Matriz de PEs).
- [x] **Integração:** Instanciar PEs usando `generate` loops.
- [x] **Verificação:** Criar `test_array.py` (Teste de fluxo de dados).

### Fase 4: Otimização e Aplicação (Futuro)
- [ ] Implementar Buffer de Entrada (FIFO) para ativações/dados.
- [ ] Implementar Controlador de Estados (FSM) para carga de pesos.
- [ ] Teste Real: Multiplicação de Matriz 4x4 completa.

---

## 🛠️ Especificações Técnicas

### 1. Pacote Global (`rtl/npu_pkg.vhd`)
Definição dos tipos padrão para garantir consistência em toda a hierarquia.

* **Tipos:**
    * `npu_data_t`: `signed(7 downto 0)` (Ativações e Pesos de 8 bits).
    * `npu_acc_t`: `signed(15 downto 0)` (Acumulador de 32 bits).
* **Constantes:**
    * `DATA_WIDTH`: 8
    * `ACC_WIDTH`: 32

---

### 2. MAC PE (Multiply-Accumulate Processing Element)
O bloco fundamental da NPU. Deve operar na arquitetura **Weight Stationary** (Peso Estacionário).

*Nota: "Act" refere-se a "Activation" (Dado de entrada da Rede Neural).*

#### **Interface (Entity)**
* **Arquivo:** `rtl/mac_pe.vhd`
* **Portas:**
    * `clk`, `rst`: Globais.
    * `load_weight`: Flag de controle.
    * `weight_in`: Entrada de peso (usada apenas quando `load_weight = '1'`).
    * `weight_out`: Saída de peso para cascateamento (Shift Register).
    * `act_in`: Ativação vinda da esquerda.
    * `act_out`: Ativação passante para a direita.
    * `acc_in`: Soma parcial vinda de cima.
    * `acc_out`: Resultado acumulado para baixo.

#### **Requisitos Funcionais (Behavior)**

1.  **Tipagem Forte:**
    * Utilizar `ieee.numeric_std`.
    * Entradas e saídas devem ser do tipo `signed` (usando `npu_pkg`).

2.  **Reset (`rst`):**
    * Síncrono.
    * Deve zerar o `stored_weight` e todos os registradores de saída (`act_out`, `acc_out`).

3.  **Modo Configuração (`load_weight = '1'`):**
    * O PE deve atuar como um registrador de deslocamento vertical para os pesos.
    * `stored_weight` <= `weight_in`.
    * `weight_out` <= `stored_weight` (No próximo ciclo, o vizinho de baixo recebe o valor que estava aqui).
    * *Nota:* Isso permite carregar uma coluna inteira empurrando pesos de cima para baixo.

4.  **Modo Execução (`load_weight = '0'`):**
    * **Multiplicação:** Calcular `act_in * stored_weight`.
    * **Acumulação:** Somar o resultado da multiplicação com `acc_in`.
    * **Pipeline (CRÍTICO):**
        * O valor de `acc_out` deve ser registrado (atraso de 1 ciclo).
        * O valor de `act_out` deve ser uma cópia de `act_in` registrada (atraso de 1 ciclo).
        * *Objetivo:* Permitir o fluxo sistólico de dados (Wavefront) sem quebrar o timing.

---
### 3. Systolic Array (`rtl/systolic_array.vhd`)
A entidade de topo que conecta os PEs em uma grade bidimensional.

#### **Arquitetura & Topologia**
Uma grade de tamanho **ROWS × COLS** onde:
* **Ativações (Acts):** Fluem da Esquerda para a Direita (Row propagation).
* **Pesos (Weights):** Fluem de Cima para Baixo (Daisy Chain Loading).
* **Acumuladores (Accs):** Fluem de Cima para Baixo (Partial Sum accumulation).

#### **Interface (Entity)**
* **Generics:**
    * `ROWS`: Altura da matriz (padrão sugerido: 4).
    * `COLS`: Largura da matriz (padrão sugerido: 4).
* **Portas (Interfaces "Blindadas"):**
    * *Nota: Usar `std_logic_vector` nas portas externas para facilitar integração com ferramentas de simulação (VPI).*
    * `clk`, `rst_n`, `load_weight`: Controle global.
    * `input_weights`: Vetor contendo todos os pesos do topo (Largura: `COLS * DATA_WIDTH`).
    * `input_acts`: Vetor contendo todas as ativações da esquerda (Largura: `ROWS * DATA_WIDTH`).
    * `output_accs`: Vetor contendo os resultados no fundo (Largura: `COLS * ACC_WIDTH`).

#### **Detalhes de Implementação (Internal Logic)**

1.  **Tipos Internos (Linearização):**
    * Para evitar problemas de simulação com matrizes 2D em portas de saída, utilizar **Arrays 1D** para os fios de interconexão.
    * Definir funções auxiliares (`get_h_idx`, `get_v_idx`) para mapear coordenadas `(i, j)` para índices lineares.

2.  **Fios de Interconexão:**
    * `act_wires`: Conecta a saída `act_out` do PE(i,j) à entrada `act_in` do PE(i, j+1).
    * `weight_wires`: Conecta `weight_out` do PE(i,j) à `weight_in` do PE(i+1, j).
    * `acc_wires`: Conecta `acc_out` do PE(i,j) à `acc_in` do PE(i+1, j).

3.  **Conexão das Bordas (Boundary Conditions):**
    * **Topo (Pesos):** Desempacotar `input_weights`, converter para `signed` e conectar na linha 0 dos fios verticais de peso.
    * **Topo (Acumuladores):** Injetar **ZERO** na linha 0 dos fios verticais de soma.
    * **Esquerda (Ativações):** Desempacotar `input_acts`, converter para `signed` e conectar na coluna 0 dos fios horizontais.
    * **Fundo (Saída):** Coleta a última linha dos fios de soma, converte para `std_logic_vector` e conecta a `output_accs`.

4.  **Instanciação (Generate):**
    * Loop duplo (`i` de 0 a ROWS-1, `j` de 0 a COLS-1).
    * Mapear as portas de cada `mac_pe` utilizando os arrays lineares e as funções de índice.