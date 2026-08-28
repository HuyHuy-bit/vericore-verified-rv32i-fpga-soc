#!/usr/bin/env python3
"""Black-box contract tests for the RV32I simulator harness.

The fixtures use only Python's standard library and tiny temporary programs.
They intentionally exercise the simulator CLI rather than its implementation.
"""
import os
from pathlib import Path
import re
import shutil
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
        self.valid_ref = self.write("valid.ref", "cycles=20\nx0=0\n")
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

    def test_noncanonical_register_keys_are_rejected(self):
        for key in ("x00", "x01", "x0001"):
            with self.subTest(key=key):
                self.reference_failure(
                    f"cycles=20\n{key}=0\n",
                    f"error: malformed reference register key: {key}",
                )

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

    def test_cycles_only_reference_is_not_a_checked_consumer(self):
        ref = self.write("cycles-only.ref", "cycles=20\n")
        result = self.invoke("+STOP=tohost", "+CYCLES=20", f"+REFFILE={ref}")
        self.assert_failure(
            result,
            "error: reference file has no register, stall, or predictor expectations",
        )

    def test_cycles_only_reference_is_valid_metadata_with_an_rvfi_consumer(self):
        ref = self.write("cycles-metadata.ref", "cycles=20\n")
        trace = self.work / "cycles-metadata.rvfi"
        result = self.invoke(
            "+STOP=tohost", "+CYCLES=20", f"+REFFILE={ref}",
            f"+RVFI_TRACE={trace}",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(trace.stat().st_size, 0)

    # These tests name terminal/result failures independently, so a later
    # successful reference comparison cannot erase an earlier failure.
    def test_non_success_tohost_is_a_failure(self):
        ref = self.write("pass.ref", "cycles=20\nx0=0\n")
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
                          "+SIGSTART=0", "+SIGEND=1",
                          "+TEST_FORCE_CACHE_DRAIN_TIMEOUT=1")
        self.assert_failure(result, "error: cache drain deadline exhausted")

    def test_impossible_cache_counters_are_a_failure(self):
        result = self.invoke(
            "+STOP=tohost", "+CYCLES=20", f"+REFFILE={self.valid_ref}",
            "+TEST_FORCE_DCACHE_COUNTER_MISMATCH=1",
        )
        self.assert_failure(result, "error: D-cache misses exceed accesses")

    def test_tohost_bypasses_dcache(self):
        result = self.invoke(
            "+STOP=tohost", "+CYCLES=20", f"+REFFILE={self.valid_ref}",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dcache: accesses=0 misses=0 hitrate=0%", result.stdout)

    def test_result_output_open_failure_is_a_failure(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20",
                          f"+SIGFILE={self.work / 'absent' / 'sig'}",
                          "+SIGSTART=0", "+SIGEND=1")
        self.assert_failure(result, "error: cannot open signature output")

    def test_result_output_write_failure_is_a_failure(self):
        result = self.invoke("+STOP=tohost", "+CYCLES=20", "+SIGFILE=/dev/full",
                          "+SIGSTART=0", "+SIGEND=1")
        self.assert_failure(result, "error: failed writing signature output")

    def signature_failure(self, diagnostic, *bounds):
        result = self.invoke(
            "+STOP=tohost", "+CYCLES=20",
            f"+SIGFILE={self.work / 'invalid.sig'}", *bounds,
        )
        self.assert_failure(result, diagnostic)

    def test_signature_requires_both_bounds_exactly_once(self):
        for bounds in ((), ("+SIGSTART=0",), ("+SIGEND=1",)):
            with self.subTest(bounds=bounds):
                self.signature_failure(
                    "error: signature output requires exactly one SIGSTART and SIGEND",
                    *bounds,
                )

    def test_signature_rejects_equal_and_reversed_bounds(self):
        for start, end in ((1, 1), (2, 1)):
            with self.subTest(start=start, end=end):
                self.signature_failure(
                    "error: signature range must satisfy start < end",
                    f"+SIGSTART={start}", f"+SIGEND={end}",
                )

    def test_signature_rejects_out_of_range_end(self):
        self.signature_failure(
            "error: signature end exceeds data memory word count",
            "+SIGSTART=16384", "+SIGEND=16385",
        )

    def test_signature_rejects_duplicate_bounds(self):
        for bounds in (
            ("+SIGSTART=0", "+SIGSTART=1", "+SIGEND=2"),
            ("+SIGSTART=0", "+SIGEND=1", "+SIGEND=2"),
        ):
            with self.subTest(bounds=bounds):
                self.signature_failure(
                    "error: signature output requires exactly one SIGSTART and SIGEND",
                    *bounds,
                )

    def test_valid_signature_range_is_a_result_consumer(self):
        signature = self.work / "valid.sig"
        result = self.invoke(
            "+STOP=tohost", "+CYCLES=20", f"+SIGFILE={signature}",
            "+SIGSTART=0", "+SIGEND=1",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(signature.read_text(), r"^[0-9a-f]{8}\n$")

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

    def test_predictor_metrics_are_checked(self):
        ref = self.write("predictor.ref", "cycles=20\nbranches=0\nmispredicts=0\n")
        result = self.invoke("+STOP=tohost", "+CYCLES=20", f"+REFFILE={ref}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS  branches", result.stdout)
        self.assertIn("PASS  mispredicts", result.stdout)

    def test_mismatched_predictor_metrics_are_failures(self):
        for key in ("branches", "mispredicts"):
            with self.subTest(key=key):
                ref = self.write(f"wrong-{key}.ref", f"cycles=20\n{key}=1\n")
                result = self.invoke("+STOP=tohost", "+CYCLES=20", f"+REFFILE={ref}")
                self.assert_failure(result, f"error: reference mismatch for {key}")

    def test_duplicate_predictor_metrics_are_rejected(self):
        for key in ("branches", "mispredicts"):
            with self.subTest(key=key):
                self.reference_failure(
                    f"cycles=20\n{key}=0\n{key}=1\n",
                    f"error: duplicate reference key: {key}",
                )

    def test_invalid_predictor_metric_values_are_rejected(self):
        for entry in ("branches=-1", "mispredicts=4294967296"):
            with self.subTest(entry=entry):
                self.reference_failure(
                    f"cycles=20\n{entry}\n",
                    "error: invalid unsigned reference value",
                )

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


class CoverageTargetTest(unittest.TestCase):
    """Exercise the real coverage target's propagation of simulator failure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-coverage-fixture-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        self.repo.mkdir()
        shutil.copy2(ROOT / "Makefile", self.repo / "Makefile")
        shutil.copy2(ROOT / "cpu_tb.cpp", self.repo / "cpu_tb.cpp")
        shutil.copytree(ROOT / "rtl", self.repo / "rtl")
        shutil.copytree(ROOT / "tests", self.repo / "tests")
        shutil.copytree(ROOT / "tools", self.repo / "tools")
        (self.repo / "docs").mkdir()
        (self.repo / "verification/coverpoints").mkdir(parents=True)
        (self.repo / "verification/coverpoints/false_predict.s").write_text("halt\n")
        (self.repo / "verification/coverpoints/false_predict.ref").write_text("cycles=10\n")
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.merge_marker = self.work / "verilator-coverage-invoked"
        self.write_fake_tools()
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            "FAKE_COVERAGE_MERGE_MARKER": str(self.merge_marker),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write_executable(self, name, contents):
        path = self.bin_dir / name
        path.write_text(contents)
        path.chmod(0o755)

    def write_fake_tools(self):
        self.write_executable("verilator", f"""#!{sys.executable}
from pathlib import Path
import sys
if "-V" in sys.argv:
    print("Verilator 5.048")
    print("VERILATOR_ROOT = /fixture/verilator")
    sys.exit(0)
out = Path(sys.argv[sys.argv.index("--Mdir") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "Vcpu").write_text('''#!{sys.executable}
import os
from pathlib import Path
import sys
for arg in sys.argv[1:]:
    if arg.endswith("c_false_predict.hex"):
        marker = os.environ.get("FAKE_COVERAGE_ALIAS_MARKER")
        if marker:
            Path(marker).write_text("ran\\\\n")
    if arg.startswith("+MEMFILE=") and arg.endswith("t01_rtype.hex"):
        mode = os.environ.get("FAKE_COVERAGE_MODE", "sim-failure")
        if mode == "sim-failure":
            sys.exit(7)
        if mode == "missing":
            sys.exit(0)
    if arg.startswith("+COVERAGE="):
        empty = os.environ.get("FAKE_COVERAGE_MODE") == "empty" \
            and any(item.endswith("t01_rtype.hex") for item in sys.argv)
        Path(arg.split("=", 1)[1]).write_text("" if empty else "coverage\\\\n")
sys.exit(0)
''')
(out / "Vcpu").chmod(0o755)
""")
        self.write_executable("verilator_coverage", f"""#!{sys.executable}
from pathlib import Path
import os
import sys
Path(os.environ["FAKE_COVERAGE_MERGE_MARKER"]).write_text("invoked\\n")
if sys.argv[1] == "--write":
    Path(sys.argv[2]).write_text("# SystemC::Coverage-3\\nC '\\x01t\\x02user\\x01h\\x02TOP.cpu.fake' 1\\n")
elif sys.argv[1] == "--annotate":
    Path(sys.argv[2]).mkdir(parents=True, exist_ok=True)
""")

    def test_coverage_fails_when_a_directed_simulation_fails(self):
        result = subprocess.run(
            ["make", "coverage"], cwd=self.repo, env=self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("coverage simulation failed: t01_rtype", combined)
        self.assertFalse(self.merge_marker.exists(), combined)

    def test_coverage_rejects_missing_and_empty_artifacts_before_merge(self):
        for mode in ("missing", "empty"):
            with self.subTest(mode=mode):
                self.env["FAKE_COVERAGE_MODE"] = mode
                self.merge_marker.unlink(missing_ok=True)
                result = subprocess.run(
                    ["make", "coverage"], cwd=self.repo, env=self.env,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=20,
                )
                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, combined)
                self.assertIn(
                    "coverage artifact missing or empty: t01_rtype", combined,
                )
                self.assertFalse(self.merge_marker.exists(), combined)

    def test_coverage_runs_deterministic_btb_alias_fixture(self):
        marker = self.work / "alias-fixture-ran"
        self.env.update({
            "FAKE_COVERAGE_MODE": "success",
            "FAKE_COVERAGE_ALIAS_MARKER": str(marker),
        })
        result = subprocess.run(
            ["make", "coverage"], cwd=self.repo, env=self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists(), result.stdout + result.stderr)


class SoakTargetTest(unittest.TestCase):
    """Exercise the real soak wrapper's handling of generator failure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-soak-fixture-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "obj_dir").mkdir()
        shutil.copy2(ROOT / "tools/soak.sh", self.repo / "tools/soak.sh")
        shutil.copy2(ROOT / "tools/configuration.py", self.repo / "tools/configuration.py")
        (self.repo / "tools/rand_gen.py").write_text("")
        self.sim_marker = self.work / "simulator-ran"
        self.generator_marker = self.work / "generator-ran"
        self.sim = self.repo / "obj_dir/Vcpu"
        self.sim.write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > \"$FAKE_SIM_MARKER\"\nexit 0\n")
        self.sim.chmod(0o755)
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        (self.bin_dir / "python3").write_text(
            "#!/usr/bin/env bash\n"
            ": > \"$FAKE_GENERATOR_MARKER\"\n"
            "if [ \"${FAKE_GENERATOR_MODE:-fail}\" = success ]; then\n"
            "  printf '00100f93\\n00010f37\\nff0f0f13\\n01ff2023\\n0000006f\\n' > \"${@: -2:1}\"\n"
            "  printf 'cycles=99\\nx0=0\\n' > \"${@: -1}\"\n"
            "  exit 0\n"
            "fi\n"
            "[ \"${FAKE_GENERATOR_MODE:-fail}\" = zero ] && exit 0\n"
            "exit 7\n")
        (self.bin_dir / "python3").chmod(0o755)
        (self.bin_dir / "seq").write_text(
            "#!/usr/bin/env bash\n"
            "[ \"${FAKE_SEQ_EMPTY:-0}\" = 1 ] && exit 0\n"
            "exec /usr/bin/seq \"$@\"\n")
        (self.bin_dir / "seq").chmod(0o755)
        self.soak_work = self.work / "rv32i_soak"
        self.soak_work.mkdir()
        (self.soak_work / "s1.hex").write_text("stale program\n")
        (self.soak_work / "s1.ref").write_text("cycles=99\n")
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            "TMPDIR": str(self.work),
            "FAKE_SIM_MARKER": str(self.sim_marker),
            "FAKE_GENERATOR_MARKER": str(self.generator_marker),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_soak_rejects_generator_failure_before_using_stale_seed_files(self):
        result = subprocess.run(
            [str(self.repo / "tools/soak.sh"), "1", "5"], cwd=self.repo,
            env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("FAIL seed=1 - random generation failed:", combined)
        self.assertFalse(self.sim_marker.exists(), combined)

    def test_soak_rejects_zero_exit_generator_with_stale_seed_files(self):
        self.env["FAKE_GENERATOR_MODE"] = "zero"
        result = subprocess.run(
            [str(self.repo / "tools/soak.sh"), "1", "5"], cwd=self.repo,
            env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("FAIL seed=1 - generated files missing or empty:", combined)
        self.assertFalse(self.sim_marker.exists(), combined)

    def test_soak_rejects_invalid_counts_before_children_start(self):
        for label, args, diagnostic in (
            ("zero seeds", ("0", "5"), "error: SEEDS must be a positive integer"),
            ("nonnumeric seeds", ("many", "5"), "error: SEEDS must be a positive integer"),
            ("zero instructions", ("1", "0"), "error: INSTRS must be a positive integer"),
            ("nonnumeric instructions", ("1", "many"), "error: INSTRS must be a positive integer"),
        ):
            with self.subTest(label=label):
                self.generator_marker.unlink(missing_ok=True)
                self.sim_marker.unlink(missing_ok=True)
                result = subprocess.run(
                    [str(self.repo / "tools/soak.sh"), *args], cwd=self.repo,
                    env=self.env, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=10,
                )
                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, combined)
                self.assertIn(diagnostic, combined)
                self.assertFalse(self.generator_marker.exists(), combined)
                self.assertFalse(self.sim_marker.exists(), combined)

    def test_soak_requires_every_requested_seed_to_pass(self):
        self.env["FAKE_SEQ_EMPTY"] = "1"
        result = subprocess.run(
            [str(self.repo / "tools/soak.sh"), "1", "5"], cwd=self.repo,
            env=self.env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10,
        )
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("0/0 random seeds passed", combined)

    def test_soak_requests_tohost_completion_for_generated_programs(self):
        self.env["FAKE_GENERATOR_MODE"] = "success"
        result = subprocess.run(
            [str(self.repo / "tools/soak.sh"), "1", "5"], cwd=self.repo,
            env=self.env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sim_args = self.sim_marker.read_text()
        self.assertIn("+STOP=tohost", sim_args)
        self.assertNotIn("+STOP=selfloop", sim_args)

    def test_soak_honors_explicit_simulator(self):
        selected_marker = self.work / "selected-simulator-ran"
        selected = self.work / "selected-sim"
        selected.write_text(
            "#!/usr/bin/env bash\n: > \"$FAKE_SELECTED_SIM_MARKER\"\nexit 0\n"
        )
        selected.chmod(0o755)
        self.env.update({
            "FAKE_GENERATOR_MODE": "success",
            "FAKE_SELECTED_SIM_MARKER": str(selected_marker),
            "SIM": str(selected),
        })
        result = subprocess.run(
            [str(self.repo / "tools/soak.sh"), "1", "5"], cwd=self.repo,
            env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(selected_marker.exists(), result.stdout + result.stderr)


class RandomGeneratorContractTest(unittest.TestCase):
    """Keep Python-model and Spike completion mappings explicit and separate."""

    TOHOST_TAIL = [
        "00100f93", "00010f37", "ff0f0f13", "01ff2023", "0000006f",
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-rand-contract-")
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_program_writes_tohost_one_and_reference_tracks_completion_registers(self):
        hexfile = self.work / "program.hex"
        reffile = self.work / "program.ref"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/rand_gen.py"), "-n", "1",
             "--seed", "7", str(hexfile), str(reffile)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hexfile.read_text().splitlines()[-5:], self.TOHOST_TAIL)
        reference = reffile.read_text().splitlines()
        self.assertIn("x30=0xfff0", reference)
        self.assertIn("x31=0x1", reference)

    def test_spike_program_remains_selfloop_terminated_without_tohost_sequence(self):
        asm = self.work / "program.S"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/rand_gen.py"), "-n", "1",
             "--seed", "7", "--spike", str(asm)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        words = [line.split("0x", 1)[1] for line in asm.read_text().splitlines()
                 if ".word 0x" in line]
        self.assertEqual(words[-1], "0000006f")
        self.assertNotEqual(words[-5:], self.TOHOST_TAIL)


class AssemblerPaddingTest(unittest.TestCase):
    def test_fill_emits_requested_nops_and_preserves_label_offsets(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-asm-fill-") as temp:
            work = Path(temp)
            source = work / "fill.s"
            output = work / "fill.hex"
            source.write_text(
                "jal x1, target\n"
                ".fill 3\n"
                "target: addi x2, x0, 7\n"
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/asm.py"), str(source), str(output)],
                cwd=ROOT, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                output.read_text().splitlines(),
                ["010000ef", "00000013", "00000013", "00000013", "00700113"],
            )


class Elf2HexTest(unittest.TestCase):
    """Require converter intermediates to be fresh and invocation-private."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-elf2hex-fixture-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        (self.repo / "compliance").mkdir(parents=True)
        shutil.copy2(ROOT / "compliance/elf2hex.py", self.repo / "compliance/elf2hex.py")
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.private_tmp = self.work / "tmp"
        self.private_tmp.mkdir()
        self.records = self.work / "records"
        self.records.mkdir()
        self.objcopy = self.bin_dir / "riscv64-unknown-elf-objcopy"
        self.objcopy.write_text(f"""#!{sys.executable}
import os
from pathlib import Path
import sys
import time

out = Path(sys.argv[-1])
allowed = Path(os.environ["FAKE_ALLOWED_TMP"])
if allowed not in out.parents:
    print(f"refusing non-private objcopy path: {{out}}", file=sys.stderr)
    sys.exit(23)
if os.environ.get("FAKE_OBJCOPY_MODE") == "no-output":
    sys.exit(0)
kind = "data" if "--only-section=.data" in sys.argv else "text"
record = Path(os.environ["FAKE_OBJCOPY_RECORDS"])
(record / f"{{os.getpid()}}-{{kind}}.path").write_text(str(out))
if kind == "text":
    (record / f"{{os.getpid()}}.started").write_text("started")
    deadline = time.monotonic() + 5
    while len(list(record.glob("*.started"))) < 2:
        if time.monotonic() >= deadline:
            print("concurrency barrier timed out", file=sys.stderr)
            sys.exit(24)
        time.sleep(0.01)
    value = int(Path(sys.argv[-2]).read_text().strip())
    out.write_bytes(value.to_bytes(4, "little"))
else:
    out.write_bytes(b"")
""")
        self.objcopy.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            "TMPDIR": str(self.private_tmp),
            "FAKE_ALLOWED_TMP": str(self.private_tmp),
            "FAKE_OBJCOPY_RECORDS": str(self.records),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_concurrent_conversions_use_distinct_private_intermediates(self):
        processes = []
        outputs = []
        for number in (1, 2):
            elf = self.work / f"case-{number}.elf"
            instr = self.work / f"case-{number}.instr.hex"
            data = self.work / f"case-{number}.data.hex"
            elf.write_text(str(number))
            outputs.append((instr, data))
            processes.append(subprocess.Popen(
                [sys.executable, str(self.repo / "compliance/elf2hex.py"),
                 str(elf), str(instr), str(data)],
                cwd=self.repo, env=self.env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ))
        results = [process.communicate(timeout=10) + (process.returncode,)
                   for process in processes]
        for stdout, stderr, returncode in results:
            self.assertEqual(returncode, 0, stdout + stderr)
        self.assertEqual(outputs[0][0].read_text(), "00000001\n")
        self.assertEqual(outputs[1][0].read_text(), "00000002\n")
        paths = [Path(path.read_text()) for path in self.records.glob("*.path")]
        self.assertEqual(len(paths), 4)
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(len({path.parent for path in paths}), 2)
        self.assertTrue(all(self.private_tmp in path.parents for path in paths))

    def test_zero_status_objcopy_without_output_cannot_reuse_stale_file(self):
        stale = self.private_tmp / "stale.bin"
        stale.write_bytes(b"stale")
        self.env["FAKE_OBJCOPY_MODE"] = "no-output"
        probe = (
            "import importlib.util, sys; "
            "spec=importlib.util.spec_from_file_location('elf2hex', sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "module.objcopy_binary('unused.elf', ['.text'], sys.argv[2])"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe,
             str(self.repo / "compliance/elf2hex.py"), str(stale)],
            cwd=self.repo, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("objcopy produced no output", result.stdout + result.stderr)
        self.assertFalse(stale.exists(), "stale objcopy output was retained")


class BenchmarkRunnerTest(unittest.TestCase):
    """Exercise benchmark producer status and private-work lifecycle."""

    KERNELS = ("crc32", "matmul", "sort", "llist", "interp")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-bench-fixture-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        (self.repo / "bench").mkdir(parents=True)
        (self.repo / "compliance/link").mkdir(parents=True)
        (self.repo / "obj_dir").mkdir()
        (self.repo / "rtl").mkdir()
        (self.repo / "tools").mkdir()
        shutil.copy2(ROOT / "bench/run_bench.sh", self.repo / "bench/run_bench.sh")
        shutil.copy2(ROOT / "bench/rv32i_runtime.c", self.repo / "bench/rv32i_runtime.c")
        shutil.copy2(ROOT / "tools/configuration.py", self.repo / "tools/configuration.py")
        for name in ("host_main.c", "crt0.S"):
            (self.repo / "bench" / name).write_text("placeholder\n")
        for kernel in self.KERNELS:
            (self.repo / "bench" / f"{kernel}.c").write_text("placeholder\n")
        (self.repo / "compliance/link/rv32i-pipeline.ld").write_text("SECTIONS {}\n")
        (self.repo / "compliance/elf2hex.py").write_text("# fake converter\n")
        (self.repo / "cpu_tb.cpp").write_text("// placeholder\n")
        (self.repo / "rtl/cpu.sv").write_text("// placeholder\n")
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.work_log = self.work / "target-work-paths"
        self.write_tools()
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin_dir) + os.pathsep + self.env["PATH"],
            "TMPDIR": str(self.work),
            "FAKE_BENCH_WORK_LOG": str(self.work_log),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write_executable(self, path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def write_tools(self):
        self.write_executable(self.bin_dir / "cc", """#!/usr/bin/env bash
set -eu
out=
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then out="$2"; break; fi
    shift
done
[ -n "$out" ] || exit 2
if [ "${FAKE_CC_MODE:-ok}" = no-output ] && [ "${out##*/}" = crc32.host ]; then
    exit 0
fi
printf '%s\n' '#!/usr/bin/env bash' 'printf "123\\n"' 'exit "${FAKE_HOST_RC:-0}"' > "$out"
chmod +x "$out"
""")
        self.write_executable(self.bin_dir / "riscv64-unknown-elf-gcc", """#!/usr/bin/env bash
set -eu
out=
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then out="$2"; break; fi
    shift
done
[ -n "$out" ] || exit 2
printf 'ELF\n' > "$out"
printf '%s\n' "$out" >> "$FAKE_BENCH_WORK_LOG"
""")
        self.write_executable(self.bin_dir / "riscv64-unknown-elf-size", """#!/usr/bin/env bash
printf '%s\n' 'section size addr' '.text 4 0'
exit "${FAKE_SIZE_RC:-0}"
""")
        self.write_executable(self.bin_dir / "python3", """#!/usr/bin/env bash
set -eu
printf '0000006f\n' > "$3"
: > "$4"
""")
        self.write_executable(self.repo / "obj_dir/Vcpu", """#!/usr/bin/env bash
printf '%s\n' \
  '  perf: cycles=10 instret=5 stalls=0 flushes=0 memstall=0 CPI=2' \
  '  bpred: branches=0 mispredicts=0 accuracy=0%' \
  '  icache: accesses=0 misses=0 hitrate=0%' \
  '  dcache: accesses=0 misses=0 hitrate=0%'
exit 0
""")

    def run_bench(self, *args, **updates):
        env = self.env.copy()
        env.update(updates)
        return subprocess.run(
            [str(self.repo / "bench/run_bench.sh"), *args], cwd=self.repo,
            env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=20,
        )

    def retained_directory(self, result):
        combined = result.stdout + result.stderr
        match = re.search(r"diagnostics retained in (\S+)", combined)
        self.assertIsNotNone(match, combined)
        retained = Path(match.group(1))
        self.assertTrue(retained.is_dir(), combined)
        return retained

    def test_native_reference_nonzero_with_plausible_output_is_a_failure(self):
        result = self.run_bench(FAKE_HOST_RC="7")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("host reference execution failed", result.stdout + result.stderr)
        self.retained_directory(result)

    def test_zero_output_host_build_cannot_reuse_stale_executable(self):
        legacy = self.work / "rv32i_bench"
        legacy.mkdir()
        stale = legacy / "crc32.host"
        self.write_executable(stale, "#!/usr/bin/env bash\nprintf '123\\n'\nexit 0\n")
        result = self.run_bench(FAKE_CC_MODE="no-output")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("host build produced no executable", result.stdout + result.stderr)

    def test_size_inspection_failure_is_propagated(self):
        result = self.run_bench(FAKE_SIZE_RC="7")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("size inspection failed", result.stdout + result.stderr)

    def test_successful_invocations_use_unique_cleaned_work_directories(self):
        first = self.run_bench()
        second = self.run_bench()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        elf_paths = [Path(line) for line in self.work_log.read_text().splitlines()]
        self.assertEqual(len(elf_paths), 2 * len(self.KERNELS))
        first_work = elf_paths[0].parent
        second_work = elf_paths[len(self.KERNELS)].parent
        self.assertNotEqual(first_work, second_work)
        self.assertFalse(first_work.exists())
        self.assertFalse(second_work.exists())

    def test_keep_work_retains_successful_invocation(self):
        result = self.run_bench(KEEP_WORK="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.retained_directory(result)

    def test_invalid_numeric_configuration_is_rejected_before_producers(self):
        result = self.run_bench("0")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LATENCY must be a positive integer", result.stdout + result.stderr)
        self.assertFalse(self.work_log.exists(), result.stdout + result.stderr)

    def test_explicit_simulator_is_used(self):
        selected_marker = self.work / "selected-simulator-ran"
        selected = self.work / "selected-sim"
        self.write_executable(selected, """#!/usr/bin/env bash
: > "$FAKE_SELECTED_SIM_MARKER"
exec "$FAKE_FALLBACK_SIM" "$@"
""")
        result = self.run_bench(
            SIM=str(selected),
            FAKE_SELECTED_SIM_MARKER=str(selected_marker),
            FAKE_FALLBACK_SIM=str(self.repo / "obj_dir/Vcpu"),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(selected_marker.exists(), result.stdout + result.stderr)

    def test_make_bench_selects_the_configuration_build(self):
        result = subprocess.run(
            [
                "make", "-Bn", "bench", "IC_BYTES=1024", "IC_WAYS=4",
                "DC_BYTES=4096", "DC_WAYS=4", "DC_WB=1",
                "IMEM_LAT=10", "DMEM_LAT=10",
            ],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=10,
        )
        expected = ROOT / "obj_dir_ic1024_4_4_dc4096_4_4_1_L10_10_bp6_10_0_8/Vcpu"
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'SIM="{expected}"', result.stdout)

    def test_benchmark_uses_the_local_rv32i_runtime(self):
        source = (ROOT / "bench/run_bench.sh").read_text()
        self.assertIn('"$RUNTIME" "$src"', source)
        self.assertNotIn("-lgcc", source)


class ComplianceRunnerTest(unittest.TestCase):
    """Exercise a copied runner in an isolated, one-case mini-repository."""

    PINNED_ARCH_SHA = REFERENCE_VERSIONS["ARCH_TEST_SHA"]
    PINNED_SPIKE_SHA = REFERENCE_VERSIONS["SPIKE_SHA"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-compliance-fixture-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        self.runner = self.repo / "compliance/run_compliance.sh"
        self.versions = self.repo / "tools/reference_versions.env"
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
        (self.repo / "compliance/link").mkdir(parents=True)
        (self.repo / "compliance/riscv-target/rv32i-pipeline").mkdir(parents=True)
        (self.repo / "tools").mkdir()
        (self.repo / "obj_dir").mkdir()
        shutil.copy2(ROOT / "compliance/run_compliance.sh", self.runner)
        (self.repo / "compliance/link/rv32i-pipeline.ld").write_text("SECTIONS {}")
        (self.repo / "compliance/elf2hex.py").write_text("# fake converter\n")
        (self.repo / "compliance/riscv-target/rv32i-pipeline/model_test.h").write_text("")
        self.write_versions()

        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.sim = self.repo / "obj_dir/Vcpu"
        self.write_tools()
        self.env = os.environ.copy()
        self.env.update({
            "ARCH_TEST": str(self.arch),
            "REPO_ROOT": str(self.repo),
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
            "ARCH_TEST_EXPECTED=1\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        ))

    def write_tools(self):
        self.write(self.bin_dir / "riscv64-unknown-elf-gcc", """#!/usr/bin/env bash
set -eu
if [ "${FAKE_GCC_RC:-0}" -ne 0 ]; then
    echo 'fake compiler diagnostic' >&2
    exit "$FAKE_GCC_RC"
fi
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
        self.write(self.bin_dir / "riscv64-unknown-elf-objcopy", """#!/usr/bin/env bash
exit 0
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
[ -z "${FAKE_SIM_MARKER:-}" ] || : > "$FAKE_SIM_MARKER"
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
            [str(self.runner)], cwd=self.repo, env=self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )

    def assert_runner_failure(self, diagnostic):
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)

    # Each test names a preflight or case-result branch that a permissive
    # runner would turn into a zero-status compliance result.
    def test_compliance_rejects_missing_version_metadata(self):
        self.versions.unlink()
        self.assert_runner_failure("error: reference version file missing")

    def test_compliance_rejects_malformed_version_metadata(self):
        self.write_versions("ARCH_TEST_SHA=not-a-sha\n")
        self.assert_runner_failure("error: malformed reference version metadata")

    def test_compliance_rejects_duplicate_version_metadata(self):
        self.write_versions(
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=1\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        )
        self.assert_runner_failure("error: duplicate reference version key: ARCH_TEST_SHA")

    def test_compliance_ignores_noncentral_version_override(self):
        self.write_versions(
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=2\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        )
        attacker_versions = self.work / "attacker.env"
        attacker_versions.write_text(
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=1\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        )
        self.env["REFERENCE_VERSIONS"] = str(attacker_versions)
        marker = self.work / "simulator-ran"
        self.env["FAKE_SIM_MARKER"] = str(marker)
        self.assert_runner_failure("error: discovered 1 cases; expected 2")
        self.assertFalse(marker.exists(), "noncentral one-case metadata ran the simulator")

    def test_compliance_stops_count_mismatch_before_simulation(self):
        self.write_versions(
            f"ARCH_TEST_SHA={self.PINNED_ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=2\n"
            f"SPIKE_SHA={self.PINNED_SPIKE_SHA}\n"
        )
        marker = self.work / "simulator-ran"
        self.env["FAKE_SIM_MARKER"] = str(marker)
        self.assert_runner_failure("error: discovered 1 cases; expected 2")
        self.assertFalse(marker.exists(), "simulator ran despite population preflight failure")

    def test_compliance_reports_disjoint_missing_reference_categories(self):
        self.ref.unlink()
        self.assert_runner_failure("FAIL  case (missing reference file)")
        result = self.run_runner()
        self.assertIn(
            "discovered=1 passed=0 failed=0 skipped/missing=1 infrastructure=1",
            result.stdout + result.stderr,
        )

    def test_compliance_rejects_missing_git_tool(self):
        no_git = self.work / "no-git-bin"
        no_git.mkdir()
        for name in ("riscv64-unknown-elf-gcc", "riscv64-unknown-elf-nm",
                     "riscv64-unknown-elf-objcopy", "python3", "diff"):
            (no_git / name).symlink_to(self.bin_dir / name)
        (no_git / "bash").symlink_to("/bin/bash")
        (no_git / "dirname").symlink_to("/usr/bin/dirname")
        self.env["PATH"] = str(no_git)
        self.assert_runner_failure("error: required tool not found: git")

    def test_compliance_rejects_missing_objcopy_tool(self):
        no_objcopy = self.work / "no-objcopy-bin"
        no_objcopy.mkdir()
        for name in ("riscv64-unknown-elf-gcc", "riscv64-unknown-elf-nm",
                     "python3", "diff", "git"):
            (no_objcopy / name).symlink_to(self.bin_dir / name)
        (no_objcopy / "bash").symlink_to("/bin/bash")
        (no_objcopy / "dirname").symlink_to("/usr/bin/dirname")
        self.env["PATH"] = str(no_objcopy)
        self.assert_runner_failure(
            "error: required tool not found: riscv64-unknown-elf-objcopy")

    def test_compliance_compile_failure_prints_diagnostic(self):
        self.env["FAKE_GCC_RC"] = "6"
        result = self.run_runner()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fake compiler diagnostic", result.stdout + result.stderr)

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
        self.assertIn("discovered=1 passed=1 failed=0 skipped/missing=0 infrastructure=0",
                      result.stdout + result.stderr)


class LockstepTest(unittest.TestCase):
    """Drive the real lockstep comparator with deterministic child processes."""

    RTL_A = "80000000 00100093 1 00000001\n"
    RTL_B = "80000004 00200113 2 00000002\n"
    RTL_END = "80000008 0000006f 0 00000000\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-lockstep-fixture-")
        self.work = Path(self.tmp.name)
        self.sim = self.work / "sim.py"
        self.spike = self.work / "spike.py"
        self.elf = self.write("case.elf", "")
        self.instr = self.write("case.instr.hex", "0000006f\n")
        self.data = self.write("case.data.hex", "")
        self.pidfile = self.work / "peer.pid"
        self.trace_arg = self.work / "trace-arg"
        self.spike_marker = self.work / "spike-started"
        self.lockstep_tmp = self.work / "tmp"
        self.lockstep_tmp.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "SPIKE": str(self.spike),
            "FAKE_SIM_MODE": "equal",
            "FAKE_SPIKE_MODE": "equal",
            "FAKE_PIDFILE": str(self.pidfile),
            "FAKE_TRACE_ARG": str(self.trace_arg),
            "FAKE_SPIKE_MARKER": str(self.spike_marker),
            "TMPDIR": str(self.lockstep_tmp),
        })
        self.write_executable(self.sim, self.fake_simulator())
        self.write_executable(self.spike, self.fake_spike())

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, contents):
        path = self.work / name
        path.write_text(contents)
        return path

    def write_executable(self, path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def fake_simulator(self):
        return f"""#!{sys.executable}
import os, sys, time
mode = os.environ.get("FAKE_SIM_MODE", "equal")
trace = ""
for arg in sys.argv[1:]:
    if arg.startswith("+RVFI_TRACE="):
        trace = arg.split("=", 1)[1]
required = {{"+STOP=selfloop", "+VCD="}}
if not required.issubset(sys.argv[1:]) or not trace:
    print("fake simulator: missing required lockstep arguments", file=sys.stderr)
    sys.exit(19)
open(os.environ["FAKE_TRACE_ARG"], "w").write(trace)
if mode in ("hang", "timeout"):
    open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
    while True: time.sleep(1)
if mode == "delayed_equal": time.sleep(0.2)
records = {{
    "equal": {self.RTL_A + self.RTL_END!r},
    "crash": {self.RTL_A + self.RTL_END!r},
    "missing": None,
    "empty": "",
    "malformed": "not an rvfi record\\n",
    "nonterminal": {self.RTL_A!r},
    "prefix": {self.RTL_A + self.RTL_END!r},
    "diverge0": "80000000 00200093 1 00000002\\n" + {self.RTL_END!r},
    "delayed_equal": {self.RTL_A + self.RTL_END!r},
}}
contents = os.environ.get("FAKE_RTL_TRACE", records[mode])
if contents is not None:
    open(trace, "w").write(contents)
print("SIM-STDOUT-DETAIL")
print("SIM-STDERR-DETAIL", file=sys.stderr)
sys.exit(7 if mode == "crash" else 0)
"""

    def fake_spike(self):
        return f"""#!{sys.executable}
import os, sys, time
mode = os.environ.get("FAKE_SPIKE_MODE", "equal")
open(os.environ["FAKE_SPIKE_MARKER"], "w").write(str(os.getpid()))
def emit(pc, insn, tail=""):
    print(f"core   0: 3 0x{{pc}} (0x{{insn}}){{tail}}", file=sys.stderr, flush=True)
if mode == "crash":
    open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
    print("SPIKE-CRASH-DETAIL", file=sys.stderr, flush=True)
    sys.exit(8)
if mode in ("hang", "timeout"):
    open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
    while True: time.sleep(1)
emit("80000000", "00100093", " x1  0x00000001")
if mode == "prefix": emit("80000004", "00200113", " x2  0x00000002")
if mode != "nonterminal": emit("80000008", "0000006f")
if mode == "terminal_then_failure":
    print("SPIKE-POST-TERMINAL-FAILURE", file=sys.stderr, flush=True)
    sys.exit(12)
if mode == "repeat_terminal":
    while True:
        time.sleep(0.02)
        emit("80000008", "0000006f")
if mode == "nonterminal":
    open(os.environ["FAKE_PIDFILE"], "w").write(str(os.getpid()))
while True: time.sleep(1)
"""

    def run_lockstep(self, timeout="0.6"):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/lockstep.py"), str(self.elf),
             str(self.instr), str(self.data), "--sim", str(self.sim),
             "--cycles", "10", f"--timeout={timeout}"],
            cwd=ROOT, env=self.env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=5,
        )

    def assert_lockstep_failure(self, diagnostic):
        result = self.run_lockstep()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)
        return result

    def assert_recorded_peer_reaped(self):
        pid = int(self.pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_simulator_crash_rejects_stale_trace_and_preserves_diagnostics(self):
        self.env["FAKE_SIM_MODE"] = "crash"
        result = self.assert_lockstep_failure("simulator exited with status 7")
        self.assertIn("SIM-STDOUT-DETAIL", result.stdout + result.stderr)
        self.assertIn("SIM-STDERR-DETAIL", result.stdout + result.stderr)

    def test_missing_empty_and_malformed_rtl_traces_are_rejected(self):
        for mode, diagnostic in (
            ("missing", "RTL trace is missing"),
            ("empty", "RTL trace is empty"),
            ("malformed", "malformed RTL trace record at line 1"),
        ):
            with self.subTest(mode=mode):
                self.env["FAKE_SIM_MODE"] = mode
                self.assert_lockstep_failure(diagnostic)

    def test_nonterminal_rtl_trace_is_rejected(self):
        self.env["FAKE_SIM_MODE"] = "nonterminal"
        self.assert_lockstep_failure("RTL trace does not end with terminal self-loop")

    def test_matching_prefix_truncation_is_rejected(self):
        self.env["FAKE_SIM_MODE"] = "prefix"
        self.env["FAKE_SPIKE_MODE"] = "prefix"
        self.assert_lockstep_failure("trace length mismatch: rtl=2 spike=3")

    def test_first_retirement_divergence_reports_index_and_both_values(self):
        self.env["FAKE_SIM_MODE"] = "diverge0"
        result = self.assert_lockstep_failure("diverged at retirement 0")
        combined = result.stdout + result.stderr
        self.assertIn("RTL   pc=0x80000000 insn=0x00200093", combined)
        self.assertIn("SPIKE pc=0x80000000 insn=0x00100093", combined)
        retained = re.search(r"diagnostics retained in (\S+)", combined)
        self.assertIsNotNone(retained, combined)
        diagnostic_dir = Path(retained.group(1))
        try:
            self.assertTrue((diagnostic_dir / "sim.stdout").exists())
            self.assertTrue((diagnostic_dir / "spike.stderr").exists())
        finally:
            shutil.rmtree(diagnostic_dir)

    def test_missing_spike_terminal_sentinel_times_out(self):
        self.env["FAKE_SPIKE_MODE"] = "nonterminal"
        self.assert_lockstep_failure("deadline expired waiting for Spike terminal self-loop")

    def test_deadline_expiry_terminates_and_reaps_children(self):
        self.env["FAKE_SIM_MODE"] = "timeout"
        self.env["FAKE_SPIKE_MODE"] = "timeout"
        self.assert_lockstep_failure("lockstep deadline expired")
        self.assert_recorded_peer_reaped()

    def test_simulator_failure_terminates_and_reaps_spike_peer(self):
        self.env["FAKE_SIM_MODE"] = "crash"
        self.env["FAKE_SPIKE_MODE"] = "hang"
        self.assert_lockstep_failure("simulator exited with status 7")
        self.assert_recorded_peer_reaped()

    def test_spike_failure_terminates_and_reaps_simulator_peer(self):
        self.env["FAKE_SIM_MODE"] = "hang"
        self.env["FAKE_SPIKE_MODE"] = "crash"
        result = self.assert_lockstep_failure("Spike exited with status 8")
        self.assertIn("SPIKE-CRASH-DETAIL", result.stdout + result.stderr)
        self.assert_recorded_peer_reaped()

    def test_natural_spike_failure_after_terminal_is_rejected(self):
        self.env["FAKE_SPIKE_MODE"] = "terminal_then_failure"
        result = self.assert_lockstep_failure(
            "Spike exited with status 12 after terminal self-loop")
        self.assertIn("SPIKE-POST-TERMINAL-FAILURE", result.stdout + result.stderr)

    def test_signed_rtl_fields_are_rejected_before_normalization(self):
        for field, record in (
            ("pc", "-1 00100093 1 00000001\n" + self.RTL_END),
            ("insn", "80000000 -1 1 00000001\n" + self.RTL_END),
            ("wdata", "80000000 00100093 1 -1\n" + self.RTL_END),
            ("x0 wdata", self.RTL_A + "80000008 0000006f 0 -1\n"),
        ):
            with self.subTest(field=field):
                self.env["FAKE_RTL_TRACE"] = record
                self.assert_lockstep_failure("malformed RTL trace record")

    def test_overflowed_rtl_fields_are_rejected(self):
        for field, record in (
            ("pc", "100000000 00100093 1 00000001\n" + self.RTL_END),
            ("insn", "80000000 100000000 1 00000001\n" + self.RTL_END),
            ("wdata", "80000000 00100093 1 100000000\n" + self.RTL_END),
            ("rd", "80000000 00100093 32 00000001\n" + self.RTL_END),
        ):
            with self.subTest(field=field):
                self.env["FAKE_RTL_TRACE"] = record
                self.assert_lockstep_failure("malformed RTL trace record")

    def test_noncanonical_rtl_field_spellings_are_rejected(self):
        for label, record in (
            ("signed pc", "+80000000 00100093 1 00000001\n" + self.RTL_END),
            ("prefixed pc", "0x80000000 00100093 1 00000001\n" + self.RTL_END),
            ("short pc", "8000000 00100093 1 00000001\n" + self.RTL_END),
            ("underscore insn", "80000000 0000_06f 1 00000001\n" + self.RTL_END),
            ("reviewer underscore", "80000000 0000_006f 0 00000000\n"),
            ("signed rd", "80000000 00100093 +1 00000001\n" + self.RTL_END),
            ("leading-zero rd", "80000000 00100093 01 00000001\n" + self.RTL_END),
            ("prefixed wdata", "80000000 00100093 1 0x00000001\n" + self.RTL_END),
            ("junk wdata", "80000000 00100093 1 00000001junk\n" + self.RTL_END),
        ):
            with self.subTest(label=label):
                self.env["FAKE_RTL_TRACE"] = record
                self.assert_lockstep_failure("malformed RTL trace record")

    def test_nonfinite_deadlines_are_rejected_before_children_start(self):
        for timeout in ("nan", "inf", "+inf", "-inf"):
            with self.subTest(timeout=timeout):
                result = self.run_lockstep(timeout=timeout)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("--timeout must be finite and positive",
                              result.stdout + result.stderr)
                self.assertFalse(self.trace_arg.exists(), "nonfinite deadline started children")
                self.assertFalse(self.spike_marker.exists(),
                                 "nonfinite deadline started Spike")

    def test_exact_terminal_inclusive_equality_uses_private_trace(self):
        shared = self.lockstep_tmp / "_rvfi.trace"
        shared.write_text("do-not-touch\n")
        result = self.run_lockstep()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 retirements match through terminal self-loop", result.stdout)
        self.assertTrue(self.spike_marker.exists(), "fake Spike marker is not functional")
        trace_path = Path(self.trace_arg.read_text())
        self.assertNotEqual(trace_path, shared)
        self.assertEqual(trace_path.parent.parent, self.lockstep_tmp)
        self.assertIn("rv32i-lockstep-", trace_path.parent.name)
        self.assertEqual(shared.read_text(), "do-not-touch\n")

    def test_spike_stream_is_sealed_at_first_terminal_retirement(self):
        self.env["FAKE_SIM_MODE"] = "delayed_equal"
        self.env["FAKE_SPIKE_MODE"] = "repeat_terminal"
        result = self.run_lockstep()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 retirements match through terminal self-loop", result.stdout)


class LockstepWrapperTest(unittest.TestCase):
    """Check wrapper accounting without compilers, RTL, or Spike."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-lockstep-wrapper-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        self.arch = self.work / "arch"
        self.src_dir = self.arch / "riscv-test-suite/rv32i_m/I/src"
        self.src_dir.mkdir(parents=True)
        (self.arch / "riscv-test-env/p").mkdir(parents=True)
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "compliance/link").mkdir(parents=True)
        (self.repo / "compliance/riscv-target/rv32i-pipeline").mkdir(parents=True)
        (self.repo / "obj_dir_lockstep").mkdir()
        shutil.copy2(ROOT / "tools/run_lockstep.sh", self.repo / "tools/run_lockstep.sh")
        self.versions = self.repo / "tools/reference_versions.env"
        self.versions.write_text(
            "ARCH_TEST_SHA=" + "a" * 40 + "\nARCH_TEST_EXPECTED=1\nSPIKE_SHA=" + "b" * 40 + "\n"
        )
        for path in (self.repo / "compliance/link/spike-lockstep.ld",
                     self.repo / "compliance/elf2hex.py",
                     self.repo / "tools/lockstep.py"):
            path.write_text("")
        self.sim = self.repo / "obj_dir_lockstep/Vcpu"
        self.sim.write_text("#!/usr/bin/env bash\nexit 0\n")
        self.sim.chmod(0o755)
        self.spike_repo = self.work / "spike-repo"
        (self.spike_repo / "build").mkdir(parents=True)
        self.spike = self.spike_repo / "build/spike"
        self.spike.write_text("#!/usr/bin/env bash\nexit 0\n")
        self.spike.chmod(0o755)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.write_tool("git", f"""
if [ "${{4:-}}" = --show-toplevel ]; then
    printf '%s\\n' {self.spike_repo!s}
elif [ "${{2:-}}" = {self.spike_repo!s} ]; then
    printf '%s\\n' "${{FAKE_SPIKE_SHA:-{'b' * 40}}}"
else
    printf '%s\\n' "${{FAKE_GIT_SHA:-{'a' * 40}}}"
fi
""")
        self.write_tool("riscv64-unknown-elf-gcc", """
[ -z "${FAKE_CHILD_MARKER:-}" ] || : > "$FAKE_CHILD_MARKER"
if [ "${FAKE_GCC_RC:-0}" -ne 0 ]; then
    echo 'fake compiler diagnostic' >&2
    exit "$FAKE_GCC_RC"
fi
touch "${@: -1}"
""")
        self.write_tool("python3", """
[ -z "${FAKE_CHILD_MARKER:-}" ] || : > "$FAKE_CHILD_MARKER"
exit "${FAKE_PYTHON_RC:-0}"
""")
        self.child_marker = self.work / "child-ran"
        self.env = os.environ.copy()
        self.env.update({
            "ARCH_TEST": str(self.arch),
            "PATH": str(self.bin) + os.pathsep + self.env["PATH"],
            "REAL_PYTHON": sys.executable,
            "LOCKSTEP_TIMEOUT": "0.25",
            "SPIKE": str(self.spike),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write_tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_wrapper(self, timeout=None):
        env = self.env.copy()
        if timeout is not None:
            env["LOCKSTEP_TIMEOUT"] = timeout
        return subprocess.run(
            [str(self.repo / "tools/run_lockstep.sh")], cwd=self.repo,
            env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=5,
        )

    def add_source(self):
        (self.src_dir / "case.S").write_text("nop\n")

    def assert_wrapper_failure(self, diagnostic):
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)
        return result

    def test_zero_discovered_lockstep_cases_is_a_failure(self):
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("error: no lockstep sources discovered", result.stdout + result.stderr)

    def test_case_failure_is_counted_and_deadline_is_forwarded(self):
        self.add_source()
        args_file = self.work / "lockstep.args"
        self.env["FAKE_LOCKSTEP_ARGS"] = str(args_file)
        self.write_tool("python3", """
if [ "${1##*/}" = lockstep.py ]; then
    printf '%s\\n' "$*" > "$FAKE_LOCKSTEP_ARGS"
    echo 'deadline expired in fake lockstep' >&2
    exit 9
fi
if [ "${1##*/}" = elf2hex.py ]; then : > "$3"; : > "$4"; exit 0; fi
exec "$REAL_PYTHON" "$@"
""")
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0/1 programs match", result.stdout + result.stderr)
        self.assertIn("deadline expired in fake lockstep", result.stdout + result.stderr)
        self.assertIn("--timeout 0.25", args_file.read_text())

    def test_architecture_compile_failure_is_counted(self):
        self.add_source()
        self.env["FAKE_GCC_RC"] = "6"
        result = self.assert_wrapper_failure("FAIL  case (compile error")
        self.assertIn("0/1 programs match", result.stdout + result.stderr)
        self.assertIn("case (compile)", result.stdout + result.stderr)
        self.assertIn("fake compiler diagnostic", result.stdout + result.stderr)

    def test_architecture_conversion_failure_is_counted(self):
        self.add_source()
        self.env["FAKE_PYTHON_RC"] = "7"
        result = self.assert_wrapper_failure("FAIL  case (elf2hex error")
        self.assertIn("0/1 programs match", result.stdout + result.stderr)
        self.assertIn("case (elf2hex)", result.stdout + result.stderr)

    def test_incomplete_architecture_population_is_rejected(self):
        self.add_source()
        self.versions.write_text(
            "ARCH_TEST_SHA=" + "a" * 40
            + "\nARCH_TEST_EXPECTED=2\nSPIKE_SHA=" + "b" * 40 + "\n")
        self.assert_wrapper_failure("discovered 1 lockstep cases; expected 2")

    def test_named_sample_runs_one_case_after_full_population_check(self):
        (self.src_dir / "alpha.S").write_text("nop\n")
        (self.src_dir / "beta.S").write_text("nop\n")
        self.versions.write_text(
            "ARCH_TEST_SHA=" + "a" * 40
            + "\nARCH_TEST_EXPECTED=2\nSPIKE_SHA=" + "b" * 40 + "\n"
        )
        compile_log = self.work / "compile.log"
        self.env["LOCKSTEP_CASE"] = "beta"
        self.env["FAKE_COMPILE_LOG"] = str(compile_log)
        self.write_tool("riscv64-unknown-elf-gcc", """
printf '%s\n' "$*" >> "$FAKE_COMPILE_LOG"
touch "${@: -1}"
""")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1/1 programs match", result.stdout)
        self.assertIn("beta.S", compile_log.read_text())
        self.assertNotIn("alpha.S", compile_log.read_text())

    def test_unknown_sample_case_is_rejected(self):
        self.add_source()
        self.env["LOCKSTEP_CASE"] = "missing"
        self.assert_wrapper_failure("requested lockstep case not found: missing")

    def test_zero_deadlines_are_rejected_before_compiler_or_comparator(self):
        self.add_source()
        self.env["FAKE_CHILD_MARKER"] = str(self.child_marker)
        for timeout in ("0", "0.0"):
            with self.subTest(timeout=timeout):
                self.child_marker.unlink(missing_ok=True)
                result = self.run_wrapper(timeout=timeout)
                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, combined)
                self.assertIn("LOCKSTEP_TIMEOUT must be greater than zero", combined)
                self.assertFalse(self.child_marker.exists(), combined)


class SoakLockstepWrapperTest(unittest.TestCase):
    """Require every requested random seed to produce a complete result."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-soak-lockstep-wrapper-")
        self.work = Path(self.tmp.name)
        self.repo = self.work / "repo"
        (self.repo / "tools").mkdir(parents=True)
        (self.repo / "compliance/link").mkdir(parents=True)
        (self.repo / "obj_dir_lockstep").mkdir()
        shutil.copy2(ROOT / "tools/soak_lockstep.sh", self.repo / "tools/soak_lockstep.sh")
        for path in (self.repo / "tools/rand_gen.py", self.repo / "tools/lockstep.py",
                     self.repo / "compliance/elf2hex.py",
                     self.repo / "compliance/link/spike-lockstep.ld"):
            path.write_text("")
        (self.repo / "tools/reference_versions.env").write_text(
            "ARCH_TEST_SHA=" + "a" * 40 + "\nARCH_TEST_EXPECTED=1\nSPIKE_SHA=" + "b" * 40 + "\n"
        )
        self.sim = self.repo / "obj_dir_lockstep/Vcpu"
        self.sim.write_text("#!/usr/bin/env bash\nexit 0\n")
        self.sim.chmod(0o755)
        self.spike_repo = self.work / "spike-repo"
        (self.spike_repo / "build").mkdir(parents=True)
        self.spike = self.spike_repo / "build/spike"
        self.spike.write_text("#!/usr/bin/env bash\nexit 0\n")
        self.spike.chmod(0o755)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.args_file = self.work / "lockstep.args"
        self.write_tool("riscv64-unknown-elf-gcc", """
[ -z "${FAKE_CHILD_MARKER:-}" ] || : > "$FAKE_CHILD_MARKER"
[ "${FAKE_GCC_RC:-0}" -eq 0 ] || exit "$FAKE_GCC_RC"
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then touch "$2"; exit 0; fi
    shift
done
exit 2
""")
        self.write_tool("git", f"""
if [ "${{4:-}}" = --show-toplevel ]; then
    printf '%s\\n' {self.spike_repo!s}
else
    printf '%s\\n' "${{FAKE_SPIKE_SHA:-{'b' * 40}}}"
fi
""")
        self.write_tool("python3", """
[ -z "${FAKE_CHILD_MARKER:-}" ] || : > "$FAKE_CHILD_MARKER"
case "${1##*/}" in
    rand_gen.py)
        [ "${FAKE_RANDOM_RC:-0}" -eq 0 ] || exit "$FAKE_RANDOM_RC"
        printf 'nop\\n' > "${@: -1}" ;;
    elf2hex.py)
        [ "${FAKE_ELF2HEX_RC:-0}" -eq 0 ] || exit "$FAKE_ELF2HEX_RC"
        : > "$3"; : > "$4" ;;
    lockstep.py)
        printf '%s\\n' "$*" > "$FAKE_LOCKSTEP_ARGS"
        echo 'deadline expired in fake random lockstep' >&2
        exit "${FAKE_LOCKSTEP_RC:-0}" ;;
    *) exec "$REAL_PYTHON" "$@" ;;
esac
""")
        self.child_marker = self.work / "child-ran"
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + self.env["PATH"],
            "REAL_PYTHON": sys.executable,
            "FAKE_LOCKSTEP_ARGS": str(self.args_file),
            "LOCKSTEP_TIMEOUT": "0.25",
            "SPIKE": str(self.spike),
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write_tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_wrapper(self, seeds, timeout=None):
        env = self.env.copy()
        if timeout is not None:
            env["LOCKSTEP_TIMEOUT"] = timeout
        return subprocess.run(
            [str(self.repo / "tools/soak_lockstep.sh"), str(seeds), "5"],
            cwd=self.repo, env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=5,
        )

    def test_zero_requested_random_cases_is_a_failure(self):
        result = self.run_wrapper(0)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("error: SEEDS must be a positive integer", result.stdout + result.stderr)

    def test_random_generation_failure_is_counted(self):
        self.env["FAKE_RANDOM_RC"] = "6"
        result = self.run_wrapper(1)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAIL seed=1 (random generation error", result.stdout + result.stderr)
        self.assertIn("0/1 random seeds", result.stdout + result.stderr)

    def test_elf2hex_failure_is_counted(self):
        self.env["FAKE_ELF2HEX_RC"] = "7"
        result = self.run_wrapper(1)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAIL seed=1 (elf2hex error", result.stdout + result.stderr)
        self.assertIn("0/1 random seeds", result.stdout + result.stderr)

    def test_random_program_compile_failure_is_counted(self):
        self.env["FAKE_GCC_RC"] = "8"
        result = self.run_wrapper(1)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FAIL seed=1 (compile error", result.stdout + result.stderr)
        self.assertIn("0/1 random seeds", result.stdout + result.stderr)
        self.assertIn("1 (compile)", result.stdout + result.stderr)

    def test_lockstep_deadline_failure_is_counted_and_forwarded(self):
        self.env["FAKE_LOCKSTEP_RC"] = "9"
        result = self.run_wrapper(1)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("deadline expired in fake random lockstep", result.stdout + result.stderr)
        self.assertIn("0/1 random seeds", result.stdout + result.stderr)
        self.assertIn("--timeout 0.25", self.args_file.read_text())

    def test_zero_deadlines_are_rejected_before_generator_compiler_or_comparator(self):
        self.env["FAKE_CHILD_MARKER"] = str(self.child_marker)
        for timeout in ("0", "0.0"):
            with self.subTest(timeout=timeout):
                self.child_marker.unlink(missing_ok=True)
                result = self.run_wrapper(1, timeout=timeout)
                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, combined)
                self.assertIn("LOCKSTEP_TIMEOUT must be greater than zero", combined)
                self.assertFalse(self.child_marker.exists(), combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
