# Verification plan

What is tested, by what mechanism, and what is not tested yet.

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

<!-- portfolio:summary:start -->
The release gate runs 25 programs across 6 memory configurations and 3 predictor configurations. Pinned architecture signatures and complete Spike traces both pass 38/38; random Spike lockstep passes 200/200; functional coverage is 44/44 (100.0%).
<!-- portfolio:summary:end -->

## Directed tests (`tests/`, via `make all`)

25 hand-assembled programs covering instruction classes, true and false load-use dependencies, control flow, precise illegal/misaligned traps, CSR permissions, timer/software interrupt state, `MRET`, cache eviction, RAS/gshare behaviour and `FENCE.I`. Each checks final register state and optional stall counts against a `.ref` file across the 6-configuration matrix; cache geometry is not architecturally visible.

Every test ends by storing to `tohost`, and that value is the exit code. This replaced a `same_pc >= 6` heuristic that could not tell "finished" from "spinning" or "stalled". Completion is detected where the store *commits*, so a write-back cache holding the value dirty behaves identically. Tests name their handler via `la` rather than a hardcoded offset — adding the `tohost` sequence shifted every label and broke eight tests that computed `mtvec` by counting instructions.

Catches decode/execute bugs, the targeted hazard, and trap entry/exit. Misses anything unwritten, and cannot tell a right answer from a right answer reached the wrong way — which is what lockstep is for.

## SoC units and firmware (`make soc-check`)

`core_external` and `csr_external_irq` isolate the external core boundary and machine-external interrupt. The bus path is covered by `wb_master_adapter`, `wb_arbiter`, `wb_interconnect` and `wb_memory`; peripherals and board control by `uart_tx`, `wb_uart`, `button_debounce`, `wb_gpio_irq` and `reset_controller`; `soc_smoke` proves the integrated hierarchy fetches and retires without a bus fault. Each unit is bounded by a timeout and covers success plus the delayed/error/permission/bounce cases relevant to it.

The firmware harness uses the exact ELF-derived images and requires the complete stream `rv32i soc ready\nexternal irq\nexternal irq\n`, not a prefix. It rejects a bouncing BTN1 waveform, then requires two debounced presses, exactly two LED transitions, continued progress after each `MRET`, no duplicate interrupt, no UART framing error, no Wishbone error, and completion before its deadline. `make soc-check` also validates the image manifest, lints `rv32i_soc` and `arty_a7_35t_top`, and runs the guarded board-flow contracts in CI. Vivado routing and physical programming remain local steps.

## Compliance (`compliance/`)

The pinned `riscv-arch-test` `rv32i_m/I` suite: 38 independently written programs, each dumping a signature diffed word-for-word against a golden reference, in its own workflow rather than multiplied across the directed matrix. Catches conformance bugs the directed suite's author — the same person who wrote the RTL — would not target. Still a final-state comparison, and only base RV32I.

## Spike lockstep (`make lockstep`)

The same 38 programs re-linked for Spike's memory map and compared **retirement by retirement**: PC, instruction word, destination register, written value. **38/38 match instruction-for-instruction** (`add-01` alone is 3,212 retirements).

The RTL exposes a simulation-only RVFI-style trace at WB (`rvfi_*` in `backend.sv`), so no pipeline register is widened for a debug consumer. `tools/lockstep.py` stops at the *first* divergence and prints both sides — a mismatch reported 400 instructions later is nearly useless. Both machines run the same ELF: Spike reserves low memory, so `spike-lockstep.ld` relocates to `0x80000000` and the RTL's memories alias it back.

Spike is pinned to the exact commit these results were measured against, not tracked from `master`: a reference model that shifts underneath you makes every divergence ambiguous between "the RTL regressed" and "upstream changed".

Catches the wrong-path class — forwarding masked by a dead value, a flush that squashes one instruction too many, a stale CSR read nobody observes.

## SVA assertions

Properties sit beside the logic they constrain: next-PC priority in `frontend.sv`, forwarding/trap/interrupt invariants in `backend.sv`, `x0` immutability in `reg_file.sv`, stall boundedness, and hazard soundness in `hazard_detect.sv`. The SoC adds `MEIP` reflection and gating, Wishbone ownership/response/stability, uncached MMIO counting, sticky bus faults, reset release, and GPIO/UART exclusivity. Counts are derived from source, not hand-maintained.

The interrupt properties are the sharpest: an interrupt resumes at the retired instruction's successor while a trap re-runs the faulting instruction, so `a_irq_mepc_is_next` and `a_trap_mepc_is_faulting` pin both directions — reversing them silently drops or repeats work. Three properties were found mis-specified during authoring and corrected against the RTL's actual behaviour, not the reverse.

## Functional coverage (`make coverage`)

Verilator has no covergroups, so `cover property` is the equivalent. 44 points across forwarding crosses, predictor outcomes, control-flow types, trap causes and the D-cache FSM, hit **44/44 (100%)** by the 25 directed programs plus one deterministic BTB-alias fixture. Full report in [`coverage.md`](coverage.md).

## Constrained-random, two flows

**`make soak`** — `tools/rand_gen.py` emits random ALU/load-store programs and `tools/rv32i_model.py` computes the expected result. **1000 seeds pass clean** on cacheless and cache-enabled builds, comparing final register state.

**`make soak-lockstep`** — the same generator pointed at Spike. Because Spike is a full ISA implementation rather than a 90-line model, this flow generates branches and jumps (~13% of emitted instructions) and compares **per retirement**. **200 seeds × 60 instructions pass clean in ~20 seconds**, in CI on every `rtl/**` push. Control flow under random stimulus was the largest hole in this project's verification.

The harness was validated by fault injection rather than assumed to work: changing `BLTU` in `branch_unit.sv` to compare signed made **4 of 20 seeds diverge**, each pointing at the first wrong retirement. A flow that has only ever reported success has not been shown capable of reporting anything else.

One non-obvious hazard: the machines do not start from the same architectural state. Spike enters through a boot ROM at `0x1000` leaving residue in `x5`/`a0`/`a1`; the RTL comes out of reset all-zero. Hand-written tests never notice because they initialise their own registers; random code reads whatever is there. The generator now emits a register-init prologue — and that, not an RTL bug, was the first divergence this flow reported.

## Not yet done

- **Traps, interrupts and CSR sequences under random stimulus** — needs the generator to model privilege state, not just emit instructions. Directed and compliance territory for now.
- **Formal.** The RVFI port makes a flow such as riscv-formal bindable, but none is set up.
- **Physical-board validation.** Simulation and flow contracts pass; no validated route/program/manual result is published. See [`soc.md`](soc.md).
