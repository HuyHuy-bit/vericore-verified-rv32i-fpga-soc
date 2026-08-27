# Evidence ledger

This ledger separates source-derived facts, pinned external inputs, current
measurements, and historical design studies. Simulation and benchmark results
were collected on 2026-08-26 local time; Vivado manifests record 2026-08-27
UTC. The source/tooling commit is
`7a34fc7e292365915687040ad1db549a2dfdb754`, and the frozen RTL baseline is
`c0a95a3a4a33d3f5611f017cb9b8c454f1d13319`.

The host was Ubuntu 22.04.5 under WSL2. Tools were Verilator 5.048
(`v5.048-56-gc233a3905`), Python 3.10.12, RISC-V GCC 10.2.0 with GNU assembler
2.35.1, pinned Spike `55b4658dbf574ba0b714083ec436ce2cb5be1998`, and
Vivado 2025.2 build 6299465.

## Machine-checked facts

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

These values are checked against the Make test list and on-disk pairs, RTL
assertions and covers, workflow matrix and seed command, coverage report, and
central reference metadata by `make evidence-check`.

## Current verification measurements

| Evidence | Command or configuration | Result |
|---|---|---|
| Fast correctness | `make check` | Pass: decoder 2,120 cases; hazard 262,144 cases; harness 102 tests; lint and evidence checks clean |
| Directed simulation | `make test` in baseline, slow-memory, I$-only, write-through, write-back, and associative configurations | 25/25 in each; 150/150 total |
| Python-model random | `make soak SEEDS=1000` | 1,000/1,000 baseline |
| Python-model random, cached | `make soak SEEDS=1000 IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1` | 1,000/1,000 |
| Architecture signatures | `make compliance` | 38/38 against pinned `riscv-arch-test` |
| Spike architecture lockstep | `make lockstep` | 38/38 complete retirement traces |
| Spike random lockstep | `make soak-lockstep SEEDS=200` | 200/200, 60 generated instructions per seed |
| Functional coverage | `make coverage` | user 44/44 (100%); line 260/278; branch 186/198; expression 202/221 |

The six directed configurations were baseline; `IMEM_LAT=10 DMEM_LAT=10`;
1KB four-way I$; that I$ plus a 4KB four-way write-through D$; the same with a
write-back D$; and a two-way associative I$/D$ variant. All slow-memory cache
rows used 10-cycle instruction and data backing memory.

## Current benchmark measurements

Each row below passed its host-oracle result check. `make bench` selected the
exact simulator built for the listed parameters.

| Kernel | 10-cycle, uncached | +1KB 4-way I$ | +4KB 4-way write-back D$ | 1-cycle, uncached |
|---|---:|---:|---:|---:|
| crc32 | 699,094 cycles / 11.3618 CPI | 160,026 / 2.60078 | 142,114 / 2.30967 | 71,776 / 1.16652 |
| matmul | 3,463,179 / 11.3948 | 782,697 / 2.57529 | 704,262 / 2.31722 | 357,306 / 1.17563 |
| sort | 2,521,051 / 12.4833 | 1,038,463 / 5.14208 | 504,847 / 2.49981 | 252,106 / 1.24833 |
| llist | 932,261 / 10.0023 | 465,080 / 4.98986 | 188,616 / 2.02367 | 93,227 / 1.00024 |
| interp | 14,644,581 / 11.8821 | 4,474,900 / 3.63078 | 2,930,114 / 2.37740 | 1,464,459 / 1.18821 |

Commands were `make bench IMEM_LAT=10 DMEM_LAT=10`; the same with
`IC_BYTES=1024 IC_WAYS=4`; the same with `DC_BYTES=4096 DC_WAYS=4 DC_WB=1`;
and plain `make bench` for ideal one-cycle uncached memory.

## Current synthesis measurements

`make synth-matrix` and `make synth-summary` routed four configurations with
512-word instruction/data backing memories on `xc7a35ticsg324-1L`. The 2 ns
constraint is intentionally aggressive; all WNS values are negative, so these
are routed critical-path estimates rather than timing closure claims.

| Configuration | LUT | FF | BRAM tiles | WNS | Critical path | fmax |
|---|---:|---:|---:|---:|---:|---:|
| core | 4,031 | 5,220 | 0.5 | −11.111 ns | 13.111 ns | 76.272 MHz |
| 1KB four-way I$ | 5,011 | 6,970 | 2 | −11.563 ns | 13.563 ns | 73.730 MHz |
| +4KB four-way write-through D$ | 8,800 | 13,527 | 4 | −12.172 ns | 14.172 ns | 70.562 MHz |
| +4KB four-way write-back D$ | 9,218 | 13,517 | 4 | −11.920 ns | 13.920 ns | 71.839 MHz |

The ignored manifests bind every route to the source and RTL commits above.
The SHA-256 pairs below are `utilization.rpt` / `timing_summary.rpt`:

| Configuration | Report hashes |
|---|---|
| core | `8678a9ac835a8fb3b627da56d5966fba9628b8750acd319e971abd92378fb4ef` / `707ff217af00e4911d21d21391a4bbf6d6dff7a39dee27a18ff22db7318686e7` |
| I$ | `9c4ccc72945626942e635035a2738b4d868243901b71172dc017ed976ab2fd96` / `a49b9623d1b362e7b96802c9fdf78ad7d2b4e8fd783a3163c798a9a8bb877d90` |
| D$ write-through | `145fb0856275c4390bbe067c33fee4913ecc958ef55793feceb5c5739013404c` / `0ec010407093f5571264a3322992ab9ccbb19538ee178014478e9f29eaa09f0f` |
| D$ write-back | `61701ff07c81611f25774c1b81c0e79479d666be32c4b09dd23262119b0d5f8d` / `d9e6a7b376809d8520df9e2f5c3953c19c8da5fe415e353427ca3f93f5fef219` |

## Historical material

Earlier cache-geometry and inference experiments remain in the README and
microarchitecture document because they explain the design decisions. They are
explicitly labeled historical and are not mixed with the current matrices.
