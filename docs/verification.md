# Verification plan

What's tested, by what mechanism, and what's explicitly not tested yet.

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

<!-- portfolio:summary:start -->
The release gate runs 25 programs across 6 memory configurations and 3 predictor configurations. Pinned architecture signatures and complete Spike traces both pass 38/38; random Spike lockstep passes 200/200; functional coverage is 44/44 (100.0%).
<!-- portfolio:summary:end -->

## Directed tests (`tests/`, run via `make all`)

25 hand-assembled programs cover instruction classes, true and false load-use dependencies, control flow, precise illegal/misaligned traps, CSR permissions, timer/software interrupt state, MRET, cache eviction, RAS/gshare behavior, and FENCE.I. Each checks final register state and optional stall counts against a `.ref` file across the 6-configuration directed matrix; cache configuration is not architecturally visible.

Every test ends by storing to a reserved address (`tohost`, the riscv-tests convention); the run stops there and the stored value is the exit code. This replaced a `same_pc >= 6` heuristic that inferred completion from the PC not moving — which cannot distinguish "finished" from "spinning on a lock", "stalled on slow memory", or "stuck", and made every legitimately-looping test a guess. Completion is detected where the store *commits* rather than by watching memory, so it behaves identically with a write-back cache holding the value dirty.

Tests name their trap handler via a `la` pseudo-instruction rather than a hardcoded byte offset. That is not cosmetic: adding the `tohost` sequence shifted every handler label and broke eight tests at once, because they computed `mtvec` by counting instructions.

**Catches:** decode/execute bugs, the specific hazard each test targets, trap entry/exit.
**Doesn't catch:** anything the author didn't think to write. Final-state comparison also can't distinguish "right answer via the wrong path" from "right answer" — which is what lockstep below is for.

## Compliance suite (`compliance/`)

The pinned `riscv-arch-test` `rv32i_m/I` suite contains 38 independently-written programs, each dumping a signature diffed word-for-word against a golden reference. It runs in a dedicated workflow for relevant pushes and pull requests; it is not multiplied across the six directed configurations.

**Catches:** ISA-conformance bugs the directed suite's author (same person as the RTL author) wouldn't target.
**Doesn't catch:** anything outside base RV32I, and it is still a final-state comparison.

## Spike lockstep (`make lockstep`)

The same 38 compliance programs, re-linked for Spike's memory map and compared **retirement by retirement** — PC, instruction word, destination register, and written value. **38/38 match instruction-for-instruction** (`add-01` alone is 3,212 retirements).

The RTL exposes an RVFI-style trace at WB (`rvfi_*` in `backend.sv`), simulation-only, so no pipeline register is widened to serve a debug consumer. `tools/lockstep.py` streams Spike's commit log and stops at the *first* divergence, printing both sides and the preceding retirements — a mismatch reported 400 instructions later is nearly useless.

Both machines run the *same ELF*. Spike reserves low memory, so `compliance/link/spike-lockstep.ld` relocates to `0x80000000`; the RTL's memories decode only their low address bits, so that image aliases back to the same words, and only the reset vector needs adjusting (`RESET_PC`).

Spike itself is pinned in CI to the exact commit these results were measured against, not tracked from `master`. A reference model that changes version underneath you makes every future divergence ambiguous between "the RTL regressed" and "upstream changed" — which is the single question this flow exists to answer unambiguously.

**Catches:** the "right answer via the wrong path" class — wrong forwarding masked by a dead value, a flush that squashes one instruction too many, or a stale CSR read nobody observes.
**Doesn't catch:** anything outside these 38 programs — though the same harness is now also driven by random stimulus, see below.

## SVA assertions

**25 concurrent properties** are built into every simulator via `--assert`, and **2 immediate assertions** enforce both directions of the load-use dependency/stall equivalence. They sit beside the logic they constrain: next-PC priority in `frontend.sv`, forwarding/trap/interrupt invariants in `backend.sv`, `x0` immutability in `reg_file.sv`, stall boundedness at the top level, and hazard soundness/completeness in `hazard_detect.sv`.

The interrupt properties are the sharpest: an interrupt resumes at `pc+4` while a trap re-runs the faulting instruction, so `a_irq_mepc_is_next` and `a_trap_mepc_is_faulting` pin down both directions — getting them backwards silently drops or repeats work.

**Catches:** any change violating an invariant, immediately, in any test.
**Doesn't catch:** anything not expressed as a property. Three were found mis-specified during authoring (not RTL bugs) and corrected against the RTL's actual behaviour, not the reverse.

## Functional coverage (`make coverage`, `docs/coverage.md`)

Verilator doesn't support covergroups; `cover property` is the supported equivalent. The RTL contains 44 points across forwarding crosses, predictor outcomes, control-flow types, trap causes, and the D-cache FSM. The current report hits **44/44 (100%)**.

The coverage target runs the 25 directed programs plus one deterministic BTB-alias fixture.

## Constrained-random, two flows

**`make soak`** — `tools/rand_gen.py` emits random ALU/load-store programs; `tools/rv32i_model.py` is a small Python reference model that computes the expected result. **1000 seeds pass clean** against both cacheless and cache-enabled builds. Compares final register state.

**`make soak-lockstep`** — the same generator pointed at Spike instead (`--spike` mode, `tools/soak_lockstep.sh`). Because Spike is a full ISA implementation rather than a 90-line model, this flow *can* generate branches and jumps — ~13% of emitted instructions — and it compares **per retirement** rather than on final state. **200 seeds × 60 instructions pass clean, in ~20 seconds**, and it runs in CI on every `rtl/**` push alongside the compliance lockstep. Control flow under random stimulus was the single largest hole in this project's verification and this is what closes it.

The harness was validated by fault injection rather than assumed to work: changing `BLTU` in `branch_unit.sv` to compare signed instead of unsigned made **4 of 20 seeds diverge**, each pointing at the retirement where the wrong branch direction first showed up. A verification flow that has only ever reported success hasn't been shown to be capable of reporting anything else.

Getting it working surfaced a non-obvious hazard worth recording: the two machines do not start from the same architectural state. Spike enters through a boot ROM at `0x1000` that leaves residue in `x5`/`a0`/`a1` before jumping to the program, while the RTL comes out of reset all-zero. Hand-written compliance tests never notice because they initialise their own registers; randomly generated code reads whatever is there and diverges for a reason that has nothing to do with the DUT. The generator now emits an explicit register-init prologue. The first divergence this flow ever reported was that, not an RTL bug — which is itself the point: a lockstep harness that has never reported a divergence hasn't been shown to be able to.

**Still doesn't catch:** traps, interrupts, or CSR sequences under random stimulus — generating those meaningfully requires the generator to model privilege state, not just emit instructions. Those remain directed-test and compliance-suite territory.

## Not yet done

- **Trap/CSR/interrupt generation under random stimulus.** Control flow is covered now (`make soak-lockstep`); privileged sequences are not, and need the generator to model privilege state rather than just emit instructions.
- **Formal.** The RVFI port makes a formal flow (e.g. riscv-formal) bindable, but none is set up.
- **Timing closure.** Nothing here says whether the design meets timing; see the synthesis section of `docs/architecture.md`.
