# Board-Ready Wishbone SoC Implementation Plan

> **For implementers:** Execute this plan task by task with test-driven development and a review checkpoint after every commit. Check boxes track completion; do not batch unrelated tasks.

**Goal:** Produce a verified and synthesis-ready Arty A7-35T SoC containing the existing RV32I pipeline, Wishbone B4 fabric, BRAM, UART TX, GPIO, and a button-driven machine-external interrupt.

**Architecture:** Extract the pipeline and caches into an external-memory `rv32i_core`, while retaining `cpu` as the exact legacy internal-memory wrapper used by the existing harness. Two request adapters and a fair arbiter connect the core to a shared Wishbone B4 fabric containing separate instruction/data BRAMs and uncached UART/GPIO peripherals. The same freestanding firmware image is validated in Verilator and then initialized into the FPGA bitstream.

**Tech Stack:** SystemVerilog, SVA, Verilator 5.048, C++17, freestanding RV32I C/assembly, Python 3.12 standard library, GNU Make, RISC-V GCC/binutils 13.2.0/2.42, Wishbone B4 Classic, Vivado 2025.2, Arty A7-35T.

**Spec:** `docs/designs/2026-08-29-board-ready-soc-design.md`

## Global Constraints

- Work only on `soc-integration`; never rewrite or force-push history.
- Keep the `cpu` module's ports, parameters, default behavior, and verification contract compatible.
- Do not delete or move files without separate user approval; this plan requires no deletions or moves.
- Use `git mv` for any subsequently approved move.
- Use only existing C++, SystemVerilog, Bash, Make, and Python standard-library dependencies.
- Keep new RTL comments limited to interface contracts, timing assumptions, and non-obvious invariants.
- Commit messages describe behavior and contain no roadmap-phase wording or co-author trailers.
- Do not publish CPI, fmax, utilization, pass-rate, or board-success claims before measuring them from the final committed RTL.
- Keep generated ELF, HEX, bitstream, checkpoint, Vivado project, raw report, log, and journal files ignored.
- Preserve the established explicit simulator completion, complete-trace, and evidence contracts.
- Run the full baseline before RTL changes and compare the same milestones after implementation.
- The board target is exactly `xc7a35ticsg324-1L` with a 100 MHz clock on pin E3.
- The Digilent constraint source is pinned to `00a3404901f35aa9567b01ecb3f2c233b6efe9f4`.
- The SoC memory map and register behavior must match the approved spec exactly.
- Stop before committing any physical-board video or creating/pushing a release; those require explicit user approval.

## Planned File Map

### Existing files modified

- `Makefile`: add SoC build/test/program targets and include fast SoC gates.
- `README.md`: repair the visible demo and later add only validated board facts.
- `rtl/rv32i_pkg.sv`: define machine-external interrupt constants.
- `rtl/core/cpu.sv`: become the compatibility wrapper around `rv32i_core` and internal memories.
- `rtl/core/frontend.sv`: expose its cache-backing instruction channel.
- `rtl/core/backend.sv`: expose its cache-backing data channel, add cacheability parameters, and accept external IRQ.
- `rtl/core/csr.sv`: implement `MEIE`, `MEIP`, and cause 11 selection.
- `rtl/memory/dcache.sv`: bypass uncacheable requests without allocation or counter updates.
- `sim/unit/dcache_counter_tb.sv`: cover uncached passthrough.
- `tools/portfolio_demo.py`, `tools/test_portfolio_demo.py`: make the existing README recording visibly complete.
- `docs/media/portfolio-demo.tape`, `.gif`, `.json`, `.txt`: regenerate the validated terminal demonstration.
- `tools/reference_versions.env`, `tools/evidence_check.py`, `tools/test_evidence_check.py`: pin and validate Digilent constraints metadata.
- `tools/verification.py`, `tools/test_verification.py`: expose the SoC fast profile through the pinned environment.
- `.github/workflows/rtl-tests.yml`: trigger and execute SoC checks.
- `.gitignore`, `.dockerignore`: exclude board build products from repository and container contexts.
- `containers/verify/Dockerfile`: include no new package; only update the environment revision if source changes require rebuilding the image.
- `docs/architecture.md`, `docs/verification.md`, `docs/evidence.md`, `docs/coverage.md`: document implemented behavior, evidence state, and measured evidence.
- `tools/results.py`, `tools/test_results.py`, `tools/render_portfolio.py`, `tools/test_render_portfolio.py`: validate and render SoC evidence after hardware measurement.

### New files

- `rtl/core/rv32i_core.sv`
- `rtl/bus/wb_master_adapter.sv`
- `rtl/bus/wb_arbiter.sv`
- `rtl/soc/wb_interconnect.sv`
- `rtl/soc/wb_imem.sv`
- `rtl/soc/wb_dmem.sv`
- `rtl/soc/uart_tx.sv`
- `rtl/soc/wb_uart.sv`
- `rtl/soc/button_debounce.sv`
- `rtl/soc/wb_gpio_irq.sv`
- `rtl/soc/reset_controller.sv`
- `rtl/soc/rv32i_soc.sv`
- `rtl/boards/arty_a7_35t_top.sv`
- `boards/arty_a7_35t.xdc`
- `sim/unit/core_external_tb.sv`
- `sim/unit/csr_external_irq_tb.sv`
- `sim/unit/wb_master_adapter_tb.sv`
- `sim/unit/wb_arbiter_tb.sv`
- `sim/unit/wb_interconnect_tb.sv`
- `sim/unit/wb_memory_tb.sv`
- `sim/unit/uart_tx_tb.sv`
- `sim/unit/wb_uart_tb.sv`
- `sim/unit/button_debounce_tb.sv`
- `sim/unit/wb_gpio_irq_tb.sv`
- `sim/unit/reset_controller_tb.sv`
- `sim/unit/soc_smoke_tb.sv`
- `sim/fixtures/soc_selfloop.hex`
- `sim/soc_tb.cpp`
- `firmware/start.S`
- `firmware/demo.c`
- `firmware/soc.h`
- `firmware/link.ld`
- `tools/soc_image.py`
- `tools/test_soc_image.py`
- `synthesis/soc/build.tcl`
- `synthesis/soc/program.tcl`
- `synthesis/soc/run_board.py`
- `synthesis/soc/test_board_tools.py`
- `docs/soc.md`

### Conditional measured publication

- `results/soc.json`: create only after a real Vivado route and physical-board run pass.

---

### Task 1: Capture the baseline and repair the blank README demonstration

**Files:**
- Modify: `tools/portfolio_demo.py:15-348`
- Modify: `tools/test_portfolio_demo.py:1-130`
- Modify: `docs/media/portfolio-demo.tape:1-13`
- Modify: `Makefile:307-321`
- Regenerate: `docs/media/portfolio-demo.gif`
- Regenerate: `docs/media/portfolio-demo.txt`
- Regenerate: `docs/media/portfolio-demo.json`

**Interfaces:**
- Consumes: validated `results/` records and the existing fast/lockstep entry points.
- Produces: `replay_demo(result: ResultSet, transcript: TextIO, sleeper: Callable[[float], None]) -> int`, a bounded visual replay, and a recorder that executes real gates before VHS starts.

- [ ] **Step 1: Record the immutable pre-change baseline outside the repository**

Run:

```bash
git status --short --branch
mkdir -p /home/huy/.cache/rv32i-soc-20260829
make verify 2>&1 | tee /home/huy/.cache/rv32i-soc-20260829/baseline-verify.log
git rev-parse HEAD > /home/huy/.cache/rv32i-soc-20260829/baseline-commit.txt
```

Expected: clean `soc-integration`; complete verification exits zero. Extract and retain the decoder, hazard, harness, directed, predictor, compliance, lockstep, random, assertion, and cover-point milestones from the log. Do not edit tracked files if the baseline fails.

- [ ] **Step 2: Add failing replay and Make-target tests**

Add to `tools/test_portfolio_demo.py`:

```python
def test_replay_is_bounded_and_finishes_with_visible_marker(self) -> None:
    pauses: list[float] = []
    output = StringIO()
    with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
        status = replay_demo(self.result, output, sleeper=pauses.append)
    self.assertEqual(status, 0)
    self.assertEqual(pauses, [3.0] * len(replay_sections(self.result)))
    self.assertIn("RV32I PIPELINE", output.getvalue())
    self.assertTrue(output.getvalue().rstrip().endswith("DEMO COMPLETE"))

def test_tape_records_replay_instead_of_slow_live_gates(self) -> None:
    source = (ROOT / "docs/media/portfolio-demo.tape").read_text(encoding="utf-8")
    self.assertIn('Type "python3 tools/portfolio_demo.py --replay"', source)
    self.assertNotIn("--live", source)

def test_record_target_runs_gates_before_vhs(self) -> None:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "portfolio-demo-record"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    self.assertEqual(result.returncode, 0, result.stdout)
    fast = result.stdout.index("tools/verification.py run --profile fast")
    spike = result.stdout.index("lockstep-sample")
    record = result.stdout.index("vhs docs/media/portfolio-demo.tape")
    self.assertLess(fast, spike)
    self.assertLess(spike, record)
```

Import `replay_demo` and `replay_sections` from `tools.portfolio_demo`.

- [ ] **Step 3: Run the focused tests and confirm the root-cause failure**

Run:

```bash
python3 -m unittest -v tools.test_portfolio_demo
```

Expected: failures because replay functions do not exist, the tape still invokes `--live`, and the record target does not run the verification gates before VHS.

- [ ] **Step 4: Implement the bounded replay**

Add to `tools/portfolio_demo.py`:

```python
import time

def gate_text(root: Path, heading: str = "LIVE VERIFICATION") -> str:
    lines = [heading]
    for step in demo_steps(root):
        lines.extend(("$ " + " ".join(step.command), f"{step.name}: PASS"))
    return "\n".join(lines)

def replay_sections(result: ResultSet) -> tuple[str, ...]:
    return (
        gate_text(result.root.parent, "VERIFICATION GATES COMPLETED"),
        *sections(result),
        "DEMO COMPLETE",
    )

def replay_demo(
    result: ResultSet,
    transcript: TextIO,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    for section in replay_sections(result):
        transcript.write("\x1b[2J\x1b[H" + section + "\n")
        transcript.flush()
        sleeper(3.0)
    return 0
```

Replace the existing `gate_text` with the heading-aware version. Add `--replay`
to the mutually exclusive CLI group and dispatch it through `load_result(root)`
and `replay_demo`. Keep `--live` for interactive use, but remove it from the VHS
tape. Update `validate_media` to require the replay command exactly once and
reject `--live` in the tape.

Change `docs/media/portfolio-demo.tape` to type `python3 tools/portfolio_demo.py --replay` at 1 ms typing speed and record for 32 seconds. Ten three-second slides finish before the recording deadline and leave the final marker visible. Change `portfolio-demo-record` to run these commands in order:

```make
python3 tools/verification.py run --profile fast
$(MAKE) --no-print-directory lockstep-sample
python3 tools/portfolio_demo.py --write-transcript
vhs docs/media/portfolio-demo.tape
python3 tools/portfolio_demo.py --write-media-manifest
```

- [ ] **Step 5: Run the focused tests**

Run:

```bash
python3 -m unittest -v tools.test_portfolio_demo tools.test_verification
```

Expected: all portfolio demo and verification command-contract tests pass.

- [ ] **Step 6: Regenerate and visually inspect the artifact**

Run:

```bash
make portfolio-gif
make portfolio-check
```

Inspect the first visible slide, at least one middle slide, and the final `DEMO COMPLETE` slide. Confirm the GitHub raw URL returns `Content-Type: image/gif` and the new committed hash matches `docs/media/portfolio-demo.json`.

- [ ] **Step 7: Commit the isolated repair**

```bash
git add Makefile tools/portfolio_demo.py tools/test_portfolio_demo.py \
  docs/media/portfolio-demo.tape docs/media/portfolio-demo.gif \
  docs/media/portfolio-demo.txt docs/media/portfolio-demo.json
git diff --cached --check
git commit -m "fix: make portfolio demo visibly complete"
```

### Task 2: Preserve trustworthy historical evidence during RTL development

**Files:**
- Modify: `tools/results.py`
- Modify: `tools/test_results.py`
- Modify: `tools/render_portfolio.py`
- Modify: `tools/test_render_portfolio.py`
- Modify: `tools/evidence_check.py`
- Modify: `tools/test_evidence_check.py`
- Modify: `docs/coverage.md`
- Modify through renderer: `README.md`
- Modify through renderer: `docs/architecture.md`
- Modify through renderer: `docs/verification.md`
- Modify through renderer: `docs/evidence.md`

**Interfaces:**
- Consumes: the committed result manifest's tooling/RTL commits and Git objects already present in the checkout.
- Produces: `evidence_state(checkout: Path, rtl_commit: str) -> Literal["current", "historical"]`, commit-aware result validation, and an explicit historical label while working RTL differs from measured RTL.

- [ ] **Step 1: Write failing current-versus-historical tests**

Create a temporary Git fixture with a committed RTL file, complete result
fixtures bound to that commit, and rendered documents. Verify the original
checkout reports `current`. Commit an RTL-only change without changing the
result records and require:

```python
self.assertEqual(evidence_state(repo, measured_rtl), "historical")
self.assertEqual(validate_result_set(repo / "results", repo), [])
rendered = render_documents(repo, load_validated(repo))
self.assertIn("Historical measurements", rendered[repo / "README.md"])
self.assertIn(measured_rtl, rendered[repo / "docs/evidence.md"])
```

Also require a tampered result hash, nonexistent recorded commit, dirty result
record, or documentation claiming `current` while RTL differs to fail. Add a
test that a documentation-only commit after measurement remains current.

- [ ] **Step 2: Run tests and confirm the provenance failure**

Run:

```bash
python3 -m unittest -v tools.test_results tools.test_render_portfolio \
  tools.test_evidence_check
```

Expected: the RTL-change fixture fails because current validation rejects any
difference from the frozen RTL and there is no historical state.

- [ ] **Step 3: Validate records against their recorded Git objects**

Define:

```python
def git_blob(checkout: Path, commit: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), "show", f"{commit}:{relative}"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ResultError(f"recorded source is unavailable: {relative}")
    return result.stdout

def evidence_state(checkout: Path, rtl_commit: str) -> str:
    paths = ("rtl", "sim/cpu_tb.cpp")
    result = subprocess.run(
        ["git", "-C", str(checkout), "diff", "--quiet", rtl_commit, "--", *paths]
    )
    return "current" if result.returncode == 0 else "historical"
```

Add `git_paths(checkout: Path, commit: str, prefix: str) -> tuple[str, ...]`
using `git ls-tree -r --name-only`; accept only paths below the requested prefix
and feed each through `git_blob`. Derive RTL assertion/cover counts from all
recorded `rtl/**/*.sv` blobs and the harness count from the recorded tooling
commit's `tools/test_harness.py`.

Keep hash, schema, population, arithmetic, and cross-record validation strict.
When historical, derive harness/assertion/cover source expectations from blobs at
the recorded commits instead of the working tree. Do not accept a missing commit
or skip internal result checks. When current, preserve the existing worktree
comparison. Replace fixed assertion/cover totals in `validate_verification` and
`validate_manifest` with those derived expectations so adding a source property
can never be hidden by a stale constant.

- [ ] **Step 4: Render and validate an explicit evidence state**

Add `EVIDENCE_STATUS` to the generated fact block. `current` means the measured
RTL matches the checkout. `historical` means every table remains bound to and
labeled with its frozen RTL commit; it does not describe unmeasured current RTL.
Render this sentence above the snapshot/tables when historical:

```text
Historical measurements — validated for RTL <40-character commit>; current RTL changes are not yet remeasured.
```

Teach `evidence_check.py` to compare source counts to current RTL only in the
`current` state. In the `historical` state, compare published fact counts to the
recorded source blobs and require the historical sentence in all four portfolio
documents. Update `docs/coverage.md` to `historical` when the result becomes
historical; `make coverage` restores `current` only after a fresh run.

- [ ] **Step 5: Run the evidence tests and current checkout gates**

Run:

```bash
python3 -m unittest -v tools.test_results tools.test_render_portfolio \
  tools.test_evidence_check
make portfolio-render
make results-check
make portfolio-render-check
make evidence-check
```

Expected: the unchanged pre-SoC RTL still renders `current`; all existing
measurements retain their exact numbers and original commits.

- [ ] **Step 6: Commit the evidence-state contract**

```bash
git add tools/results.py tools/test_results.py tools/render_portfolio.py \
  tools/test_render_portfolio.py tools/evidence_check.py \
  tools/test_evidence_check.py README.md docs/architecture.md \
  docs/verification.md docs/evidence.md docs/coverage.md
git diff --cached --check
git commit -m "evidence: distinguish historical measurements"
```

After the first RTL modification, run `make portfolio-render` before its commit
so the same commit labels prior measurements historical. Do not change any
measurement value until the final remeasurement task.

### Task 3: Extract the external-memory core without changing legacy behavior

**Files:**
- Create: `rtl/core/rv32i_core.sv`
- Create: `sim/unit/core_external_tb.sv`
- Modify: `rtl/core/cpu.sv:1-153`
- Modify: `rtl/core/frontend.sv:14-94`
- Modify: `rtl/core/backend.sv:11-443`
- Modify: `tools/run_unit.sh`
- Modify: `Makefile:30-101`

**Interfaces:**
- Consumes: existing cache-backing `req/burst/addr/data/ready` semantics.
- Produces: module `rv32i_core` with instruction/data backing ports, `irq_external`, existing performance/debug ports, and `retired_debug`.

- [ ] **Step 1: Write the failing external-core smoke test**

Create `sim/unit/core_external_tb.sv` that instantiates this contract:

```systemverilog
rv32i_core #(
    .ICACHE_BYTES(0), .DCACHE_BYTES(0), .RESET_PC(32'h0000_0000)
) dut (
    .clk(clk), .rst(rst), .irq_external(1'b0),
    .imem_req(imem_req), .imem_burst(imem_burst), .imem_addr(imem_addr),
    .imem_rdata(32'h0000_006f), .imem_ready(1'b1),
    .dmem_req(dmem_req), .dmem_burst(dmem_burst), .dmem_addr(dmem_addr),
    .dmem_wstrb(dmem_wstrb), .dmem_wdata(dmem_wdata),
    .dmem_rdata(32'h0), .dmem_ready(1'b1),
    .dbg_flush(1'b0), .dbg_flush_done(), .retired_debug(),
    .perf_cycle_count(), .perf_instr_retired(), .perf_stall_count(),
    .perf_flush_count(), .perf_mispredict_count(), .perf_branch_count(),
    .perf_mem_stall_count(), .perf_icache_access(), .perf_icache_miss(),
    .perf_dcache_access(), .perf_dcache_miss()
);
```

Pulse reset, run 12 clocks, and require `imem_req`, word-aligned `imem_addr`, no data request, and no unknown output. Register the test in `tools/run_unit.sh`.

- [ ] **Step 2: Run the smoke test and confirm it fails to elaborate**

Run:

```bash
./tools/run_unit.sh core_external
```

Expected: compile failure because `rv32i_core` does not exist.

- [ ] **Step 3: Move backing-memory ownership out of the front and back ends**

Change `frontend` to expose:

```systemverilog
output var logic             imem_req,
output var logic             imem_burst,
output var logic [XLEN-1:0]  imem_addr,
input  var logic [ILEN-1:0]  imem_rdata,
input  var logic             imem_ready
```

Wire these ports to the current `ic_mem_*` signals and remove only the `instr_mem` instantiation. Keep I-cache behavior unchanged.

Change `backend` to expose:

```systemverilog
output var logic             ext_dmem_req,
output var logic             ext_dmem_burst,
output var logic [XLEN-1:0]  ext_dmem_addr,
output var logic [XBYTES-1:0] ext_dmem_wstrb,
output var logic [XLEN-1:0]  ext_dmem_wdata,
input  var logic [XLEN-1:0]  ext_dmem_rdata,
input  var logic             ext_dmem_ready
```

Connect them to the current `dc_mem_*` signals and remove only the `data_mem` instantiation.

- [ ] **Step 4: Create `rv32i_core` from the current top-level wiring**

Move the pipeline/cache/predictor/counter wiring currently in `cpu.sv` into `rv32i_core.sv`. Keep the next-PC, stall, trap, debug-flush, and performance behavior unchanged. Add `irq_external` and pass it into `backend`; initially tie it unused until Task 4. Drive `retired_debug` from the backend's existing `retired` signal.

- [ ] **Step 5: Rebuild `cpu` as the compatibility wrapper**

Keep the current `cpu` port list and parameters. Instantiate `rv32i_core`, tie `irq_external=1'b0`, instantiate `instr_mem` and `data_mem` with the existing latency/depth parameters, and connect their channels to the external-core backing ports.

- [ ] **Step 6: Run focused and legacy tests**

Run:

```bash
./tools/run_unit.sh core_external
make focused-test TEST=t01_rtype
make focused-test TEST=t19_dcache_evict IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10
make unit
make lint
make portfolio-render
make evidence-check
```

Expected: the new smoke test and all selected legacy paths pass. Portfolio
tables retain their measured values but are visibly labeled historical against
their recorded RTL commit.

- [ ] **Step 7: Commit the boundary refactor**

```bash
git add rtl/core/rv32i_core.sv rtl/core/cpu.sv rtl/core/frontend.sv \
  rtl/core/backend.sv sim/unit/core_external_tb.sv tools/run_unit.sh Makefile \
  README.md docs/architecture.md docs/verification.md docs/evidence.md \
  docs/coverage.md
git diff --cached --check
git commit -m "refactor: expose core memory interfaces"
```

### Task 4: Add machine-external interrupt support

**Files:**
- Create: `sim/unit/csr_external_irq_tb.sv`
- Modify: `rtl/rv32i_pkg.sv:148-165`
- Modify: `rtl/core/csr.sv:6-208`
- Modify: `rtl/core/backend.sv:11-714`
- Modify: `rtl/core/rv32i_core.sv`
- Modify: `rtl/core/cpu.sv`
- Modify: `tools/run_unit.sh`

**Interfaces:**
- Consumes: `irq_external` level from the future GPIO block.
- Produces: `mie.MEIE`, `mip.MEIP`, `CAUSE_IRQ_EXTERNAL`, external-over-software-over-timer selection, and unchanged precise interrupt commit behavior.

- [ ] **Step 1: Write the failing CSR unit vectors**

Create `sim/unit/csr_external_irq_tb.sv`. Drive CSR writes through `csr_access/csr_addr/csr_funct3/csr_wdata`, then check:

```systemverilog
write_csr(CSR_MIE, 32'h0000_0888);
write_csr(CSR_MSTATUS, 32'h0000_0008);
irq_external = 1'b1;
tick();
check(irq_pending, 1'b1, "MEIP pending");
check(irq_cause, 32'h8000_000b, "external cause");
read_csr(CSR_MIP, value);
check(value[11], 1'b1, "mip.MEIP");
```

Also check global disable, `MEIE` disable, external priority while MSIP/MTIP are pending, trap entry clearing MIE, and `mret_en` restoring it.

- [ ] **Step 2: Run the test and confirm compile/behavior failure**

Run:

```bash
./tools/run_unit.sh csr_external_irq
```

Expected: failure because `csr` has no `irq_external` input and no external constants.

- [ ] **Step 3: Add package constants and CSR state**

Add:

```systemverilog
localparam int IRQ_E_BIT = 11;
localparam logic [XLEN-1:0] CAUSE_IRQ_EXTERNAL =
    {1'b1, {(XLEN-1){1'b0}}} | XLEN'(IRQ_E_BIT);
```

Add `input var logic irq_external` to `csr`. Implement `mie_meie`, reflect `irq_external` into `mip_val[IRQ_E_BIT]`, allow `CSR_MIE` writes to bit 11, and select:

```systemverilog
logic pending_external, pending_software, pending_timer;
assign pending_external = mie_meie && irq_external;
assign pending_software = mie_msie && mip_msip;
assign pending_timer    = mie_mtie && mip_mtip;
assign irq_pending = mstatus_mie &&
                     (pending_external || pending_software || pending_timer);
assign irq_cause = pending_external ? CAUSE_IRQ_EXTERNAL
                 : pending_software ? CAUSE_IRQ_SOFT
                 :                    CAUSE_IRQ_TIMER;
```

Reset `mie_meie` low. Do not make MEIP software writable through `mip`.

- [ ] **Step 4: Wire the interrupt and add invariants**

Pass `irq_external` through `rv32i_core` and `backend` into `csr`; keep the compatibility wrapper tied low. Add assertions for external cause, enable gating, priority, and commit mutual exclusion. Preserve the existing MEM-stage interrupt commit path.

- [ ] **Step 5: Run interrupt and regression tests**

Run:

```bash
./tools/run_unit.sh csr_external_irq
make focused-test TEST=t16_irq_timer
make focused-test TEST=t17_irq_mret
make focused-test TEST=t18_trap_causes
make unit
make lint
```

Expected: external vectors and all existing timer/software interrupt programs pass.

- [ ] **Step 6: Commit the interrupt extension**

```bash
git add rtl/rv32i_pkg.sv rtl/core/csr.sv rtl/core/backend.sv \
  rtl/core/rv32i_core.sv rtl/core/cpu.sv sim/unit/csr_external_irq_tb.sv tools/run_unit.sh
git diff --cached --check
git commit -m "feat: add machine external interrupts"
```

### Task 5: Add the request-to-Wishbone adapter

**Files:**
- Create: `rtl/bus/wb_master_adapter.sv`
- Create: `sim/unit/wb_master_adapter_tb.sv`
- Modify: `tools/run_unit.sh`
- Modify: `Makefile`

**Interfaces:**
- Consumes: one level-held request/ready channel.
- Produces: one 32-bit byte-addressed Wishbone B4 Classic master and a one-cycle `fault_pulse`.

- [ ] **Step 1: Write the failing adapter test**

Instantiate this exact module contract:

```systemverilog
wb_master_adapter dut (
    .clk(clk), .rst(rst),
    .src_req(src_req), .src_addr(src_addr), .src_wstrb(src_wstrb),
    .src_wdata(src_wdata), .src_rdata(src_rdata), .src_ready(src_ready),
    .fault_pulse(fault_pulse),
    .wb_cyc(wb_cyc), .wb_stb(wb_stb), .wb_we(wb_we),
    .wb_adr(wb_adr), .wb_dat_w(wb_dat_w), .wb_sel(wb_sel),
    .wb_ack(wb_ack), .wb_err(wb_err), .wb_dat_r(wb_dat_r)
);
```

Test idle `src_ready=1`, a delayed read, a byte write, request-field stability while waiting, one ready completion, `err` returning zero plus `fault_pulse`, and a new request after the previous source observes ready.

- [ ] **Step 2: Run the test and confirm missing-module failure**

Run:

```bash
./tools/run_unit.sh wb_master_adapter
```

Expected: compile failure because the adapter does not exist.

- [ ] **Step 3: Implement the two-state adapter**

Use `IDLE` and `ACTIVE`. In `IDLE`, `src_ready=1` when `src_req=0`; on `src_req=1`, latch address, write data, and strobes. In `ACTIVE`, assert `wb_cyc` and `wb_stb` and hold all fields stable. Complete on exactly one of `wb_ack` or `wb_err`. Set `src_rdata=wb_dat_r` on ACK, zero on ERR, pulse `src_ready`, and pulse `fault_pulse` only on ERR. Derive `wb_we=|latched_wstrb`; reads drive `wb_sel=4'b1111`.

Add assertions:

```systemverilog
a_request_stable: assert property (@(posedge clk) disable iff (rst)
    wb_cyc && !(wb_ack || wb_err) |=> $stable({wb_adr, wb_we, wb_sel, wb_dat_w}));
a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
    !(wb_ack && wb_err));
a_fault_from_error: assert property (@(posedge clk) disable iff (rst)
    fault_pulse |-> $past(wb_err));
```

- [ ] **Step 4: Run unit and lint gates**

Run:

```bash
./tools/run_unit.sh wb_master_adapter
make unit
make lint
```

Expected: all adapter vectors and existing units pass.

- [ ] **Step 5: Commit the adapter**

```bash
git add rtl/bus/wb_master_adapter.sv sim/unit/wb_master_adapter_tb.sv tools/run_unit.sh Makefile
git diff --cached --check
git commit -m "feat: add Wishbone request adapter"
```

### Task 6: Add fair arbitration and address decoding

**Files:**
- Create: `rtl/bus/wb_arbiter.sv`
- Create: `rtl/soc/wb_interconnect.sv`
- Create: `sim/unit/wb_arbiter_tb.sv`
- Create: `sim/unit/wb_interconnect_tb.sv`
- Modify: `tools/run_unit.sh`

**Interfaces:**
- Consumes: two Wishbone masters from Task 5 and the approved address map.
- Produces: one transaction-locked shared Wishbone master, four one-hot slave channels, and a terminating default-error response.

- [ ] **Step 1: Write failing arbiter vectors**

Create `sim/unit/wb_arbiter_tb.sv` with independent instruction/data request and response signals. Test:

```systemverilog
request_i(32'h0000_0010);
check(i_ack, 1'b1, "uncontested instruction response");

request_both(32'h0000_0020, 32'h2000_0000);
hold_shared_response(4);
check_grant_stable();
complete_grant();
check_other_master_wins_next();
```

Also inject `shared_err`, require it reaches only the current owner, and require no requester can observe an ACK/ERR belonging to the other requester.

- [ ] **Step 2: Write failing interconnect vectors**

Create `sim/unit/wb_interconnect_tb.sv`. Issue reads and writes at the first and last address of each region, then check exactly one slave request:

```systemverilog
check_decode(32'h0000_0000, SLAVE_IMEM);
check_decode(32'h0000_7fff, SLAVE_IMEM);
check_decode(32'h1000_0000, SLAVE_UART);
check_decode(32'h1000_100c, SLAVE_GPIO);
check_decode(32'h2000_7fff, SLAVE_DMEM);
check_error(32'h0000_8000);
check_error(32'hffff_ffff);
```

Drive `m_instr=1` and require IMEM reads to decode while UART, GPIO, DMEM, and
unmapped addresses terminate with ERR. Drive `m_instr=0` and require data reads
from IMEM plus normal UART/GPIO/DMEM accesses. Hold an address-changing upstream
request while the first transfer is active and require the original slave
selection and instruction/data identity remain latched until completion.

- [ ] **Step 3: Run the focused tests and confirm both modules are missing**

Run:

```bash
./tools/run_unit.sh wb_arbiter
./tools/run_unit.sh wb_interconnect
```

Expected: both fail to elaborate.

- [ ] **Step 4: Implement the arbiter**

`wb_arbiter` has two complete master-side port groups (`i_*`, `d_*`) and one
shared group (`s_*`). Add `s_instr`, high only while the latched owner is
`INSTR`. Use owner values `NONE`, `INSTR`, and `DATA`. Latch the owner when idle,
hold it until `s_ack || s_err`, and update `last_contested` only when both
masters requested at grant time.

Selection rule:

```systemverilog
if (i_cyc && d_cyc)
    next_owner = last_contested == INSTR ? DATA : INSTR;
else if (d_cyc)
    next_owner = DATA;
else if (i_cyc)
    next_owner = INSTR;
else
    next_owner = NONE;
```

Mux the selected request to the shared channel and demux `ack`, `err`, and read data only to the owner. Add assertions for stable ownership, one-hot responses, and bounded contested fairness over two completed grants.

- [ ] **Step 5: Implement the interconnect**

`wb_interconnect` accepts one master plus `m_instr` and exposes four flat slave
groups named `imem_*`, `uart_*`, `gpio_*`, and `dmem_*`. Decode byte addresses
with these constants:

```systemverilog
localparam logic [31:0] IMEM_BASE = 32'h0000_0000;
localparam logic [31:0] IMEM_LAST = 32'h0000_7fff;
localparam logic [31:0] UART_BASE = 32'h1000_0000;
localparam logic [31:0] UART_LAST = 32'h1000_000f;
localparam logic [31:0] GPIO_BASE = 32'h1000_1000;
localparam logic [31:0] GPIO_LAST = 32'h1000_101f;
localparam logic [31:0] DMEM_BASE = 32'h2000_0000;
localparam logic [31:0] DMEM_LAST = 32'h2000_7fff;
```

Latch the decoded slave, request fields, and `m_instr` on an idle
`m_cyc && m_stb`. An instruction request may select only IMEM. A data request
may read IMEM or access UART/GPIO/DMEM; the IMEM slave itself rejects data
writes. Hold one slave request until response. For a disallowed or unmapped
address, return `m_err=1` and zero data on the next clock. Add elaboration checks
proving region non-overlap and SVA proving one-hot slave selection, instruction
permission, and response exclusivity.

- [ ] **Step 6: Run bus tests and lint**

Run:

```bash
./tools/run_unit.sh wb_arbiter
./tools/run_unit.sh wb_interconnect
make unit
make lint
```

Expected: all arbitration/decode vectors pass with no new lint errors.

- [ ] **Step 7: Commit the fabric control plane**

```bash
git add rtl/bus/wb_arbiter.sv rtl/soc/wb_interconnect.sv \
  sim/unit/wb_arbiter_tb.sv sim/unit/wb_interconnect_tb.sv tools/run_unit.sh
git diff --cached --check
git commit -m "feat: add Wishbone arbitration and decoding"
```

### Task 7: Add Wishbone-backed instruction and data BRAMs

**Files:**
- Create: `rtl/soc/wb_imem.sv`
- Create: `rtl/soc/wb_dmem.sv`
- Create: `sim/unit/wb_memory_tb.sv`
- Modify: `tools/run_unit.sh`

**Interfaces:**
- Consumes: Wishbone slave requests from Task 6 and optional initialization files.
- Produces: synchronous 32 KiB instruction/data BRAM slaves with exact permission and byte-lane behavior.

- [ ] **Step 1: Write the failing memory-slave test**

Create a small test fixture with `DEPTH_WORDS=8`. Initialize instruction words through a checked-in unit fixture generated inside the test build directory, then test:

```systemverilog
wb_read_imem(32'h0000_0000, value);
check(value, 32'h0000_0013, "first instruction");
wb_read_imem(32'h0000_001c, value);
check(value, 32'h0000_006f, "last instruction");
wb_write_imem(32'h0000_0000, 4'hf, 32'hdead_beef, expect_err);

wb_write_dmem(32'h2000_0000, 4'b0100, 32'h00aa_0000);
wb_read_dmem(32'h2000_0000, value);
check(value[23:16], 8'haa, "byte lane write");
wb_read_dmem(32'h2000_0020, value, expect_err);
```

Require one-cycle-later completion, never combinational ACK, and exactly one response per request.

- [ ] **Step 2: Run the test and confirm missing-module failure**

Run:

```bash
./tools/run_unit.sh wb_memory
```

Expected: compile failure because both memory slaves are absent.

- [ ] **Step 3: Implement the read-only instruction BRAM**

Use this parameter contract:

```systemverilog
module wb_imem #(
    parameter int DEPTH_WORDS = 8192,
    parameter logic [31:0] BASE_ADDR = 32'h0000_0000,
    parameter string INIT_FILE = ""
) (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic        wb_cyc,
    input  var logic        wb_stb,
    input  var logic        wb_we,
    input  var logic [31:0] wb_adr,
    input  var logic [31:0] wb_dat_w,
    input  var logic [3:0]  wb_sel,
    output var logic        wb_ack,
    output var logic        wb_err,
    output var logic [31:0] wb_dat_r
);
```

Store `logic [31:0] mem [0:DEPTH_WORDS-1]` with `(* ram_style = "block" *)`. Initialize from `+IMEMFILE=<path>` in simulation and `INIT_FILE` in synthesis. Latch reads and ACK them synchronously. Return ERR for writes, unaligned addresses, or indices outside the array.

- [ ] **Step 4: Implement byte-writable data BRAM**

Use the same parameter shape with `BASE_ADDR=32'h2000_0000` and `+DMEMFILE`. On an accepted write, update only selected byte lanes in one `always_ff`. ACK valid aligned in-range reads/writes and ERR all other transfers.

- [ ] **Step 5: Run focused tests and an inference lint**

Run:

```bash
./tools/run_unit.sh wb_memory
make unit
make lint
```

Expected: initialization, permissions, lane writes, and boundary errors pass. Lint reports no multiple drivers or inferred latches.

- [ ] **Step 6: Commit the BRAM slaves**

```bash
git add rtl/soc/wb_imem.sv rtl/soc/wb_dmem.sv sim/unit/wb_memory_tb.sv tools/run_unit.sh
git diff --cached --check
git commit -m "feat: add Wishbone on-chip memories"
```

### Task 8: Bypass the D-cache for non-data-BRAM addresses

**Files:**
- Modify: `rtl/core/backend.sv:11-443`
- Modify: `rtl/core/rv32i_core.sv`
- Modify: `rtl/core/cpu.sv`
- Modify: `rtl/memory/dcache.sv:23-360`
- Modify: `sim/unit/dcache_counter_tb.sv`

**Interfaces:**
- Consumes: `DCACHEABLE_BASE`, `DCACHEABLE_MASK`, and the existing D-cache memory channel.
- Produces: direct one-at-a-time passthrough for uncacheable accesses, with no allocation, dirty state, access count, or miss count.

- [ ] **Step 1: Add failing uncached D-cache vectors**

Extend `sim/unit/dcache_counter_tb.sv` with a `cacheable` input and these cases:

```systemverilog
cacheable = 1'b0;
issue_load(32'h1000_0004);
check(mem_req, 1'b1, "uncached load forwarded");
check(mem_addr, 32'h1000_0004, "uncached address");
complete_read(32'h0000_0001);
check(read_word, 32'h0000_0001, "uncached read data");
check(access, 1'b0, "uncached access not counted");
check(miss_pulse, 1'b0, "uncached access not missed");

issue_store(32'h1000_0000, 4'b0001, 32'h0000_0041);
check(mem_byte_en, 4'b0001, "uncached byte lane");
```

Then issue the same cacheable address twice and retain the existing miss-then-hit expectations.

- [ ] **Step 2: Run the unit and confirm failure**

Run:

```bash
./tools/run_unit.sh dcache_counter
```

Expected: compile failure because `dcache` has no `cacheable` port.

- [ ] **Step 3: Implement uncached passthrough in `dcache`**

Add `input var logic cacheable`. Define `bypass = state == S_IDLE && req && !cacheable`. While bypassing:

- Drive backing address, byte enables, and write data directly from the CPU side.
- Assert `mem_req` until `mem_ready`.
- Return `mem_read_word` and `mem_ready` directly.
- Keep access/miss pulses low and leave tag/data/victim/dirty arrays unchanged.
- Give an active refill/write-back/flush state priority over any new CPU request.

Add assertions that bypass never writes cache state and that a bypass completion mirrors `mem_ready`.

- [ ] **Step 4: Add the cacheability predicate to the backend**

Add parameters:

```systemverilog
parameter logic [XLEN-1:0] DCACHEABLE_BASE = '0,
parameter logic [XLEN-1:0] DCACHEABLE_MASK = '0
```

Compute:

```systemverilog
logic dmem_cacheable;
assign dmem_cacheable = (DCACHEABLE_MASK == '0) ||
                        ((ex_mem_q.alu_result & DCACHEABLE_MASK) == DCACHEABLE_BASE);
```

Pass it into the D-cache. Propagate the parameters through `rv32i_core`. The compatibility `cpu` leaves the mask at zero. The future SoC sets base `0x2000_0000` and mask `0xFFFF_8000`.

- [ ] **Step 5: Run cache and legacy regressions**

Run:

```bash
./tools/run_unit.sh dcache_counter
make focused-test TEST=t03_memory DC_BYTES=4096 DC_WAYS=4 DC_WB=1 DMEM_LAT=10
make focused-test TEST=t19_dcache_evict DC_BYTES=4096 DC_WAYS=4 DC_WB=1 DMEM_LAT=10
make unit
make lint
```

Expected: uncached transactions bypass and cached behavior remains unchanged.

- [ ] **Step 6: Commit cacheability behavior**

```bash
git add rtl/core/backend.sv rtl/core/rv32i_core.sv rtl/core/cpu.sv \
  rtl/memory/dcache.sv sim/unit/dcache_counter_tb.sv
git diff --cached --check
git commit -m "feat: bypass cache for peripheral accesses"
```

### Task 9: Add the transmit-only UART peripheral

**Files:**
- Create: `rtl/soc/uart_tx.sv`
- Create: `rtl/soc/wb_uart.sv`
- Create: `sim/unit/uart_tx_tb.sv`
- Create: `sim/unit/wb_uart_tb.sv`
- Modify: `tools/run_unit.sh`

**Interfaces:**
- Consumes: Wishbone accesses at offsets `0x0` and `0x4`, `CLOCK_HZ`, and `UART_BAUD`.
- Produces: 8-N-1 `tx`, `TX_READY`, and write backpressure until one byte is accepted.

- [ ] **Step 1: Write failing serializer vectors**

Create `uart_tx_tb.sv` with `CLOCK_HZ=80`, `UART_BAUD=10`, giving eight clocks per bit. Send `8'hA5` and sample the center of each bit. Require:

```text
idle=1, start=0, data=1,0,1,0,0,1,0,1, stop=1, idle=1
```

Attempt a second `valid` while busy and require it is not accepted. Require `ready` returns only after the stop bit completes.

- [ ] **Step 2: Write failing Wishbone-register vectors**

Create `wb_uart_tb.sv`. Check `STATUS[0]`, TXDATA accepting only one low byte, TXDATA withholding ACK while busy, unsupported offsets returning ERR, STATUS writes returning ERR, and reset leaving TX idle high.

- [ ] **Step 3: Run both tests and confirm missing-module failures**

Run:

```bash
./tools/run_unit.sh uart_tx
./tools/run_unit.sh wb_uart
```

Expected: both fail to elaborate.

- [ ] **Step 4: Implement `uart_tx`**

Use parameters and derived divider:

```systemverilog
parameter int CLOCK_HZ = 100_000_000;
parameter int UART_BAUD = 115_200;
localparam int DIVISOR = (CLOCK_HZ + UART_BAUD/2) / UART_BAUD;
```

Shift a ten-bit frame `{1'b1, data[7:0], 1'b0}`. Hold each bit for exactly `DIVISOR` clocks. Accept `valid && ready` once. Elaboration fails when `DIVISOR < 1` or rounded baud error exceeds two percent.

- [ ] **Step 5: Implement `wb_uart`**

Decode word offset zero as TXDATA and offset one as STATUS. A TXDATA write keeps the Wishbone transaction pending until `uart_tx.ready`, then pulses `valid` and ACKs exactly once. STATUS reads ACK with bit 0 equal to ready. All unsupported operations return ERR on the next cycle.

- [ ] **Step 6: Run UART, unit, and lint gates**

Run:

```bash
./tools/run_unit.sh uart_tx
./tools/run_unit.sh wb_uart
make unit
make lint
```

Expected: framing, backpressure, register permissions, and existing tests pass.

- [ ] **Step 7: Commit the UART**

```bash
git add rtl/soc/uart_tx.sv rtl/soc/wb_uart.sv \
  sim/unit/uart_tx_tb.sv sim/unit/wb_uart_tb.sv tools/run_unit.sh
git diff --cached --check
git commit -m "feat: add Wishbone UART transmitter"
```

### Task 10: Add synchronized GPIO interrupts and deterministic reset

**Files:**
- Create: `rtl/soc/button_debounce.sv`
- Create: `rtl/soc/wb_gpio_irq.sv`
- Create: `rtl/soc/reset_controller.sv`
- Create: `sim/unit/button_debounce_tb.sv`
- Create: `sim/unit/wb_gpio_irq_tb.sv`
- Create: `sim/unit/reset_controller_tb.sv`
- Modify: `tools/run_unit.sh`

**Interfaces:**
- Consumes: asynchronous BTN0/BTN1, Wishbone GPIO accesses, and clock/reset.
- Produces: synchronized reset, debounced button state, four LEDs, sticky W1C pending state, and `irq_external`.

- [ ] **Step 1: Write failing debounce vectors**

Instantiate `button_debounce #(.STABLE_CYCLES(4))`. Check two-flop synchronization, alternating bounce for fewer than four stable clocks, one state change after four stable clocks, one-cycle `rise`, stable-high producing no repeated rise, and the same stable interval for release.

- [ ] **Step 2: Write failing GPIO/IRQ vectors**

Create `wb_gpio_irq_tb.sv` and test the exact register offsets:

```systemverilog
wb_write(32'h0, 32'h0000_0005, 4'hf);  // LED
wb_read (32'h0, value); check(value, 32'h5, "LED readback");
wb_read (32'h4, value); check(value[0], button_state, "button read");
wb_write(32'hc, 32'h1, 4'hf);           // IRQ_ENABLE
button_rise = 1'b1; tick(); button_rise = 1'b0;
wb_read (32'h8, value); check(value[0], 1'b1, "pending latched");
check(irq_external, 1'b1, "enabled IRQ");
wb_write(32'h8, 32'h1, 4'hf);           // W1C
check(irq_external, 1'b0, "pending cleared");
```

Drive `button_rise` during the W1C transaction and require set wins. Check writes to BUTTON and unsupported offsets return ERR.

- [ ] **Step 3: Write failing reset-controller vectors**

Instantiate `reset_controller #(.POWER_ON_CYCLES(4))`. Require reset high for the first four clocks, low only on a clock edge, BTN0 asserting reset without waiting for an edge, and deassertion passing through two synchronized clocks.

- [ ] **Step 4: Run all three tests and confirm missing-module failures**

Run:

```bash
./tools/run_unit.sh button_debounce
./tools/run_unit.sh wb_gpio_irq
./tools/run_unit.sh reset_controller
```

Expected: all three fail to elaborate.

- [ ] **Step 5: Implement synchronization and debounce**

Use this contract:

```systemverilog
module button_debounce #(
    parameter int STABLE_CYCLES = 1_000_000
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic async_in,
    output var logic state,
    output var logic rise
);
```

Synchronize through two registers marked `(* ASYNC_REG = "TRUE" *)`. Reset the stability counter whenever synchronized input equals `state`; otherwise count consecutive differing samples and update state at `STABLE_CYCLES`. Compute `rise` only for a low-to-high accepted state change. Reject `STABLE_CYCLES < 1` at elaboration.

- [ ] **Step 6: Implement GPIO and pending behavior**

`wb_gpio_irq` accepts already-debounced `button_state` and `button_rise`. Store `led[3:0]`, `irq_pending`, and `irq_enable`. Use set-over-clear ordering:

```systemverilog
if (button_rise)
    irq_pending <= 1'b1;
else if (pending_w1c)
    irq_pending <= 1'b0;
```

Drive `irq_external = irq_pending && irq_enable`. ACK valid register operations synchronously, honor write lanes containing bit 0, and ERR unsupported or read-only writes.

- [ ] **Step 7: Implement configuration and button reset**

Use a `POWER_ON_CYCLES` counter/shift register initialized asserted for FPGA configuration. BTN0 asynchronously fills the synchronizer with ones; release shifts zeros on `clk100`, so `rst` deasserts synchronously. Add assertions that reset cannot fall between clock edges and remains high for the configured power-on interval.

- [ ] **Step 8: Run focused and aggregate gates**

Run:

```bash
./tools/run_unit.sh button_debounce
./tools/run_unit.sh wb_gpio_irq
./tools/run_unit.sh reset_controller
make unit
make lint
```

Expected: all bounce, W1C, and reset vectors pass.

- [ ] **Step 9: Commit the board-control peripherals**

```bash
git add rtl/soc/button_debounce.sv rtl/soc/wb_gpio_irq.sv rtl/soc/reset_controller.sv \
  sim/unit/button_debounce_tb.sv sim/unit/wb_gpio_irq_tb.sv \
  sim/unit/reset_controller_tb.sv tools/run_unit.sh
git diff --cached --check
git commit -m "feat: add GPIO interrupt and reset control"
```

### Task 11: Integrate the core, bus, memories, and peripherals

**Files:**
- Create: `rtl/soc/rv32i_soc.sv`
- Create: `sim/unit/soc_smoke_tb.sv`
- Create: `sim/fixtures/soc_selfloop.hex`
- Modify: `tools/run_unit.sh`
- Modify: `Makefile`

**Interfaces:**
- Consumes: all RTL modules from Tasks 3–10.
- Produces: a parameterized `rv32i_soc` with clock/reset, button, LED, UART, sticky bus fault, and debug retirement/progress outputs.

- [ ] **Step 1: Write the failing SoC smoke test**

Create `sim/fixtures/soc_selfloop.hex` containing `0000006f`. Instantiate:

```systemverilog
rv32i_soc #(
    .CLOCK_HZ(80), .UART_BAUD(10), .DEBOUNCE_CYCLES(4),
    .ICACHE_BYTES(1024), .ICACHE_BLOCK_WORDS(4), .ICACHE_WAYS(4),
    .DCACHE_BYTES(4096), .DCACHE_BLOCK_WORDS(4), .DCACHE_WAYS(4),
    .DCACHE_WRITE_BACK(1),
    .IMEM_DEPTH_WORDS(16), .DMEM_DEPTH_WORDS(16)
) dut (
    .clk(clk), .rst(rst), .button_irq(button_irq),
    .led(led), .uart_tx(uart_tx), .bus_fault(bus_fault),
    .retired_debug(retired_debug), .progress_debug(progress_debug)
);
```

Pass `+IMEMFILE=sim/fixtures/soc_selfloop.hex`, reset the design, and require UART idle high, LED zero, no sticky fault, instruction-bus activity, and retirement/progress activity within a bounded number of cycles.

- [ ] **Step 2: Run the smoke test and confirm missing-module failure**

Run:

```bash
./tools/run_unit.sh soc_smoke
```

Expected: compile failure because `rv32i_soc` does not exist.

- [ ] **Step 3: Implement `rv32i_soc` parameters and top-level ports**

Use:

```systemverilog
module rv32i_soc #(
    parameter int CLOCK_HZ = 100_000_000,
    parameter int UART_BAUD = 115_200,
    parameter int DEBOUNCE_CYCLES = 1_000_000,
    parameter int ICACHE_BYTES = 1024,
    parameter int ICACHE_BLOCK_WORDS = 4,
    parameter int ICACHE_WAYS = 4,
    parameter int DCACHE_BYTES = 4096,
    parameter int DCACHE_BLOCK_WORDS = 4,
    parameter int DCACHE_WAYS = 4,
    parameter int DCACHE_WRITE_BACK = 1,
    parameter int IMEM_DEPTH_WORDS = 8192,
    parameter int DMEM_DEPTH_WORDS = 8192,
    parameter string IMEM_INIT_FILE = "",
    parameter string DMEM_INIT_FILE = ""
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic button_irq,
    output var logic [3:0] led,
    output var logic uart_tx,
    output var logic bus_fault,
    output var logic retired_debug,
    output var logic [31:0] progress_debug
);
```

Instantiate `rv32i_core` with the approved cache parameters and `DCACHEABLE_BASE=32'h2000_0000`, `DCACHEABLE_MASK=32'hffff_8000`. Tie core `dbg_flush=0`. Feed GPIO IRQ to `irq_external`.

- [ ] **Step 4: Wire adapters, arbitration, interconnect, and slaves**

Use one adapter per external core client. The instruction adapter always supplies `src_wstrb=0`. Connect both adapters to the arbiter, then the arbiter to the interconnect and the four slaves. Connect `button_debounce` to `wb_gpio_irq`; connect GPIO IRQ to the core; connect UART TX to the SoC output.

Connect the arbiter's `s_instr` to the interconnect's `m_instr`. Preserve
`imem_burst` and `dmem_burst` as core outputs for compatibility and debug, but
do not translate them into Wishbone block cycles: each refill or write-back word
must complete as an independent Classic transaction, and an adapter must
deassert its cycle between consecutive words.

Latch `bus_fault` on either adapter fault pulse. Drive:

```systemverilog
assign led = bus_fault ? 4'hf : gpio_led;
assign progress_debug = perf_instr_retired;
```

Add one-hot bus-response assertions and an assertion that any non-data-BRAM data request reaches the backing bus without a D-cache access pulse.

- [ ] **Step 5: Run smoke, units, and core regression**

Run:

```bash
./tools/run_unit.sh soc_smoke
make unit
make focused-test TEST=t01_rtype
make focused-test TEST=t19_dcache_evict IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10
make lint
```

Expected: the integrated SoC fetches without fault and legacy CPU behavior still passes.

- [ ] **Step 6: Commit the integrated RTL**

```bash
git add rtl/soc/rv32i_soc.sv sim/unit/soc_smoke_tb.sv \
  sim/fixtures/soc_selfloop.hex tools/run_unit.sh Makefile
git diff --cached --check
git commit -m "feat: integrate the Wishbone SoC"
```

### Task 12: Build and validate the freestanding firmware image

**Files:**
- Create: `firmware/start.S`
- Create: `firmware/demo.c`
- Create: `firmware/soc.h`
- Create: `firmware/link.ld`
- Create: `tools/soc_image.py`
- Create: `tools/test_soc_image.py`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `.dockerignore`

**Interfaces:**
- Consumes: the approved memory map and pinned RISC-V cross-toolchain.
- Produces: `build/soc/firmware.elf`, `firmware-imem.hex`, `firmware-dmem.hex`, and a deterministic image manifest.

- [ ] **Step 1: Write failing ELF parser/image tests**

In `tools/test_soc_image.py`, construct small ELF32 little-endian fixtures with `struct.pack`. Test:

```python
image = parse_elf(valid_elf)
self.assertEqual(image.entry, 0)
self.assertEqual(image.sections[0].address, 0)
imem, dmem = build_images(image, imem_words=8, dmem_words=8)
self.assertEqual(imem[0], 0x00000013)
self.assertEqual(dmem[0], 0x11223344)
```

Negative fixtures must reject bad magic, ELF64, big-endian, wrong machine, truncated headers, duplicate/overlapping allocated sections, entry outside instruction BRAM, a section crossing a region boundary, allocated content in MMIO/unmapped space, and images exceeding 8192 words.

- [ ] **Step 2: Run the tests and confirm missing-module failure**

Run:

```bash
python3 -m unittest -v tools.test_soc_image
```

Expected: import failure because `tools.soc_image` does not exist.

- [ ] **Step 3: Implement the dependency-free ELF32 reader**

Define:

```python
@dataclass(frozen=True)
class ElfSection:
    name: str
    kind: int
    flags: int
    address: int
    offset: int
    size: int
    data: bytes

@dataclass(frozen=True)
class ElfImage:
    entry: int
    sections: tuple[ElfSection, ...]
```

Implement `parse_elf(path: Path) -> ElfImage`,
`build_images(image: ElfImage, imem_words: int, dmem_words: int) -> tuple[list[int], list[int]]`,
and `write_hex(path: Path, words: list[int]) -> None`. Each validation failure raises
`ImageError` with the input path and violated field. Parse the 52-byte ELF32
header with little-endian `struct`; require `e_machine=243`. Parse section
headers and the section-name table, retain `SHF_ALLOC` sections, ignore bounded
`SHT_NOBITS` content while reserving its range, and place bytes only within
instruction or data BRAM. Emit exactly 8192 lowercase eight-hex-digit words per
image using an atomic replace.

The image manifest uses this exact shape so later synthesis/evidence tasks do
not infer filenames or hashes:

```python
{
    "schema": 1,
    "status": "complete",
    "entry": image.entry,
    "elf": {"path": str(elf), "sha256": sha256(elf)},
    "imem": {"path": str(imem), "words": 8192, "sha256": sha256(imem)},
    "dmem": {"path": str(dmem), "words": 8192, "sha256": sha256(dmem)},
}
```

Reject unknown/duplicate fields when the manifest is read back, and validate
all three hashes before returning success.

- [ ] **Step 4: Write the MMIO and CSR firmware header**

`firmware/soc.h` defines volatile 32-bit registers at the approved addresses, `MSTATUS_MIE=(1u<<3)`, `MIE_MEIE=(1u<<11)`, interrupt cause 11, and inline `csrr/csrw/csrsi` helpers. It exposes:

```c
void uart_putc(char value);
void uart_puts(const char *text);
void trap_handler_c(uint32_t cause);
```

- [ ] **Step 5: Implement startup and trap entry**

`firmware/start.S` loads `sp=0x20008000`, clears `__bss_start` through `__bss_end`, writes `mtvec=trap_entry`, and calls `main`. `trap_entry` allocates a 64-byte 16-byte-aligned frame, saves every caller-saved register it uses (`ra`, `t0–t6`, `a0–a7`), reads `mcause` into `a0`, calls `trap_handler_c`, restores registers, and executes `mret`. A returned `main` enters a self-loop after setting LED to `0xf`.

- [ ] **Step 6: Implement the demo firmware**

`firmware/demo.c` polls `UART_STATUS.TX_READY` and writes bytes to TXDATA. `main` clears pending, initializes LED to one, enables the peripheral, enables `mie.MEIE`, sets global MIE, prints `rv32i soc ready\n`, and increments a volatile main-loop progress word forever.

`trap_handler_c` verifies `(cause & 0x8000000f) == 0x8000000b`. On success it writes one to `IRQ_PENDING`, rotates the low four LED bits, increments an IRQ count, and prints `external irq\n`. Otherwise it disables global interrupts, writes LED `0xf`, prints `unexpected trap\n`, and loops.

- [ ] **Step 7: Add the linker script and Make target**

`firmware/link.ld` defines:

```ld
MEMORY {
  IMEM (rx)  : ORIGIN = 0x00000000, LENGTH = 32K
  DMEM (rwx) : ORIGIN = 0x20000000, LENGTH = 32K
}
```

Place `.text.init`, `.text`, and `.rodata` in IMEM; place `.data` and `.bss` in DMEM; define BSS bounds and `__stack_top=ORIGIN(DMEM)+LENGTH(DMEM)`; assert every section and stack remain in range.

Add `make soc-firmware` using:

```make
riscv64-unknown-elf-gcc -march=rv32i_zicsr_zifencei -mabi=ilp32 \
  -nostdlib -ffreestanding -fno-builtin -fno-pic -mno-relax -Os \
  -ffunction-sections -fdata-sections -msmall-data-limit=0 \
  -Wl,-T,firmware/link.ld -Wl,--gc-sections -Wl,--build-id=none -Wl,--no-relax \
  -o build/soc/firmware.elf firmware/start.S firmware/demo.c
python3 tools/soc_image.py --elf build/soc/firmware.elf \
  --imem build/soc/firmware-imem.hex --dmem build/soc/firmware-dmem.hex \
  --manifest build/soc/firmware-images.json
```

- [ ] **Step 8: Verify deterministic firmware outputs**

Run:

```bash
python3 -m unittest -v tools.test_soc_image
make soc-firmware
sha256sum build/soc/firmware.elf build/soc/firmware-imem.hex build/soc/firmware-dmem.hex
cp build/soc/firmware-images.json /tmp/rv32i-soc-images-first.json
make -B soc-firmware
cmp /tmp/rv32i-soc-images-first.json build/soc/firmware-images.json
if riscv64-unknown-elf-objdump -d build/soc/firmware.elf | \
    rg -q '\b(mul|div|rem|amo|wfi)\b'; then
  echo "unsupported instruction found in firmware" >&2
  exit 1
fi
```

Expected: tests pass, image manifest is reproducible, and disassembly contains no unsupported instruction.

- [ ] **Step 9: Commit firmware sources and tooling only**

```bash
git add firmware tools/soc_image.py tools/test_soc_image.py Makefile .gitignore .dockerignore
git diff --cached --check
git commit -m "feat: build board demo firmware"
```

Confirm `git status --short` does not list any generated file.

### Task 13: Verify the exact firmware on the integrated SoC

**Files:**
- Create: `sim/soc_tb.cpp`
- Modify: `Makefile`
- Modify: `tools/verification.py`
- Modify: `tools/test_verification.py`

**Interfaces:**
- Consumes: `rv32i_soc`, the exact images from Task 12, UART TX, button input, LED output, bus fault, and progress count.
- Produces: `make soc-sim` and the integration portion of `make soc-check`.

- [ ] **Step 1: Write the failing Verilator integration harness**

Implement `sim/soc_tb.cpp` with these explicit states:

```cpp
enum class DemoState {
    WaitBoot,
    BouncePress,
    StablePress1,
    WaitIrq1,
    StableRelease,
    StablePress2,
    WaitIrq2,
    Complete,
};
```

Add a UART decoder that detects a high-to-low start edge, samples at half a bit then every configured divisor, reconstructs eight LSB-first bits, and requires a high stop bit. Accumulate complete lines only.

The state machine must require:

```text
rv32i soc ready\n
external irq\n
external irq\n
```

It must inject sub-debounce bounce, confirm no line/LED change, issue two stable press/release cycles, require exactly two LED transitions, and require `progress_debug` increases after each interrupt. Exit nonzero immediately on `bus_fault`, UART framing error, duplicate line, wrong line, or cycle deadline.

- [ ] **Step 2: Add the failing `soc-sim` target**

Build `rv32i_soc` with all `rtl/**/*.sv`, `--assert --timing`, and these simulation overrides:

```text
CLOCK_HZ=80
UART_BAUD=10
DEBOUNCE_CYCLES=4
IMEM_DEPTH_WORDS=8192
DMEM_DEPTH_WORDS=8192
```

Run with `+IMEMFILE=build/soc/firmware-imem.hex` and `+DMEMFILE=build/soc/firmware-dmem.hex`. Make `soc-sim` depend on `soc-firmware`.

- [ ] **Step 3: Run and confirm the integration test fails before target/wiring completion**

Run:

```bash
make soc-sim
```

Expected: compile or runtime failure identifying the first missing port/build contract; it must not report success by timeout or output prefix.

- [ ] **Step 4: Complete the build and simulation-only observability wiring**

Expose only `retired_debug` and `progress_debug` from `rv32i_soc`; do not add board pins for them. Ensure the memory slaves consume plusargs in simulation and fixed initialization parameters in synthesis. Set a cycle deadline large enough for three complete UART lines at the simulation divisor, then make the bound explicit in the C++ source.

- [ ] **Step 5: Add SoC verification profile contracts**

Add `soc` to `tools/verification.py` as an explicit profile invoking `make soc-check`. Extend `tools/test_verification.py` to require the command, timeout propagation, repository working directory, and container target. Define:

```make
SOC_UNIT_NAMES := core_external csr_external_irq wb_master_adapter wb_arbiter \
  wb_interconnect wb_memory dcache_counter uart_tx wb_uart button_debounce \
  wb_gpio_irq reset_controller soc_smoke

soc-unit:
	@for name in $(SOC_UNIT_NAMES); do ./tools/run_unit.sh "$$name"; done

soc-lint:
	verilator --lint-only --timing -Wall -Wno-fatal --top-module rv32i_soc \
	  rtl/rv32i_pkg.sv rtl/core/*.sv rtl/memory/*.sv rtl/bus/*.sv rtl/soc/*.sv

soc-check: soc-unit soc-firmware soc-sim soc-lint
```

At this checkpoint, `soc-lint` targets `rv32i_soc`; Task 14 adds the board top.
Add `soc-unit` and `soc-sim` as prerequisites of `check`; `soc-sim` already
depends on `soc-firmware`, so the fast gate executes the exact image.

- [ ] **Step 6: Run the integration and existing fast gates**

Run:

```bash
make soc-sim
make soc-check
make check
```

Expected: exact UART/IRQ/LED/progress sequence passes and all existing fast gates stay green.

- [ ] **Step 7: Commit the integration harness**

```bash
git add sim/soc_tb.cpp Makefile tools/verification.py tools/test_verification.py
git diff --cached --check
git commit -m "test: verify firmware on the integrated SoC"
```

### Task 14: Add the Arty A7 board top and guarded Vivado flow

**Files:**
- Create: `rtl/boards/arty_a7_35t_top.sv`
- Create: `boards/arty_a7_35t.xdc`
- Create: `synthesis/soc/build.tcl`
- Create: `synthesis/soc/program.tcl`
- Create: `synthesis/soc/run_board.py`
- Create: `synthesis/soc/test_board_tools.py`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `.dockerignore`

**Interfaces:**
- Consumes: `rv32i_soc`, the two 8192-word firmware images, Vivado 2025.2 discovery helpers in `synthesis.run_synth`, and the approved Arty pin map.
- Produces: `arty_a7_35t_top`, an isolated `make soc-bitstream` route, validated reports/manifest/bitstream under `build/soc/board`, and an explicit `make soc-program` command.

- [ ] **Step 1: Write failing board-contract tests**

In `synthesis/soc/test_board_tools.py`, parse `boards/arty_a7_35t.xdc` and require this exact map:

```python
EXPECTED_PINS = {
    "clk100": "E3",
    "btn[0]": "D9",
    "btn[1]": "C9",
    "led[0]": "H5",
    "led[1]": "J5",
    "led[2]": "T9",
    "led[3]": "T10",
    "uart_tx": "D10",
}
```

Require one `create_clock -period 10.000`, `IOSTANDARD LVCMOS33` on every port,
no extra constrained ports, the part `xc7a35ticsg324-1L`, and the pinned Digilent
source SHA in the file header. Add a source test that `arty_a7_35t_top` has only
`clk100`, `btn[1:0]`, `led[3:0]`, and `uart_tx` as top-level ports.

- [ ] **Step 2: Run the contract test and confirm missing-file failures**

Run:

```bash
python3 -m unittest -v synthesis.soc.test_board_tools
```

Expected: failures identify the absent board top, constraints, and runner.

- [ ] **Step 3: Implement the board-only wrapper**

Use this exact boundary:

```systemverilog
module arty_a7_35t_top #(
    parameter string IMEM_INIT_FILE = "firmware-imem.hex",
    parameter string DMEM_INIT_FILE = "firmware-dmem.hex"
) (
    input  var logic       clk100,
    input  var logic [1:0] btn,
    output var logic [3:0] led,
    output var logic       uart_tx
);
```

Instantiate `reset_controller #(.POWER_ON_CYCLES(16))` with `btn[0]`, then
instantiate `rv32i_soc` with `CLOCK_HZ=100_000_000`, `UART_BAUD=115_200`,
`DEBOUNCE_CYCLES=1_000_000`, the approved 1 KiB four-way I-cache, 4 KiB
four-way write-back D-cache, 8192-word memories, and synthesis initialization
parameters `IMEM_INIT_FILE` and `DMEM_INIT_FILE`. Connect `btn[1]` only to
`button_irq`; leave simulation-only debug outputs on internal wires. Parameters
may change initialization filenames but never board clock/cache/debounce values.

- [ ] **Step 4: Add the exact physical constraints**

Write `boards/arty_a7_35t.xdc` with the pinned-source comment and these commands:

```tcl
set_property -dict {PACKAGE_PIN E3 IOSTANDARD LVCMOS33} [get_ports clk100]
create_clock -period 10.000 -name clk100 [get_ports clk100]
set_property -dict {PACKAGE_PIN D9 IOSTANDARD LVCMOS33} [get_ports {btn[0]}]
set_property -dict {PACKAGE_PIN C9 IOSTANDARD LVCMOS33} [get_ports {btn[1]}]
set_property -dict {PACKAGE_PIN H5 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN J5 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN T9 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
set_property -dict {PACKAGE_PIN D10 IOSTANDARD LVCMOS33} [get_ports uart_tx]
```

- [ ] **Step 5: Write the batch synthesis and implementation script**

`synthesis/soc/build.tcl` accepts exactly `output_dir`, `imem_file`, and
`dmem_file`. It must execute:

```tcl
create_project -in_memory -part xc7a35ticsg324-1L
read_verilog -sv rtl/rv32i_pkg.sv
read_verilog -sv [concat [glob rtl/core/*.sv] [glob rtl/memory/*.sv] \
    [glob rtl/bus/*.sv] [glob rtl/soc/*.sv] [glob rtl/boards/*.sv]]
read_xdc boards/arty_a7_35t.xdc
synth_design -top arty_a7_35t_top -part xc7a35ticsg324-1L \
    -verilog_define SYNTHESIS \
    -generic IMEM_INIT_FILE=$imem_file -generic DMEM_INIT_FILE=$dmem_file
opt_design
place_design
route_design
report_utilization -file "$output_dir/utilization.rpt"
report_timing_summary -delay_type min_max -report_unconstrained \
    -file "$output_dir/timing_summary.rpt"
report_drc -file "$output_dir/drc.rpt"
write_bitstream -force "$output_dir/rv32i-soc-arty-a7-35t.bit"
```

Fail unless exactly one `clk100` clock has period 10 ns, the timing summary
contains no unconstrained endpoints, the worst setup-path WNS is nonnegative,
and DRC contains no critical warning or error. Write `build_meta.txt` containing
only `part`, `clock_period_ns`, `wns_ns`, and `top`, then print
`===SOC_BUILD_DONE===`.

- [ ] **Step 6: Write the guarded programming script**

`synthesis/soc/program.tcl` accepts one absolute bitstream path, opens hardware
manager, connects and opens the target, selects exactly one device whose `PART`
equals the JTAG-visible die `xc7a35t`, assigns `PROGRAM.FILE`, programs it,
verifies `REGISTER.IR.BIT5_DONE=1`, prints `===SOC_PROGRAM_DONE===`, and closes
hardware manager. The build separately requires the full
`xc7a35ticsg324-1L` part. Zero, multiple, or wrong-die devices are fatal.

- [ ] **Step 7: Add failing fake-Vivado wrapper tests**

Build a temporary fake launcher following `synthesis/test_synth_tools.py`. Test
that `run_board.py`:

- honors an explicit `VIVADO` path and rejects a missing override;
- requires Vivado `2025.2` and the exact part and 10 ns period;
- validates both memory images as exactly 8192 lowercase 32-bit words;
- stages RTL, XDC, Tcl, and firmware in a private native or Windows-temp directory;
- rejects nonzero exit, timeout, missing completion marker, missing/stale bitstream, missing/stale reports, negative WNS, wrong part, wrong period, and dirty tracked source;
- atomically replaces `build/soc/board` only after every artifact passes;
- copies only `manifest.json`, `utilization.rpt`, `timing_summary.rpt`, `drc.rpt`, and `rv32i-soc-arty-a7-35t.bit`.

Run:

```bash
python3 -m unittest -v synthesis.soc.test_board_tools
```

Expected: wrapper tests fail because `run_board.py` does not exist.

- [ ] **Step 8: Implement the isolated board runner**

Import `VivadoTool`, `discover_tool`, `source_identity`, `command_output`, and
`sha256` from `synthesis.run_synth`. Define:

```python
PART = "xc7a35ticsg324-1L"
PERIOD_NS = 10.0
IMAGE_WORDS = 8192

@dataclass(frozen=True)
class BoardArtifacts:
    bitstream: Path
    utilization: Path
    timing: Path
    drc: Path
    metadata: Path
```

Implement `validate_firmware_image(path: Path) -> str`, returning SHA-256 only
after validating exactly `IMAGE_WORDS` canonical words. Implement
`create_board_stage(root: Path, parent: Path | None, imem: Path, dmem: Path) -> tempfile.TemporaryDirectory[str]`,
copying only required build inputs. Implement
`run_build(root: Path, output: Path, imem: Path, dmem: Path, rtl_commit: str | None, timeout: int) -> None`.

Use `source_identity` before creating the stage. Record source/RTL commits, UTC
measurement time, firmware hashes, XDC SHA, Vivado version/build/platform,
invocation, part, period, WNS, and output hashes in `manifest.json`. On any
exception, remove the private output and leave the previous destination unchanged.

Add `build` and `program` subcommands. `program` requires an explicit existing
`.bit`, runs only `program.tcl`, and propagates timeout, return code, marker, and
device-part failures.

- [ ] **Step 9: Add Make targets and ignore rules**

Define:

```make
SOC_BUILD_DIR ?= build/soc
SOC_BOARD_DIR ?= $(SOC_BUILD_DIR)/board
SOC_BITSTREAM ?= $(SOC_BOARD_DIR)/rv32i-soc-arty-a7-35t.bit

soc-bitstream: soc-firmware
	VIVADO="$(VIVADO)" python3 -m synthesis.soc.run_board build \
	  --imem "$(SOC_BUILD_DIR)/firmware-imem.hex" \
	  --dmem "$(SOC_BUILD_DIR)/firmware-dmem.hex" \
	  --output "$(SOC_BOARD_DIR)" --rtl-commit "$(RTL_COMMIT)"

soc-program:
	VIVADO="$(VIVADO)" python3 -m synthesis.soc.run_board program \
	  --bitstream "$(SOC_BITSTREAM)"
```

Add `build/`, `synthesis/soc/out_*`, and `.soc-board-*` to both ignore files.
Do not ignore source files under `synthesis/soc/` or `boards/`.

Extend `soc-lint` with a second Verilator invocation whose top is
`arty_a7_35t_top` and whose source list adds `rtl/boards/*.sv`. Keep the existing
`rv32i_soc` lint invocation so both public integration boundaries are checked.

- [ ] **Step 10: Run board-contract tests and synthesis lint**

Run:

```bash
python3 -m unittest -v synthesis.soc.test_board_tools
make soc-lint
make soc-check
```

Expected: fake-tool failures are caught, both top levels lint, and the
open-source SoC regression passes. Do not claim a routed bitstream from
fake-Vivado tests.

- [ ] **Step 11: Commit the board build flow**

```bash
git add rtl/boards/arty_a7_35t_top.sv boards/arty_a7_35t.xdc \
  synthesis/soc Makefile .gitignore .dockerignore
git diff --cached --check
git commit -m "build: add Arty A7 bitstream flow"
```

### Task 15: Integrate SoC verification, pin metadata, and evidence validation

**Files:**
- Modify: `tools/reference_versions.env`
- Modify: `tools/evidence_check.py`
- Modify: `tools/test_evidence_check.py`
- Modify: `tools/results.py`
- Modify: `tools/test_results.py`
- Modify: `tools/render_portfolio.py`
- Modify: `tools/test_render_portfolio.py`
- Modify: `tools/verification.py`
- Modify: `tools/test_verification.py`
- Modify: `.github/workflows/rtl-tests.yml`
- Modify: `results/FORMAT.md`

**Interfaces:**
- Consumes: the exact Digilent XDC SHA, `make soc-check`, the existing workflow parser, result validation, and marker-based portfolio renderer.
- Produces: PR/push coverage for every SoC input, a pinned `DIGILENT_XDC_SHA`, a `soc` verification profile, strict optional physical-board evidence validation, and `collect-soc`.

- [ ] **Step 1: Write failing metadata and workflow tests**

Extend `APPROVED_REFERENCES` with:

```python
"DIGILENT_XDC_SHA": "00a3404901f35aa9567b01ecb3f2c233b6efe9f4"
```

Require missing, malformed, duplicate, uppercase, or unknown XDC pins to fail.
Add `SOC_PATHS = ("firmware/**", "boards/**", "synthesis/soc/**")` and require
those paths on both `push` and `pull_request` in `rtl-tests.yml`; do not add
them to compliance/lockstep because those flows consume the legacy CPU image,
not SoC firmware or board constraints. Require the RTL workflow step:

```yaml
- name: Verify integrated SoC
  run: python3 tools/verification.py container --profile soc
```

- [ ] **Step 2: Write failing optional SoC-result tests**

In `tools/test_results.py`, construct `results/soc.json` fixtures and require
exact fields:

```python
SOC_FIELDS = {
    "schema", "measured_at", "tooling_commit", "rtl_commit",
    "board", "part", "digilent_xdc_sha", "firmware_sha256",
    "bitstream_sha256", "vivado", "route", "verification",
    "uart", "manual_observations",
}
```

Reject duplicate/unknown/missing fields, invalid commits/hashes/timestamps,
wrong board/part/XDC SHA, non-2025.2 Vivado, non-10 ns constraint, negative WNS,
incomplete verification, any UART line sequence other than `rv32i soc ready`,
`external irq`, `external irq`, or anything other than two button events and
two LED transitions. When the file is absent, validation remains green and the
renderer must say `Physical-board evidence: not published`; it must not render
any board-success or utilization number.

Require these exact nested fields:

```python
SOC_FIRMWARE_FIELDS = {"elf", "imem", "dmem"}
SOC_VIVADO_FIELDS = {"version", "build", "platform"}
SOC_ROUTE_FIELDS = {
    "clock_period_ns", "wns_ns", "critical_path_ns", "fmax_mhz",
    "lut", "ff", "bram_tiles", "timing_sha256",
    "utilization_sha256", "drc_sha256",
}
SOC_VERIFICATION_FIELDS = {
    "full_status", "soc_status", "full_receipt_sha256", "soc_receipt_sha256",
}
SOC_UART_FIELDS = {"transcript_sha256", "lines"}
SOC_OBSERVATION_FIELDS = {
    "reset_banner", "button_presses", "led_transitions", "release_transitions",
}
SOC_RECEIPT_FIELDS = {
    "schema", "measured_at", "profile", "status", "tooling_commit",
    "rtl_commit", "commands",
}
```

- [ ] **Step 3: Write failing collection tests**

Create fixture board/firmware manifests, a verification receipt, UART transcript,
and observations record under a temporary directory. Invoke:

```python
status = results.main([
    "collect-soc",
    "--board-manifest", str(board_manifest),
    "--firmware-manifest", str(firmware_manifest),
    "--verification", str(full_receipt),
    "--soc-verification", str(soc_receipt),
    "--uart", str(uart),
    "--observations", str(observations),
    "--output", str(output),
])
self.assertEqual(status, 0)
self.assertEqual(json.loads(output.read_text())["uart"]["lines"], [
    "rv32i soc ready", "external irq", "external irq",
])
```

Negative fixtures must reject missing/tampered inputs, mismatched source or RTL
commits, stale or failed build status, wrong part/period/version/XDC pin, negative
WNS, failed verification, malformed/duplicate UART output, incorrect manual
event counts, and a destination inside the raw report directory.

- [ ] **Step 4: Run focused tests and confirm contract failures**

Run:

```bash
python3 -m unittest -v tools.test_evidence_check tools.test_results \
  tools.test_render_portfolio tools.test_verification
```

Expected: failures identify the missing pin, missing workflow paths/step,
unknown result schema, absent collector, and absent rendering behavior.

- [ ] **Step 5: Pin and validate the Digilent source**

Add exactly:

```text
DIGILENT_XDC_SHA=00a3404901f35aa9567b01ecb3f2c233b6efe9f4
```

Extend `REFERENCE_KEYS`, `parse_reference_versions`, and fixture writers to
require a lowercase 40-hex value. Add a checker that reads the single source
line in `boards/arty_a7_35t.xdc`, extracts the commit segment from the official
GitHub URL, and requires it equals `DIGILENT_XDC_SHA`. Keep architecture-test
and Spike workflow outputs unchanged.

- [ ] **Step 6: Implement optional SoC evidence validation**

Define:

```python
def validate_soc_result(root: Path, checkout: Path) -> list[str]:
    path = root / "soc.json"
    if not path.exists():
        return []
    value = load_json(path)
    errors: list[str] = []
    exact_fields(value, SOC_FIELDS, "soc result", errors)
    validate_soc_fields(value, checkout, errors)
    return errors
```

`validate_soc_fields` must call `require_timestamp`, `require_sha`,
`require_hash`, `require_decimal`, and `require_uint` for every matching field.
Require both commits to exist. Require `rtl_commit` to be an ancestor of
`tooling_commit` and `git diff --quiet <rtl_commit> <tooling_commit> -- rtl` to
pass. Keep this SoC provenance independent from the older CPU-only result set,
which remains labeled with its own commits. Call this validator from
`validate_result_set` after existing records validate. Add a
`soc_status(result_root)` renderer helper that returns either the pending
sentence or a table derived solely from validated `soc.json` fields.

Retain Task 2's commit-aware assertion/cover comparison. Add negative tests in
which a final-current full record omits one new SVA or cover, and require the
manifest cover-point population to equal the full verification record.

- [ ] **Step 7: Implement `collect-soc` without numeric overrides**

Add the fixed CLI:

```text
tools/results.py collect-soc
  --board-manifest PATH
  --firmware-manifest PATH
  --verification PATH
  --soc-verification PATH
  --uart PATH
  --observations PATH
  --output PATH
```

The collector reads part, clock, WNS, utilization, Vivado identity, commits,
artifact paths, and hashes from the validated manifests/reports. It accepts no
CLI option for a measured number. It requires complete `full` and `soc` receipts,
hashes the firmware, bitstream, and UART transcript itself, normalizes only CRLF
to LF, requires the exact three lines, validates two presses/two LED transitions,
writes through a sibling temporary file, calls `validate_soc_result`, and then
atomically replaces the output.

- [ ] **Step 8: Add the SoC workflow surface**

Add the three SoC path patterns to both RTL workflow trigger lists and add the
containerized `soc` profile step. Extend `tools/verification.py` profile tests so
`soc` resolves to exactly `make soc-check`, uses the repository working directory,
propagates a nonzero status, and has an explicit timeout. Permit receipts
for `full` and `soc`. Keep the existing detailed full receipt. Add
`write_profile_receipt` for `soc` using `SOC_RECEIPT_FIELDS`, `profile="soc"`,
`status="complete"`, the exact `make soc-check` command, and current source/RTL
commits; it must not copy full-suite counts from a previous coverage database.
Test that a failed command removes any stale receipt. Keep Vivado out of GitHub
Actions.

- [ ] **Step 9: Run contract and fast verification**

Run:

```bash
python3 -m unittest -v tools.test_evidence_check tools.test_results \
  tools.test_render_portfolio tools.test_verification
make evidence-check
make portfolio-render-check
make soc-check
```

Expected: all metadata, result, render, workflow, and SoC checks pass with the
honest `not published` board state.

- [ ] **Step 10: Commit reproducibility contracts**

```bash
git add tools/reference_versions.env tools/evidence_check.py \
  tools/test_evidence_check.py tools/results.py tools/test_results.py \
  tools/render_portfolio.py tools/test_render_portfolio.py \
  tools/verification.py tools/test_verification.py \
  .github/workflows/rtl-tests.yml results/FORMAT.md
git diff --cached --check
git commit -m "ci: verify SoC integration changes"
```

### Task 16: Document the system and prove the regression baseline is preserved

**Files:**
- Create: `docs/soc.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/verification.md`
- Modify: `docs/evidence.md`
- Modify: `docs/coverage.md`
- Modify: `tools/render_portfolio.py`
- Modify: `tools/test_render_portfolio.py`

**Interfaces:**
- Consumes: implemented SoC interfaces, generated Make targets, the pre-change baseline log, and validated result records.
- Produces: a concise recruiter-facing SoC summary, a complete engineering guide, explicit limitations, and a same-gate before/after comparison.

- [ ] **Step 1: Add failing documentation contracts**

Extend renderer/document tests to require:

- README links to `docs/soc.md`, labels the terminal GIF as a verification workflow, and contains the validated physical-board evidence state.
- `docs/soc.md` contains the exact memory-map ranges, UART/GPIO offsets, cacheability rule, `make soc-check`, `make soc-bitstream`, `make soc-program`, serial setting `115200 8-N-1`, BTN0 reset, BTN1 interrupt, and failure semantics.
- `docs/architecture.md` distinguishes `cpu`, `rv32i_core`, `rv32i_soc`, and `arty_a7_35t_top`.
- `docs/verification.md` names every new unit and the complete three-line firmware-integration expectation.
- `docs/evidence.md` refuses physical-board wording when `results/soc.json` is absent.

- [ ] **Step 2: Run documentation tests and confirm failure**

Run:

```bash
python3 -m unittest -v tools.test_render_portfolio
python3 tools/render_portfolio.py --check
```

Expected: failures list the absent SoC guide and marker content.

- [ ] **Step 3: Write the SoC engineering guide**

Structure `docs/soc.md` in this order:

```text
Board and observable demo
System hierarchy
Core memory-client contract
Wishbone transaction contract
Memory map and register tables
Cacheability and MMIO ordering
External-interrupt flow and priority
Firmware build and image validation
Verilator integration procedure
Vivado build and programming procedure
Manual reset/button/UART checklist
Fault behavior
Known limitations
Evidence provenance
```

Use the exact addresses and parameters from the approved design. State that bus
errors are sticky integration faults and are not architectural access-fault
traps. State that UART is transmit-only and the design has no bootloader,
external memory, PLIC, or operating system. Do not claim the board ran until
validated evidence exists.

- [ ] **Step 4: Update recruiter-facing and engineering documents**

Keep README concise: add one `Board-ready SoC` paragraph, one command block with
`make soc-check` and `make soc-bitstream`, and a link to the full guide. Do not
duplicate register tables or insert unmeasured CPI, fmax, utilization,
prediction, or pass-rate values. Update architecture and verification details at
their existing generated/manual boundaries. Render the evidence state through
`tools/render_portfolio.py`; do not hand-edit a generated result block.

- [ ] **Step 5: Run the full post-change regression**

Run and retain the log outside the repository:

```bash
mkdir -p /home/huy/.cache/rv32i-soc-20260829
make verify 2>&1 | tee /home/huy/.cache/rv32i-soc-20260829/final-verify.log
make soc-check 2>&1 | tee /home/huy/.cache/rv32i-soc-20260829/final-soc-check.log
make portfolio-render
make portfolio-check
make portfolio-render-check
make evidence-check
```

Compare the exact named milestones captured in Task 1. Decoder, hazard, harness,
directed-memory, predictor, architecture-test, lockstep, random, assertion, and
cover counts must be equal; any missing milestone or regression blocks the
commit. New SoC gates are additive and must all report success.

- [ ] **Step 6: Verify deterministic firmware and repository hygiene**

Run:

```bash
make soc-firmware
sha256sum build/soc/firmware.elf build/soc/firmware-imem.hex \
  build/soc/firmware-dmem.hex > /tmp/rv32i-soc-firmware-first.sha256
make -B soc-firmware
sha256sum build/soc/firmware.elf build/soc/firmware-imem.hex \
  build/soc/firmware-dmem.hex > /tmp/rv32i-soc-firmware-second.sha256
diff -u /tmp/rv32i-soc-firmware-first.sha256 \
  /tmp/rv32i-soc-firmware-second.sha256
git status --short
```

Expected: hashes match and generated firmware/build products do not appear in
Git status.

- [ ] **Step 7: Commit the documentation**

```bash
git add README.md docs/soc.md docs/architecture.md docs/verification.md \
  docs/evidence.md docs/coverage.md tools/render_portfolio.py \
  tools/test_render_portfolio.py
git diff --cached --check
git commit -m "docs: explain the board-ready SoC"
```

### Task 17: Route, validate hardware, and publish only measured evidence

**Files:**
- Create after successful hardware validation: `results/soc.json`
- Modify after successful hardware validation: `README.md`
- Modify after successful hardware validation: `docs/evidence.md`
- Modify after successful hardware validation: `results/FORMAT.md`

**Interfaces:**
- Consumes: a clean committed checkout, the final RTL commit, Vivado 2025.2, an Arty A7-35T, and the generated firmware images.
- Produces: one validated physical-board evidence record and rendered documentation; release/video publication remains a separate user-approved action.

- [ ] **Step 1: Freeze and record source identities before measurement**

Run:

```bash
test -z "$(git status --porcelain --untracked-files=normal)"
SOC_SOURCE_COMMIT=$(git rev-parse HEAD)
SOC_RTL_COMMIT=$(git log -1 --format=%H -- rtl)
git diff --quiet "$SOC_RTL_COMMIT" "$SOC_SOURCE_COMMIT" -- rtl
printf '%s\n' "$SOC_SOURCE_COMMIT" > /home/huy/.cache/rv32i-soc-20260829/source-commit.txt
printf '%s\n' "$SOC_RTL_COMMIT" > /home/huy/.cache/rv32i-soc-20260829/rtl-commit.txt
```

Expected: clean checkout and no RTL difference between the recorded RTL and
source commits. If either test fails, commit the legitimate source change and
rerun all Task 16 gates before measuring.

- [ ] **Step 2: Generate fresh verification receipts**

Run:

```bash
python3 tools/verification.py container --profile full \
  --receipt .portfolio-runs/soc-final-verification.json
python3 tools/verification.py container --profile soc \
  --receipt .portfolio-runs/soc-final-soc.json
make portfolio-render
test -z "$(git status --porcelain --untracked-files=normal)"
```

Expected: both exit zero. The receipt and logs remain ignored measurement
inputs, not committed evidence by themselves. Re-rendering restores the
committed historical coverage label after the fresh coverage command, leaving
the tracked checkout clean for synthesis; the new receipt remains in the
ignored run directory until publication.

- [ ] **Step 3: Remeasure the four benchmark configurations**

Use the same source and RTL commits for every row:

```bash
mkdir -p .portfolio-runs/current/benchmarks
cp .portfolio-runs/soc-final-verification.json \
  .portfolio-runs/current/verification.json
make bench IMEM_LAT=10 DMEM_LAT=10 BENCH_CONFIG=slow-memory \
  BENCH_CSV=.portfolio-runs/current/benchmarks/slow-memory.csv
make bench IMEM_LAT=10 DMEM_LAT=10 IC_BYTES=1024 IC_WAYS=4 \
  BENCH_CONFIG=icache \
  BENCH_CSV=.portfolio-runs/current/benchmarks/icache.csv
make bench IMEM_LAT=10 DMEM_LAT=10 IC_BYTES=1024 IC_WAYS=4 \
  DC_BYTES=4096 DC_WAYS=4 DC_WB=1 BENCH_CONFIG=write-back \
  BENCH_CSV=.portfolio-runs/current/benchmarks/write-back.csv
make bench BENCH_CONFIG=ideal-memory \
  BENCH_CSV=.portfolio-runs/current/benchmarks/ideal-memory.csv
```

Expected: all five kernels pass their host oracle in all four configurations,
each CSV contains exactly five rows, and the tooling/RTL commit fields match the
identities from Step 1. Do not copy a previous benchmark row.

- [ ] **Step 4: Reroute the four CPU evidence configurations**

Run:

```bash
SOC_RTL_COMMIT=$(cat /home/huy/.cache/rv32i-soc-20260829/rtl-commit.txt)
make synth-matrix RTL_COMMIT="$SOC_RTL_COMMIT"
make synth-summary
make results-synth RESULT_RUN_DIR=.portfolio-runs/current
VERIFY_IMAGE=$(sed -n 's/^VERIFY_IMAGE=//p' tools/tool_versions.env)
VERIFY_REVISION=$(sed -n 's/^VERIFY_IMAGE_REVISION=//p' tools/tool_versions.env)
CONTAINER_DIGEST=$(docker image inspect --format '{{.Id}}' \
  "$VERIFY_IMAGE:$VERIFY_REVISION")
VIVADO_BUILD=$(python3 -c 'import json; print(json.load(open("synthesis/reports/core/manifest.json"))["tool_build"])')
VIVADO_PLATFORM=$(python3 -c 'import json; print(json.load(open("synthesis/reports/core/manifest.json"))["platform"])')
python3 tools/results.py tool-versions \
  --output .portfolio-runs/current/tool_versions.json \
  --rtl-commit "$SOC_RTL_COMMIT" --vivado-build "$VIVADO_BUILD" \
  --vivado-platform "$VIVADO_PLATFORM" --container-digest "$CONTAINER_DIGEST"
```

Expected: four fresh route manifests share the current source/RTL commits and
Vivado identity; tool versions are derived from the built image and manifests.
Do not reuse the previous synthesis CSV or type a measurement by hand.

- [ ] **Step 5: Route the exact committed RTL and firmware**

Run:

```bash
SOC_RTL_COMMIT=$(cat /home/huy/.cache/rv32i-soc-20260829/rtl-commit.txt)
make soc-bitstream RTL_COMMIT="$SOC_RTL_COMMIT"
python3 -m unittest -v synthesis.soc.test_board_tools
```

Expected: Vivado 2025.2 completes synthesis, placement, routing, DRC, and
bitstream generation for `xc7a35ticsg324-1L`; WNS is nonnegative at the
physical 10 ns constraint. The manifest hashes every copied artifact. A missing
Vivado installation, failed timing, or failed DRC blocks publication and remains
an honestly reported pending measurement.

- [ ] **Step 6: Program and manually exercise the board**

Connect the Arty A7-35T USB programming/UART port, identify its actual serial
device, then run:

```bash
make soc-program SOC_BITSTREAM=build/soc/board/rv32i-soc-arty-a7-35t.bit
SOC_SERIAL=/dev/ttyUSB1
stty -F "$SOC_SERIAL" 115200 cs8 -cstopb -parenb -ixon -ixoff raw -echo
timeout 30s tee .portfolio-runs/soc-board-uart.txt < "$SOC_SERIAL"
```

While the 30-second capture is active, press BTN0 once, then press and fully
release BTN1 twice. Require exactly:

```text
rv32i soc ready
external irq
external irq
```

Only after observing the behavior, create
`.portfolio-runs/soc-board-observations.json` with:

```json
{
  "reset_banner": true,
  "button_presses": 2,
  "led_transitions": 2,
  "release_transitions": 0
}
```

Replace `/dev/ttyUSB1` only with the enumerated board port; do not guess or
commit a host device name.

- [ ] **Step 7: Collect the refreshed portfolio and measured SoC result**

Run:

```bash
make results-open RESULT_RUN_DIR=.portfolio-runs/current
python3 tools/results.py collect-soc \
  --board-manifest build/soc/board/manifest.json \
  --firmware-manifest build/soc/firmware-images.json \
  --verification .portfolio-runs/soc-final-verification.json \
  --soc-verification .portfolio-runs/soc-final-soc.json \
  --uart .portfolio-runs/soc-board-uart.txt \
  --observations .portfolio-runs/soc-board-observations.json \
  --output results/soc.json
```

Expected: the collector parses values from manifests/reports, hashes artifacts
and transcript itself, validates the complete UART/manual behavior, and writes
the result atomically. `results-open` replaces the standard result set only
after all verification, benchmark, synthesis, and tool-version records validate;
the SoC collector then adds `soc.json`. Neither accepts numeric measurement
overrides.

- [ ] **Step 8: Validate and render the measured records**

Run:

```bash
python3 tools/results.py check
make evidence-check
make portfolio-render
make portfolio-render-check
```

Expected: README/evidence text is derived from the validated record and contains
only actual Vivado/board values. Inspect every new number against
`build/soc/board/manifest.json`, the two reports, and `results/soc.json`.

- [ ] **Step 9: Commit compact evidence only**

Run:

```bash
git status --short
git add results README.md docs/evidence.md docs/architecture.md \
  docs/verification.md docs/coverage.md
git diff --cached --check
if git diff --cached --name-only | rg -q '\.(bit|dcp|rpt|jou|log|elf|hex)$'; then
  echo "generated artifact staged" >&2
  exit 1
fi
git commit -m "evidence: publish measured SoC results"
```

The staged set must contain no raw Vivado report, bitstream, firmware build
product, serial-device path, or video.

- [ ] **Step 10: Run final verification and compare repository state**

Run:

```bash
make results-check
make portfolio-check
make portfolio-render-check
make evidence-check
git status --short --branch
git log --format='%h %s%n%b' main..HEAD
```

Expected: all evidence gates pass, checkout is clean, every commit is logical,
no message contains roadmap-phase wording, and no commit contains an automated
attribution trailer.

- [ ] **Step 11: Stop for publication approval**

Report the branch commits, exact verification results, measured route facts,
board behavior, generated-but-ignored artifact paths, and remaining limitations.
Do not push, merge, tag, create a release, or commit the physical-board video
until the user explicitly approves those separate actions. If no physical board
is available, stop after Task 16 with `results/soc.json` absent and documentation
still stating `Physical-board evidence: not published`.
