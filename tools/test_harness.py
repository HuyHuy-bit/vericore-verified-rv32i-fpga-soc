#!/usr/bin/env python3
"""Black-box contract tests for the RV32I simulator harness.

The fixtures use only Python's standard library and tiny temporary programs.
They intentionally exercise the simulator CLI rather than its implementation.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIM = Path(os.environ.get("SIM", ROOT / "obj_dir" / "Vcpu"))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
