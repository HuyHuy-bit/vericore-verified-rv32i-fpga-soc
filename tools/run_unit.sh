#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <top-module> <source>..." >&2
    exit 2
fi

top=$1
shift
build_dir="obj_dir_unit_${top%_tb}"

verilator --binary --assert --timing -j 0 \
    --Mdir "$build_dir" --top-module "$top" "$@"
"./$build_dir/V$top"
