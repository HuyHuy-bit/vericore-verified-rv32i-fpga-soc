#!/usr/bin/env python3
"""Black-box contract tests for the RV32I simulator harness.

The fixtures use only Python's standard library and tiny temporary programs.
They intentionally exercise the simulator CLI rather than its implementation.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIM = Path(os.environ.get("SIM", ROOT / "obj_dir" / "Vcpu"))
REFERENCE_VERSIONS = dict(
    line.split("=", 1)
    for line in (ROOT / "tools/reference_versions.env").read_text().splitlines()
    if line and not line.startswith("#")
)

TOHOST_PASS = "00100f93\n00010f37\nff0f0f13\n01ff2023\n0000006f\n"
TOHOST_FAIL = "00200f93\n00010f37\nff0f0f13\n01ff2023\n0000006f\n"
SELF_LOOP = "0000006f\n"
WRONG_LOOP = "000000ef\n"
LOAD_USE = """02a00093
00102023
00002103
00110113
06400193
00302223
00402203
004202b3
00500313
0c800393
00702423
00802403
00640433
00100f93
00010f37
ff0f0f13
01ff2023
0000006f
"""
MEMORY = """02a00093
00102023
00002103
fff00193
00301223
00401203
00405283
fff00313
00600423
00800383
00804403
06400493
00902623
00c02503
00100f93
00010f37
ff0f0f13
01ff2023
0000006f
"""


class HarnessTest(unittest.TestCase):
    """Exercise observable simulator contracts with real temporary inputs."""

    def setUp(self):
        if not SIM.is_file() or not os.access(SIM, os.X_OK):
            self.fail(f"simulator is not executable: {SIM}; run make sim first")
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-harness-")
        self.work = Path(self.tmp.name)
        self.pass_hex = self.write("pass.hex", TOHOST_PASS)
        self.fail_hex = self.write("fail.hex", TOHOST_FAIL)
        self.loop_hex = self.write("loop.hex", SELF_LOOP)
        self.wrong_loop_hex = self.write("wrong-loop.hex", WRONG_LOOP)
        self.load_use_hex = self.write("load-use.hex", LOAD_USE)
        self.memory_hex = self.write("memory.hex", MEMORY)
        self.valid_ref = self.write("valid.ref", "cycles=20\n")
        self.memory_ref = self.write(
            "memory.ref",
            "cycles=20\nx2=42\nx4=0xFFFFFFFF\nx5=65535\nx7=0xFFFFFFFF\nx8=255\nx10=100\n",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, contents):
        path = self.work / name
        path.write_text(contents)
        return path

    def invoke(self, *args):
        return subprocess.run(
            [str(SIM), f"+MEMFILE={self.pass_hex}", "+VCD=", *args],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )

    def assert_failure(self, result, diagnostic):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)

    def reference_failure(self, contents, diagnostic):
        ref = self.write("invalid.ref", contents)
        result = self.invoke("+STOP=tohost", "+CYCLES=20", f"+REFFILE={ref}")
        self.assert_failure(result, diagnostic)

    # A permissive parser would turn every case below into an empty or partial
    # comparison and accidentally pass it.
    def test_missing_reference_is_rejected(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20",
                          f"+REFFILE={self.work / 'missing.ref'}")
        self.assert_failure(result, "error: cannot read reference file")

    def test_empty_reference_is_rejected(self):
        self.reference_failure("", "error: empty reference file")

    def test_malformed_reference_is_rejected(self):
        self.reference_failure("cycles=20oops\n", "error: malformed reference entry")

    def test_duplicate_reference_is_rejected(self):
        self.reference_failure("cycles=20\ncycles=21\n", "error: duplicate reference key: cycles")

    def test_unknown_reference_is_rejected(self):
        self.reference_failure("cycles=20\npc=0\n", "error: unknown reference key: pc")

    def test_out_of_range_reference_is_rejected(self):
        self.reference_failure("cycles=20\nx32=0\n", "error: reference register out of range: x32")

    def test_signed_and_overflowed_reference_values_are_rejected(self):
        for contents in ("cycles=-1\n", "cycles=4294967296\n", "x1=0x100000000\n"):
            with self.subTest(contents=contents):
                self.reference_failure(contents, "error: invalid unsigned reference value")

    # These catch the old implicit/default plusarg behavior.
    def test_missing_run_mode_is_rejected(self):
        result = self.invoke("+CYCLES=20", f"+REFFILE={self.valid_ref}")
        self.assert_failure(result, "error: exactly one run mode is required")

    def test_unknown_run_mode_is_rejected(self):
        result = self.invoke("+STOP=park", "+CYCLES=20", f"+REFFILE={self.valid_ref}")
        self.assert_failure(result, "error: unknown stop mode: park")

    def test_duplicate_run_mode_is_rejected(self):
        result = self.invoke("+STOP=tohost", "+STOP=tohost", "+CYCLES=20",
                          f"+REFFILE={self.valid_ref}")
        self.assert_failure(result, "error: duplicate run mode")

    def test_mutually_exclusive_run_modes_are_rejected(self):
        result = self.invoke("+STOP=tohost", "+SNAPSHOT=1", "+CYCLES=20",
                          f"+REFFILE={self.valid_ref}")
        self.assert_failure(result, "error: mutually exclusive run modes")

    def test_snapshot_requires_an_explicit_cycle_count(self):
        result = self.invoke("+SNAPSHOT=1")
        self.assert_failure(result, "error: snapshot mode requires +CYCLES=N")

    def test_verification_requires_a_result_consumer(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20")
        self.assert_failure(result, "error: verification mode requires a result consumer")

    # These tests name terminal/result failures independently, so a later
    # successful reference comparison cannot erase an earlier failure.
    def test_non_success_tohost_is_a_failure(self):
        ref = self.write("pass.ref", "cycles=20\n")
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.fail_hex}", "+VCD=", "+STOP=tohost",
             "+CYCLES=20", f"+REFFILE={ref}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assert_failure(result, "error: tohost completion value is not 1")

    def test_selfloop_requires_the_retired_sentinel(self):
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.wrong_loop_hex}", "+VCD=", "+STOP=selfloop",
             "+CYCLES=4", f"+RVFI_TRACE={self.work / 'wrong.rvfi'}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assert_failure(result, "error: timeout waiting for retired self-loop sentinel")

    def test_tohost_timeout_is_a_failure(self):
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.loop_hex}", "+VCD=", "+STOP=tohost",
             "+CYCLES=4", f"+RVFI_TRACE={self.work / 'timeout.rvfi'}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assert_failure(result, "error: timeout waiting for tohost completion")

    def test_failed_cache_drain_is_a_failure(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20", "+SIGFILE=/dev/null",
                          "+TEST_FORCE_CACHE_DRAIN_TIMEOUT=1")
        self.assert_failure(result, "error: cache drain deadline exhausted")

    def test_result_output_open_failure_is_a_failure(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20",
                          f"+SIGFILE={self.work / 'absent' / 'sig'}")
        self.assert_failure(result, "error: cannot open signature output")

    def test_result_output_write_failure_is_a_failure(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20", "+SIGFILE=/dev/full", "+SIGEND=1")
        self.assert_failure(result, "error: failed writing signature output")

    def test_successful_tohost_reference_and_stalls_check(self):
        ref = self.write("valid.ref", "cycles=30\nstalls=3\nx1=42\nx8=205\n")
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.load_use_hex}", "+VCD=", "+STOP=tohost",
             "+CYCLES=30", f"+REFFILE={ref}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  stalls", result.stdout)

    def test_mismatched_load_use_stalls_are_a_failure(self):
        ref = self.write("wrong-stalls.ref", "cycles=30\nstalls=2\nx1=42\nx8=205\n")
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.load_use_hex}", "+VCD=", "+STOP=tohost",
             "+CYCLES=30", f"+REFFILE={ref}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assert_failure(result, "error: reference mismatch for stalls")

    def test_verification_cycle_budget_allows_directed_tohost_headroom(self):
        """The legacy reference value remains an explicit verified-run budget."""
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.memory_hex}", "+VCD=", "+STOP=tohost",
             "+CYCLES=20", f"+REFFILE={self.memory_ref}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_successful_retired_selfloop_writes_terminal_rvfi_record(self):
        trace = self.work / "loop.rvfi"
        result = subprocess.run(
            [str(SIM), f"+MEMFILE={self.loop_hex}", "+VCD=", "+STOP=selfloop",
             "+CYCLES=4", f"+RVFI_TRACE={trace}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(trace.read_text().splitlines()[-1].split()[1] == "0000006f")

    def test_snapshot_is_explicitly_non_verifying(self):
        result = self.invoke("+SNAPSHOT=1", "+CYCLES=1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SNAPSHOT DEBUG RUN (non-verifying)", result.stdout)
        self.assertNotIn("PASS", result.stdout)

    def test_snapshot_never_claims_a_reference_pass(self):
        ref = self.write("snapshot.ref", "cycles=20\nx31=1\n")
        result = self.invoke("+SNAPSHOT=1", "+CYCLES=6", f"+REFFILE={ref}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SNAPSHOT DEBUG RUN (non-verifying)", result.stdout)
        self.assertNotIn("PASS", result.stdout)


class ComplianceRunnerTest(unittest.TestCase):
    """Exercise the compliance runner with a one-case, fake toolchain."""

    PINNED_ARCH_SHA = REFERENCE_VERSIONS["ARCH_TEST_SHA"]
    PINNED_SPIKE_SHA = REFERENCE_VERSIONS["SPIKE_SHA"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-compliance-fixture-")
        self.work = Path(self.tmp.name)
        self.arch = self.work / "riscv-arch-test"
        self.src_dir = self.arch / "riscv-test-suite/rv32i_m/I/src"
        self.ref_dir = self.arch / "riscv-test-suite/rv32i_m/I/references"
        self.src_dir.mkdir(parents=True)
        self.ref_dir.mkdir(parents=True)
        (self.arch / "riscv-test-env/p").mkdir(parents=True)
        self.src = self.src_dir / "case.S"
        self.src.write_text("nop\n")
        self.ref = self.ref_dir / "case.reference_output"
        self.ref.write_text("00000000\n")
        self.versions = self.work / "reference_versions.env"
        self.write_versions()

        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.sim = self.bin_dir / "fake-sim"
        self.write_tools()
        self.env = os.environ.copy()
        self.env.update({
            "ARCH_TEST": str(self.arch),
            "REPO_ROOT": str(ROOT),
            "REFERENCE_VERSIONS": str(self.versions),
            "SIM": str(self.sim),
            "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            "REAL_PYTHON": sys.executable,
            "FAKE_GIT_SHA": self.PINNED_ARCH_SHA,
            "FAKE_SIGNATURE": "00000000\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def write_versions(self, contents=None):
        self.versions.write_text(contents or (
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED_CASES=1\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        ))

    def write_tools(self):
        self.write(self.bin_dir / "riscv64-unknown-elf-gcc", """#!/usr/bin/env bash
set -eu
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then touch "$2"; exit 0; fi
    shift
done
exit 2
""")
        self.write(self.bin_dir / "riscv64-unknown-elf-nm", """#!/usr/bin/env bash
if [ "${FAKE_NM_MODE:-ok}" = crash ]; then exit 7; fi
printf '%s\\n' '00000000 T begin_signature' '00000004 T end_signature'
""")
        self.write(self.bin_dir / "python3", """#!/usr/bin/env bash
set -eu
if [ "${1##*/}" = elf2hex.py ]; then
    printf '00000013\\n' > "$3"
    : > "$4"
    exit "${FAKE_ELF2HEX_RC:-0}"
fi
exec "$REAL_PYTHON" "$@"
""")
        self.write(self.bin_dir / "git", """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$FAKE_GIT_SHA"
""")
        self.write(self.bin_dir / "diff", """#!/usr/bin/env bash
if [ "${FAKE_DIFF_MODE:-ok}" = crash ]; then exit 2; fi
exec /usr/bin/diff "$@"
""")
        self.write(self.sim, """#!/usr/bin/env bash
set -eu
sig=
for arg in "$@"; do
    case "$arg" in +SIGFILE=*) sig="${arg#'+SIGFILE='}" ;; esac
done
if [ "${FAKE_SIM_MODE:-ok}" = crash ]; then
    [ -z "$sig" ] || printf 'stale\\n' > "$sig"
    exit 7
fi
[ -z "$sig" ] || printf '%s' "$FAKE_SIGNATURE" > "$sig"
""")

    def run_runner(self):
        return subprocess.run(
            [str(ROOT / "compliance/run_compliance.sh")], cwd=ROOT, env=self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )

    def assert_runner_failure(self, diagnostic):
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)

    # Each test names a preflight or case-result branch that a permissive
    # runner would turn into a zero-status compliance result.
    def test_compliance_rejects_missing_version_metadata(self):
        self.env["REFERENCE_VERSIONS"] = str(self.work / "missing.env")
        self.assert_runner_failure("error: reference version file missing")

    def test_compliance_rejects_malformed_version_metadata(self):
        self.write_versions("ARCH_TEST_SHA=not-a-sha\n")
        self.assert_runner_failure("error: malformed reference version metadata")

    def test_compliance_rejects_duplicate_version_metadata(self):
        self.write_versions(
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED_CASES=1\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        )
        self.assert_runner_failure("error: duplicate reference version key: ARCH_TEST_SHA")

    def test_compliance_rejects_simulator_crash_with_stale_signature(self):
        self.env["FAKE_SIM_MODE"] = "crash"
        self.assert_runner_failure("FAIL  case (simulation error")

    def test_compliance_rejects_missing_reference(self):
        self.ref.unlink()
        self.assert_runner_failure("FAIL  case (missing reference")

    def test_compliance_rejects_mismatched_signature(self):
        self.env["FAKE_SIGNATURE"] = "ffffffff\n"
        self.assert_runner_failure("FAIL  case (signature mismatch)")

    def test_compliance_rejects_signature_symbol_lookup_failure(self):
        self.env["FAKE_NM_MODE"] = "crash"
        self.assert_runner_failure("FAIL  case (signature symbol lookup error")

    def test_compliance_rejects_signature_comparison_error(self):
        self.env["FAKE_DIFF_MODE"] = "crash"
        self.assert_runner_failure("FAIL  case (signature comparison error")

    def test_compliance_rejects_zero_discovery(self):
        self.src.unlink()
        self.assert_runner_failure("error: no compliance sources discovered")

    def test_compliance_rejects_wrong_architecture_checkout(self):
        self.env["FAKE_GIT_SHA"] = "0000000000000000000000000000000000000000"
        self.assert_runner_failure("error: architecture test checkout SHA mismatch")

    def test_compliance_accepts_a_fresh_matching_signature(self):
        result = self.run_runner()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("discovered=1 passed=1 failed=0 skipped/missing=0",
                      result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
