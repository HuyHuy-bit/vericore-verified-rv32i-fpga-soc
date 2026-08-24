#!/usr/bin/env bash
# Run the pinned RV32I architecture-test signature suite strictly.
set -u -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" \
    || { echo "error: cannot resolve compliance runner location" >&2; exit 1; }
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)" \
    || { echo "error: cannot resolve repository root" >&2; exit 1; }
ARCH_TEST="${ARCH_TEST:-$HOME/riscv-arch-test}"
ARCH_TEST="${ARCH_TEST/#\~/$HOME}"
COMPLIANCE="$REPO_ROOT/compliance"
SIM="$REPO_ROOT/obj_dir/Vcpu"
CYCLES="${CYCLES:-2000}"
VERSION_FILE="$REPO_ROOT/tools/reference_versions.env"

SRC_DIR="$ARCH_TEST/riscv-test-suite/rv32i_m/I/src"
REF_DIR="$ARCH_TEST/riscv-test-suite/rv32i_m/I/references"
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

    ARCH_TEST_SHA=""
    ARCH_TEST_EXPECTED_CASES=""
    SPIKE_SHA=""
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            '' | \#*) continue ;;
        esac
        if [[ ! "$line" =~ ^([A-Z_][A-Z0-9_]*)=([^[:space:]#]+)$ ]]; then
            die "malformed reference version metadata: $VERSION_FILE"
        fi
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        case "$key" in
            ARCH_TEST_SHA)
                [ "$seen_arch" -eq 0 ] || die "duplicate reference version key: $key"
                ARCH_TEST_SHA="$value"; seen_arch=1 ;;
            ARCH_TEST_EXPECTED_CASES)
                [ "$seen_count" -eq 0 ] || die "duplicate reference version key: $key"
                ARCH_TEST_EXPECTED_CASES="$value"; seen_count=1 ;;
            SPIKE_SHA)
                [ "$seen_spike" -eq 0 ] || die "duplicate reference version key: $key"
                SPIKE_SHA="$value"; seen_spike=1 ;;
            *) die "malformed reference version metadata: unknown key $key" ;;
        esac
    done < "$VERSION_FILE"

    [[ "$ARCH_TEST_SHA" =~ ^[0-9a-f]{40}$ ]] || die "malformed reference version metadata: ARCH_TEST_SHA"
    [[ "$SPIKE_SHA" =~ ^[0-9a-f]{40}$ ]] || die "malformed reference version metadata: SPIKE_SHA"
    [[ "$ARCH_TEST_EXPECTED_CASES" =~ ^[1-9][0-9]*$ ]] || die "malformed reference version metadata: ARCH_TEST_EXPECTED_CASES"
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"
}

load_versions
require_tool riscv64-unknown-elf-gcc
require_tool riscv64-unknown-elf-nm
require_tool python3
require_tool diff
require_tool git
[ -x "$SIM" ] || die "simulator is not executable: $SIM"
[ -d "$SRC_DIR" ] || die "architecture-test source tree missing: $SRC_DIR"
[ -d "$REF_DIR" ] || die "architecture-test reference tree missing: $REF_DIR"
[ -f "$COMPLIANCE/link/rv32i-pipeline.ld" ] || die "target linker script missing"
[ -f "$COMPLIANCE/elf2hex.py" ] || die "elf2hex converter missing"
[ -f "$COMPLIANCE/riscv-target/rv32i-pipeline/model_test.h" ] || die "target model header missing"

checkout_sha=$(git -C "$ARCH_TEST" rev-parse HEAD 2>/dev/null) \
    || die "cannot determine architecture-test checkout SHA: $ARCH_TEST"
[ "$checkout_sha" = "$ARCH_TEST_SHA" ] \
    || die "architecture test checkout SHA mismatch: expected $ARCH_TEST_SHA, got $checkout_sha"

mapfile -d '' -t SOURCES < <(find "$SRC_DIR" -maxdepth 1 -type f -name '*.S' -print0 | sort -z)
DISCOVERED=${#SOURCES[@]}
[ "$DISCOVERED" -gt 0 ] || die "no compliance sources discovered in $SRC_DIR"
[ "$DISCOVERED" -eq "$ARCH_TEST_EXPECTED_CASES" ] \
    || die "discovered $DISCOVERED cases; expected $ARCH_TEST_EXPECTED_CASES"

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rv32i-compliance.XXXXXX") \
    || die "could not create compliance run directory"

PASS=0
FAIL=0
SKIPPED=0
INFRA_FAILURES=0
FAILED_TESTS=()

for src in "${SOURCES[@]}"; do
    name=$(basename "$src" .S)
    case_dir="$WORK_DIR/$name"
    mkdir -p "$case_dir"
    elf="$case_dir/$name.elf"
    instr_hex="$case_dir/$name.instr.hex"
    data_hex="$case_dir/$name.data.hex"
    sig_out="$case_dir/$name.sig.output"
    ref="$REF_DIR/$name.reference_output"

    if [ ! -f "$ref" ]; then
        echo "FAIL  $name (missing reference file)"
        SKIPPED=$((SKIPPED + 1)); INFRA_FAILURES=$((INFRA_FAILURES + 1))
        FAILED_TESTS+=("$name (missing reference)")
        continue
    fi

    if ! riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -static -mcmodel=medany \
        -fvisibility=hidden -nostdlib -nostartfiles \
        -T "$COMPLIANCE/link/rv32i-pipeline.ld" \
        -I "$COMPLIANCE/riscv-target/rv32i-pipeline" \
        -I "$ARCH_TEST/riscv-test-env" \
        -I "$ARCH_TEST/riscv-test-env/p" \
        -DXLEN=32 "$src" -o "$elf" 2> "$case_dir/compile.log"; then
        echo "FAIL  $name (compile error - see $case_dir/compile.log)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (compile)")
        continue
    fi

    if ! python3 "$COMPLIANCE/elf2hex.py" "$elf" "$instr_hex" "$data_hex" \
        > "$case_dir/elf2hex.log" 2>&1; then
        echo "FAIL  $name (elf2hex error - see $case_dir/elf2hex.log)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (elf2hex)")
        continue
    fi

    if ! begin_addr=$(riscv64-unknown-elf-nm "$elf" | awk '/ begin_signature$/{print $1}'); then
        echo "FAIL  $name (signature symbol lookup error)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (symbols)")
        continue
    fi
    if ! end_addr=$(riscv64-unknown-elf-nm "$elf" | awk '/ end_signature$/{print $1}'); then
        echo "FAIL  $name (signature symbol lookup error)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (symbols)")
        continue
    fi
    if [[ ! "$begin_addr" =~ ^[0-9A-Fa-f]+$ ]] || [[ ! "$end_addr" =~ ^[0-9A-Fa-f]+$ ]]; then
        echo "FAIL  $name (signature symbols missing)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (symbols)")
        continue
    fi
    begin_word=$(( (16#$begin_addr & 0xFFFF) / 4 ))
    end_word=$(( (16#$end_addr & 0xFFFF) / 4 ))

    rm -f "$sig_out"
    if ! "$SIM" +MEMFILE="$instr_hex" +DATAFILE="$data_hex" +REFFILE= \
        +STOP=selfloop +CYCLES="$CYCLES" +SIGSTART="$begin_word" +SIGEND="$end_word" \
        +SIGFILE="$sig_out" +VCD="$case_dir/wave.vcd" > "$case_dir/run.log" 2>&1; then
        echo "FAIL  $name (simulation error - see $case_dir/run.log)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (simulation)")
        continue
    fi

    if [ ! -s "$sig_out" ]; then
        echo "FAIL  $name (fresh nonempty signature missing - see $case_dir/run.log)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (signature)")
        continue
    fi

    diff -q "$sig_out" "$ref" > /dev/null
    diff_status=$?
    if [ "$diff_status" -eq 0 ]; then
        echo "PASS  $name"
        PASS=$((PASS + 1))
    elif [ "$diff_status" -eq 1 ]; then
        echo "FAIL  $name (signature mismatch)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (signature mismatch)")
    else
        echo "FAIL  $name (signature comparison error)"
        FAIL=$((FAIL + 1)); FAILED_TESTS+=("$name (comparison)")
    fi
done

echo
echo "========== discovered=$DISCOVERED passed=$PASS failed=$FAIL skipped/missing=$SKIPPED infrastructure=$INFRA_FAILURES =========="
if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
    echo "Failed: ${FAILED_TESTS[*]}"
fi

[ "$FAIL" -eq 0 ] && [ "$INFRA_FAILURES" -eq 0 ] && [ "$PASS" -eq "$ARCH_TEST_EXPECTED_CASES" ]
