# Board-ready SoC guide

## Board and observable demo

The board target is the Digilent Arty A7-35T (`xc7a35ticsg324-1L`) at 100 MHz. The freestanding firmware initializes the GPIO interrupt, sets LED0, and transmits `rv32i soc ready` through the board USB-UART connection. BTN0 resets the system. A debounced BTN1 press raises a machine-external interrupt; the handler clears the pending bit, rotates the LED pattern, transmits `external irq`, and returns with `MRET`.

Physical-board evidence: not published. The RTL, firmware, simulation, constraints, and guarded Vivado flow are present, but this document does not claim that a bitstream has run on hardware.

## System hierarchy

```text
arty_a7_35t_top
├── reset_controller
└── rv32i_soc
    ├── rv32i_core
    ├── instruction and data Wishbone adapters
    ├── round-robin Wishbone arbiter
    ├── address-decoding interconnect
    ├── instruction and data BRAM slaves
    ├── UART transmitter
    └── GPIO, debounce, and external-interrupt logic
```

`rv32i_core` contains the pipeline, caches, predictor, CSRs, and counters. The legacy `cpu` top wraps the same core with the original memory models, preserving directed, compliance, and lockstep verification. `rv32i_soc` attaches the external-memory form to the bus and peripherals. `arty_a7_35t_top` contains only the board reset, clock, buttons, LEDs, UART pin, and fixed board parameters.

## Core memory-client contract

The core exposes independent instruction and data clients. A requester holds `req`, byte address, write data, and byte enables stable until `ready`. Instruction transfers are word reads. Data reads use zero byte enables; writes carry lane-aligned data and one enable per byte. The returned word is extended or narrowed by the LSU. Cache refills and write-backs issue one word at a time; the retained `burst` signal is a sequential hint and does not create a Wishbone block cycle.

## Wishbone transaction contract

The internal fabric implements 32-bit, byte-addressed Wishbone B4 Classic single transfers with `CYC`, `STB`, `WE`, `ADR`, `DAT_W`, `SEL`, `ACK`, `ERR`, and `DAT_R`. Each adapter latches a source request, aligns its bus address to a word boundary, holds it until exactly one response, and deasserts the cycle before accepting the next request. An error completes the source transfer with zero read data and emits a fault pulse.

The arbiter retains ownership through completion and alternates contested instruction/data grants. The interconnect latches one decoded slave per transaction. An unmapped or disallowed request returns `ERR` instead of hanging.

## Memory map and register tables

| Address range | Access | Device |
|---|---|---|
| `0x0000_0000–0x0000_7FFF` | instruction read, data read | 32 KiB instruction BRAM containing `.text` and `.rodata` |
| `0x1000_0000–0x1000_000F` | data read/write | UART registers |
| `0x1000_1000–0x1000_101F` | data read/write | GPIO and external-interrupt registers |
| `0x2000_0000–0x2000_7FFF` | data read/write | 32 KiB data BRAM containing `.data`, `.bss`, and stack |

Instruction fetches are permitted only from instruction BRAM. Instruction-BRAM writes, fetches from the other regions, and unmapped accesses return `ERR`.

| Address | Register | Behavior |
|---|---|---|
| `0x1000_0000` | `TXDATA` | Writing byte lane 0 transmits bits `[7:0]`; the transfer waits while busy. Reads return zero. |
| `0x1000_0004` | `STATUS` | Read-only; bit 0 is `TX_READY`. |
| `0x1000_1000` | `LED` | Read/write bits `[3:0]`. |
| `0x1000_1004` | `BUTTON` | Read-only debounced BTN1 state in bit 0. |
| `0x1000_1008` | `IRQ_PENDING` | Read bit 0; writing one to bit 0 clears it. A simultaneous button event wins over clear. |
| `0x1000_100C` | `IRQ_ENABLE` | Read/write enable in bit 0. |

The physical serial configuration is 115200 8-N-1, idle high, least-significant data bit first. The UART is transmit-only.

## Cacheability and MMIO ordering

The board configuration uses a 1 KiB four-way I-cache and a 4 KiB four-way write-back D-cache. A data address is cacheable only when:

```text
(address & 0xFFFF_8000) == 0x2000_0000
```

Only data BRAM is D-cacheable. Instruction-BRAM data reads, UART, GPIO, and unmapped transactions bypass the D-cache. MMIO writes therefore reach the selected device before the instruction completes, MMIO reads observe current device state, and cache-access/miss counters exclude bypassed requests.

## External-interrupt flow and priority

BTN1 passes through two synchronization flops and must remain stable for 10 ms at the board clock. A debounced rising edge sets a sticky pending bit; holding or releasing the button does not retrigger. Firmware enables the peripheral, `mie.MEIE`, and `mstatus.MIE`.

The core reflects the peripheral level in `mip.MEIP`. Machine external interrupt cause 11 has priority over machine software and timer interrupts. Precise trap entry commits the selected instruction, writes its architectural successor to `mepc`, writes `0x8000_000B` to `mcause`, and updates the MIE/MPIE state. The handler clears `IRQ_PENDING`; `MRET` resumes the interrupted loop.

## Firmware build and image validation

```bash
make soc-firmware
```

The freestanding build targets `rv32i_zicsr_zifencei`/`ilp32`, starts at address zero, clears `.bss`, initializes `sp` to `0x2000_8000`, installs the trap entry, and calls `main`. The dependency-free image tool validates ELF32 little-endian RISC-V headers, entry point, allocated-section bounds and overlap, region placement, exact image capacity, and artifact hashes. It emits deterministic 8192-word instruction and data hexadecimal images plus a manifest under `build/soc/`.

## Verilator integration procedure

```bash
make soc-check
```

This runs the bus/peripheral/core units, builds and validates the firmware images, executes the firmware-level simulator, lints both SoC tops, and tests the board wrapper. The integration harness requires the complete stream:

```text
rv32i soc ready
external irq
external irq
```

It also rejects button bounce, requires two separate press/release events, observes two LED transitions and post-`MRET` progress, and fails on a bus fault, framing error, duplicate event, incomplete output, simulator failure, or deadline.

## Vivado build and programming procedure

Vivado 2025.2 is required. An explicit `VIVADO` path is authoritative; otherwise the wrapper detects native Vivado or the installed Windows tool under WSL. The build stages only source, constraints, scripts, and validated firmware images in private temporary storage.

```bash
make soc-bitstream
make soc-program
```

The build requires the exact Arty part, top, 10.000 ns clock constraint, nonnegative WNS, clean DRC, completion marker, and fresh outputs. It publishes only the bitstream, compact reports, and manifest under the ignored build directory. Programming requires a `.bit` file, checks the JTAG-visible FPGA die, waits for the DONE bit, and rejects a missing completion marker.

## Manual reset/button/UART checklist

1. Connect the Arty A7 USB-JTAG/UART port and open a terminal at 115200 8-N-1.
2. Program the validated bitstream.
3. Require one complete `rv32i soc ready` line and LED0 lit.
4. Press BTN1 once; require one LED-pattern change and one complete `external irq` line.
5. Keep BTN1 held; require no repeated event.
6. Release BTN1, press it again, and require exactly one additional LED change and line.
7. Press BTN0; require a fresh boot banner and the initial LED state.

Record observations only after every item passes. Do not convert simulation output into a physical-board claim.

## Fault behavior

A Wishbone `ERR` completes the pending core request with zero read data, latches `bus_fault` until reset, fails simulation, and forces all four LEDs on. These integration errors are not architectural access-fault traps; firmware must access only decoded regions. A slave that never responds is caught by the simulation or Vivado-flow deadline. An unexpected architectural trap disables interrupts, sets all LEDs, transmits `unexpected trap` when possible, and loops.

## Known limitations

The system has no bootloader, no external memory, no PLIC, and no operating system. It also omits UART receive, FIFOs, DMA, DDR3, QSPI boot, AXI, instruction-memory writes, and architectural instruction/load/store access-fault exceptions. The caches remain blocking, the front end remains globally stalled by memory waits, and the speculative RAS is not repaired after a wrong-path update.

## Evidence provenance

The Digilent constraint source is pinned in `tools/reference_versions.env`. Board publication additionally requires a clean committed checkout, matching RTL/tooling identities, validated firmware and route manifests, complete full and SoC verification receipts, the exact UART transcript, two manually observed button/LED events, report and artifact hashes, and a passing `tools/results.py collect-soc` run. Until that process creates a valid `results/soc.json`, README and evidence output remain in the not-published state.
