# Functional coverage report

**Evidence status: historical.**

**44/44 cover points hit (100.0%)**, from the directed suite and deterministic BTB-alias fixture run against a cache-enabled build (`make coverage`).

SoC unit and integration checks are not part of this core coverage database.

| Cover point | Hits |
|---|---|
| `cpu.u_backend.c_branch_nottaken` | 216 |
| `cpu.u_backend.c_branch_taken` | 281 |
| `cpu.u_backend.c_cause_ebreak` | 1 |
| `cpu.u_backend.c_cause_ecall` | 1 |
| `cpu.u_backend.c_cause_illegal` | 20 |
| `cpu.u_backend.c_cause_mis_load` | 1 |
| `cpu.u_backend.c_cause_mis_store` | 1 |
| `cpu.u_backend.c_false_predict` | 2 |
| `cpu.u_backend.c_fwd_a0_b0` | 12241 |
| `cpu.u_backend.c_fwd_a0_b1` | 130 |
| `cpu.u_backend.c_fwd_a0_b2` | 44 |
| `cpu.u_backend.c_fwd_a1_b0` | 959 |
| `cpu.u_backend.c_fwd_a1_b1` | 28 |
| `cpu.u_backend.c_fwd_a1_b2` | 17 |
| `cpu.u_backend.c_fwd_a2_b0` | 138 |
| `cpu.u_backend.c_fwd_a2_b1` | 66 |
| `cpu.u_backend.c_fwd_a2_b2` | 2 |
| `cpu.u_backend.c_jal` | 205 |
| `cpu.u_backend.c_jalr` | 34 |
| `cpu.u_backend.c_load_use_and_mispredict` | 1 |
| `cpu.u_backend.c_mret` | 23 |
| `cpu.u_backend.c_pred_nn` | 162 |
| `cpu.u_backend.c_pred_nt` | 330 |
| `cpu.u_backend.c_pred_tn` | 54 |
| `cpu.u_backend.c_pred_tt_match` | 186 |
| `cpu.u_backend.c_pred_tt_mismatch` | 4 |
| `cpu.u_backend.c_trap_pending_and_stall` | 97 |
| `cpu.u_backend.g_dcache.u_dcache.c_dirty_evict` | 2 |
| `cpu.u_backend.g_dcache.u_dcache.c_hit_load` | 76 |
| `cpu.u_backend.g_dcache.u_dcache.c_hit_store` | 43 |
| `cpu.u_backend.g_dcache.u_dcache.c_miss_load` | 1 |
| `cpu.u_backend.g_dcache.u_dcache.c_miss_store_alloc` | 9 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_fill` | 160 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_flush` | 6689 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_idle` | 6596 |
| `cpu.u_backend.g_dcache.u_dcache.c_state_wb` | 180 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_fill_to_idle` | 10 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_flush_to_idle` | 26 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_flush_to_wb` | 7 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_fill` | 8 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_flush` | 26 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_idle_to_wb` | 2 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_wb_to_fill` | 2 |
| `cpu.u_backend.g_dcache.u_dcache.c_trans_wb_to_flush` | 7 |
