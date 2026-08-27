# Microarchitecture specification

## Overview and design goals

A 5-stage in-order `RV32I_Zicsr_Zifencei` pipeline optimized for **measurable trade-offs over raw performance**: every major design choice below has a cheaper or faster alternative that was deliberately not taken, and the point of the project is to state what it cost. Machine-mode traps, CSRs, timer/software interrupts, and `FENCE.I` are implemented; external interrupts and other ISA extensions are not.

<details>
<summary>Machine-checked repository facts</summary>

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

</details>

## Pipeline organization

IF → ID → EX → MEM → WB, one instruction wide, in order. See the datapath diagram at the top of the [README](../README.md) for the full block diagram, including both forwarding paths, the load-use stall path, and the next-PC priority mux.

- **IF**: PC → optional I-cache → `instr_mem`. Branch prediction (BTB + 2-bit counters) looks up in parallel with fetch and can redirect the *next* fetch speculatively.
- **ID**: decode (`control.sv`), register read (`reg_file.sv`, with a same-cycle write/read bypass), immediate generation.
- **EX**: ALU, branch/jump resolution, forwarding mux (EX/MEM and MEM/WB → EX).
- **MEM**: optional D-cache → `data_mem`; also the single commit point for traps, MRET, and CSR writes.
- **WB**: register file write-back.

Every pipeline register carries a `valid` bit end-to-end, so a flushed bubble is distinguishable from a genuinely-retired instruction at every stage — this is what makes the performance counters and precise exceptions exact rather than approximate.

## Major trade-offs, with their cost

Each entry: what was chosen, the alternative, what it costs, and the evidence.

### EX-resolve branches, not ID-resolve
**Chosen:** branches and jumps resolve in EX. **Alternative:** resolve in ID, which would cut the mispredict penalty from 2 cycles to 1. **Cost:** an ID-stage comparator on what's likely close to the critical path already, plus a second forwarding network feeding it (EX/MEM and MEM/WB values would need to reach ID, not just EX). **Evidence:** not isolated — fmax numbers now exist (see Synthesis), but only for the design as structured; no ID-resolve variant was built to compare against, so the specific claim "an ID comparator would cost X MHz" remains an argument, not a measurement. The 2-cycle penalty itself is directly measured: `bpred: mispredicts=N` in every test's perf counters, and the predictor's measured accuracy (80%+ on loop-heavy code, reported per-run by the perf counters) is the reason it doesn't dominate.

### Global pipeline freeze, not a decoupled front end
**Chosen:** any memory stall (`pipe_stall`) freezes the *entire* pipeline — PC, all four pipeline registers, the predictor, the CSR file, and the counters — for the cycle. **Alternative:** a fetch buffer between IF and ID would let the back end drain through an instruction-fetch miss instead of stalling on it. **Cost:** this is the single biggest structural limiter in the design (see `cpu.sv`'s `ponytail:` comment at the freeze mux). It inflates both the cached and uncached CPI numbers in the README's Performance section equally, so it doesn't fabricate a cache speedup, but it does mean the I-cache's measured benefit is somewhat inflated relative to what a decoupled front end would show — a D-cache miss currently stalls fetch too, which a real design would avoid. **Not implemented**: a correct fetch-buffer redesign touches the freeze/flush/redirect priority logic this whole codebase's precise-exception and forwarding guarantees are built on. The Spike lockstep regression (see Verification summary) now exists as the regression net that kind of change would need — it just hasn't been attempted yet.

### Blocking caches, not hit-under-miss
**Chosen:** both caches are blocking — one outstanding miss stalls everything behind it. **Alternative:** a single MSHR would let independent hits proceed under a miss. **Cost:** simplicity (`dcache.sv`'s FSM is 4 states) against throughput lost to serialization; not quantified here for the same reason as above — it's downstream of the decoupled-front-end work.

### Write-through vs. write-back, both implemented and measured
**Chosen:** the D-cache supports both as a build-time parameter (`DCACHE_WRITE_BACK`), rather than picking one. **Cost:** none architecturally — this is the one trade-off in this list that's fully measured rather than argued about. The README's Performance section has the actual numbers: write-back wins on `sort` (2.25 → 1.25 CPI at 1KB) but *loses* to write-through on `matmul` at 256B/1KB, crossing over at 4KB. The comparison is somewhat unfair to write-through as implemented (no write buffer — every store pays full backing-memory latency), which the improvement plan flags as a natural next measurement; not done this pass.

### FIFO victim selection, not LRU
**Chosen:** both caches use a simple round-robin/FIFO victim pointer per set (`ponytail:` comments in `icache.sv` and `dcache.sv`). **Alternative:** true LRU. **Cost:** for the associativities actually swept in this project (1-4 way), the plan predicts the difference is usually small for a 2-way cache — that's a real, cheap-to-run finding this pass didn't get to. Not measured here.

### Single MEM commit point for precise exceptions
**Chosen:** every control-flow-changing exceptional event (trap, MRET, CSR write) resolves at one point, in MEM, in program order. **Alternative:** none seriously — this is what makes the exception model precise "for free" (see `cpu.sv`'s commit-point comment) rather than needing a reorder buffer. **Cost:** none beyond what precise exceptions cost anywhere: the offending and every younger instruction must be flushable, which is why `valid` is threaded through every pipeline register. This is the foundation the 27 assertions and the directed exception tests check.

### BTB-gated prediction (never predicts taken until a first taken hit)
**Chosen:** a branch is only ever predicted taken after the BTB has already recorded a taken outcome for it — the first execution of any branch is always predicted not-taken. **Cost:** every branch pays a guaranteed misprediction on its first taken occurrence; measured indirectly in the `bpred: accuracy=` figures already reported per test/kernel.

### Return-address stack, speculative and unrepaired

**Chosen:** `ras.sv` — a small (default 8-entry) LIFO, pushed with `pc+4` on a call (`JAL`/`JALR` with a link `rd`, per the RISC-V hint convention) and popped to predict a matching `JALR` return (link `rs1`). It sits alongside the BTB in `frontend.sv` and wins whenever it has a valid answer; an empty stack falls back to the plain BTB prediction. The reason it exists at all: a BTB indexes purely by PC, so a `ret` shared by multiple call sites can only ever cache the *most recent* caller's address — every other caller's return mispredicts by construction, regardless of how well-trained the BTB otherwise is.

**Cost — measured, not assumed:** [`tests/t20_ras_multi_caller.s`](../tests/t20_ras_multi_caller.s) calls one subroutine from three call sites, five times each. Built twice, same program:

| | Branches | Mispredicts | Accuracy | Cycles | CPI |
|---|---|---|---|---|---|
| `RAS_DEPTH=0` (BTB only) | 35 | 20 | 42.9% | 117 | 1.60 |
| `RAS_DEPTH=8` (default) | 35 | 7 | **80.0%** | 91 | **1.25** |

The 7 remaining mispredicts with RAS enabled aren't noise — they're the RAS's own honest limitation surfacing. Push/pop happen speculatively at fetch time, before the pipeline knows whether the fetch is even on the correct path, and a misprediction flush does not roll the stack back. Concretely here: the *first* call to `sub` is a cold BTB miss (predicted not-taken, since nothing has trained that entry yet), so fetch continues down the wrong (fall-through) path for the 1-2 cycles before EX resolves and flushes it — and in a tight, unrolled call sequence like this test, that wrong-path fetch window can itself contain the *next* call site, pushing a premature entry onto the RAS before the real call gets there. This is the same category of accepted simplification as the BTB's own uncheckpointed state (see below) and the FIFO cache victim policy — a real, occasionally-corrupting cost, disclosed rather than hidden, and still a decisive net win over no RAS at all.

None of the five C benchmark kernels in `bench/` exercise multi-site calls meaningfully (they're loop-dominated, not call-heavy), so the CPI table in the README doesn't move much at RAS's default-on setting — the win here is real but specific to call/return-heavy code, which is exactly what the directed microbenchmark above was built to isolate.

### Optional gshare direction predictor (`GSHARE=1`)

**Chosen:** the BHT's 2-bit counters are normally indexed by PC alone (bimodal — one counter per branch, independent of any other branch's outcome). `GSHARE=1` indexes by `PC XOR global_history` instead, so the *same* branch gets a different counter per recent global outcome pattern. The BTB (tag/target) stays PC-indexed either way — a branch's target doesn't depend on history, only its direction does. The exact history value used for each prediction travels with that instruction through `if_id_t`/`id_ex_t` (`predict_ghistory`, `GHIST_BITS` wide) and is replayed at update time, so a second in-flight branch's history update can't corrupt the wrong table entry — the live `ghistory` register may already have shifted past what was used for an older in-flight prediction by the time it resolves.

**Cost — measured:** bimodal only helps when a branch is predictable *from its own past*. [`tests/t21_gshare_correlated.s`](../tests/t21_gshare_correlated.s) builds two branches where the second's direction is fully determined by the first's outcome one loop iteration earlier — in isolation (ignoring history), branch 2's own sequence is a plain period-4 pattern, exactly the kind of case where correlation across branches, not within one, matters:

| | Branches | Mispredicts | Accuracy | Cycles | CPI |
|---|---|---|---|---|---|
| `GSHARE=0` (bimodal, default) | 120 | 61 | 49.2% | 491 | 1.35 |
| `GSHARE=1` | 120 | 16 | **86.7%** | 401 | **1.10** |

Bimodal lands near chance (49.2%) because it genuinely cannot see the correlation — its one counter per PC has no way to distinguish "branch 1 was just taken" from "branch 1 was just not-taken" contexts for branch 2. Off by default because real code's branch-correlation profile varies enough that it isn't a strict win the way the RAS is — it's a real, measured option, not a default recommendation, which is exactly why the plan called for it to be selectable rather than always-on.

### FENCE.I as a commit-point redirect, not a pipeline-local flush

**Chosen:** `FENCE.I` is decoded in `control.sv`, carried to MEM like any other instruction, and handled at the *same single commit point* as traps, MRET and interrupts. Committing it does two things: pulse `icache_invalidate` (clearing every valid bit in `icache.sv`), and redirect the PC to `pc+4`.

**Why the redirect is the load-bearing half:** invalidating the cache alone would be wrong. By the time `FENCE.I` reaches MEM, the four instructions behind it have already been *fetched* — possibly from the very cache lines being invalidated. Dropping the cache without discarding those in-flight fetches leaves exactly the stale instructions the fence was executed to get rid of. Routing it through the existing commit-point redirect gets the flush for free and keeps every ordering guarantee the trap path already proves.

**Why the invalidate can't collide with a refill:** the commit point is gated on `!pipe_stall`, and an in-progress refill holds `imem_ready` low — which *is* `pipe_stall`. So `invalidate` is structurally unable to fire mid-refill, and `icache.sv` doesn't need abort logic for a case that can't occur. This is asserted indirectly by `a_commit_onehot`, which now includes `fencei_take`.

**Cost — and an honest limit.** Measured on an identical loop, 20 iterations, 1KB 4-way I-cache:

| | I-cache accesses | misses | hit rate | CPI |
|---|---|---|---|---|
| loop body without `fence.i` | 71 | 3 | 95.8% | 2.95 |
| loop body with `fence.i` | 151 | 43 | 71.5% | 10.43 |

That is the invalidation demonstrably working — roughly two extra misses per iteration, and a 3.5× CPI penalty for discarding the cache every time round.

What this core **cannot** demonstrate is `FENCE.I` doing its actual job. `instr_mem.sv` and `data_mem.sv` are separate arrays — a Harvard split, not merely split caches over unified memory — so a store can never reach code space at all, and self-modifying code isn't expressible here with or without the fence. The instruction is implemented because it's part of the ISA and its cache-invalidate semantics are real and testable; the coherence problem it exists to solve is gated behind a unified memory this design doesn't have. Worth stating plainly rather than letting "FENCE.I implemented" imply more than it delivers.

### A structural read-only-CSR convention, not a hand-maintained permission table
**Chosen:** CSR write permission is derived from address bits `[11:10] == 2'b11` (the standard RISC-V convention), rather than a per-CSR read/write flag. **Cost:** none found — this is a case where following the spec's own structural convention was strictly simpler than the alternative, not a trade-off with a real downside.

## Hazard and exception model

| Load-use stall | Mispredict recovery | Trap at MEM commit |
|---|---|---|
| ![Load-use stall](timing_load_use.svg) | ![Mispredict recovery](timing_mispredict.svg) | ![Trap commit](timing_trap.svg) |

(WaveDrom sources alongside each SVG in this directory.)

- **Data hazards**: EX/MEM and MEM/WB forwarding cover same-register producer/consumer pairs at distance 1 and 2; load-use (distance-1 dependency on a load, which forwarding can't fix because the value doesn't exist yet at EX) is caught by `hazard_detect.sv` and resolved with a one-cycle stall.
- **Control hazards**: predicted speculatively in IF; resolved in EX. A misprediction squashes IF/ID and ID/EX (the two younger in-flight instructions).
- **Exceptions and interrupts**: illegal instruction, misaligned load/store/control-flow target, `ECALL`/`EBREAK`, and illegal CSR access are detected in EX and committed precisely in MEM. Trap entry records `mepc`/`mcause`/`mtval`, moves `mstatus.MIE` to `MPIE`, clears `MIE`, and records M-mode in `MPP`; `MRET` restores `MIE` from `MPIE`, sets `MPIE`, clears `MPP`, and redirects to `mepc`.
- **Priority** (next-PC mux, highest to lowest): memory-stall freeze > trap/MRET commit > EX misprediction recovery > load-use stall > front-end predicted-taken redirect > sequential.

## Memory hierarchy

![Memory hierarchy](mem_hierarchy.svg)

`lsu.sv` handles RV32I subword load/store semantics (sign/zero extension, byte-enable generation); `dcache.sv`/`icache.sv` hold geometry and policy; `mem_timing.sv` is the backing-memory access-cost model everything above scales against. The burst-refill discount it models (full `LATENCY` for the first word of a block, 1 cycle per sequential word after) is what makes the block-size sweep in the README's Performance section mean anything — without it, every block size above one word would look strictly worse, which would be an artifact of the model, not a property of caches.

![D-cache FSM](cache_fsm.svg)

## Performance results

See the README's [Performance](../README.md#performance) section for the full CPI table and the three sweep findings (block-size/hit-rate inversion, write-back's non-uniform win, and `llist`'s non-monotonic block-size behavior).

## Synthesis

The current four-route matrix uses Vivado 2025.2, `xc7a35ticsg324-1L`, a 2 ns constraint, and 512-word backing memories. Exact source identity and report hashes are tracked in [`EVIDENCE.md`](EVIDENCE.md).

| Config | Result | fmax | WNS | LUT | FF | BRAM tiles |
|---|---|---:|---:|---:|---:|---:|
| core only (no caches) | Routed | 76.272 MHz | −11.111 ns | 4,031 / 20,800 (19.4%) | 5,220 / 41,600 (12.5%) | 0.5 / 50 |
| + 1KB I-cache (4-way) | Routed | 73.730 MHz | −11.563 ns | 5,011 / 20,800 (24.1%) | 6,970 / 41,600 (16.8%) | 2 / 50 |
| + 4KB D-cache, write-through | Routed | 70.562 MHz | −12.172 ns | 8,800 / 20,800 (42.3%) | 13,527 / 41,600 (32.5%) | 4 / 50 |
| + 4KB D-cache, write-back | Routed | 71.839 MHz | −11.920 ns | 9,218 / 20,800 (44.3%) | 13,517 / 41,600 (32.5%) | 4 / 50 |

The current comparison shows two direct costs:

- **The full hierarchy fits below 45% LUT and 33% flip-flop utilization**, with both cache configurations using four BRAM tiles in total.
- **Write-back costs 418 LUT over write-through** (9,218 vs 8,800) for dirty-state and writeback control, with essentially identical flip-flop and BRAM use.

All four rows were routed from the same frozen RTL and tooling commits. The negative WNS values are intentional evidence that the 2 ns target is not met; `fmax` is derived from each routed critical path rather than presented as timing closure.

Getting the D-cache rows to exist at all took two rounds of RTL work, and the intermediate measurements are more instructive than the final table:

| D-cache RTL structure | Result | LUT | FF | BRAM |
|---|---|---|---|---|
| combinational read, `[WAYS][SETS][BLOCK_WORDS]` array | **DRC fail, placer never ran** | 65,724 (316%) | 54,344 (131%) | 0 |
| registered read, same 3D array | DRC fail | 65,600 (315%) | 54,412 (131%) | 0 |
| registered read, per-way flat arrays + `ram_style="block"` | Routed | 17,106 (82%) | 21,705 (52%) | 0 |
| …plus a single unified write port | Routed | 14,237 (68%) | 21,545 (52%) | **4 × RAMB18** |

**A registered read is necessary but nowhere near sufficient.** Registering the read alone changed essentially nothing (315% vs 316% LUT) — the intuition that "async read is why it won't infer BRAM" is right about the mechanism and useless as a fix on its own.

**What actually got the array out of flip-flops** was splitting the single `[WAYS][SETS][BLOCK_WORDS]` array into `WAYS` separate flat per-way arrays, read in parallel and muxed *after* the register. That's a 3.8× LUT reduction (65,600 → 17,106) and is what made the design fit at all. It's also just how a real set-associative data array is built — the restructuring is the correct shape, not a synthesis workaround.

**But that still produced zero Block RAM** — Vivado silently used distributed RAM (2,368 LUTs of it) instead, and said so only in a warning worth reading carefully:

```
WARNING: [Synth 8-6849] Infeasible attribute ram_style = "block" set for RAM
"g_dcache.u_dcache/g_way[3].way_mem_reg", trying to implement using LUTRAM
```

The cause: each way's `always_ff` wrote *two different addresses* — `idx*BLOCK_WORDS + off` for a byte-enabled store, `idx*BLOCK_WORDS + fill_word` for a refill word. A BRAM write port physically has one address input, so no amount of `ram_style="block"` can force it. Muxing address/data/byte-enable ahead of the port (which is what the hardware does anyway) is what finally produced `256 x 32` true-dual-port RAMB18s — one per way, write on port A, read on port B — and bought a further 2,869 LUTs and ~4 MHz on top.

### The same pattern applied to the I-cache

`icache.sv` kept its original `[WAYS][SETS][BLOCK_WORDS]` array long after the D-cache was reworked, on the reasoning that it already fit the device. The historical restructuring study compared it against an otherwise-identical control with only the array shape reverted:

| 1KB 4-way I-cache | LUT | FF | BRAM | WNS | fmax |
|---|---|---|---|---|---|
| `[WAYS][SETS][BLOCK_WORDS]` | 10,760 (52%) | 15,183 (37%) | 0 | −12.424 ns | 69.3 MHz |
| per-way flat + `ram_style="block"` | 5,029 (24%) | 6,942 (17%) | 4 × RAMB18 | −11.142 ns | 76.1 MHz |

It is strictly simpler than the D-cache version, for a structural reason: this cache is read-only on the hit path, so a refill is the *only* writer. The "one physical write address per BRAM port" constraint that forced `dcache.sv` into a unified write mux is satisfied here by construction, and no mux is needed at all.

**The frequency result is the interesting one.** +9.8% fmax, against +0.45% from the deliberate, targeted timing optimization documented below. A change made for *area* delivered roughly twenty times the frequency improvement that the change made for *timing* did. That isn't a coincidence, and it isn't an argument against doing timing analysis — it's confirmation of what the timing analysis concluded: this build is congestion-bound, not logic-depth-bound. Removing 8,241 flip-flops from the fabric relieves routing pressure across the whole design, which is precisely the constraint a shorter critical path can't address. The right response to "congestion-bound" is to make the design smaller, not to keep shortening chains.

The general lesson, worth more than the numbers: **`ram_style="block"` is a request, not an instruction.** When synthesis declines it, it says so in a warning that's easy to miss in a 60,000-line log, and the reason is usually that the RTL is asking for something a BRAM port cannot physically do.

One honest caveat on the fmax figures: the reported critical paths (`report_timing`'s worst-path listings) show a source/destination pairing — e.g. a performance-counter register driving into the PC register — that isn't a real architectural dependency. This is very likely an artifact of out-of-context synthesis with a dozen `perf_*`/`dbg_*` outputs that don't feed anything beyond the module boundary, giving the optimizer freedom to share resources in ways that produce confusing endpoint names. The fmax *numbers* are real (they're what the implemented netlist's static timing analysis actually computed), but attributing the bottleneck to a specific named stage would be overclaiming past what this data supports. A synthesis run with the perf/debug ports genuinely connected to something (a real SoC integration, or at minimum a register slice deliberately intended to consume them) would give cleaner attribution.

### One measured timing optimization

The caveat above turned out to be only half the story. Re-synthesizing the core-only config after interrupt support landed, `report_timing`'s top 5 worst paths all shared one real, consistent source (`u_perf/cycle_count_reg`) and routed through `mtimecmp`/`mtime` comparison logic before reaching their (still confusingly-named) destinations — 6 of the path's 17 logic levels were `CARRY4` cells, the signature of a wide ripple-carry chain. That's `mip_mtip = (mtime >= mtimecmp)` in `csr.sv`: a 64-bit magnitude comparison, recomputed combinationally every cycle regardless of whether an interrupt is even enabled, feeding straight through `irq_pending` → `irq_take` into the next-PC redirect mux.

The fix is a one-line, well-precedented change: register the comparison instead of leaving it combinational (`rtl/csr.sv`). RISC-V doesn't bound interrupt response latency, so spending one cycle to let `mip.MTIP` settle is free architecturally — it's the same registered-timer-pending convention a real CLINT implementation uses. Measured, same core-only config, same seed:

| | WNS | fmax | Worst-path `CARRY4` | Worst-path logic delay |
|---|---|---|---|---|
| Before | −11.339 ns | 74.97 MHz | 6 | 3.729 ns |
| After | −11.279 ns | 75.31 MHz | 3 | 2.557 ns |

The targeted mechanism shrank exactly as predicted — logic delay on the worst path dropped 31%, `CARRY4` count halved — but the net fmax gain is only **+0.34 MHz (+0.45%)**, because a second, nearly-as-expensive path (route-delay-dominated: 79.75% route vs. 70.6% before) immediately took over as the new worst case. That's the honest result, not a disappointing one: this out-of-context build at this size is routing/congestion-bound, not logic-depth-bound, so fixing one specific chain reliably surfaces the next-worst one rather than moving fmax by the full amount the fixed chain's cost would suggest. A real win here would need either a less congested/larger device or a placement-aware pass, neither of which is "one optimization."

Revised reading of the CPI table in light of all this: the current configurations span 70.6–76.3 MHz, so frequency is similar enough that CPI remains a useful first-order throughput comparison, but caches are not frequency-free. Their registered reads also cost cycles: the current write-back benchmark lands around 2.0–2.5 CPI rather than the ideal-memory 1.0–1.25 CPI. The honest summary is that simulation and routing both expose costs that a hit-rate-only comparison hides.

## Verification summary

See [`docs/VERIFICATION_PLAN.md`](VERIFICATION_PLAN.md) for the full breakdown. In one line each:

- 25 directed tests run across the 6-configuration cache/latency CI matrix.
- 38/38 pinned architecture signatures and 38/38 complete Spike traces run in their own workflows, not across the directed matrix.
- 27 assertions: 25 concurrent SVA properties plus 2 immediate hazard checks.
- 44/44 source cover points hit (100%) in the current `make coverage` report.
- Constrained-random regression (`make soak`) against a small Python golden model, 1000/1000 seeds clean on both cacheless and cache-enabled builds — scoped to the ALU/load-store subset, since the model doesn't interpret control flow or CSRs (the directed suite, compliance suite, and lockstep cover those instead).

## Known limitations and future work

Kept in the same honest tone as the README's Notes section, because a list like this is worth more than it costs to write:

- **The backing memories are still simulation-scale arrays.** Both caches use the per-way flat-array structure needed for Block RAM inference, while `instr_mem.sv` and `data_mem.sv` retain combinational interfaces rather than a production BRAM or bus protocol.
- **fmax is still a working number, not a good one.** The current matrix spans 70.6–76.3 MHz and misses the aggressive 500 MHz target. No retiming of the tag-compare/way-select path or shortening of the redirect priority mux has been attempted.
- **No decoupled front end, no non-blocking caches, no store buffer.** Each is a significant redesign of the freeze/flush/redirect logic the Spike lockstep regression now protects; none has been attempted.
- **`FENCE.I` cannot demonstrate unified-memory coherence.** It commits, invalidates the I-cache, flushes younger fetches, and refetches from `pc+4`; the separate instruction/data backing arrays prevent stores to code space, so self-modifying-code visibility is outside this memory model.
- **No AXI wrapper.** The bespoke `req`/`burst`/`ready` memory-port protocol works but isn't the industry-standard interface an SoC integration would expect.
- **No external interrupt.** `mie`/`mip` only implement the software and timer bits; there's no `mip.MEIP` and nothing to drive it, since this core has no interrupt controller or SoC fabric to source an external interrupt from.
- **RAS is speculative and unrepaired.** Pushes/pops happen at fetch time, before the pipeline knows whether that fetch is even on the correct path, and a misprediction flush doesn't roll the stack back — see the Return-address stack section above for a measured example of this actually happening.
- **RV32 only.** `XLEN` is a package parameter and the datapath elaborates cleanly at `XLEN=64` (verified this pass), but RV64 additionally needs `LD`/`SD` and the `*W` instruction forms — decode work in `control.sv`/`lsu.sv` that hasn't been done.
