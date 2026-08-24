# Functional coverage report

**34/38 cover points hit (89.5%)**, from the directed test suite run against a cache-enabled build (`make coverage`).

| Cover point | Hits |
|---|---|
| `cpu.u_backend.c_branch_nottaken` | 99 |
| `cpu.u_backend.c_branch_taken` | 256 |
| `cpu.u_backend.c_cause_ebreak` | 1 |
| `cpu.u_backend.c_cause_ecall` | 1 |
| `cpu.u_backend.c_cause_illegal` | 4 |
| `cpu.u_backend.c_cause_mis_load` | 1 |
| `cpu.u_backend.c_cause_mis_store` | 1 |
| `cpu.u_backend.c_false_predict` | 0 **(unhit)** |
| `cpu.u_backend.c_jal` | 430 |
| `cpu.u_backend.c_jalr` | 32 |
| `cpu.u_backend.c_load_use_and_mispredict` | 0 **(unhit)** |
| `cpu.u_backend.c_mret` | 5 |
| `cpu.u_backend.c_pred_nn` | 53 |
| `cpu.u_backend.c_pred_nt` | 562 |
| `cpu.u_backend.c_pred_tn` | 46 |
| `cpu.u_backend.c_pred_tt_match` | 152 |
| `cpu.u_backend.c_pred_tt_mismatch` | 4 |
| `cpu.u_backend.c_trap_pending_and_stall` | 24 |
| `cpu.u_backend.g_dcache.u_dcache.c_dirty_evict` | 1 |
| `cpu.u_backend.g_dcache.u_dcache.c_hit_load` | 57 |
| `cpu.u_backend.g_dcache.u_dcache.c_hit_store` | 48 |
| `cpu.u_backend.g_dcache.u_dcache.c_miss_load` | 0 **(unhit)** |
| `cpu.u_backend.g_dcache.u_dcache.c_miss_store_alloc` | 29 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_fill` | 464 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_flush` | 5660 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_idle` | 3469 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_wb` | 140 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_fill_to_idle` | 29 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_flush_to_idle` | 0 **(unhit)** |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_flush_to_wb` | 6 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_fill` | 28 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_flush` | 22 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_wb` | 1 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_wb_to_fill` | 1 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_wb_to_flush` | 6 |
| `cpu.u_backend.g_fwd_a[*].g_fwd_b[0]` | 9543 |
| `cpu.u_backend.g_fwd_a[*].g_fwd_b[1]` | 135 |
| `cpu.u_backend.g_fwd_a[*].g_fwd_b[2]` | 55 |

## Unhit points

Each is reachable in principle; none is dead logic.

- `cpu.u_backend.c_false_predict` — requires a BTB alias: a non-control-flow instruction whose PC collides with a previously-taken branch's tag. Reachable only by constructing a specific PC collision, which random stimulus finds more naturally than a directed test.
- `cpu.u_backend.c_load_use_and_mispredict` — a load-use stall coincident with a mispredict in the same cycle. Needs a load feeding a branch's operand at exactly distance 1 with the branch mispredicting - a narrow window best reached by random stimulus.
- `cpu.u_backend.g_dcache.u_dcache.c_miss_load` — a load that misses with no dirty victim. t19 dirties every way before missing, so its misses all take the write-back path; an unmodified working set larger than the cache would hit this.
- `cpu.u_backend.g_dcache.u_dcache.c_trans_flush_to_idle` — the debug flush walk completing with no dirty line left to write back. The testbench flush always follows a dirty run, so it exits through FLUSH->WB rather than FLUSH->IDLE.
