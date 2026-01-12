# 🌸 Documentação do Dataset Iris

## 1. Visão Geral
O **Iris Dataset** é o conjunto de dados utilizado para validar a inferência real na NPU. Ele consiste na classificação de flores em 3 espécies baseando-se em 4 medidas físicas.

Este dataset foi escolhido porque suas dimensões (4 entradas) casam perfeitamente com a arquitetura física da NPU (Matriz Sistólica 4x4), permitindo validação sem necessidade de *tiling*.

## 2. Estrutura dos Dados

### Entradas (Features)
Cada amostra enviada para a NPU (`valid_in`) é um vetor de 4 bytes (Int8), representando:

| Índice | Feature (Característica) | Unidade Original | Representação NPU |
| :--- | :--- | :--- | :--- |
| **0** | Comprimento da Sépala | cm | Int8 (Quantizado) |
| **1** | Largura da Sépala | cm | Int8 (Quantizado) |
| **2** | Comprimento da Pétala | cm | Int8 (Quantizado) |
| **3** | Largura da Pétala | cm | Int8 (Quantizado) |

### Saídas (Classes)
A NPU retorna um vetor de 4 bytes. Os 3 primeiros correspondem aos *scores* (logits) de cada classe:

| Índice (Coluna) | Espécie (Classe) | Característica Principal |
| :--- | :--- | :--- |
| **0** | **Iris Setosa** | Pétalas pequenas e largas. Fácil de separar. |
| **1** | **Iris Versicolor** | Tamanho médio. Confunde-se com a Virginica. |
| **2** | **Iris Virginica** | Pétalas grandes e longas. |
| **3** | *(Padding)* | Não utilizado (valor ignorado). |

## 3. Mapeamento no Hardware

### Matriz de Pesos (Weights)
O modelo treinado gera uma matriz de pesos de dimensão `[4 entradas x 3 saídas]`.
Na NPU 4x4, adicionamos uma coluna de zeros (padding) para completar a matriz `4x4`.

* **Load Order:** Os pesos são carregados via `ADDR_FIFO_W` (0x10).
* **Layout:**
    ```text
    W[0,0] W[0,1] W[0,2] 0
    W[1,0] W[1,1] W[1,2] 0
    W[2,0] W[2,1] W[2,2] 0
    W[3,0] W[3,1] W[3,2] 0
    ```

### Quantização (Int8)
Como a NPU opera com inteiros de 8 bits, os valores reais (ex: 5.1 cm) são convertidos:

1.  **Escala:** Encontramos o valor máximo absoluto no dataset de treino (ex: 7.9 cm).
2.  **Fator:** `Scale = 7.9 / 127`.
3.  **Conversão:** `Valor_Int8 = Valor_Float / Scale`.

Isso garante que usamos toda a faixa dinâmica de -128 a +127.

### Calibração da PPU (O Segredo da Acurácia)

A NPU opera internamente com acumuladores de 32 bits, mas a saída é limitada a 8 bits (Int8). Sem calibração, ocorre o fenômeno de **saturação** (*quantization saturation*), prejudicando a acurácia do modelo.

#### Problema: Saturação
Durante a inferência, a soma dos produtos (Pesos × Entradas) pode gerar valores muito altos, por exemplo `50.000`.

Ao converter diretamente esse valor para Int8 (intervalo [-128, 127]), ocorre saturação:
* `50.000` -> vira `127` (clamp)
* `48.000` -> vira `127` (clamp)

Apesar de `50.000` ser maior que `48.000`, ambos passam a ter **exatamente a mesma representação**.

Com isso, o hardware perde a capacidade de diferenciar qual valor era realmente maior.  
Na prática, o modelo entra em um regime de **empate artificial**, e a decisão final se assemelha a um chute aleatório — semelhante a uma questão de múltipla escolha em que duas alternativas parecem igualmente corretas.

#### Solução: Re-escalonamento (Rescaling)
Configuramos a PPU para multiplicar e dividir o resultado acumulado *antes* de cortar para 8 bits, trazendo os valores para a faixa dinâmica correta (-128 a +127).

**Configuração Utilizada no Teste:**
* **Mult (0x08):** `100` (Aumenta precisão antes da divisão)
* **Shift (0x04):** `16` (Divide por $2^{16} = 65536$)

**Matemática Real:**
$$Saída = \frac{Acumulador \times 100}{65536}$$

**Exemplo Prático:**
Tomando o mesmo valor de `50.000` que antes saturava:
$$\frac{50.000 \times 100}{65536} \approx \frac{5.000.000}{65536} \approx 76$$

* O valor **76** cabe perfeitamente em 8 bits.
* O valor `48.000` viraria **73**.
* A NPU agora consegue distinguir que **76 > 73**, restaurando a acurácia.

## 4. Exemplo de Inferência

**Entrada (Amostra Real de uma Versicolor):**
* Sépala: 6.0 cm, 2.2 cm
* Pétala: 4.0 cm, 1.0 cm

**Processamento:**
1.  O vetor quantizado entra na NPU.
2.  A matriz sistólica multiplica pelas colunas de pesos das 3 flores.
3.  A PPU aplica o Bias e faz o Rescaling.

**Saída Esperada (Scores):**
* Col 0 (Setosa): -45 (Baixa probabilidade)
* Col 1 (Versicolor): **82** (Alta probabilidade) 🏆
* Col 2 (Virginica): 30 (Média probabilidade)

O testbench (driver) lê esses valores, aplica `argmax([ -45, 82, 30 ])` e retorna **Classe 1 (Versicolor)**.