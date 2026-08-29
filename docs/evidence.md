# Evidence ledger

<!-- portfolio:overview:start -->
This ledger separates source-derived facts, pinned external inputs, current measurements, and historical design studies. Open-source gates were measured at `2026-08-29T05:23:30Z`; the compact result set was published at `2026-08-29T05:56:10Z`; Vivado manifests record `2026-08-29`. The tooling commit is `b8217e0294c26f14abd1cdb3f4e7b6d9fee3d359`, and the frozen RTL baseline is `e55cf402670481413c910c2f2a51617ed53342a5`.

The pinned environment is Ubuntu 24.04 in `ghcr.io/huyhuy-bit/rv32i-verify:1` (`sha256:45fa6be40bdfce85a4aa8dfde1b67f3c9433e42b2fd0e759ae57f3c4ffcb1df8`), Verilator 5.048, Python 3.12, RISC-V GCC 13.2.0-2024.04.12 with assembler 2.42, Spike `55b4658dbf574ba0b714083ec436ce2cb5be1998`, architecture tests `6f7f47bdc61c0c51c0cbf75789678a1235eeefc2`, and Vivado 2025.2 build 6299465.
<!-- portfolio:overview:end -->

## Machine-checked facts

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
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=current
EVIDENCE_FACT CI_CONFIGS=6
EVIDENCE_FACT CI_MATRIX=baseline,slow-mem,icache-only,wt,wb,assoc
EVIDENCE_FACT ARCH_TEST_SHA=6f7f47bdc61c0c51c0cbf75789678a1235eeefc2
EVIDENCE_FACT ARCH_TEST_EXPECTED=38
EVIDENCE_FACT SPIKE_SHA=55b4658dbf574ba0b714083ec436ce2cb5be1998
EVIDENCE_FACT SPIKE_RANDOM_SEEDS=200
<!-- evidence-facts:end -->
<!-- portfolio:facts:end -->

These values are checked against the Make test list and on-disk pairs, RTL
assertions and covers, workflow matrix and seed command, coverage report, and
central reference metadata by `make evidence-check`.

## Current verification measurements

<!-- portfolio:verification:start -->
| Metric | Value | How measured |
|---|---:|---|
| Decoder unit vectors | 2,120/2,120 | `make unit` |
| Hazard unit vectors | 262,144/262,144 | `make unit` |
| Harness tests | 109/109 | `make harness-test` |
| Directed memory matrix | 150/150 | `make verify` |
| Predictor matrix | 75/75 | `make predictor-test` |
| Architecture signatures | 38/38 | `make compliance` |
| Architecture Spike lockstep | 38/38 | `make lockstep` |
| Python-model random | 2000/2000 | `make soak SEEDS=1000` |
| Random Spike lockstep | 200/200 | `make soak-lockstep SEEDS=200` |
| Functional cover points | 44/44 | `make coverage` |
<!-- portfolio:verification:end -->

The six directed configurations were baseline; `IMEM_LAT=10 DMEM_LAT=10`;
1KB four-way I$; that I$ plus a 4KB four-way write-through D$; the same with a
write-back D$; and a two-way associative I$/D$ variant. All slow-memory cache
rows used 10-cycle instruction and data backing memory.

## Current benchmark measurements

Each row below passed its host-oracle result check. `make bench` selected the
exact simulator built for the listed parameters.

<!-- portfolio:benchmarks:start -->
| Kernel | 10-cycle uncached | +1KB 4-way I$ | +4KB 4-way WB D$ | 1-cycle uncached |
|---|---:|---:|---:|---:|
| crc32 | 758,160 / 10.28041 | 170,189 / 2.30771 | 152,285 / 2.06494 | 75,816 / 1.02804 |
| matmul | 3,504,148 / 11.37629 | 790,915 / 2.56772 | 712,507 / 2.31317 | 361,402 / 1.17330 |
| sort | 2,521,060 / 12.48334 | 1,038,506 / 5.14229 | 504,874 / 2.49995 | 252,106 / 1.24833 |
| llist | 932,270 / 10.00236 | 465,099 / 4.99006 | 188,643 / 2.02396 | 93,227 / 1.00024 |
| interp | 14,652,250 / 11.69906 | 4,443,716 / 3.54808 | 2,933,372 / 2.34214 | 1,467,250 / 1.17152 |
<!-- portfolio:benchmarks:end -->

Commands were `make bench IMEM_LAT=10 DMEM_LAT=10`; the same with
`IC_BYTES=1024 IC_WAYS=4`; the same with `DC_BYTES=4096 DC_WAYS=4 DC_WB=1`;
and plain `make bench` for ideal one-cycle uncached memory.

## Current synthesis measurements

`make synth-matrix` and `make synth-summary` routed four configurations with
512-word instruction/data backing memories on `xc7a35ticsg324-1L`. The 2 ns
constraint is intentionally aggressive; all WNS values are negative, so these
are routed critical-path estimates rather than timing closure claims.

<!-- portfolio:synthesis:start -->
| Configuration | LUT | FF | BRAM tiles | WNS (ns) | Critical path (ns) | fmax (MHz) |
|---|---:|---:|---:|---:|---:|---:|
| Core | 4,031 | 5,220 | 0.5 | -11.111 | 13.111 | 76.272 |
| +1KB 4-way I$ | 5,011 | 6,970 | 2.0 | -11.563 | 13.563 | 73.730 |
| +4KB 4-way WT D$ | 8,800 | 13,527 | 4.0 | -12.172 | 14.172 | 70.562 |
| +4KB 4-way WB D$ | 9,218 | 13,517 | 4.0 | -11.920 | 13.920 | 71.839 |
<!-- portfolio:synthesis:end -->

<!-- portfolio:synthesis-hashes:start -->
The SHA-256 pairs below are `utilization.rpt` / `timing_summary.rpt`:

| Configuration | Report hashes |
|---|---|
| core | `96925f405a08f2e168b9ce69ebf323d43cc72c66b92be3437b8bb61dbe33b21c` / `3df0869006aa498b30d56b35299263decb9213dec567640380bf05f0ac32baa3` |
| I$ | `8059baf0a2d593be8a56974974ace0928a06a00ea57e21427f729e7ac207145e` / `0415ed47e5133ab7ec6fc0de2e88c5c62cceefcd38c9ef285a9296a90681b11f` |
| D$ write-through | `2a98b8d37f67e9d393b1c4072e484a6a5c696ce772984a6710e2549ca35c82ca` / `6af38f4ea2a279b49c75013858cdfb3205c3697dfeb4d27ee640c2834b8c1251` |
| D$ write-back | `3e088416f98d84ef9ddb8d4784ddde2e6f7a80472d322b56752b192f2eda4ba3` / `a12a3e63c32789d561ad0658b8c0954b6313e8a34dec7d8365523de90b2cfec7` |
<!-- portfolio:synthesis-hashes:end -->

<!-- portfolio:provenance:start -->
- Measurement timestamp: `2026-08-29T05:56:10Z`
- Tooling commit: `b8217e0294c26f14abd1cdb3f4e7b6d9fee3d359`
- Frozen RTL commit: `e55cf402670481413c910c2f2a51617ed53342a5`
- Canonical container: `ghcr.io/huyhuy-bit/rv32i-verify:1`
- Open tools: Ubuntu 24.04; Verilator 5.048; RISC-V GCC 13.2.0-2024.04.12; RISC-V assembler 2.42; Python 3.12
- Vivado: 2025.2 build 6299465; `xc7a35ticsg324-1L`; measured 2026-08-29
- Reproduce verification: `make verify`
- Reproduce benchmarks: `make bench` with the recorded headline configuration
- Reproduce implementation: `make synth-matrix && make synth-summary`
<!-- portfolio:provenance:end -->

## Historical material

Earlier cache-geometry and inference experiments remain in the README and
microarchitecture document because they explain the design decisions. They are
explicitly labeled historical and are not mixed with the current matrices.
