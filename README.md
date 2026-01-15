# NPU: Neural Processing Unit 

![VHDL](https://img.shields.io/badge/VHDL-2008-blue?style=for-the-badge&logo=vhdl)
![GHDL](https://img.shields.io/badge/Simulator-GHDL-green?style=for-the-badge&logo=ghdl)
![GTKWave](https://img.shields.io/badge/Waveform-GTKWave-9cf?style=for-the-badge&logo=gtkwave)
![Python](https://img.shields.io/badge/Python-3.10-blue?style=for-the-badge&logo=python)

```
    ███╗   ██╗██████╗ ██╗   ██╗
    ████╗  ██║██╔══██╗██║   ██║
    ██╔██╗ ██║██████╔╝██║   ██║
    ██║╚██╗██║██╔═══╝ ██║   ██║     ->> PROJECT: NPU Systolic Array Accelerator
    ██║ ╚████║██║     ╚██████╔╝     ->> AUTHOR: André Solano F. R. Maiolini
    ╚═╝  ╚═══╝╚═╝      ╚═════╝      ->> DATE: 11/1/2026
```

This repository contains the implementation of a Neural Processing Unit (NPU) based on a Systolic Array architecture, designed to accelerate NN (Neural Networks) workloads. The project is developed entirely in VHDL-2008. 

The design implements a Weight-Stationary architecture, where weights are pre-loaded into the Processing Elements (PEs) and input activations flow through the array in a wavefront pattern. This approach maximizes data reuse and minimizes memory bandwidth requirements.

Verification is a core pillar of this project. It utilizes Cocotb (Python) for automated testing, featuring unit tests, randomized fuzzing against Python Golden Models, and end-to-end integration tests.

| Document | Description | Link |
| :-: | :-: | :-: | 
| **Programmer's Guide** | Register map, UART protocol, and data formats. | [**docs/NPU_PROGRAMMING.md** ](./docs/NPU_PROGRAMMING.md) | 
| **MNIST Dataset** | Details on the digit recognition network. | [**docs/MNIST.md** ](./docs/MNIST.md) | 
| **IRIS Dataset** | Details on the iris flower classification network. | [**docs/IRIS.md** ](./docs/IRIS.md) | 

## 🎯 Goals and Features

* **Architecture**: Systloci Array (Weight Stationary)
* **Precision**: INT8 for Input/Weights, INT32 for Accumulators
* **Language**: VHDL-2008
* **Automation**: fully automated build system via `makefile` for simulation and waveform generation
* **Hadware-in-the-Loop (HIL)**: real-time inference verification on Nexys 4 FPGA using Python drivers

## 📂 Project Structure

The repository is organized to separate hardware design (RTL), verification testbenches, and build artifacts.

```
npu-accelerator/
|
├── rtl/               # VHDL Source Code
│   ├── core/          # NPU Core, Systolic Array, MACs
│   ├── ppu/           # Post-Processing Unit (ReLU, Accumulation)
│   ├── common/        # Shared Components (FIFOs)
│   └── fpga_tester/   # UART Wrapper & Top Level for FPGA
├── sim/               # Cocotb Testbenches
├── fpga/              # Vivado Constraints (XDC) & Build Scripts (Tcl)
├── sw/                # Python Host Drivers & HIL Applications
├── pkg/               # VHDL Packages
└── mk/                # Modular Build System (Makefiles)
```

## 🛠️ Prerequisites
To compile and simulate this project, install the following tools and ensure they are in your PATH:

1. **GHDL**: Open-source VHDL simulator.
2. **GTKWave**: Waveform viewer.
3. **COCOTB**: Python-based coroutine testbench framework for hardware simulation.
4. **Python 3**: Required for running cocotb testbenches.
5. **Xilinx Vivado**: synthesis and FPGA programming.

## 🚀 How to Compile and Simulate (Using the Makefile)

All commands are executed from the root of the repository. The Makefile automates hardware simulation via COCOTB and waveform visualization.

```
 
 
      ███╗   ██╗██████╗ ██╗   ██╗ 
      ████╗  ██║██╔══██╗██║   ██║ 
      ██╔██╗ ██║██████╔╝██║   ██║ 
      ██║╚██╗██║██╔═══╝ ██║   ██║ 
      ██║ ╚████║██║     ╚██████╔╝ 
      ╚═╝  ╚═══╝╚═╝      ╚═════╝  
 
============================================================================================
           NPU BUILD SYSTEM                      
============================================================================================
 
 🧠 PROJECT OVERVIEW
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   Target       : Neural Processing Unit (NPU)
   Architecture : Systolic Array Accelerator
   Tooling      : Make + GHDL + Cocotb + GTKWave + Vivado
 
 
 🧪 SIMULATION & VERIFICATION
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make cocotb TOP=<top> TEST=<test>        Rodar simulação Cocotb
   make view TEST=<test>                    Abrir ondas no GTKWave
   make sim_mnist                           Atalho: Simulação do MNIST
   make sim_iris                            Atalho: Simulação do IRIS
 
 
 🛠️  FPGA WORKFLOW (Inteligente)
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make fpga                                Verificar bitstream, gerar se necessário e programar
   make fpga_bit                            Forçar geração do Bitstream (Vivado)
   make fpga_prog                           Apenas programar (sem check)
 
 
 🐍 HARDWARE-IN-THE-LOOP (HIL)
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make hil TEST=<script>                   Rodar script Python da pasta sw/
   make hil_mnist                           Atalho: Rodar HIL do MNIST
   make hil_iris                            Atalho: Rodar HIL do IRIS
 
 
 📦 HOUSEKEEPING
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make clean                               Limpar tudo
 
 
============================================================================================
```

### 1. Clean Project
Removes all generated files:
```bash
make clean
```

### 2. Run Automated Tests with COCOTB

Run automated tests using COCOTB (Python-based coroutine testbenches):

```bash
make cocotb TEST=<testbench_name> TOP=<top_level>
```

**Parameters:**
- `TEST`: Name of the Python testbench file (without `.py` extension) located in `sim/`
- `TOP`: Top-level VHDL entity to test 

### 3. Visualize Waveforms

Open the last simulation waveform in GTKWave:
```bash
make view TEST=<testbench_name>
```

This opens `build/<testbench_name>.vcd` in GTKWave for detailed signal inspection.

## 🛠️ FPGA Workflow

The project includes an automated Makefile flow for Xilinx Vivado to synthesize, implement, and program the bitstream.

**Target Device**: Xilinx Artix-7 (XC7A100T-CSG324-1) - e.g., Nexys 4

```bash
# Verify if bitstream exists; if not, synthesize it, then program the board.
make fpga

# Force bitstream generation (Synthesis + Implementation)
make fpga_bit

# Program the FPGA 
make fpga_prog
```

## 🐍 Hardware-in-the-Loop (HIL)

Once the FPGA is programmed, you can use the Python drivers to send data from your PC to the FPGA and receive the classification results in real-time.

```bash
# Run MNIST Inference on FPGA 
make hil_mnist

# Run Iris Inference on FPGA
make hil_iris
```

### How HIL Works
1. **Training**: The Python script trains a Neural Network on the CPU.
2. **Quantization**: Floating-point weights are converted to Int8.
3. **Stream**: Weights are packed and sent via UART to the NPU's internal buffers.
4. **Inference**: Input vectors are streamed to the NPU.
5. **Result**: The NPU computes the class scores and sends them back to the PC for validation.

## ⚙️ Memory Map & Control

The NPU uses a memory-mapped interface over UART:
| Address | Register / FIFO | Access | Description |
| :-: | :-: | :-: | :-: |
| `0x00` | `CSR_CTRL`     | W | Control Flags (Load Weights, Clear Acc, ReLU) |
| `0x04` | `CSR_QUANT`    | W | Quantization Shift Amount | 
| `0x08` | `CSR_MULT`     | W | PPU Multiplier Factor |
| `0x0C` | `CSR_STATUS`   | R |	Status Flags (Busy, Output Ready) |
| `0x10` | `FIFO_WEIGHTS` | W |	Write packed weights (Int8 x4) |
| `0x14` | `FIFO_ACT`     | W |	Write input activations |
| `0x18` | `FIFO_OUT`     | R |	Read result scores |
| `0x20` | `BIAS_BASE`    | W |	Bias Registers Base Address |