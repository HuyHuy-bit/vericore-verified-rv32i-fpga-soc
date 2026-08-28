#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <top-module> <source>..." >&2
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
