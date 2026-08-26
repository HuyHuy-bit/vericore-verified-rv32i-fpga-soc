# Evidence ledger

This ledger separates source-derived facts, pinned external inputs, historical
measurements, and results awaiting the final reproducible rerun. Current
measurement rows will record the date, exact RTL and tooling commits, command,
configuration, tool version, result, and any limitation.

The frozen RTL baseline is `2d9623f2a20396cf5559f0f676cb4889d74aeb3c`.
The final tooling commit and measurement date remain pending until the synthesis
wrapper and full measurement matrix are complete.

## Machine-checked facts

<!-- evidence-facts:begin -->
EVIDENCE_FACT ISA=RV32I_Zicsr_Zifencei
EVIDENCE_FACT DIRECTED_TESTS=25
EVIDENCE_FACT ASSERTIONS_TOTAL=27
EVIDENCE_FACT ASSERTIONS_CONCURRENT=25
EVIDENCE_FACT ASSERTIONS_IMMEDIATE=2
EVIDENCE_FACT SOURCE_COVER_POINTS=44
EVIDENCE_FACT TRACKED_COVERAGE_HIT=34
EVIDENCE_FACT TRACKED_COVERAGE_TOTAL=38
EVIDENCE_FACT TRACKED_COVERAGE_STATUS=historical
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

## Pending current measurements

| Evidence | Command or matrix | Status |
|---|---|---|
| Fast correctness | `make check` | Pending final recorded rerun |
| Directed simulation | Six named CI configurations, 25 programs each | Pending final recorded rerun |
| Python-model random | 1,000 baseline and 1,000 cached seeds | Pending final recorded rerun |
| Architecture signatures | `make compliance`, pinned 38 cases | Pending final recorded rerun |
| Spike architecture lockstep | `make lockstep`, pinned 38 cases | Pending final recorded rerun |
| Spike random lockstep | `make soak-lockstep SEEDS=200` | Pending final recorded rerun |
| Functional coverage | `make coverage` | Tracked 34/38 report is historical; current 44-point rerun pending |
| Benchmarks | Four specified memory/cache configurations | Pending final recorded rerun |
| FPGA routes | `make synth-matrix` and `make synth-summary`, four 512-word configurations | Pending final recorded rerun |

## Historical material

The performance, cache-geometry, and FPGA tables retained in the README and
microarchitecture document predate this ledger. They remain useful design
studies but are not current headline evidence until replaced by the final
matrix. Their provenance limitations are labeled where they appear.
