# Microarchitecture specification

A 5-stage in-order `RV32I_Zicsr_Zifencei` pipeline built for **measurable trade-offs over raw performance**: every choice below has a faster alternative that was deliberately not taken, and the point is to state what it cost.

<details>
<summary>Machine-checked repository facts</summary>

<!-- portfolio:facts:start -->
<!-- evidence-facts:begin -->
EVIDENCE_FACT ISA=RV32I_Zicsr_Zifencei
EVIDENCE_FACT DIRECTED_TESTS=25
EVIDENCE_FACT ASSERTIONS_TOTAL=66
EVIDENCE_FACT ASSERTIONS_CONCURRENT=63
EVIDENCE_FACT ASSERTIONS_IMMEDIATE=3
EVIDENCE_FACT SOURCE_COVER_POINTS=44
EVIDENCE_FACT TRACKED_COVERAGE_HIT=44
EVIDENCE_FACT TRACKED_COVERAGE_TOTAL=44
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=current
EVIDENCE_FACT EVIDENCE_STATUS=current
EVIDENCE_FACT SYNTHESIS_STATUS=historical
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
Current measurements — validated for the checked-out RTL.
Historical synthesis — the implementation table was measured for RTL e55cf402670481413c910c2f2a51617ed53342a5; current RTL changes are not yet resynthesised.
<!-- portfolio:status:end -->

## Integration boundaries

`rv32i_core` is the memory-independent pipeline and caches. The legacy `cpu` top wraps it with `instr_mem`/`data_mem` for verification and out-of-context synthesis; `rv32i_soc` instantiates it behind Wishbone adapters, BRAMs, UART and GPIO; `arty_a7_35t_top` adds clock, reset and board wiring. See the [SoC guide](soc.md).

## Pipeline organization

IF → ID → EX → MEM → WB, one instruction wide, in order; datapath diagram in the [README](../README.md). IF looks up the BTB in parallel with fetch; ID decodes and reads registers with a same-cycle write bypass; EX resolves branches and drives the forwarding mux; MEM holds the D-cache and the single commit point for traps, `MRET` and CSR writes.

Every pipeline register carries a `valid` bit end to end, so a flushed bubble is distinguishable from a retired instruction at every stage — that is what makes the counters and precise exceptions exact rather than approximate.

## Trade-offs

**Branches resolve in EX, not ID.** ID-resolve would halve the 2-cycle penalty, at the price of an ID-stage comparator on a likely-critical path and a second forwarding network. No variant was built, so this is an argument, not a measurement.

**Global pipeline freeze, not a decoupled front end.** Any memory stall freezes PC, pipeline registers, predictor, CSRs and counters together — the single biggest structural limiter. It inflates cached and uncached CPI equally, so it does not fabricate a cache speedup, but a D-cache miss stalls fetch, which a real design avoids. A fetch buffer would touch the freeze/flush/redirect logic the precise-exception guarantees rest on.

**Both D-cache write policies** (`DCACHE_WRITE_BACK`, build-time). Write-back wins on `sort` but loses to write-through on `matmul` below 4 KB; write-through has no write buffer, so every store pays full backing-memory latency.

**Blocking caches** — one outstanding miss stalls everything behind it; an MSHR is downstream of the front-end work. **FIFO victim selection**, expected to be small at 1–4 ways, not measured. **Single MEM commit point** — precise exceptions without a reorder buffer. **BTB-gated prediction** — a branch is predicted taken only after the BTB records a taken outcome, so its first taken occurrence always mispredicts. **CSR write permission from address bits `[11:10]`**, the spec's own convention.

### Return-address stack (`RAS_DEPTH=8`)

A BTB indexes by PC, so a `ret` shared by several call sites caches only the most recent caller — every other mispredicts by construction. `ras.sv` is an 8-entry LIFO pushed with `pc+4` on a linking `JAL`/`JALR`. [`t20_ras_multi_caller.s`](../tests/t20_ras_multi_caller.s), one subroutine called from three sites, five times each (35 branches):

| | Mispredicts | Accuracy | Cycles | CPI |
|---|---|---|---|---|
| `RAS_DEPTH=0` (BTB only) | 20 | 42.9% | 117 | 1.60 |
| `RAS_DEPTH=8` | 7 | **80.0%** | 91 | **1.25** |

The 7 remaining are the RAS's own limitation: push/pop happen speculatively at fetch and a flush does not roll the stack back, so a wrong-path fetch can push a premature entry. The `bench/` kernels are loop-dominated, so this does not move the CPI table.

### Optional gshare (`GSHARE=1`)

Indexes the BHT by `PC XOR global_history` rather than PC alone, so one branch gets a different counter per recent outcome pattern; the BTB stays PC-indexed. The history used for a prediction travels with the instruction and is replayed at update, so a second in-flight branch cannot corrupt the entry. [`t21_gshare_correlated.s`](../tests/t21_gshare_correlated.s), where branch 2 is determined by branch 1 one iteration earlier (120 branches):

| | Mispredicts | Accuracy | Cycles | CPI |
|---|---|---|---|---|
| `GSHARE=0` (default) | 61 | 49.2% | 491 | 1.35 |
| `GSHARE=1` | 16 | **86.7%** | 401 | **1.10** |

Bimodal lands near chance because one counter per PC cannot distinguish the two contexts. Off by default: real code's correlation profile varies enough that it is not a strict win.

### FENCE.I

Handled at the same commit point as traps: pulse `icache_invalidate`, redirect to `pc+4`. The redirect is the load-bearing half — by the time the fence reaches MEM the instructions behind it are already fetched, possibly from the lines being invalidated, so dropping the cache without discarding them leaves exactly the stale instructions the fence was meant to remove. The invalidate cannot collide with a refill, since the commit point is gated on `!pipe_stall` and a refill holds `imem_ready` low. Identical loop, 20 iterations, 1 KB 4-way I-cache:

| | Accesses | Misses | Hit rate | CPI |
|---|---|---|---|---|
| without `fence.i` | 71 | 3 | 95.8% | 2.95 |
| with `fence.i` | 151 | 43 | 71.5% | 10.43 |

What this core **cannot** show is `FENCE.I` doing its self-modifying-code job: both integrations prevent stores to code space.

## Hazard and exception model

| Load-use stall | Mispredict recovery | Trap at MEM commit |
|---|---|---|
| ![Load-use stall](images/timing_load_use.svg) | ![Mispredict recovery](images/timing_mispredict.svg) | ![Trap commit](images/timing_trap.svg) |

Forwarding covers distance-1 and -2 pairs; load-use costs one stall (`hazard_detect.sv`). Control hazards are predicted in IF and resolved in EX, squashing IF/ID and ID/EX. Illegal instruction, misaligned load/store/target, `ECALL`/`EBREAK` and illegal CSR access are detected in EX and committed in MEM, recording `mepc`/`mcause`/`mtval` and stacking `MIE`→`MPIE`; `MRET` reverses it. Next-PC priority: freeze > trap/MRET > mispredict > load-use stall > predicted-taken redirect > sequential.

## Memory hierarchy

![Memory hierarchy](images/mem_hierarchy.svg)

`lsu.sv` handles subword load/store semantics; `dcache.sv`/`icache.sv` hold geometry and policy. `mem_timing.sv`'s burst-refill discount (full latency for the first word, 1 cycle per word after) makes the block-size sweep meaningful. The SoC treats each word as an independent Wishbone transfer, D-caches only `0x2000_0000–0x2000_7FFF`, and turns bus errors into sticky integration faults.

![D-cache FSM](images/cache_fsm.svg)

## Performance

<!-- portfolio:benchmarks:start -->
| Kernel | 10-cycle uncached | +1KB 4-way I$ | +4KB 4-way WB D$ | 1-cycle uncached |
|---|---:|---:|---:|---:|
| crc32 | 758,160 / 10.28041 | 151,765 / 2.05789 | 152,021 / 2.06136 | 75,816 / 1.02804 |
| matmul | 3,504,148 / 11.37629 | 710,907 / 2.30797 | 711,691 / 2.31052 | 361,402 / 1.17330 |
| sort | 2,227,300 / 11.02875 | 471,714 / 2.33575 | 504,610 / 2.49864 | 252,106 / 1.24833 |
| llist | 932,270 / 10.00236 | 186,587 / 2.00190 | 187,611 / 2.01289 | 93,227 / 1.00024 |
| interp | 14,652,250 / 11.69906 | 2,932,916 / 2.34178 | 2,933,124 / 2.34195 | 1,467,250 / 1.17152 |
<!-- portfolio:benchmarks:end -->

## Synthesis

Vivado 2025.2, `xc7a35ticsg324-1L`, 2 ns constraint, 512-word backing memories. Negative WNS is intentional — the constraint is deliberately aggressive, and `fmax` comes from each routed critical path rather than being presented as closure.

<!-- portfolio:synthesis:start -->
| Configuration | LUT | FF | BRAM tiles | WNS (ns) | Critical path (ns) | fmax (MHz) |
|---|---:|---:|---:|---:|---:|---:|
| Core | 4,031 | 5,220 | 0.5 | -11.111 | 13.111 | 76.272 |
| +1KB 4-way I$ | 5,011 | 6,970 | 2.0 | -11.563 | 13.563 | 73.730 |
| +4KB 4-way WT D$ | 8,800 | 13,527 | 4.0 | -12.172 | 14.172 | 70.562 |
| +4KB 4-way WB D$ | 9,218 | 13,517 | 4.0 | -11.920 | 13.920 | 71.839 |
<!-- portfolio:synthesis:end -->

The hierarchy fits below 45% LUT and 33% FF. Write-back costs 418 LUT over write-through for dirty-state control, at identical FF and BRAM use.

### Getting the caches into Block RAM

The intermediate measurements are more instructive than the final table. D-cache, in order:

| D-cache RTL structure | Result | LUT | BRAM |
|---|---|---|---|
| combinational read, `[WAYS][SETS][BLOCK_WORDS]` | **DRC fail** | 65,724 (316%) | 0 |
| registered read, same 3D array | DRC fail | 65,600 (315%) | 0 |
| registered read, per-way flat arrays | Routed | 17,106 (82%) | 0 |
| …plus a unified write port | Routed | 14,237 (68%) | **4 × RAMB18** |

A registered read is necessary but nowhere near sufficient — registering alone changed nothing. What removed the flip-flops was splitting the 3D array into per-way flat arrays read in parallel and muxed *after* the register: a 3.8× LUT reduction.

That still produced zero Block RAM, because each way wrote two addresses — a byte-enabled store and a refill word — and a BRAM write port has one address input. Muxing address, data and byte-enable ahead of the port finally inferred true-dual-port RAMB18s. **`ram_style="block"` is a request, not an instruction.**

The same restructuring on the read-only I-cache is simpler, since a refill is the only writer:

| 1 KB 4-way I-cache | LUT | FF | BRAM | fmax |
|---|---|---|---|---|
| `[WAYS][SETS][BLOCK_WORDS]` | 10,760 | 15,183 | 0 | 69.3 MHz |
| per-way flat + `ram_style="block"` | 5,029 | 6,942 | 4 × RAMB18 | 76.1 MHz |

**+9.8% fmax from a change made for area**, against +0.45% from the timing optimization below. Removing 8,241 flip-flops relieved routing pressure, which a shorter critical path cannot address: this build is congestion-bound, not logic-depth-bound.

### The timing optimization

The top 5 worst paths shared one source (`u_perf/cycle_count_reg`) routing through `mtime`/`mtimecmp` logic, 6 of 17 levels being `CARRY4` — a wide ripple-carry chain. That is `mip_mtip = (mtime >= mtimecmp)` in `csr.sv`, a 64-bit comparison recomputed every cycle. Registering it is architecturally free, since RISC-V does not bound interrupt response latency:

| | fmax | `CARRY4` | Logic delay |
|---|---|---|---|
| Before | 74.97 MHz | 6 | 3.729 ns |
| After | 75.31 MHz | 3 | 2.557 ns |

The mechanism shrank as predicted — logic delay down 31%, `CARRY4` halved — but net fmax moved **+0.45%**, because a route-dominated path took over. Fixing one chain surfaces the next-worst.

Caveat: reported critical paths show source/destination pairings that are not real architectural dependencies, likely an out-of-context artifact of `perf_*`/`dbg_*` outputs feeding nothing. The fmax numbers are what static timing analysis computed, but naming a bottleneck stage would overclaim.

## Known limitations

- **No decoupled front end, non-blocking caches, or store buffer** — each redesigns the logic the lockstep regression protects.
- **fmax is a working number** — 70.6–76.3 MHz against an aggressive 500 MHz target, no retiming attempted.
- **No external-memory controller**; the legacy wrapper uses simulation memories and the board adds Wishbone BRAM slaves.
- **Wishbone is internal** (no AXI/TileLink bridge), with one external interrupt source and no PLIC.
- **RV32 only.** `XLEN` elaborates at 64, but RV64 needs `LD`/`SD` and the `*W` forms.

Verification is covered in [`verification.md`](verification.md).
