#!/usr/bin/env bash
# Generate random programs and require complete Spike/RTL lockstep per seed.
set -u -o pipefail

SEEDS="${1:-50}"
INSTRS="${2:-60}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)" \
    || { echo "error: cannot resolve repository root" >&2; exit 1; }
SIM="${SIM:-$ROOT/obj_dir_lockstep/Vcpu}"
SPIKE="${SPIKE:-$HOME/projects/riscv-isa-sim/build/spike}"
SPIKE="${SPIKE/#\~/$HOME}"
CYCLES="${CYCLES:-4000}"
LOCKSTEP_TIMEOUT="${LOCKSTEP_TIMEOUT:-300}"
VERSION_FILE="$ROOT/tools/reference_versions.env"
WORK_DIR=""

die() {
    echo "error: $*" >&2
    exit 1
}

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

load_spike_pin() {
    local line key value seen_spike=0
    [ -f "$VERSION_FILE" ] || die "reference version file missing: $VERSION_FILE"
    [ -r "$VERSION_FILE" ] || die "reference version file unreadable: $VERSION_FILE"
    SPIKE_SHA=""
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in '' | \#*) continue ;; esac
        if [[ ! "$line" =~ ^([A-Z_][A-Z0-9_]*)=([^[:space:]#]+)$ ]]; then
            die "malformed reference version metadata: $VERSION_FILE"
        fi
        key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
        case "$key" in
            SPIKE_SHA)
                [ "$seen_spike" -eq 0 ] || die "duplicate reference version key: $key"
                SPIKE_SHA="$value"; seen_spike=1 ;;
            ARCH_TEST_SHA | ARCH_TEST_EXPECTED_CASES) ;;
            *) die "malformed reference version metadata: unknown key $key" ;;
        esac
    done < "$VERSION_FILE"
    [[ "$SPIKE_SHA" =~ ^[0-9a-f]{40}$ ]] \
        || die "malformed reference version metadata: SPIKE_SHA"
}

[[ "$SEEDS" =~ ^[1-9][0-9]*$ ]] || die "SEEDS must be a positive integer"
[[ "$INSTRS" =~ ^[1-9][0-9]*$ ]] || die "INSTRS must be a positive integer"
[[ "$CYCLES" =~ ^[1-9][0-9]*$ ]] || die "CYCLES must be a positive integer"
[[ "$LOCKSTEP_TIMEOUT" =~ ^[0-9]+([.][0-9]+)?$ ]] \
    || die "LOCKSTEP_TIMEOUT must be a positive number"
[[ "$LOCKSTEP_TIMEOUT" =~ [1-9] ]] \
    || die "LOCKSTEP_TIMEOUT must be greater than zero"
command -v git >/dev/null 2>&1 || die "required tool not found: git"
command -v python3 >/dev/null 2>&1 || die "required tool not found: python3"
command -v riscv64-unknown-elf-gcc >/dev/null 2>&1 \
    || die "required tool not found: riscv64-unknown-elf-gcc"
[ -x "$SIM" ] || die "simulator is not executable: $SIM"
[ -x "$SPIKE" ] || die "Spike is not executable: $SPIKE"
[ -f "$ROOT/tools/rand_gen.py" ] || die "random generator missing"
[ -f "$ROOT/compliance/link/spike-lockstep.ld" ] || die "lockstep linker script missing"
[ -f "$ROOT/compliance/elf2hex.py" ] || die "elf2hex converter missing"
[ -f "$ROOT/tools/lockstep.py" ] || die "lockstep comparator missing"
load_spike_pin

spike_repo=$(git -C "$(dirname "$SPIKE")" rev-parse --show-toplevel 2>/dev/null) \
    || die "cannot determine Spike checkout for $SPIKE"
spike_sha=$(git -C "$spike_repo" rev-parse HEAD 2>/dev/null) \
    || die "cannot determine Spike checkout SHA: $spike_repo"
[ "$spike_sha" = "$SPIKE_SHA" ] \
    || die "Spike checkout SHA mismatch: expected $SPIKE_SHA, got $spike_sha"

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rv32i-soak-lockstep.XXXXXX") \
    || die "could not create random lockstep directory"
PASS=0
FAIL=0
FAILED=()

for seed in $(seq 1 "$SEEDS"); do
    case_dir="$WORK_DIR/s$seed"
    mkdir -p "$case_dir"
    asm="$case_dir/s$seed.S"
    elf="$case_dir/s$seed.elf"
    instr_hex="$case_dir/s$seed.instr.hex"
    data_hex="$case_dir/s$seed.data.hex"

    if ! python3 "$ROOT/tools/rand_gen.py" -n "$INSTRS" --seed "$seed" --spike \
            "$asm" > "$case_dir/generate.log" 2>&1; then
        echo "FAIL seed=$seed (random generation error - see $case_dir/generate.log)"
        FAIL=$((FAIL + 1)); FAILED+=("$seed (generate)"); continue
    fi

    if ! riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -static -mcmodel=medany \
            -fvisibility=hidden -nostdlib -nostartfiles \
            -T "$ROOT/compliance/link/spike-lockstep.ld" \
            "$asm" -o "$elf" 2> "$case_dir/compile.log"; then
        echo "FAIL seed=$seed (compile error - see $case_dir/compile.log)"
        FAIL=$((FAIL + 1)); FAILED+=("$seed (compile)"); continue
    fi

    if ! python3 "$ROOT/compliance/elf2hex.py" "$elf" "$instr_hex" "$data_hex" \
            > "$case_dir/elf2hex.log" 2>&1; then
        echo "FAIL seed=$seed (elf2hex error - see $case_dir/elf2hex.log)"
        FAIL=$((FAIL + 1)); FAILED+=("$seed (elf2hex)"); continue
    fi

    if SPIKE="$SPIKE" python3 "$ROOT/tools/lockstep.py" "$elf" "$instr_hex" \
            "$data_hex" --sim "$SIM" --cycles "$CYCLES" \
            --timeout "$LOCKSTEP_TIMEOUT" -q > "$case_dir/lockstep.log" 2>&1; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1)); FAILED+=("$seed (lockstep)")
        echo "FAIL seed=$seed (lockstep error - see $case_dir/lockstep.log)"
        cat "$case_dir/lockstep.log"
    fi
done

echo
echo "========== $PASS/$SEEDS random seeds match Spike (instrs=$INSTRS) =========="
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "Failed seeds: ${FAILED[*]}"
fi
[ "$FAIL" -eq 0 ] && [ "$PASS" -eq "$SEEDS" ]
