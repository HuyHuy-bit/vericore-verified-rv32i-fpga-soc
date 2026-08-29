# Board-Ready Wishbone SoC Design

**Status:** Approved design

**Target:** Digilent Arty A7-35T, `xc7a35ticsg324-1L`

**Purpose:** Turn the verified RV32I core into a small, demonstrable FPGA system without weakening the existing CPU verification baseline.

## Outcome

The repository will produce a bitstream containing the existing pipelined CPU, its configurable caches, a Wishbone B4 interconnect, BRAM-backed program and data memories, a transmit-only UART, and a GPIO external-interrupt peripheral. The same firmware image will run in Verilator and on an Arty A7-35T.

The hardware demonstration has two observable behaviors:

1. After configuration or reset, the firmware prints `rv32i soc ready` over the board's USB-UART connection.
2. Pressing BTN1 raises a machine-external interrupt. The handler clears the peripheral, changes the four user LEDs, prints `external irq`, and returns with `MRET`.

Measured verification, implementation, and board results will only be published after they are generated from the final RTL commit.

## Scope

### Included

- An external-memory form of the current core.
- Wishbone B4 Classic single-transfer masters, arbitration, and address decoding.
- Separate instruction and data BRAMs initialized from the firmware ELF.
- A transmit-only 115200-baud, 8-N-1 UART.
- Four output LEDs, one debounced interrupt button, and a sticky interrupt-pending bit.
- Machine-external interrupt support through `mip.MEIP`, `mie.MEIE`, and `mcause` code 11.
- Verilator unit and firmware-level integration tests.
- An Arty A7-35T Vivado bitstream and programming flow.
- Reproducible evidence and a physical-board demo after hardware validation.

### Excluded

- UART receive, FIFOs, DMA, Ethernet, DDR3, QSPI boot, or a bootloader.
- AXI, TileLink, or a multi-master external expansion port.
- A multi-source PLIC or claim/complete protocol.
- Memory protection, user mode, an operating system, or an RTOS.
- RISC-V instruction/load/store access-fault exceptions.
- Non-blocking caches, a store buffer, or a decoupled front end.
- Changing the existing timer/software interrupt discovery model.

## Compatibility Requirement

The existing `cpu` module remains the verification and out-of-context synthesis top. Its port list, default parameters, internal memory behavior, simulator completion contract, directed references, compliance signatures, and RVFI lockstep trace must remain compatible.

The refactor introduces `rv32i_core` as the memory-independent pipeline/cache module. The legacy `cpu` becomes a compatibility wrapper around `rv32i_core`, `instr_mem`, and `data_mem`. The SoC instantiates `rv32i_core` directly.

This boundary prevents board-specific logic from entering the established CPU harness:

```text
Existing verification                           Board system

cpu                                             arty_a7_35t_top
├── rv32i_core                                  ├── reset_controller
├── instr_mem                                   └── rv32i_soc
└── data_mem                                        ├── rv32i_core
                                                    ├── 2 request-to-Wishbone adapters
                                                    ├── Wishbone arbiter/interconnect
                                                    ├── instruction BRAM
                                                    ├── data BRAM
                                                    ├── UART TX
                                                    └── GPIO/external IRQ
```

## Source Organization

| Path | Responsibility |
|---|---|
| `rtl/core/rv32i_core.sv` | Pipeline, caches, predictor, CSRs, counters, and external memory-client ports. |
| `rtl/core/cpu.sv` | Backward-compatible wrapper with the existing internal instruction and data memories. |
| `rtl/bus/wb_master_adapter.sv` | Convert one existing request/ready channel into Wishbone Classic transactions. |
| `rtl/bus/wb_arbiter.sv` | Fair arbitration between instruction and data Wishbone masters. |
| `rtl/soc/wb_interconnect.sv` | Decode the single shared master into BRAM and peripheral slaves. |
| `rtl/soc/wb_imem.sv` | Read-only, initialized 32 KiB instruction BRAM. |
| `rtl/soc/wb_dmem.sv` | Initialized 32 KiB data BRAM with byte write strobes. |
| `rtl/soc/uart_tx.sv` | Byte-level 8-N-1 transmitter. |
| `rtl/soc/wb_uart.sv` | UART Wishbone registers and TX backpressure. |
| `rtl/soc/button_debounce.sv` | Two-flop synchronization and stable-state debounce. |
| `rtl/soc/wb_gpio_irq.sv` | LED, button, interrupt-pending, and interrupt-enable registers. |
| `rtl/soc/reset_controller.sv` | Configuration-time reset plus asynchronous button assertion and synchronous release. |
| `rtl/soc/rv32i_soc.sv` | Core, bus, memories, peripherals, fault latch, and parameters. |
| `rtl/boards/arty_a7_35t_top.sv` | Board pins and board-specific parameter values only. |
| `boards/arty_a7_35t.xdc` | Physical pins, I/O standards, and 100 MHz clock constraint. |
| `sim/unit/*.sv` | Bus, peripheral, debounce, and external-interrupt unit tests. |
| `sim/soc_tb.cpp` | Firmware-level SoC simulation and UART decoder. |
| `firmware/start.S` | Stack setup, BSS clearing, trap entry, context save/restore, and `MRET`. |
| `firmware/demo.c` | UART/GPIO initialization, demo loop, and interrupt behavior. |
| `firmware/soc.h` | MMIO addresses, register masks, and CSR helpers. |
| `firmware/link.ld` | Instruction/data regions and section placement. |
| `tools/soc_image.py` | Produce bounded instruction/data memory images from the ELF. |
| `synthesis/soc/build.tcl` | Board synthesis, implementation, timing/utilization reports, and bitstream generation. |
| `synthesis/soc/program.tcl` | Verify the connected FPGA part and program the bitstream. |
| `synthesis/soc/run_board.py` | Native/WSL Vivado launcher and isolated staging wrapper. |
| `docs/soc.md` | Memory map, build, simulation, programming, and demo guide. |

Flat SystemVerilog ports will be used instead of a SystemVerilog `interface` so the boundary remains straightforward for both Verilator and Vivado.

## Core External-Memory Contract

`rv32i_core` exposes the backing side of the current caches. The instruction and data request channels retain the semantics already used by `instr_mem` and `data_mem`.

### Instruction client

| Signal | Direction | Meaning |
|---|---|---|
| `imem_req` | output | A backing-memory instruction word is requested. |
| `imem_burst` | output | Sequential-refill hint retained for the legacy timing model. |
| `imem_addr[31:0]` | output | Byte address; word aligned. |
| `imem_rdata[31:0]` | input | Returned instruction word. |
| `imem_ready` | input | The current word completed. High when no request is pending. |

### Data client

| Signal | Direction | Meaning |
|---|---|---|
| `dmem_req` | output | A backing-memory or bypassed-MMIO transfer is requested. |
| `dmem_burst` | output | Sequential-refill/write-back hint retained for the legacy timing model. |
| `dmem_addr[31:0]` | output | Byte address. |
| `dmem_wstrb[3:0]` | output | Byte write enables; zero denotes a read. |
| `dmem_wdata[31:0]` | output | Lane-aligned write data. |
| `dmem_rdata[31:0]` | input | Returned word. The LSU extracts and extends subword loads. |
| `dmem_ready` | input | The current word completed. High when no request is pending. |

A requester holds `req`, address, write data, and byte enables stable until `ready`. A cache refill may present the next sequential address on the cycle after the previous word completes. The SoC adapters treat each word as an independent bus transaction; `burst` does not become a Wishbone block cycle.

`rv32i_core` also gains `irq_external`. The compatibility `cpu` wrapper ties it low, so existing tests see no new interrupt source.

## Cacheability and MMIO Ordering

The board uses these existing cache parameters:

- `ICACHE_BYTES=1024`, `ICACHE_BLOCK_WORDS=4`, `ICACHE_WAYS=4`.
- `DCACHE_BYTES=4096`, `DCACHE_BLOCK_WORDS=4`, `DCACHE_WAYS=4`, `DCACHE_WRITE_BACK=1`.

The backend gains a parameterized cacheability predicate:

```text
cacheable = DCACHEABLE_MASK == 0
          || (address & DCACHEABLE_MASK) == DCACHEABLE_BASE
```

The compatibility wrapper keeps `DCACHEABLE_MASK=0`, preserving the current all-addresses-cacheable behavior. The SoC sets:

```text
DCACHEABLE_BASE = 0x2000_0000
DCACHEABLE_MASK = 0xFFFF_8000
```

Only the 32 KiB data-BRAM window is cached. Loads from instruction BRAM, UART accesses, GPIO accesses, and unmapped transactions bypass the D-cache. MMIO stores therefore reach the device before the instruction completes, and MMIO loads return the device's current state. Cache-access/miss counters exclude bypassed accesses.

The instruction BRAM is readable from the data bus so firmware can load constants in `.rodata`. It is not writable. Self-modifying code remains outside the design contract.

## Wishbone B4 Contract

The internal bus is a 32-bit, byte-addressed Wishbone B4 Classic bus.

| Signal | Meaning |
|---|---|
| `wb_cyc` | A bus cycle is active. |
| `wb_stb` | A valid transfer is being presented. |
| `wb_we` | Write when high, read when low. |
| `wb_adr[31:0]` | Byte address. |
| `wb_dat_w[31:0]` | Write data. |
| `wb_sel[3:0]` | Active byte lanes. Reads use `4'b1111`. |
| `wb_ack` | Successful completion for exactly one transfer. |
| `wb_err` | Failed completion for exactly one transfer. |
| `wb_dat_r[31:0]` | Read data returned with `ack`. |

`RTY`, `STALL`, `LOCK`, `CTI`, and `BTE` are not implemented. A master latches its source request, asserts `cyc` and `stb`, and holds every request field stable until exactly one of `ack` or `err`. It deasserts the cycle before accepting another source request.

`wb_master_adapter` returns source `ready` for either `ack` or `err`. An error returns zero data and emits a one-cycle `fault_pulse`. The SoC latches any fault permanently until reset. Simulation treats the sticky fault as a failure. On the board, a fault overrides the GPIO value and drives all four LEDs high.

The CPU does not yet convert `wb_err` into an architectural access-fault exception. This limitation is explicit: firmware must only access decoded regions, the integration test must observe no error, and every default-error response must terminate rather than deadlock the CPU.

### Arbitration

The instruction and data adapters are independent masters. `wb_arbiter` implements round-robin selection:

- A grant is latched for the entire transaction.
- A requester cannot lose ownership before `ack` or `err`.
- If both request after a completion, the requester that did not win the previous contested grant wins next.
- A continuously requesting instruction refill cannot starve a data access, and a cache write-back cannot starve instruction fetch indefinitely.
- Response data, `ack`, and `err` are returned only to the granted master.

The reset state gives the first uncontested requester immediate ownership; it does not wait for both requesters.

### Address decoding

The interconnect decodes one slave per transaction and latches that selection until completion. Overlap is a build-time error. An unmapped address selects a default slave that asserts `err` and returns zero on the following cycle.

## Memory Map

| Address range | Size | Access | Device |
|---|---:|---|---|
| `0x0000_0000–0x0000_7FFF` | 32 KiB | instruction read, data read | Instruction BRAM containing `.text` and `.rodata`. |
| `0x1000_0000–0x1000_000F` | 16 B | data read/write | UART TX registers. |
| `0x1000_1000–0x1000_101F` | 32 B | data read/write | GPIO/button/external-interrupt registers. |
| `0x2000_0000–0x2000_7FFF` | 32 KiB | data read/write | Data BRAM containing `.data`, `.bss`, and stack. |

Instruction fetch outside instruction BRAM, writes to instruction BRAM, instruction fetch from MMIO/data BRAM, and all unmapped accesses receive `wb_err`.

### UART registers

| Address | Name | Contract |
|---|---|---|
| `0x1000_0000` | `TXDATA` | A write transmits bits `[7:0]`. The slave withholds `ack` while TX is busy, then accepts the byte exactly once. Reads return zero. |
| `0x1000_0004` | `STATUS` | Read bit 0 is `TX_READY`; all other bits are zero. Writes receive `err`. |

The board parameters are `CLOCK_HZ=100000000`, `UART_BAUD=115200`, eight data bits, no parity, one stop bit, idle high, least-significant data bit first. The integer divider is rounded to the nearest clock count. Elaboration rejects a zero divider or a baud-rate error above two percent.

The unit and integration simulations override the clock/baud parameters with a smaller integral divider; they test the same state machine without simulating hundreds of physical clock cycles per serial bit.

### GPIO and external-interrupt registers

| Address | Name | Contract |
|---|---|---|
| `0x1000_1000` | `LED` | Read/write bits `[3:0]`; other bits read zero and are ignored on write. |
| `0x1000_1004` | `BUTTON` | Read bit 0 as the debounced BTN1 state. Writes receive `err`. |
| `0x1000_1008` | `IRQ_PENDING` | Read bit 0. Writing one to bit 0 clears it; writing zero leaves it unchanged. |
| `0x1000_100C` | `IRQ_ENABLE` | Read/write bit 0. Reset value is zero. |

BTN1 passes through two synchronizer flip-flops. A counter changes the debounced state only after the synchronized input remains different for `DEBOUNCE_CYCLES`. The board value is `1000000`, representing 10 ms at 100 MHz; unit tests use a small override.

A rising edge of the debounced state sets `IRQ_PENDING`. A set event wins over a simultaneous software clear so an event cannot be lost. The peripheral interrupt output is:

```text
irq_external = IRQ_PENDING[0] && IRQ_ENABLE[0]
```

The pending level stays asserted until firmware clears it. Releasing the button does not clear pending and does not create an interrupt. Another interrupt requires a debounced release followed by a new debounced press.

## Machine-External Interrupt Extension

The core adds:

- `IRQ_E_BIT = 11`.
- `CAUSE_IRQ_EXTERNAL = 0x8000_000B` for RV32.
- `mie.MEIE` at bit 11.
- `mip.MEIP` at bit 11, read from `irq_external`.

The interrupt selector considers only pending sources whose corresponding `mie` bit and global `mstatus.MIE` are set. Priority is machine external, then machine software, then machine timer. The chosen cause is held by the existing precise MEM-stage commit path.

The existing interrupt semantics remain unchanged:

- The instruction at the commit point completes normally.
- `mepc` receives its `pc+4`.
- `mcause` receives the interrupt bit and cause 11.
- Trap entry moves `mstatus.MIE` to `MPIE` and clears `MIE`.
- `MRET` restores interrupt-enable state and resumes at `mepc`.

New assertions cover MEIP reflection, enable gating, cause priority, interrupt/trap exclusion, and `MRET` resumption. Existing timer and software interrupt tests remain unchanged because the compatibility wrapper ties `irq_external` low.

## Reset and Board Wiring

`reset_controller` holds the SoC in reset for 16 `clk100` cycles after FPGA configuration. BTN0 asynchronously asserts reset and passes through a two-flop chain for synchronous deassertion. Reset clears bus state, cache valid/dirty state, UART activity, GPIO output, IRQ state, CSRs, pipeline state, and the sticky bus-fault indicator.

The board constraints are derived from Digilent's `Arty-A7-35-Master.xdc` at commit `00a3404901f35aa9567b01ecb3f2c233b6efe9f4`:

| Top-level port | Package pin | Board function |
|---|---|---|
| `clk100` | E3 | 100 MHz oscillator; 10.000 ns clock constraint. |
| `btn[0]` | D9 | SoC reset. |
| `btn[1]` | C9 | Debounced external-interrupt input. |
| `led[0]` | H5 | GPIO LED 0. |
| `led[1]` | J5 | GPIO LED 1. |
| `led[2]` | T9 | GPIO LED 2. |
| `led[3]` | T10 | GPIO LED 3. |
| `uart_tx` | D10 | FPGA output to the USB-UART receiver (`uart_rxd_out` in Digilent's schematic naming). |

Every port uses `LVCMOS33`. UART RX and the remaining buttons, switches, RGB LEDs, Ethernet, DDR3, QSPI, and Pmod pins remain unconstrained and absent from the top-level port list.

Official constraint source: <https://github.com/Digilent/digilent-xdc/blob/00a3404901f35aa9567b01ecb3f2c233b6efe9f4/Arty-A7-35-Master.xdc>

## Firmware Contract

The firmware is freestanding RV32I code built with the repository's pinned RISC-V GCC/binutils environment. It uses `-march=rv32i_zicsr_zifencei`, `-mabi=ilp32`, `-nostdlib`, `-ffreestanding`, and `-msmall-data-limit=0`.

The linker places:

- `.text`, trap entry, and `.rodata` in instruction BRAM starting at `0x0000_0000`.
- `.data` and `.bss` in data BRAM starting at `0x2000_0000`.
- The initial stack pointer at `0x2000_8000`, aligned to 16 bytes and growing downward.

`start.S` performs these steps:

1. Load the stack pointer.
2. Clear `.bss` using word stores.
3. Install the assembly trap entry in `mtvec`.
4. Call `main`.
5. Enter a visible fault loop if `main` returns.

The trap entry saves and restores every register it uses before executing `MRET`, because the interrupt is asynchronous to the C code. The C handler reads `mcause`. Cause 11 clears `IRQ_PENDING`, advances the LED pattern, and writes `external irq\n`. Any unexpected trap disables interrupts, sets the LED register to `4'hF`, prints `unexpected trap\n` when UART remains reachable, and loops.

`main` clears stale peripheral pending state, enables the GPIO IRQ, enables `mie.MEIE`, enables global `mstatus.MIE`, prints `rv32i soc ready\n`, and spins. It does not use `WFI`, which the core intentionally treats as unsupported.

`tools/soc_image.py` validates the ELF class, endianness, machine type, section bounds, and memory capacities before emitting one 32-bit hexadecimal word per line. It rejects sections outside their assigned region and images larger than either BRAM. Generated ELF, binary, hexadecimal, bitstream, checkpoint, and report artifacts remain ignored; only compact validated results are committed.

## Simulation Strategy

### Unit verification

Each new unit receives a focused negative and positive test:

- `wb_master_adapter`: stable request fields, one completion pulse, read data, byte enables, back-to-back source requests, delayed response, and error completion.
- `wb_arbiter`: uncontested grants, simultaneous requests, grant retention, response isolation, alternating contested grants, and error routing.
- `wb_interconnect`: every valid region, boundary addresses, read/write permissions, one-hot slave selection, and default errors.
- `wb_imem`/`wb_dmem`: initialized reads, synchronous acknowledgment, byte-lane writes, read-only rejection, and upper-bound rejection.
- `uart_tx`/`wb_uart`: idle level, start/data/stop sequence, least-significant-bit order, busy backpressure, one accepted byte, and status reads.
- `button_debounce`/`wb_gpio_irq`: synchronizer latency, rejected bounce, stable press/release, rising-edge pending, set-over-clear priority, W1C behavior, enable gating, and LED writes.
- `reset_controller`: configuration reset length, asynchronous assertion, and synchronous release.
- `csr`: MEIP visibility, MEIE/global gating, cause 11, priority over software/timer, and external interrupt state restoration through `MRET`.

Unit tests must contain bounded timeouts. A timeout, assertion failure, simulator crash, missing output, or skipped vector is a test failure.

### Firmware integration verification

`sim/soc_tb.cpp` instantiates `rv32i_soc` with simulation-sized UART and debounce divisors while loading the exact firmware images produced by `make soc-firmware`.

The integration test must:

1. Apply and release reset.
2. Decode UART start/data/stop bits and require the complete `rv32i soc ready\n` banner.
3. Confirm the initial LED value.
4. Drive a bouncing BTN1 waveform that must not create an interrupt.
5. Drive a stable press long enough to pass debounce.
6. Require one LED-pattern transition and one complete `external irq\n` line.
7. Release and press again, requiring exactly one additional transition and line.
8. Observe continued main-loop progress after each `MRET` through a simulation-only retirement/progress signal.
9. Fail immediately on Wishbone error, UART framing error, duplicate interrupt, missing response, or deadline expiration.

No integration test may infer success from a matching output prefix. The expected UART stream and event count must be complete before success is reported.

### Regression preservation

Before the first RTL change, record a clean `make verify` baseline. After every core-boundary or interrupt change, run the relevant directed tests plus unit tests. Before merging, run the full verification profile and compare its established milestones with the baseline.

The final acceptance run must include:

- `make check`.
- `make verify`.
- `make soc-check`.
- `make soc-firmware` followed by a clean rebuild comparison.
- `make soc-sim`.
- `make soc-bitstream` using Vivado 2025.2.
- Hardware programming and the manual board procedure.

## Build and CI Surface

The Makefile gains these entry points:

| Target | Contract |
|---|---|
| `make soc-unit` | Run the new bus/peripheral/interrupt unit tests. |
| `make soc-firmware` | Build the ELF and validated BRAM images. |
| `make soc-sim` | Build and run the firmware-level Verilator integration test. |
| `make soc-lint` | Lint the external core, SoC, and board top. |
| `make soc-check` | Run units, firmware build, integration simulation, and SoC lint. |
| `make soc-bitstream` | Stage sources/images, route the Arty A7-35T design, write reports and `.bit`. |
| `make soc-program` | Check the connected FPGA part and program the selected `.bit` through Vivado hardware manager. |

`make check` includes the fast `soc-unit` and `soc-sim` gates. `make verify` continues to cover the existing complete profile and therefore includes the fast SoC gate through `make check`.

The verification container includes the already pinned cross-compiler and Verilator; it does not include Vivado. GitHub Actions runs `make soc-check` for changes under `rtl/**`, `sim/**`, `firmware/**`, `boards/**`, `tools/**`, `synthesis/soc/**`, the Makefile, container definitions, relevant documentation/results, and the workflow itself. The licensed Vivado route remains a reproducible local evidence step.

`synthesis/soc/run_board.py` reuses the existing native/WSL Vivado discovery behavior, honors an explicit `VIVADO` override, stages only required sources and generated firmware images, requires completion markers and fresh reports, and copies only requested reports and the bitstream back to the repository build directory.

## Evidence and Portfolio Publication

Evidence is collected only after the implementation RTL is committed. The evidence record includes:

- Exact source and RTL commit IDs.
- Firmware ELF and both memory-image SHA-256 hashes.
- Bitstream SHA-256 hash.
- Verification-container identity and tool versions.
- Digilent XDC source SHA.
- Vivado version/build, FPGA part, clock constraint, and build date.
- Post-route utilization, WNS, achieved critical-path estimate, and BRAM use taken from generated reports.
- `make verify` and `make soc-check` results.
- Captured UART transcript from the physical board.
- Manual test steps and observed reset/button/LED behavior.

README and evidence-ledger figures are rendered from validated result records. Until the board test succeeds, documentation may describe the design and commands but must not claim that the bitstream ran on hardware or quote new performance/utilization figures.

After validation, the portfolio artifact includes a short physical-board video showing configuration, the boot UART banner, two button interrupts, corresponding LED changes, and the terminal output. The current terminal-style GIF remains labeled as a repository workflow recording; it is not relabeled as board footage.

## Failure Behavior

| Failure | Required behavior |
|---|---|
| Wishbone slave does not answer | Simulation deadline fails; no success can be reported. |
| Wishbone `err` | Source transaction completes with zero data, sticky SoC fault sets, simulation fails, board LEDs become `4'hF`. |
| UART busy | `TXDATA` write remains pending until the byte can be accepted exactly once. |
| Button bounce | No pending interrupt until the synchronized input is stable for the full debounce interval. |
| Repeated level while held | One interrupt only; another requires a debounced release and press. |
| Unexpected trap | Firmware disables interrupts, reports the fault when possible, lights all LEDs, and stops. |
| Oversized or misplaced firmware section | Image generation fails before simulation or synthesis. |
| Wrong connected FPGA | Programming script exits nonzero before configuring a device. |
| Stale/missing Vivado output | Board-build wrapper exits nonzero and publishes no evidence. |

## Implementation Checkpoints

The implementation plan will divide the work into independently reviewable checkpoints:

1. Preserve a verified baseline and introduce the external-memory core boundary.
2. Add machine-external interrupt behavior and directed/unit verification.
3. Add Wishbone adapters, arbitration, decoding, and BRAM slaves.
4. Add uncached-access selection and UART/GPIO peripherals.
5. Add firmware, ELF-to-memory validation, and integration simulation.
6. Add the Arty board top, constraints, bitstream/programming flow, and synthesis tests.
7. Expand CI and documentation, then run the full regression.
8. Commit the final RTL baseline, collect implementation/hardware evidence, and publish only measured results.

Each checkpoint uses test-first changes and a focused commit message describing the behavior, without roadmap-phase wording or automated co-author trailers.

## Acceptance Criteria

The SoC work is complete only when all of these conditions hold:

- The legacy CPU verification milestones still pass from a clean checkout.
- All new bus and peripheral negative tests fail for their intended reason before implementation and pass afterward.
- The SoC integration test validates the complete boot and two-interrupt transcript without prefix acceptance or timeout ambiguity.
- MMIO transactions bypass the D-cache in every cache mode and complete exactly once.
- External interrupts produce `mcause=0x8000000B`, preserve the interrupted instruction's effects, clear through the peripheral W1C register, and resume through `MRET`.
- The Arty A7-35T bitstream builds with the physical 100 MHz constraint and the exact committed firmware image.
- The programmed board produces the recorded UART and LED behavior.
- Every published number comes from committed logs or validated reports generated for the recorded RTL commit.
- Generated Vivado projects, checkpoints, logs, journals, raw reports, ELF files, memory images, and bitstreams remain outside Git history unless the user explicitly approves a compact release artifact.
- The final checkout is clean, and integration or remote publication occurs only after explicit user approval.
