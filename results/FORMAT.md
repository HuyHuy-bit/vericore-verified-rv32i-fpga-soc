# Reproducible result records

The files in this directory are compact, machine-checked summaries bound to
the exact tooling and RTL commits that produced them.

- `verification.json` records all open-source correctness gates and commands.
- `benchmarks.csv` stores raw counters for five kernels in four configurations.
- `synthesis.csv` stores four routed Vivado configurations and report hashes.
- `tool_versions.json` records the pinned open-source environment and Vivado.
- `manifest.json` records completeness, expected populations, and file hashes.
- Optional `soc.json` records validated Arty A7 routing, firmware, UART, and
  manual button/LED evidence. Its absence means physical-board evidence has not
  been published.

Open-source verification and benchmark records are reproducible with the
pinned verification container. Synthesis requires native Vivado 2025.2 or the
supported WSL-to-Windows wrapper.

Use `make verify`, collect the run receipts under `.portfolio-runs/`, run
`make results-synth`, then run `make results-open` and `make results-check`.
Raw logs, simulator builds, coverage databases, and Vivado projects are not
committed because the compact records retain the reviewable results and hashes.

`python3 tools/results.py collect-soc` accepts only the board manifest,
firmware manifest, full and SoC verification receipts, UART transcript, manual
observations, and output path. Timing, utilization, hashes, and event counts are
derived from those inputs; the command has no numeric measurement overrides.

The `soc.json` top-level schema is exact: identity and timestamp fields, board
and part, the pinned Digilent XDC SHA, firmware and bitstream hashes, Vivado
identity, route measurements/report hashes, verification receipt statuses and
hashes, the complete UART line array, and manual reset/button/LED observations.
Unknown, missing, or duplicate fields are rejected at every nesting level. The
record is valid only for Vivado 2025.2, the 10 ns Arty constraint, nonnegative
WNS, complete full/SoC receipts, exactly two interrupt events and LED changes,
and unchanged RTL between the recorded RTL and tooling commits.

The tooling commit identifies the clean checkout used for collection. The RTL
commit identifies the last commit affecting RTL or the testbench, avoiding a
self-reference to the later commit that publishes these result files.
