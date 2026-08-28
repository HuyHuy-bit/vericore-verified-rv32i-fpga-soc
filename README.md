# RV32I Pipelined CPU

A 5-stage pipelined `RV32I_Zicsr_Zifencei` core in SystemVerilog — forwarding, branch prediction, precise exceptions, and a parameterised I/D cache hierarchy. Its directed, architecture-signature, and retirement-lockstep flows are independently gated, with current measurement provenance tracked in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

[![RTL Tests](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/rtl-tests.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/rtl-tests.yml)
[![RISC-V Compliance Suite](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/compliance.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/compliance.yml)
[![Spike Lockstep](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/lockstep.yml/badge.svg)](https://github.com/HuyHuy-bit/5-stage-pipeline-rv32i-datapath/actions/workflows/lockstep.yml)

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
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=current
EVIDENCE_FACT CI_CONFIGS=6
EVIDENCE_FACT CI_MATRIX=baseline,slow-mem,icache-only,wt,wb,assoc
EVIDENCE_FACT ARCH_TEST_SHA=6f7f47bdc61c0c51c0cbf75789678a1235eeefc2
EVIDENCE_FACT ARCH_TEST_EXPECTED=38
EVIDENCE_FACT SPIKE_SHA=55b4658dbf574ba0b714083ec436ce2cb5be1998
EVIDENCE_FACT SPIKE_RANDOM_SEEDS=200
<!-- evidence-facts:end -->
<!-- portfolio:facts:end -->

</details>

<!-- portfolio:snapshot:start -->
> **Portfolio Snapshot** — 5-stage `RV32I_Zicsr_Zifencei` • 25 directed tests × 6 memory configurations • 3 predictor configurations • 38/38 architecture signatures • 38/38 Spike lockstep • 200/200 random Spike seeds • 27 assertions • 44/44 functional cover points • 70.6–76.3 MHz routed Artix-7 implementations
<!-- portfolio:snapshot:end -->

<!-- portfolio:provenance:start -->
- Measurement timestamp: `2026-08-28T13:46:38Z`
- Tooling commit: `031fcd07c45b9fe59f6951fd0bafda275e6ce0d0`
- Frozen RTL commit: `3c7e84e392b345332d6acdd0ed899928dafb1058`
- Canonical container: `ghcr.io/huyhuy-bit/rv32i-verify:1`
- Open tools: Ubuntu 24.04; Verilator 5.048; RISC-V GCC 13.2.0-2024.04.12; RISC-V assembler 2.42; Python 3.12
- Vivado: 2025.2 build 6299465; `xc7a35ticsg324-1L`; measured 2026-08-28
- Reproduce verification: `make verify`
- Reproduce benchmarks: `make bench` with the recorded headline configuration
- Reproduce implementation: `make synth-matrix && make synth-summary`
<!-- portfolio:provenance:end -->

![Portfolio verification demo](docs/portfolio-demo.gif)

![Datapath block diagram](docs/datapath.svg)

Next-PC priority: `freeze > trap > mispredict > load-use stall > predict > +4`. Every pipeline register carries a `valid` bit end-to-end, so a flushed bubble is always distinguishable from a retired instruction — that's what makes the counters and precise exceptions exact rather than approximate.

## Specification

| | |
|---|---|
| **ISA** | `RV32I_Zicsr_Zifencei`, with documented M-mode trap, CSR, and interrupt facilities |
| **Pipeline** | 5-stage in-order (IF/ID/EX/MEM/WB), single issue |
| **Hazards** | EX/MEM + MEM/WB forwarding; 1-cycle stall on load-use |
| **Branch prediction** | 64-entry BTB + 2-bit saturating counters, resolved in EX (2-cycle penalty); optional gshare direction table (`GSHARE=1`); 8-entry return-address stack, on by default |
| **Exceptions** | Precise, single commit point in MEM. Illegal instruction, misaligned load/store/fetch, `ECALL`/`EBREAK`, `MRET`, illegal CSR access |
| **CSRs** | `mstatus` `mie` `mip` `mtvec` `mepc` `mcause` `mscratch` `mtval` `misa` `mvendorid` `marchid` `mimpid` `mhartid` `mcycle` `minstret` |
| **Caches** | Parameterised I$ and D$ — capacity, block size, associativity, write-through/no-allocate or write-back/write-allocate |
| **Interrupts** | `mstatus` MIE/MPIE/MPP stack, `mie`/`mip`, timer (`mtime`/`mtimecmp`) and software interrupts |
| **Memory ordering** | `FENCE` is a no-op (in-order, single hart); `FENCE.I` invalidates the I-cache and refetches |
| **Not implemented** | External interrupts, M/A/C extensions, S/U privilege modes |

## Synthesis

This current Vivado 2025.2 matrix uses `xc7a35ticsg324-1L`, 512-word backing memories, and a deliberately aggressive 2 ns constraint. `fmax` is calculated from the routed critical path; the negative WNS values make clear that none of these configurations closes at 500 MHz. Exact commits, commands, and report hashes are in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

<!-- portfolio:synthesis:start -->
| Configuration | LUT | FF | BRAM tiles | WNS (ns) | Critical path (ns) | fmax (MHz) |
|---|---:|---:|---:|---:|---:|---:|
| Core | 4,031 | 5,220 | 0.5 | -11.111 | 13.111 | 76.272 |
| +1KB 4-way I$ | 5,011 | 6,970 | 2.0 | -11.563 | 13.563 | 73.730 |
| +4KB 4-way WT D$ | 8,800 | 13,527 | 4.0 | -12.172 | 14.172 | 70.562 |
| +4KB 4-way WB D$ | 9,218 | 13,517 | 4.0 | -11.920 | 13.920 | 71.839 |
<!-- portfolio:synthesis:end -->

The current write-back policy costs 418 LUT over write-through while using the same four BRAM tiles. The full hierarchy still fits below 45% LUT and 33% flip-flop utilization. Historical inference experiments below explain how the cache arrays reached Block RAM; they are retained as design studies, not mixed into the current headline matrix.

Getting the D-cache to fit took four RTL revisions, and the intermediate results were the lesson: a registered read alone changed nothing (316% → 315% LUT); splitting the `[WAYS][SETS][BLOCK_WORDS]` array into per-way flat arrays did the real work (→ 82%); and `ram_style="block"` was *refused* until the two write addresses in one `always_ff` were muxed into one — a BRAM port has a single address input. Full progression in [`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md#synthesis).

**Getting the I-cache into Block RAM was worth more than the timing work.** In that historical study, the D-cache's per-way-flat-array pattern was measured against an otherwise-identical control with only the I-cache array structure reverted:

| 1KB 4-way I$ | LUT | FF | BRAM | fmax |
|---|---|---|---|---|
| `[WAYS][SETS][BLOCK_WORDS]` array | 10,760 (52%) | 15,183 (37%) | 0 | 69.3 MHz |
| per-way flat + `ram_style="block"` | **5,029 (24%)** | **6,942 (17%)** | **4 × RAMB18** | **76.1 MHz** |

53% fewer LUTs, 54% fewer flip-flops, and **+9.8% fmax** — about twenty times the frequency gain the deliberate timing optimization below produced. That ordering is the actual lesson: the earlier timing pass concluded this build was congestion-bound rather than logic-depth-bound, and this confirms it directly, because moving 8,241 flip-flops out of the fabric relieved exactly the congestion that a shorter logic path couldn't.

The core-only row dropped from an earlier 79.2 MHz once interrupt support added a 64-bit `mtime`/`mtimecmp` comparator, which `report_timing` showed dominating the worst path (a 6-`CARRY4` ripple chain feeding straight through `irq_pending` into the PC redirect mux). Registering that comparison — one cycle of interrupt latency, which RISC-V doesn't bound — cut the chain to 3 `CARRY4` and recovered +0.34 MHz; the net gain was small because a second, route-dominated path immediately became the new worst case, meaning this build is congestion-bound rather than logic-depth-bound at this size. Detail and the real before/after `report_timing` data in [`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md#one-measured-timing-optimization).

## Performance

This current benchmark matrix covers five C kernels, each also compiled for the host so a wrong CPU result fails instead of quietly skewing CPI. The first three columns use 10-cycle instruction/data memory; the final column uses ideal one-cycle memory. It was measured on the frozen RTL in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

<!-- portfolio:benchmarks:start -->
| Kernel | 10-cycle uncached | +1KB 4-way I$ | +4KB 4-way WB D$ | 1-cycle uncached |
|---|---:|---:|---:|---:|
| crc32 | 758,160 / 10.28041 | 170,189 / 2.30771 | 152,285 / 2.06494 | 75,816 / 1.02804 |
| matmul | 3,504,148 / 11.37629 | 790,915 / 2.56772 | 712,507 / 2.31317 | 361,402 / 1.17330 |
| sort | 2,521,060 / 12.48334 | 1,038,506 / 5.14229 | 504,874 / 2.49995 | 252,106 / 1.24833 |
| llist | 932,270 / 10.00236 | 465,099 / 4.99006 | 188,643 / 2.02396 | 93,227 / 1.00024 |
| interp | 14,652,250 / 11.69906 | 4,443,716 / 3.54808 | 2,933,372 / 2.34214 | 1,467,250 / 1.17152 |
<!-- portfolio:benchmarks:end -->

`crc32` is a tight bitwise loop, `matmul` a 16×16 integer multiply, `sort` a data-dependent bubble sort, `llist` a deliberately cache-hostile pointer chase, `interp` a stack-machine interpreter with a real instruction footprint.

The hierarchy recovers most of a 10-cycle memory penalty — roughly 5× on the worst kernel — but lands about 2× off the ideal-memory column, not near it. That gap is the registered cache read the FPGA requires: one extra cycle on every hit, the direct cost of the array living in Block RAM rather than flip-flops. It's the clearest example in the project of a design decision that looks free in simulation and isn't.

Three findings from the geometry sweeps (measured pre-BRAM-rework; the qualitative results hold, the exact figures predate the extra hit cycle):

- **Bigger blocks are not better blocks.** On `interp`/512B I$, 8-word blocks gave the *best* hit rate (96.8%) and the *worst* CPI (3.48); 1-word blocks the worst hit rate (93.3%) and best CPI (3.02). Tuning on hit rate alone picks the slowest config on the board.
- **Write-back is not a free upgrade.** It wins big where stores dominate (`sort`: 2.25 → 1.25 CPI at 1KB) but *loses* to write-through on `matmul` at 256B and 1KB — write-allocate fetches a block before overwriting it. They cross over at 4KB.
- **Non-monotonic in block size.** `llist` hits 74% with 4-word blocks but only 62.8% with 8-word: fixed capacity split into fewer, larger blocks thrashes harder on scattered access.

## Verification

<!-- portfolio:verification:start -->
| Gate | Result |
|---|---:|
| Decoder unit vectors | 2,120/2,120 |
| Hazard unit vectors | 262,144/262,144 |
| Harness tests | 109/109 |
| Directed memory matrix | 150/150 |
| Predictor matrix | 75/75 |
| Architecture signatures | 38/38 |
| Architecture Spike lockstep | 38/38 |
| Python-model random | 2000/2000 |
| Random Spike lockstep | 200/200 |
| Functional cover points | 44/44 |
<!-- portfolio:verification:end -->

See [`docs/VERIFICATION_PLAN.md`](docs/VERIFICATION_PLAN.md) for what each mechanism catches and what it explicitly doesn't.

## Build

Requires **Verilator**; the compliance suite also needs the **RISC-V GNU toolchain**.

```bash
make all        # build + run directed tests (assertions live)
make check      # units + harness negatives + lint + evidence consistency
make evidence-check             # source/document consistency only
make bench      # C kernels, CPI table
make coverage   # functional coverage report
make soak SEEDS=1000            # random programs vs. the Python model
make lockstep                  # compliance suite vs. Spike, per retirement
make soak-lockstep SEEDS=200   # random programs vs. Spike, with control flow
make synth-matrix              # four private Vivado 2025.2 routes
make synth-summary             # validate reports and calculate fmax
```

Cache geometry is a set of RTL parameters, so each configuration is its own build:

```bash
make all IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10
```

The synthesis wrapper honors `VIVADO=/path/to/vivado`, then native Vivado, then Windows Vivado 2025.2 under WSL. It stages private projects outside the checkout and retains only ignored reports plus hashed manifests.

## What I learned

- **A clean single-cycle design pays for itself later.** Pipelining, forwarding, prediction, and exceptions were all added *around* the original ALU/control/decode logic without rewriting it — good early modularity compounds.
- **Forwarding and stalling solve different problems.** It's tempting to think of them as one "hazard handling" feature; they're not interchangeable, and conflating them is an easy way to miss the load-use case specifically.
- **The narrowest bugs are the easiest to miss and the most worth finding.** A same-cycle register-file write/read race, a CSR value that wasn't threaded through forwarding correctly, `FENCE` silently trapping as illegal — none of these fit the "adjacent instruction" mental model that motivates most hazard logic, and none of my own directed tests caught them until I specifically went looking.
- **Precise exceptions are a control-flow discipline, not a checklist.** Getting `mepc`/`mcause` right is easy; making sure a trap can't corrupt or duplicate architectural state under speculation (a mispredicted branch, an in-flight load) is the actual work.
- **Passing your own tests and being *correct* are different claims.** The compliance suite exists because directed tests, however careful, reflect the blind spots of whoever wrote them. Running against an external, independently-generated reference is what turns "I believe this works" into "this is verified."
- **A test that ends by guessing isn't a test.** Runs used to stop when the PC stopped moving, which cannot tell "finished" from "spinning" or "stalled". Switching to a `tohost` store made termination deterministic — and immediately broke eight tests, because inserting those instructions shifted every trap handler they located by a hardcoded byte offset. The heuristic had been hiding how fragile the tests were.
- **Simulation hides the cost of memory.** A combinational array read is free in Verilator and impossible in a Block RAM. Synthesis turned a "1.18 CPI" cache into a 2.3 CPI cache and a silent 3.2×-over-budget design into one that fits — neither fact was visible from any amount of simulation.
- **A reference model has to be pinned, or a future divergence is unreadable.** CI builds Spike from a fixed commit, not `master`. Otherwise the next time lockstep fails you can't tell whether the RTL regressed or the reference moved — and that ambiguity destroys the exact property the comparison was built to provide.
- **When a design is congestion-bound, the area fix *is* the timing fix.** Registering a 64-bit comparator on the reported critical path bought +0.45% fmax. Moving the I-cache array into Block RAM — done for area, not timing — bought +9.8%, because freeing 8,241 flip-flops relieved the routing pressure that was the real limit. Reading the constraint correctly mattered more than optimizing the thing the timing report named.
- **An interrupt and a trap resume at different addresses, and that's easy to get backwards.** A trap re-runs the faulting instruction (`mepc = pc`); an interrupt lets the instruction in flight complete and resumes after it (`mepc = pc+4`). Swap them and every interrupt either duplicates or silently drops one instruction — invisible in any test that doesn't specifically check `mepc` against the *right* one of those two.
- **A "critical path" name in a synthesis report isn't automatically the real one.** The first re-synthesis after adding interrupts pointed at a plausible-looking chain (a 64-bit timer comparator feeding the PC redirect mux); fixing it *did* measurably shrink that exact chain (logic delay ↓31%, carry-chain length halved) but moved fmax by only +0.45%, because a second, route-dominated path was waiting to take over. The fix was real and worth keeping; the lesson is that "the" bottleneck in a small, congested build is often several similarly-bad paths, not one.

## Limitations

- **fmax is a working number, not a good one.** The current matrix spans 70.6–76.3 MHz and misses the 500 MHz constraint in every configuration. No retiming of the tag-compare/way-select path or shortening of the redirect priority chain has been attempted; the build appears congestion-bound rather than logic-depth-bound.
- **The pipeline freezes globally on a memory stall** rather than letting the back end drain through a fetch miss. It inflates cached and uncached numbers alike, so it doesn't manufacture a speedup — but a decoupled front end would make the I-cache look less essential than it does here.
- **The backing memories are simulation-scale arrays, not an SoC memory subsystem.** `instr_mem.sv`/`data_mem.sv` retain combinational interfaces while the caches use synchronous Block-RAM-friendly arrays. Replacing the backing stores with a real BRAM or bus interface remains integration work.
- **`FENCE.I` works, but this core can't demonstrate what it's for.** It decodes, invalidates the I-cache, and refetches — measurably: an identical loop goes from 3 I-cache misses to 43 with a `fence.i` in the body. What it can't show is self-modifying code becoming visible, because `instr_mem.sv` and `data_mem.sv` are *separate arrays* (a Harvard split), so a store never reaches code space at all — with or without `FENCE.I`. Unifying them is the prerequisite, and it's a memory-system change, not an ISA one.
- **Random testing still excludes traps and CSRs.** `make soak-lockstep` now generates branches and jumps (13% of emitted instructions) and compares against Spike retirement-by-retirement, so control flow is no longer the blind spot it was — but trap-taking and CSR sequences are still directed-test-only, because generating them randomly needs the generator to model privilege state, not just instructions.

[`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md) has the full spec: every trade-off with its measured cost, the hazard/exception model, and the complete synthesis progression.
