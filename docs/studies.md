# Measured studies

Four experiments behind the design decisions in [`architecture.md`](architecture.md). Each is a built-twice comparison, not an estimate.

## Branch prediction

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

## Instruction fetch

### FENCE.I

Handled at the same commit point as traps: pulse `icache_invalidate`, redirect to `pc+4`. The redirect is the load-bearing half — by the time the fence reaches MEM the instructions behind it are already fetched, possibly from the lines being invalidated, so dropping the cache without discarding them leaves exactly the stale instructions the fence was meant to remove. The invalidate cannot collide with a refill, since the commit point is gated on `!pipe_stall` and a refill holds `imem_ready` low. Identical loop, 20 iterations, 1 KB 4-way I-cache:

| | Accesses | Misses | Hit rate | CPI |
|---|---|---|---|---|
| without `fence.i` | 71 | 3 | 95.8% | 2.95 |
| with `fence.i` | 151 | 43 | 71.5% | 10.43 |

What this core **cannot** show is `FENCE.I` doing its self-modifying-code job: both integrations prevent stores to code space.

## Synthesis

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
