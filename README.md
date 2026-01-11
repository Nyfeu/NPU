# RISC-V (RV32I) Processor in VHDL

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

## 🎯 Goals and Features

* **Architecture**: Systloci Array (Weight Stationary)
* **Precision**: INT8 for Input/Weights, INT32 for Accumulators
* **Language**: VHDL-2008
* **Automation**: fully automated build system via `makefile` for simulation and waveform generation

## 📂 Project Structure

The repository is organized to separate hardware design (RTL), verification testbenches, and build artifacts.

```
npu-accelerator/
|
├── rtl/                          # Synthesizable VHDL code (Hardware)
│   ├── npu_pkg.vhd               # Global constants and type definitions (INT8/INT32)
│   ├── mac_pe.vhd                # Multiply-Accumulate Processing Element (The "Brick")
│   └── systolic_array.vhd        # The Matrix interconnecting PEs
│
├── tb/                           # Verification Environment (Cocotb/Python)
│   ├── test_mac_pe.py            # Unit Test: PE Reset, Loading, and Math verification
│   ├── test_array.py             # Integration Test: Matrix Multiplication & Dataflow
│   └── test_utils.py             # Shared logging and utility functions
│
├── sim_build/                    # Build Artifacts (Generated Automatically)
│   ├── results.xml               # JUnit-style test reports
│   └── *.vcd                     # Waveform files for debugging
│
├── mk/                           # Makefile modules (Future expansion)
└── Makefile                      # Main Automation Script (Entry Point)
```

## 🛠️ Prerequisites

To compile and simulate this project, ensure the following tools are in your PATH:

## 🛠️ Prerequisites
To compile and simulate this project, install the following tools and ensure they are in your PATH:

1. **GHDL**: Open-source VHDL simulator.
2. **GTKWave**: Waveform viewer.
3. **COCOTB**: Python-based coroutine testbench framework for hardware simulation.
4. **Python 3**: Required for running cocotb testbenches.

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
   Tooling      : Make + GHDL + Cocotb + GTKWave
 
 
 🧪 SIMULATION & VERIFICATION
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make cocotb TOP=<top> TEST=<test>        Rodar simulação Cocotb do módulo especificado
   make view TEST=<test>                    Abrir formas de onda (VCD) no GTKWave
 
 
 📦 BUILD & HOUSEKEEPING
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make                                     Mostrar este menu de ajuda
   make clean                               Remover artefatos de build e simulação
 
 
 📌 EXAMPLES
 ──────────────────────────────────────────────────────────────────────────────────────────
 
   make cocotb TOP=systolic_array TEST=test_array
   make view TEST=test_array
 
 
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

