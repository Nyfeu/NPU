# 🔢 Documentação do Dataset MNIST

## 1. Visão Geral
O **MNIST Dataset** foi o conjunto de dados utilizado para validar a capacidade de **Tiling (Ladrilhamento)** e o processamento de grandes volumes de dados na NPU. Ele consiste no reconhecimento de dígitos manuscritos (0 a 9) a partir de imagens em escala de cinza de 28x28 pixels.

Diferente do Iris, este dataset excede as dimensões físicas da NPU (784 entradas vs 4 linhas físicas), exigindo que o driver de software fracione o problema em blocos menores que são acumulados temporalmente pelo hardware.

## 2. Estrutura dos Dados

### Entradas (Features)
Cada amostra é uma imagem de $28 \times 28$ pixels, que é "achatada" (*flattened*) em um vetor linear de 784 bytes (Int8).

| Índice | Feature (Pixel) | Representação Original | Representação NPU |
| :--- | :--- | :--- | :--- |
| **0** | Pixel (0,0) - Canto Sup. Esq. | 0 (Preto) a 255 (Branco) | Int8 (Padronizado) |
| **1..782** | Pixels intermediários | 0 a 255 | Int8 (Padronizado) |
| **783** | Pixel (27,27) - Canto Inf. Dir. | 0 a 255 | Int8 (Padronizado) |

### Saídas (Classes)
A NPU deve calcular scores para 10 classes. Como o array tem largura 4, o processamento é feito em 3 passadas de colunas:

| Índice | Dígito (Classe) | Passada do Tiling |
| :--- | :--- | :--- |
| **0, 1, 2, 3** | Dígitos **0, 1, 2, 3** | 1ª Passada |
| **4, 5, 6, 7** | Dígitos **4, 5, 6, 7** | 2ª Passada |
| **8, 9** | Dígitos **8, 9** | 3ª Passada (+ Padding) |

## 3. Mapeamento no Hardware (Tiling)

O desafio do MNIST é mapear uma matriz de pesos virtual de `[784 entradas x 10 saídas]` em um hardware físico de `[4x4]`. Utilizamos a estratégia de **Double Tiling**:

### 1. Tiling Vertical (Accumulation)
Como temos 784 entradas e apenas 4 linhas:
* O driver divide as 784 entradas em **196 blocos** de 4 valores.
* **Controle:**
    * No 1º bloco: O driver envia flag `ACC_CLEAR` (zera acumuladores).
    * Nos blocos centrais: A NPU soma os resultados parciais internamente.
    * No 196º bloco: O driver envia flag `ACC_DUMP` (libera o resultado).

### 2. Tiling Horizontal (Passadas)
Como temos 10 classes e apenas 4 colunas:
* O processo acima é repetido 3 vezes para cobrir todas as colunas da matriz de pesos.

### Calibração "Inteligente" da PPU

No MNIST, a dispersão dos dados é diferente do Iris (muitos zeros devido ao fundo preto das imagens). Uma calibração teórica baseada no pior caso leva à perda total de sinal.

#### Problema: O "Over-Shifting"
O pior caso teórico (todos pixels brancos × todos pesos máximos) geraria um acumulador de ~12.000.000.
* Para acomodar isso em 8 bits, precisaríamos de um **Shift = 17** (dividir por 131.072).
* Porém, a soma real observada nas inferências raramente passa de **32.000**.
* **Resultado:** $32.000 \div 131.072 = 0$. A saída da NPU seria sempre zero.

#### Solução: Calibração por Observação
Ajustamos o shift baseando-nos nos valores máximos reais observados durante a execução do conjunto de validação.

**Configuração Otimizada (Smart Calibration):**
* **Mult (0x08):** `1` (Pass-through)
* **Shift (0x04):** `9` (Divide por $2^9 = 512$)

**Matemática Real:**
$$Saída = \frac{Acumulador \times 1}{512}$$

**Exemplo Prático:**
Se o acumulador final para o dígito "7" for `32.700`:
$$\frac{32.700}{512} \approx 63$$

* O valor **63** é um score alto e válido em Int8.
* Isso permitiu atingir acurácia **Bit-Exact** em relação ao modelo de software.

## 4. Exemplo de Inferência

**Entrada (Imagem de um "7"):**
* Vetor de 784 bytes, onde a maioria é 0 (fundo), mas os pixels centrais formam o desenho.

**Processamento (Resumo):**
1.  **Passada 1 (Dígitos 0-3):** Acumuladores terminam baixos (ex: -10, -5, 2, -20).
2.  **Passada 2 (Dígitos 4-7):**
    * O acumulador da coluna 3 (Dígito 7) soma muita correlação positiva.
    * Valor bruto atinge `32.000`.
    * PPU aplica Shift 9 -> Saída **62**.
3.  **Passada 3 (Dígitos 8-9):** Acumuladores baixos.

**Saída Final (Scores):**
```text
[ -10, -5, 2, -20,  15, -8, -2,  62,  5,  -12 ]
                                 ^
                                 Dígito 7