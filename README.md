# RV32I Pipelined CPU

A synthesis-tested 5-stage RISC-V core with caches, precise traps, and retirement-level verification.

[![RTL Tests](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/rtl-tests.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/rtl-tests.yml)
[![RISC-V Compliance Suite](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/compliance.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/compliance.yml)
[![Spike Lockstep](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/lockstep.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/lockstep.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repository implements `RV32I_Zicsr_Zifencei` in SystemVerilog with forwarding, branch prediction, M-mode traps and interrupts, and parameterized instruction/data caches. Verification combines directed tests, exhaustive decode and hazard units, pinned RISC-V architecture tests, and instruction-by-instruction Spike comparison. Results are generated from machine-readable records and bound to exact tool and source revisions.

<details>
<summary>Machine-checked repository facts</summary>

<!-- portfolio:facts:start -->
<!-- evidence-facts:begin -->
EVIDENCE_FACT ISA=RV32I_Zicsr_Zifencei
EVIDENCE_FACT DIRECTED_TESTS=25
EVIDENCE_FACT ASSERTIONS_TOTAL=27
EVIDENCE_FACT ASSERTIONS_CONCURRENT=25
EVIDENCE_FACT ASSERTIONS_IMMEDIATE=2
EVIDENCE_FACT SOURCE_COVER_POINTS=44
EVIDENCE_FACT TRACKED_COVERAGE_HIT=44
EVIDENCE_FACT TRACKED_COVERAGE_TOTAL=44
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=historical
EVIDENCE_FACT EVIDENCE_STATUS=historical
EVIDENCE_FACT CI_CONFIGS=6
EVIDENCE_FACT CI_MATRIX=baseline,slow-mem,icache-only,wt,wb,assoc
EVIDENCE_FACT ARCH_TEST_SHA=6f7f47bdc61c0c51c0cbf75789678a1235eeefc2
EVIDENCE_FACT ARCH_TEST_EXPECTED=38
EVIDENCE_FACT SPIKE_SHA=55b4658dbf574ba0b714083ec436ce2cb5be1998
EVIDENCE_FACT SPIKE_RANDOM_SEEDS=200
<!-- evidence-facts:end -->
<!-- portfolio:facts:end -->

</details>

<!-- portfolio:status:start -->
Historical measurements — validated for RTL e55cf402670481413c910c2f2a51617ed53342a5; current RTL changes are not yet remeasured.
<!-- portfolio:status:end -->

## Portfolio snapshot

<!-- portfolio:snapshot:start -->
> **Portfolio Snapshot** — 5-stage `RV32I_Zicsr_Zifencei` • 25 directed tests × 6 memory configurations • 3 predictor configurations • 38/38 architecture signatures • 38/38 Spike lockstep • 200/200 random Spike seeds • 27 assertions • 44/44 functional cover points • 70.6–76.3 MHz routed Artix-7 implementations
<!-- portfolio:snapshot:end -->

<!-- portfolio:verification:start -->
| Metric | Value | How measured |
|---|---:|---|
| Decoder unit vectors | 2,120/2,120 | `make unit` |
| Hazard unit vectors | 262,144/262,144 | `make unit` |
| Harness tests | 109/109 | `make harness-test` |
| Directed memory matrix | 150/150 | `make verify` |
| Predictor matrix | 75/75 | `make predictor-test` |
| Architecture signatures | 38/38 | `make compliance` |
| Architecture Spike lockstep | 38/38 | `make lockstep` |
| Python-model random | 2000/2000 | `make soak SEEDS=1000` |
| Random Spike lockstep | 200/200 | `make soak-lockstep SEEDS=200` |
| Functional cover points | 44/44 | `make coverage` |
<!-- portfolio:verification:end -->

![Five-stage datapath with forwarding, prediction, caches, and commit control](docs/images/datapath.svg)

The redirect priority is `freeze > trap > mispredict > load-use stall > predict > PC+4`. Pipeline validity is carried from fetch through commit so flushed instructions cannot update architectural state, counters, or traces.

## Core design

**Pipeline and control**

- 5-stage, single-issue, in-order pipeline: IF, ID, EX, MEM, WB.
- EX/MEM and MEM/WB forwarding with operand-aware load-use stalls.
- 64-entry BTB with 2-bit counters, optional gshare direction history, and an 8-entry return-address stack.
- Branches resolve in EX; traps and interrupts redirect at one precise commit point.

**ISA and privilege**

- RV32I integer instructions plus `Zicsr` and `Zifencei`.
- Machine CSRs, `ECALL`, `EBREAK`, `MRET`, `mcycle`, and `minstret`.
- Precise illegal-instruction and misaligned fetch/load/store exceptions with `mepc`, `mcause`, and `mtval`.
- Machine timer and software interrupts with the MIE/MPIE/MPP state stack.

**Memory hierarchy**

- Parameterized I-cache and D-cache capacity, block size, and associativity.
- Write-through/no-allocate and write-back/write-allocate D-cache policies.
- Configurable backing-memory latency and Block-RAM-oriented cache arrays.
- `FENCE.I` invalidates the I-cache and restarts fetch; `FENCE` is a no-op for this single-hart, in-order design.

## Quick start

Docker is the only host requirement for the pinned open-source verification path.

```bash
git clone https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath.git
cd 5-stage-pipeline-rv32i-datapath
make verify
make portfolio-check
```

`make verify` runs the complete open-source profile in the pinned container. For iteration inside the devcontainer or a matching native environment, use `make check` for units, harness negatives, lint, and evidence consistency.

## Repository map

```text
rtl/core/          pipeline, control, prediction, CSRs, and counters
rtl/memory/        backing memories, timing model, LSU, I-cache, D-cache
sim/               Verilator harness and focused SystemVerilog units
tests/             directed assembly programs and strict references
compliance/        RISC-V architecture-test target and linker support
bench/             host-checked C workloads and benchmark runner
verification/      deterministic functional-coverage programs
synthesis/         Vivado wrapper, constraints, fixtures, and summaries
tools/             assemblers, models, lockstep, evidence, and environment tools
docs/              architecture, verification, evidence, diagrams, and media
results/           compact validated benchmark, synthesis, and tool records
```

## Verification strategy

The simulator accepts only explicit completion modes and rejects malformed references, unsuccessful `tohost` values, timeouts, incomplete traces, and stale outputs. Spike lockstep compares complete retirement streams through the terminal self-loop, while architecture signatures provide an independent externally generated test source. See [verification.md](docs/verification.md) for coverage boundaries and failure semantics.

The animated artifact below is a terminal demonstration of the verification and evidence workflow; it is not FPGA board footage.

![Portfolio verification demo](docs/media/portfolio-demo.gif)

## Measured performance and implementation

The tables below are generated from committed records. Benchmark entries are `cycles / CPI`; each workload also runs against a native host oracle. Synthesis used Vivado 2025.2, `xc7a35ticsg324-1L`, 512-word backing memories, and a deliberately aggressive 2 ns constraint. Negative WNS means the designs do not close at 500 MHz; the reported fmax is calculated from the routed critical path.

<details>
<summary>Benchmark matrix</summary>

<!-- portfolio:benchmarks:start -->
| Kernel | 10-cycle uncached | +1KB 4-way I$ | +4KB 4-way WB D$ | 1-cycle uncached |
|---|---:|---:|---:|---:|
| crc32 | 758,160 / 10.28041 | 170,189 / 2.30771 | 152,285 / 2.06494 | 75,816 / 1.02804 |
| matmul | 3,504,148 / 11.37629 | 790,915 / 2.56772 | 712,507 / 2.31317 | 361,402 / 1.17330 |
| sort | 2,521,060 / 12.48334 | 1,038,506 / 5.14229 | 504,874 / 2.49995 | 252,106 / 1.24833 |
| llist | 932,270 / 10.00236 | 465,099 / 4.99006 | 188,643 / 2.02396 | 93,227 / 1.00024 |
| interp | 14,652,250 / 11.69906 | 4,443,716 / 3.54808 | 2,933,372 / 2.34214 | 1,467,250 / 1.17152 |
<!-- portfolio:benchmarks:end -->

</details>

<details>
<summary>Routed Artix-7 matrix</summary>

<!-- portfolio:synthesis:start -->
| Configuration | LUT | FF | BRAM tiles | WNS (ns) | Critical path (ns) | fmax (MHz) |
|---|---:|---:|---:|---:|---:|---:|
| Core | 4,031 | 5,220 | 0.5 | -11.111 | 13.111 | 76.272 |
| +1KB 4-way I$ | 5,011 | 6,970 | 2.0 | -11.563 | 13.563 | 73.730 |
| +4KB 4-way WT D$ | 8,800 | 13,527 | 4.0 | -12.172 | 14.172 | 70.562 |
| +4KB 4-way WB D$ | 9,218 | 13,517 | 4.0 | -11.920 | 13.920 | 71.839 |
<!-- portfolio:synthesis:end -->

</details>

Exact commands, tool versions, source identities, and synthesis report hashes are in the [evidence ledger](docs/evidence.md).

## Design notes and next steps

- The pipeline freezes globally on a memory stall; a decoupled front end is the clearest architectural performance experiment.
- Instruction and data backing stores are separate simulation-scale arrays. A unified memory or standard bus interface is required for meaningful self-modifying code and SoC integration.
- External interrupts, M/A/C extensions, and S/U privilege modes are intentionally outside the implemented scope.
- Random lockstep covers control flow but not randomized traps or CSR state transitions; those remain directed-test territory.

The deeper rationale—including cache inference experiments, exception ordering, and measured trade-offs—is in [architecture.md](docs/architecture.md).

<details>
<summary>Measurement provenance</summary>

<!-- portfolio:provenance:start -->
- Measurement timestamp: `2026-08-29T05:56:10Z`
- Tooling commit: `b8217e0294c26f14abd1cdb3f4e7b6d9fee3d359`
- Frozen RTL commit: `e55cf402670481413c910c2f2a51617ed53342a5`
- Canonical container: `ghcr.io/huyhuy-bit/rv32i-verify:1`
- Open tools: Ubuntu 24.04; Verilator 5.048; RISC-V GCC 13.2.0-2024.04.12; RISC-V assembler 2.42; Python 3.12
- Vivado: 2025.2 build 6299465; `xc7a35ticsg324-1L`; measured 2026-08-29
- Reproduce verification: `make verify`
- Reproduce benchmarks: `make bench` with the recorded headline configuration
- Reproduce implementation: `make synth-matrix && make synth-summary`
<!-- portfolio:provenance:end -->

</details>

## References

- [Architecture and implementation notes](docs/architecture.md)
- [Verification plan](docs/verification.md)
- [Evidence ledger](docs/evidence.md)
- [Result file format](results/FORMAT.md)
- [RISC-V unprivileged ISA specification](https://docs.riscv.org/reference/isa/unpriv/rv32.html)
- [RISC-V machine-level ISA specification](https://docs.riscv.org/reference/isa/priv/machine.html)

Licensed under the [MIT License](LICENSE).
