# Reproducible result records

The files in this directory are compact, machine-checked summaries bound to
the exact tooling and RTL commits that produced them.

- `verification.json` records all open-source correctness gates and commands.
- `benchmarks.csv` stores raw counters for five kernels in four configurations.
- `synthesis.csv` stores four routed Vivado configurations and report hashes.
- `tool_versions.json` records the pinned open-source environment and Vivado.
- `manifest.json` records completeness, expected populations, and file hashes.

Open-source verification and benchmark records are reproducible with the
pinned verification container. Synthesis requires native Vivado 2025.2 or the
supported WSL-to-Windows wrapper.

Use `make verify`, collect the run receipts under `.portfolio-runs/`, run
`make results-synth`, then run `make results-open` and `make results-check`.
Raw logs, simulator builds, coverage databases, and Vivado projects are not
committed because the compact records retain the reviewable results and hashes.

The tooling commit identifies the clean checkout used for collection. The RTL
commit identifies the last commit affecting RTL or the testbench, avoiding a
self-reference to the later commit that publishes these result files.
