#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 1 ]]; then
    unit_name=$1
    repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
    case "$unit_name" in
        core_external)
            set -- "$unit_name" \
                "$repo_root/rtl/rv32i_pkg.sv" \
                "$repo_root/rtl/core/rv32i_core.sv" \
                "$repo_root/rtl/core/frontend.sv" \
                "$repo_root/rtl/core/backend.sv" \
                "$repo_root/rtl/core/pc.sv" \
                "$repo_root/rtl/core/reg_file.sv" \
                "$repo_root/rtl/core/imm_gen.sv" \
                "$repo_root/rtl/core/alu.sv" \
                "$repo_root/rtl/core/control.sv" \
                "$repo_root/rtl/core/branch_unit.sv" \
                "$repo_root/rtl/core/if_id_reg.sv" \
                "$repo_root/rtl/core/id_ex_reg.sv" \
                "$repo_root/rtl/core/ex_mem_reg.sv" \
                "$repo_root/rtl/core/mem_wb_reg.sv" \
                "$repo_root/rtl/core/forwarding_unit.sv" \
                "$repo_root/rtl/core/hazard_detect.sv" \
                "$repo_root/rtl/core/branch_predictor.sv" \
                "$repo_root/rtl/core/ras.sv" \
                "$repo_root/rtl/core/csr.sv" \
                "$repo_root/rtl/memory/icache.sv" \
                "$repo_root/rtl/memory/lsu.sv" \
                "$repo_root/rtl/memory/dcache.sv" \
                "$repo_root/rtl/core/perf_counters.sv" \
                "$repo_root/sim/unit/core_external_tb.sv"
            ;;
        csr_external_irq)
            set -- "$unit_name" \
                "$repo_root/rtl/rv32i_pkg.sv" \
                "$repo_root/rtl/core/csr.sv" \
                "$repo_root/sim/unit/csr_external_irq_tb.sv"
            ;;
        wb_master_adapter)
            set -- wb_master_adapter_tb \
                "$repo_root/rtl/bus/wb_master_adapter.sv" \
                "$repo_root/sim/unit/wb_master_adapter_tb.sv"
            ;;
        wb_arbiter)
            set -- wb_arbiter_tb \
                "$repo_root/rtl/bus/wb_arbiter.sv" \
                "$repo_root/sim/unit/wb_arbiter_tb.sv"
            ;;
        wb_interconnect)
            set -- wb_interconnect_tb \
                "$repo_root/rtl/soc/wb_interconnect.sv" \
                "$repo_root/sim/unit/wb_interconnect_tb.sv"
            ;;
    esac
fi

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <registered-test> | <top-module> <source>..." >&2
    exit 2
fi

top=$1
shift
[[ "$top" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "invalid top module: $top" >&2
    exit 2
}
unit_build_dir=$(mktemp -d "${TMPDIR:-/tmp}/rv32i-unit-${top}.XXXXXX")
trap 'rm -rf -- "$unit_build_dir"' EXIT

verilator --binary --assert --timing -j 0 \
    --Mdir "$unit_build_dir" --top-module "$top" "$@"
"$unit_build_dir/V$top"
