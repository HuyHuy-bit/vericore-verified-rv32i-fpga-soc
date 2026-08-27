#!/usr/bin/env bash
# Run the pinned RV32I architecture tests through complete Spike lockstep.
set -u -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" \
    || { echo "error: cannot resolve lockstep runner location" >&2; exit 1; }
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)" \
    || { echo "error: cannot resolve repository root" >&2; exit 1; }
VERSION_FILE="$REPO_ROOT/tools/reference_versions.env"
ARCH_TEST="${ARCH_TEST:-$HOME/riscv-arch-test}"
ARCH_TEST="${ARCH_TEST/#\~/$HOME}"
SPIKE="${SPIKE:-$HOME/projects/riscv-isa-sim/build/spike}"
SPIKE="${SPIKE/#\~/$HOME}"
SIM="${SIM:-$REPO_ROOT/obj_dir_lockstep/Vcpu}"
CYCLES="${CYCLES:-4000}"
LOCKSTEP_TIMEOUT="${LOCKSTEP_TIMEOUT:-300}"
SRC_DIR="$ARCH_TEST/riscv-test-suite/rv32i_m/I/src"
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

load_versions() {
    local line key value
    local seen_arch=0 seen_count=0 seen_spike=0
    [ -f "$VERSION_FILE" ] || die "reference version file missing: $VERSION_FILE"
    [ -r "$VERSION_FILE" ] || die "reference version file unreadable: $VERSION_FILE"
    ARCH_TEST_SHA=""; ARCH_TEST_EXPECTED=""; SPIKE_SHA=""
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in '' | \#*) continue ;; esac
        if [[ ! "$line" =~ ^([A-Z_][A-Z0-9_]*)=([^[:space:]#]+)$ ]]; then
            die "malformed reference version metadata: $VERSION_FILE"
        fi
        key="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
        case "$key" in
            ARCH_TEST_SHA)
                [ "$seen_arch" -eq 0 ] || die "duplicate reference version key: $key"
                ARCH_TEST_SHA="$value"; seen_arch=1 ;;
            ARCH_TEST_EXPECTED)
                [ "$seen_count" -eq 0 ] || die "duplicate reference version key: $key"
                ARCH_TEST_EXPECTED="$value"; seen_count=1 ;;
            SPIKE_SHA)
                [ "$seen_spike" -eq 0 ] || die "duplicate reference version key: $key"
                SPIKE_SHA="$value"; seen_spike=1 ;;
            *) die "malformed reference version metadata: unknown key $key" ;;
        esac
    done < "$VERSION_FILE"
    [[ "$ARCH_TEST_SHA" =~ ^[0-9a-f]{40}$ ]] \
        || die "malformed reference version metadata: ARCH_TEST_SHA"
    [[ "$SPIKE_SHA" =~ ^[0-9a-f]{40}$ ]] \
        || die "malformed reference version metadata: SPIKE_SHA"
    [[ "$ARCH_TEST_EXPECTED" =~ ^[1-9][0-9]*$ ]] \
        || die "malformed reference version metadata: ARCH_TEST_EXPECTED"
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"
}

load_versions
require_tool git
require_tool python3
require_tool riscv64-unknown-elf-gcc
[ -x "$SIM" ] || die "simulator is not executable: $SIM"
[ -x "$SPIKE" ] || die "Spike is not executable: $SPIKE"
[ -d "$SRC_DIR" ] || die "architecture-test source tree missing: $SRC_DIR"
[ -f "$REPO_ROOT/compliance/link/spike-lockstep.ld" ] || die "lockstep linker script missing"
[ -f "$REPO_ROOT/compliance/elf2hex.py" ] || die "elf2hex converter missing"
[ -f "$REPO_ROOT/tools/lockstep.py" ] || die "lockstep comparator missing"
[[ "$CYCLES" =~ ^[1-9][0-9]*$ ]] || die "CYCLES must be a positive integer"
[[ "$LOCKSTEP_TIMEOUT" =~ ^[0-9]+([.][0-9]+)?$ ]] \
    || die "LOCKSTEP_TIMEOUT must be a positive number"
[[ "$LOCKSTEP_TIMEOUT" =~ [1-9] ]] \
    || die "LOCKSTEP_TIMEOUT must be greater than zero"

arch_sha=$(git -C "$ARCH_TEST" rev-parse HEAD 2>/dev/null) \
    || die "cannot determine architecture-test checkout SHA: $ARCH_TEST"
[ "$arch_sha" = "$ARCH_TEST_SHA" ] \
    || die "architecture test checkout SHA mismatch: expected $ARCH_TEST_SHA, got $arch_sha"
spike_repo=$(git -C "$(dirname "$SPIKE")" rev-parse --show-toplevel 2>/dev/null) \
    || die "cannot determine Spike checkout for $SPIKE"
spike_sha=$(git -C "$spike_repo" rev-parse HEAD 2>/dev/null) \
    || die "cannot determine Spike checkout SHA: $spike_repo"
[ "$spike_sha" = "$SPIKE_SHA" ] \
    || die "Spike checkout SHA mismatch: expected $SPIKE_SHA, got $spike_sha"

mapfile -d '' -t SOURCES < <(find "$SRC_DIR" -maxdepth 1 -type f -name '*.S' -print0 | sort -z)
DISCOVERED=${#SOURCES[@]}
[ "$DISCOVERED" -gt 0 ] || die "no lockstep sources discovered in $SRC_DIR"
[ "$DISCOVERED" -eq "$ARCH_TEST_EXPECTED" ] \
    || die "discovered $DISCOVERED lockstep cases; expected $ARCH_TEST_EXPECTED"

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rv32i-lockstep-suite.XXXXXX") \
    || die "could not create lockstep suite directory"
PASS=0
FAIL=0
FAILED=()

for src in "${SOURCES[@]}"; do
    name=$(basename "$src" .S)
    case_dir="$WORK_DIR/$name"
    mkdir -p "$case_dir"
    elf="$case_dir/$name.elf"
    instr_hex="$case_dir/$name.instr.hex"
    data_hex="$case_dir/$name.data.hex"

    if ! riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -static -mcmodel=medany \
            -fvisibility=hidden -nostdlib -nostartfiles \
            -T "$REPO_ROOT/compliance/link/spike-lockstep.ld" \
            -I "$REPO_ROOT/compliance/riscv-target/rv32i-pipeline" \
            -I "$ARCH_TEST/riscv-test-env" -I "$ARCH_TEST/riscv-test-env/p" \
            -DXLEN=32 "$src" -o "$elf" 2> "$case_dir/compile.log"; then
        echo "FAIL  $name (compile error - see $case_dir/compile.log)"
        cat "$case_dir/compile.log"
        FAIL=$((FAIL + 1)); FAILED+=("$name (compile)"); continue
    fi

    if ! python3 "$REPO_ROOT/compliance/elf2hex.py" "$elf" \
            "$instr_hex" "$data_hex" > "$case_dir/elf2hex.log" 2>&1; then
        echo "FAIL  $name (elf2hex error - see $case_dir/elf2hex.log)"
        FAIL=$((FAIL + 1)); FAILED+=("$name (elf2hex)"); continue
    fi

    if SPIKE="$SPIKE" python3 "$REPO_ROOT/tools/lockstep.py" "$elf" \
            "$instr_hex" "$data_hex" --sim "$SIM" --cycles "$CYCLES" \
            --timeout "$LOCKSTEP_TIMEOUT" -q > "$case_dir/lockstep.log" 2>&1; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1)); FAILED+=("$name (lockstep)")
        echo "FAIL  $name (lockstep error - see $case_dir/lockstep.log)"
        cat "$case_dir/lockstep.log"
    fi
done

echo
echo "========== $PASS/$DISCOVERED programs match Spike instruction-for-instruction =========="
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "Failed: ${FAILED[*]}"
fi
[ "$FAIL" -eq 0 ] && [ "$PASS" -eq "$ARCH_TEST_EXPECTED" ]
