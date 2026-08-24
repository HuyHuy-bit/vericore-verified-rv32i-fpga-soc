#!/usr/bin/env bash
# soak.sh [seeds] [instrs] — run random programs against the Python golden
# model (see tools/rv32i_model.py's docstring for why it's Python and not
# Spike) through the RTL, seed by seed. A failing seed is a self-contained
# bug report: rerun with the same seed to reproduce.
set -u

SEEDS="${1:-100}"
INSTRS="${2:-60}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM="$ROOT/obj_dir/Vcpu"
WORK="${TMPDIR:-/tmp}/rv32i_soak"
mkdir -p "$WORK"

if [ ! -x "$SIM" ]; then
    echo "error: $SIM not built - run 'make sim' first" >&2
    exit 1
fi

PASS=0
FAIL=0
for seed in $(seq 1 "$SEEDS"); do
    hexf="$WORK/s$seed.hex"
    reff="$WORK/s$seed.ref"
    python3 "$ROOT/tools/rand_gen.py" -n "$INSTRS" --seed "$seed" "$hexf" "$reff" 2>/dev/null
    cycles=$(grep '^cycles=' "$reff" | cut -d= -f2)

    if "$SIM" +MEMFILE="$hexf" +REFFILE="$reff" +STOP=selfloop +CYCLES="$cycles" +VCD= > "$WORK/s$seed.log" 2>&1; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL seed=$seed - program: $hexf, expected: $reff, log: $WORK/s$seed.log"
    fi
done

echo ""
echo "========== $PASS/$((PASS+FAIL)) random seeds passed (instrs=$INSTRS) =========="
[ "$FAIL" -eq 0 ]
