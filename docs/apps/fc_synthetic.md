# Documentação do Dataset Sintético 🚀

## 1. Visão Geral

O **dataset sintético FC** (*Fully Connected*) foi desenvolvido especificamente como uma ferramenta de benchmarking para extrair o limite de desempenho (*peak performance*) da NPU. 

Diferentemente de datasets do mundo real (como o [MNIST](MNIST.md)), que frequentemente contêm alta esparsidade (muitos valores nulos), este conjunto de dados utiliza matrizes densas geradas aleatoriamente. O objetivo é eliminar o viés do *zero-skipping* das CPUs e medir a capacidade bruta de processamento paralelo dos arrays sistólicos da NPU sob carga máxima. 

## 2. Estrutura dos Dados

Os dados são gerados dinamicamente no momento do teste em formato `INT8`, simulando o comportamento de uma camada densa (*Fully Connected Layer*) de uma rede neural de grande porte. 

### 2.1. Dimensões do Teste

A topologia selecionada para a rede avaliada é:

- **Entradas** ($K_{DIM}$): 2048 *features* de entrada;
- **Saídas** ($N_{OUT}$): 64 neurônios na camada;
- **Total de Pesos**: 2048 $\times$ 64 = 131.072 parâmetros (ocupando 128 KB de memória RAM).

### 2.2. Geração Aleatória e Densidade (*Sparsity*)

As matrizes de pesos e os vetores de entrada são preenchidos utilizando uma distribuição uniforme entre `-128` e `126`. 

!!! note "Por que usar dados aleatórios?"
    Em uma distruibuição uniforme de `255`inteiros, a probabilidade de um elemento assumir o valor `0` é de aproximadamente `0,39%`. Isso garante que a matriz resultante seja `> 99,6%` densa. 

Como os aceleradores sistólicos calculam multiplicações de forma agnóstica ao valor do dado (inclusive $0 \times X$), o uso de matrizes quase 100% densas nivela o campo de jogo contra CPUs. Isso revela o ganho real e absoluto de velocidade (*speedup*) originado exclusivamente do paralelismo massivo em hardware, sem a interferência de otimizações de software para dados esparsos.

## 3. Métricas Avaliadas (Benchmark)

O *script* de validação não apenas confere a exatidão dos cálculos, mas também extrai métricas de performance cruciais para a avaliação da arquitetura:

- **Integridade (Bit-Exactness)**: a saída da NPU é comparada *byte* a *byte* com um modelo de referência em software rodando na CPU. O teste só é validado se a taxa de acerto for de 100%, garantindo que o acúmulo e o shifting não introduzam erros de precisão matemática.

- **Speedup**: calculado pela razão direta entre os ciclos de clock consumidos pela CPU e os ciclos consumidos pela NPU para a mesma inferência.

- **Throughput (GOPS)**: mensura a quantidade de Giga Operações por Segundo. Considerando que cada conexão exige uma operação de multiplicação e acúmulo (MAC), o throughput efetivo é calculado com base no tempo total gasto pela NPU para processar todas as amostras.

$$
\text{GOPS} = \cfrac{\text{Total Operações}}{\text{Tempo NPU Segundos} \times 10^9}
$$

## 4. Análise de Desempenho e Aceleração (Speedup)

Os resultados do benchmark sintético demonstraram um speedup médio de 384.6x da NPU em relação à CPU. Embora esse valor absoluto possa parecer ordens de grandeza acima do convencional à primeira vista, ele é matematicamente coerente e esperado quando analisamos as diferenças microarquiteturais entre os dois domínios de execução.

!!! abstract "Paralelo com a Literatura (Google TPU)"
    No artigo que introduziu a Tensor Processing Unit (TPU), Jouppi et al. (2017) reportaram ganhos de aceleração de 15x a 30x (chegando a picos de 71x) contra CPUs e GPUs da época.

É fundamental, no entanto, contextualizar o *baseline* de comparação. O Google utilizou como referência processadores de servidor robustos (Intel Haswell Xeon de 18 núcleos), dotados de execução superescalar fora de ordem (*out-of-order*) e instruções vetoriais complexas (AVX2). Quando contrastamos uma arquitetura de aplicação específica (DSA) com um processador escalar embarcado — que não possui unidades de vetorização nativas — ganhos na casa das centenas representam o comportamento padrão validado pela literatura de arquitetura de computadores.

### 4.1. O Gargalo de Von Neumann no RV32I

O modelo de referência em software foi executado em um processador RISC-V (RV32I) com microarquitetura multi-ciclo. Neste paradigma computacional clássico, o custo real de uma operação de Multiplicação e Acúmulo (MAC), essencial para redes neurais, é dominado pelo acesso à memória e pelo controle de fluxo estrutural.

Considere a instrução interna do laço de processamento de uma camada densa:

$$
acc \leftarrow acc + (\text{peso} \times \text{entrada})
$$

Para computar apenas esta etapa de uma única conexão, o RV32I multi-ciclo exige:

1. Busca de Instruções (Instruction Fetch): Múltiplos ciclos consumidos apenas para ler as instruções de Load, Multiply, Add, Store e de desvio condicional (Branch).

2. Latência de Memória (Data Hazard): A arquitetura consome 12 ciclos apenas para movimentação de dados, sendo 7 ciclos dedicados a cada instrução de LOAD (para buscar o peso e a entrada na memória RAM) e 5 ciclos para eventuais STORE de resultados intermediários.

3. Overhead de Controle: O incremento de ponteiros dos arrays e a verificação de condições do laço for inserem dezenas de ciclos adicionais de controle (overhead) para cada cálculo útil realizado.

Isso explica por que a CPU consome mais de 330 milhões de ciclos para processar as 131.072 conexões da camada, resultando em uma média de milhares de ciclos de clock para completar uma única operação MAC.

### 4.2. Eficiência da Arquitetura Sistólica (NPU)

Em contraste drástico, a NPU resolve o gargalo de acesso à memória através do paralelismo espacial e da localidade de dados.

- **Execução Livre de Instruções**: Os Arrays Sistólicos não buscam instruções em tempo de execução. A Máquina de Estados Finita (FSM) de controle despacha os dados geometricamente pela malha de Processamento (PEs).

- **Localidade de Operandos**: Os 128 KB de pesos pré-carregados nas BRAMs internas eliminam completamente a latência dos 7 ciclos de LOAD do barramento principal.

- **Throughput Constante**: A NPU executa multiplicações e acúmulos a cada batida de clock de forma pipelined, sem penalidades de saltos (branches) ou gerenciamento de ponteiros.

Dessa forma, a métrica de 384.6x ilustra de forma clara e rigorosa o isolamento da carga computacional útil, comprovando o impacto massivo de se transferir algoritmos de alta densidade aritmética de processadores de propósito geral para arquiteturas baseadas em fluxo de dados (dataflow).

### 4.3. Controlador DMA

Um dos fatores mais determinantes para alcançar o speedup relatado em nível de sistema (SoC) é a estratégia de movimentação de dados implementada. O desempenho de um acelerador de hardware não é ditado apenas pela sua capacidade de computação interna, mas diretamente pela forma como ele é alimentado (data feeding).

- O Gargalo do **Programmed I/O (PIO)**: Se o processador RV32I fosse responsável por orquestrar a transferência manual dos dados, ele precisaria ler cada operando da memória principal e escrever nos registradores mapeados em memória do acelerador. Considerando os 12 ciclos de latência de memória do RV32I, o barramento ficaria saturado e a vantagem temporal dos arrays sistólicos seria anulada pelo tempo de transferência.

- **Transferência Autônoma (DMA)**: A arquitetura resolve esse problema de largura de banda delegando a movimentação ao controlador de DMA (Direct Memory Access). A CPU atua apenas em nível de supervisão: ela configura os endereços de origem, destino e o tamanho do bloco. O DMA assume o controle do barramento e realiza transferências diretamente da RAM para as BRAMs locais da NPU, maximizando a largura de banda da interconexão.

- **Sobreposição e Paralelismo Real (Overlap)**: Com a transferência descarregada (offloaded) para o DMA, o custo de latência de I/O é efetivamente mascarado. O RV32I fica com seus ciclos completamente livres para realizar o escalonamento de tarefas do sistema operacional em background (como o gerenciamento de threads no RTOS AXON) ou pré-processar as próximas amostras, enquanto a NPU processa a carga atual de forma totalmente autônoma.

## Referências

- JOUPPI, Norman P. et al. In-datacenter performance analysis of a tensor processing unit. In: Proceedings of the 44th annual international symposium on computer architecture. 2017. p. 1-12.