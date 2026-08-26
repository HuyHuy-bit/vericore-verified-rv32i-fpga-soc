# RV32I Pipelined CPU

A 5-stage pipelined `RV32I_Zicsr_Zifencei` core in SystemVerilog — forwarding, branch prediction, precise exceptions, and a parameterised I/D cache hierarchy. Its directed, architecture-signature, and retirement-lockstep flows are independently gated, with current measurement provenance tracked in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

[![RTL Tests](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/rtl-tests.yml/badge.svg)](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/rtl-tests.yml)
[![RISC-V Compliance Suite](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/compliance.yml/badge.svg)](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/compliance.yml)
[![Spike Lockstep](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/lockstep.yml/badge.svg)](https://github.com/HuyHuy-bit/rv32i-pipeline/actions/workflows/lockstep.yml)

<details>
<summary>Machine-checked repository facts</summary>

<!-- evidence-facts:begin -->
EVIDENCE_FACT ISA=RV32I_Zicsr_Zifencei
EVIDENCE_FACT DIRECTED_TESTS=25
EVIDENCE_FACT ASSERTIONS_TOTAL=27
EVIDENCE_FACT ASSERTIONS_CONCURRENT=25
EVIDENCE_FACT ASSERTIONS_IMMEDIATE=2
EVIDENCE_FACT SOURCE_COVER_POINTS=44
EVIDENCE_FACT TRACKED_COVERAGE_HIT=34
EVIDENCE_FACT TRACKED_COVERAGE_TOTAL=38
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=historical
EVIDENCE_FACT CI_CONFIGS=6
EVIDENCE_FACT CI_MATRIX=baseline,slow-mem,icache-only,wt,wb,assoc
EVIDENCE_FACT ARCH_TEST_SHA=6f7f47bdc61c0c51c0cbf75789678a1235eeefc2
EVIDENCE_FACT ARCH_TEST_EXPECTED=38
EVIDENCE_FACT SPIKE_SHA=55b4658dbf574ba0b714083ec436ce2cb5be1998
EVIDENCE_FACT SPIKE_RANDOM_SEEDS=200
<!-- evidence-facts:end -->

</details>

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

The table below is a historical Vivado 2025.2 route snapshot for `xc7a35ticsg324-1L` with 512-word backing memories and a 2 ns constraint. It is retained as design history, not current headline evidence; the reproducible four-route rerun is tracked in [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

| Config | fmax | LUT | FF | BRAM |
|---|---|---|---|---|
| core only | 75.3 MHz | 3,990 (19%) | 4,966 (12%) | 0 |
| + 1KB I$ (4-way) | 76.1 MHz | 5,029 (24%) | 6,942 (17%) | 4 × RAMB18 |
| + 4KB D$ write-through | 71.6 MHz | 8,306 (40%) | 13,461 (32%) | 8 × RAMB18 |
| + 4KB D$ write-back | 73.5 MHz | 9,256 (45%) | 13,491 (32%) | 8 × RAMB18 |

Within that historical snapshot, the rows compare the cache configurations under one routing setup. They show the full hierarchy fitting in **45% of the device instead of 71%**, because the Block RAM rework applies to both caches, and a **+950 LUT** write-back cost over write-through for dirty-bit and writeback-FSM logic.

The fmax figures are *lower* than earlier revisions of this table reported (the D-cache rows previously read ~76 MHz). That is not a regression from the Block RAM work — that change measurably *improved* fmax by 9.8%, see below. It is the accumulated cost of everything added since those numbers were taken: interrupts, the return-address stack, and the gshare predictor. The core-only row shows the same effect in isolation, 79.2 → 75.3 MHz.

Getting the D-cache to fit took four RTL revisions, and the intermediate results were the lesson: a registered read alone changed nothing (316% → 315% LUT); splitting the `[WAYS][SETS][BLOCK_WORDS]` array into per-way flat arrays did the real work (→ 82%); and `ram_style="block"` was *refused* until the two write addresses in one `always_ff` were muxed into one — a BRAM port has a single address input. Full progression in [`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md#synthesis).

**Getting the I-cache into Block RAM was worth more than the timing work.** In that historical study, the D-cache's per-way-flat-array pattern was measured against an otherwise-identical control with only the I-cache array structure reverted:

| 1KB 4-way I$ | LUT | FF | BRAM | fmax |
|---|---|---|---|---|
| `[WAYS][SETS][BLOCK_WORDS]` array | 10,760 (52%) | 15,183 (37%) | 0 | 69.3 MHz |
| per-way flat + `ram_style="block"` | **5,029 (24%)** | **6,942 (17%)** | **4 × RAMB18** | **76.1 MHz** |

53% fewer LUTs, 54% fewer flip-flops, and **+9.8% fmax** — about twenty times the frequency gain the deliberate timing optimization below produced. That ordering is the actual lesson: the earlier timing pass concluded this build was congestion-bound rather than logic-depth-bound, and this confirms it directly, because moving 8,241 flip-flops out of the fabric relieved exactly the congestion that a shorter logic path couldn't.

The core-only row dropped from an earlier 79.2 MHz once interrupt support added a 64-bit `mtime`/`mtimecmp` comparator, which `report_timing` showed dominating the worst path (a 6-`CARRY4` ripple chain feeding straight through `irq_pending` into the PC redirect mux). Registering that comparison — one cycle of interrupt latency, which RISC-V doesn't bound — cut the chain to 3 `CARRY4` and recovered +0.34 MHz; the net gain was small because a second, route-dominated path immediately became the new worst case, meaning this build is congestion-bound rather than logic-depth-bound at this size. Detail and the real before/after `report_timing` data in [`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md#one-measured-timing-optimization).

## Performance

This historical benchmark snapshot covers five C kernels, each also compiled for the host so a wrong CPU result fails instead of quietly skewing CPI. The current four-configuration rerun is pending in the evidence ledger.

| kernel | no caches | +1KB I$ | +4KB write-back D$ | ideal 1-cycle memory |
|---|---|---|---|---|
| crc32  | 11.36 | 2.60 | **2.31** | 1.17 |
| matmul | 11.39 | 2.58 | **2.32** | 1.18 |
| sort   | 12.48 | 5.14 | **2.50** | 1.25 |
| llist  | 10.00 | 4.99 | **2.02** | 1.00 |
| interp | 11.88 | 3.63 | **2.38** | 1.19 |

`crc32` is a tight bitwise loop, `matmul` a 16×16 integer multiply, `sort` a data-dependent bubble sort, `llist` a deliberately cache-hostile pointer chase, `interp` a stack-machine interpreter with a real instruction footprint.

The hierarchy recovers most of a 10-cycle memory penalty — roughly 5× on the worst kernel — but lands about 2× off the ideal-memory column, not near it. That gap is the registered cache read the FPGA requires: one extra cycle on every hit, the direct cost of the array living in Block RAM rather than flip-flops. It's the clearest example in the project of a design decision that looks free in simulation and isn't.

Three findings from the geometry sweeps (measured pre-BRAM-rework; the qualitative results hold, the exact figures predate the extra hit cycle):

- **Bigger blocks are not better blocks.** On `interp`/512B I$, 8-word blocks gave the *best* hit rate (96.8%) and the *worst* CPI (3.48); 1-word blocks the worst hit rate (93.3%) and best CPI (3.02). Tuning on hit rate alone picks the slowest config on the board.
- **Write-back is not a free upgrade.** It wins big where stores dominate (`sort`: 2.25 → 1.25 CPI at 1KB) but *loses* to write-through on `matmul` at 256B and 1KB — write-allocate fetches a block before overwriting it. They cross over at 4KB.
- **Non-monotonic in block size.** `llist` hits 74% with 4-word blocks but only 62.8% with 8-word: fixed capacity split into fewer, larger blocks thrashes harder on scattered access.

## Verification

| Mechanism | Coverage |
|---|---|
| Directed tests | 25, one per hazard/instruction-class/trap/predictor scenario; `tohost` end-of-test |
| Compliance | `riscv-arch-test` `rv32i_m/I` — **38/38** |
| Spike lockstep | Same 38, compared instruction-by-instruction — **38/38** |
| CI matrix | Directed suite × 6 cache/latency configs per push; result must be invariant to cache config |
| Assertions | 27 total: 25 concurrent SVA properties and 2 immediate hazard assertions |
| Functional coverage | 44 source points; tracked historical report is 34/38 (89.5%) pending the current rerun — [`docs/coverage.md`](docs/coverage.md) |
| Constrained-random | 1000 seeds vs. a Python model (ALU/load-store); **200 seeds vs. Spike** with branches/jumps, per-retirement, in CI |
| Lint | `verilator -Wall` clean, waivers justified in [`rtl/verilator.vlt`](rtl/verilator.vlt) |

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
```

Cache geometry is a set of RTL parameters, so each configuration is its own build:

```bash
make all IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10
```

Synthesis scripts are in [`syn/`](syn/); see [`syn/build.tcl`](syn/build.tcl) for the per-config invocation.

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

- **fmax is a working number, not a good one.** ~75–77 MHz with one small timing optimization attempted (registering the interrupt timer comparator, +0.45%): no retiming of the tag-compare/way-select path, no shortening of the redirect priority chain, and this build appears congestion-bound rather than logic-depth-bound, so the next win likely isn't another single-chain fix.
- **The pipeline freezes globally on a memory stall** rather than letting the back end drain through a fetch miss. It inflates cached and uncached numbers alike, so it doesn't manufacture a speedup — but a decoupled front end would make the I-cache look less essential than it does here.
- **The backing memories still don't use Block RAM.** The I-cache now does (see Synthesis); `instr_mem.sv`/`data_mem.sv` still read combinationally, which is what keeps them in flip-flops. Same fix applies, not done because they're a simulation-scale stand-in for real memory rather than part of the core.
- **`FENCE.I` works, but this core can't demonstrate what it's for.** It decodes, invalidates the I-cache, and refetches — measurably: an identical loop goes from 3 I-cache misses to 43 with a `fence.i` in the body. What it can't show is self-modifying code becoming visible, because `instr_mem.sv` and `data_mem.sv` are *separate arrays* (a Harvard split), so a store never reaches code space at all — with or without `FENCE.I`. Unifying them is the prerequisite, and it's a memory-system change, not an ISA one.
- **Random testing still excludes traps and CSRs.** `make soak-lockstep` now generates branches and jumps (13% of emitted instructions) and compares against Spike retirement-by-retirement, so control flow is no longer the blind spot it was — but trap-taking and CSR sequences are still directed-test-only, because generating them randomly needs the generator to model privilege state, not just instructions.

[`docs/MICROARCHITECTURE.md`](docs/MICROARCHITECTURE.md) has the full spec: every trade-off with its measured cost, the hazard/exception model, and the complete synthesis progression.
