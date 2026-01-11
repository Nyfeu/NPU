# NPU Project - Roadmap & Specifications

Este documento rastreia o progresso do desenvolvimento da NPU e define as especificações técnicas para cada componente.

## 📋 Roadmap (TO-DO List)

### Fase 1: Infraestrutura e Definições
- [x] Criar estrutura de diretórios (`rtl/`, `sim/`, `build/`).
- [x] Configurar `makefile` principal e scripts de suporte.
- [ ] Definir `npu_pkg.vhd` (Pacote de constantes e tipos globais).

### Fase 2: O Coração (MAC PE)
- [ ] **Design:** Implementar `mac_pe.vhd` (Processing Element).
- [ ] **Verificação:** Criar `test_mac_pe.py` (Teste unitário).
- [ ] **Simulação:** Validar comportamento de *Weight Stationary* e Pipeline.

### Fase 3: A Arquitetura (Systolic Array)
- [ ] **Design:** Implementar `systolic_array.vhd` (Matriz de PEs).
- [ ] **Integração:** Instanciar PEs usando `generate` loops.
- [ ] **Verificação:** Criar `test_array.py` (Teste de fluxo de dados).
- [ ] **Correção:** Garantir propagação correta de sinais (evitar inferência de latches).

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
    * `npu_acc_t`: `signed(15 downto 0)` (Acumulador de 16 bits).
* **Constantes:**
    * `DATA_WIDTH`: 8
    * `ACC_WIDTH`: 16

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
