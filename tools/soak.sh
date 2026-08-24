#!/usr/bin/env bash
# soak.sh [seeds] [instrs] — run random programs against the Python golden
# model (see tools/rv32i_model.py's docstring for why it's Python and not
# Spike) through the RTL, seed by seed. A failing seed is a self-contained
# bug report: rerun with the same seed to reproduce.
set -u

SEEDS="${1:-100}"
INSTRS="${2:-60}"
[[ "$SEEDS" =~ ^[1-9][0-9]*$ ]] \
    || { echo "error: SEEDS must be a positive integer" >&2; exit 1; }
[[ "$INSTRS" =~ ^[1-9][0-9]*$ ]] \
    || { echo "error: INSTRS must be a positive integer" >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM="$ROOT/obj_dir/Vcpu"
WORK_DIR=""

cleanup() {
    local status=$?
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        if [ "$status" -eq 0 ] && [ "${KEEP_WORK:-0}" != 1 ]; then
            rm -rf "$WORK_DIR"
        else
            echo "diagnostics retained in $WORK_DIR" >&2
        fi
    fi
}
trap cleanup EXIT

if [ ! -x "$SIM" ]; then
    echo "error: $SIM not built - run 'make sim' first" >&2
    exit 1
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rv32i-soak.XXXXXX") \
    || { echo "error: could not create random soak directory" >&2; exit 1; }

PASS=0
FAIL=0
for seed in $(seq 1 "$SEEDS"); do
    case_dir="$WORK_DIR/s$seed"
    mkdir -p "$case_dir"
    hexf="$case_dir/s$seed.hex"
    reff="$case_dir/s$seed.ref"
    if ! python3 "$ROOT/tools/rand_gen.py" -n "$INSTRS" --seed "$seed" "$hexf" "$reff" \
            > "$case_dir/generate.log" 2>&1; then
        FAIL=$((FAIL+1))
        echo "FAIL seed=$seed - random generation failed: $case_dir/generate.log"
        continue
    fi
    if [ ! -s "$hexf" ] || [ ! -s "$reff" ]; then
        FAIL=$((FAIL+1))
        echo "FAIL seed=$seed - generated files missing or empty: $case_dir"
        continue
    fi
    cycles=$(grep '^cycles=' "$reff" | cut -d= -f2)

    if "$SIM" +MEMFILE="$hexf" +REFFILE="$reff" +STOP=tohost +CYCLES="$cycles" +VCD= > "$case_dir/run.log" 2>&1; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL seed=$seed - program: $hexf, expected: $reff, log: $case_dir/run.log"
    fi
done

echo ""
echo "========== $PASS/$((PASS+FAIL)) random seeds passed (instrs=$INSTRS) =========="
[ "$FAIL" -eq 0 ] && [ "$PASS" -eq "$SEEDS" ]
