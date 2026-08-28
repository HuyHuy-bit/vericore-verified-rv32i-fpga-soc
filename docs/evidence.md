# Evidence ledger

<!-- portfolio:overview:start -->
This ledger separates source-derived facts, pinned external inputs, current measurements, and historical design studies. Open-source gates were measured at `2026-08-28T03:34:50Z`; the compact result set was published at `2026-08-28T13:46:38Z`; Vivado manifests record `2026-08-28`. The tooling commit is `031fcd07c45b9fe59f6951fd0bafda275e6ce0d0`, and the frozen RTL baseline is `3c7e84e392b345332d6acdd0ed899928dafb1058`.

The pinned environment is Ubuntu 24.04 in `ghcr.io/huyhuy-bit/rv32i-verify:1` (`sha256:c5e3ca79ff535e1399e2a57753d8103d789172531a58c8ff420b502697790e81`), Verilator 5.048, Python 3.12, RISC-V GCC 13.2.0-2024.04.12 with assembler 2.42, Spike `55b4658dbf574ba0b714083ec436ce2cb5be1998`, architecture tests `6f7f47bdc61c0c51c0cbf75789678a1235eeefc2`, and Vivado 2025.2 build 6299465.
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
| core | `4c83d1366b6706a20d9a2cc8276c0ad96ccd55f1a3e8a40d915026ad3fb4a419` / `4da3b45e91d44fbcf1a12d12737e61bf4512b6a6a2c6f88cdf098bb910a5c278` |
| I$ | `2ec3f5376634a8321ef2de183a8b5ca86ad8a3483fc4ed88f50cf3d943cc72b7` / `a1da34c85b579621966b1e89dd60248a8c63f080734aa53ad26d2e6cf5138acf` |
| D$ write-through | `4544fbf9ccad5ca1f62d9cd216abebe063afc0ffe68b6e0df8c2795ae2a359e2` / `942c1dda0a2ce3f0c76a909b70f30941b9e4f83519e75ec06b5483d363f6c5ba` |
| D$ write-back | `e8994c085b2b91f16df7b92be791a9bc50468264387c8d389f5f84d55c42d9a6` / `3834c564c2dcf047d40a5bd4678bf089e2d235044f54d6d1100f6010a6f5d9bb` |
<!-- portfolio:synthesis-hashes:end -->

<!-- portfolio:provenance:start -->
- Measurement timestamp: `2026-08-28T13:46:38Z`
- Tooling commit: `031fcd07c45b9fe59f6951fd0bafda275e6ce0d0`
- Frozen RTL commit: `3c7e84e392b345332d6acdd0ed899928dafb1058`
- Canonical container: `ghcr.io/huyhuy-bit/rv32i-verify:1`
- Open tools: Ubuntu 24.04; Verilator 5.048; RISC-V GCC 13.2.0-2024.04.12; RISC-V assembler 2.42; Python 3.12
- Vivado: 2025.2 build 6299465; `xc7a35ticsg324-1L`; measured 2026-08-28
- Reproduce verification: `make verify`
- Reproduce benchmarks: `make bench` with the recorded headline configuration
- Reproduce implementation: `make synth-matrix && make synth-summary`
<!-- portfolio:provenance:end -->

## Historical material

Earlier cache-geometry and inference experiments remain in the README and
microarchitecture document because they explain the design decisions. They are
explicitly labeled historical and are not mixed with the current matrices.
