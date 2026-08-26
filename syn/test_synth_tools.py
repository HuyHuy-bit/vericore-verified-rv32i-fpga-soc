#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from syn import run_synth


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "syn/run_synth.py"
SUMMARIZER = ROOT / "syn/summarize_reports.py"


class SynthToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-synth-tools-")
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "rtl").mkdir(parents=True)
        (self.repo / "syn").mkdir()
        (self.repo / "rtl/core.sv").write_text("module cpu; endmodule\n", encoding="utf-8")
        (self.repo / "syn/build.tcl").write_text("puts build\n", encoding="utf-8")
        (self.repo / "syn/cpu.xdc").write_text(
            "create_clock -period 2.000 -name clk [get_ports clk]\n",
            encoding="utf-8",
        )
        image = "".join(f"{index:08x}\n" for index in range(512))
        (self.repo / "syn/blank_instr.hex").write_text(image, encoding="utf-8")
        data_image = "".join(f"{index:08x}\n" for index in reversed(range(512)))
        (self.repo / "syn/blank_data.hex").write_text(data_image, encoding="utf-8")
        self.fake = Path(self.tmp.name) / "fake-vivado"
        self.fake.write_text(
            "#!/usr/bin/env bash\n"
            "set -u\n"
            "if [ \"${1:-}\" = -version ]; then\n"
            "  echo \"vivado v${FAKE_VERSION:-2025.2} (64-bit)\"\n"
            "  echo \"SW Build 1234567\"\n"
            "  exit ${FAKE_VERSION_STATUS:-0}\n"
            "fi\n"
            "name=\n"
            "while [ $# -gt 0 ]; do\n"
            "  if [ \"$1\" = -tclargs ]; then shift; name=$1; break; fi\n"
            "  shift\n"
            "done\n"
            "[ -n \"$name\" ] || exit 90\n"
            "mode=${FAKE_MODE:-ok}\n"
            "[ \"$mode\" != nonzero ] || exit 9\n"
            "out=out_$name\n"
            "mkdir -p \"$out\"\n"
            "part=xc7a35ticsg324-1L\n"
            "period=2.000\n"
            "[ \"$mode\" != wrong_part ] || part=xc7a100tcsg324-1\n"
            "[ \"$mode\" != wrong_period ] || period=10.000\n"
            "printf 'config=%s\\npart=%s\\nclock_period_ns=%s\\n' \"$name\" \"$part\" \"$period\" > \"$out/build_meta.txt\"\n"
            "[ \"$mode\" != missing_meta ] || rm -f \"$out/build_meta.txt\"\n"
            "if [ \"$mode\" != missing_util ]; then\n"
            "  printf '| Slice LUTs* | 3990 |\\n| Slice Registers | 4966 |\\n| Block RAM Tile | 2.0 |\\n| RAMB18 | 4 |\\n' > \"$out/utilization.rpt\"\n"
            "fi\n"
            "if [ \"$mode\" != missing_timing ]; then\n"
            "  printf 'WNS(ns) TNS(ns) TNS Failing Endpoints\\n------- ------- ---------------------\\n-11.280 -1.0 1\\n' > \"$out/timing_summary.rpt\"\n"
            "fi\n"
            "[ \"$mode\" != stale ] || touch -t 200001010000 \"$out/utilization.rpt\"\n"
            "[ \"$mode\" = missing_marker ] || echo \"===BUILD_DONE:$name===\"\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)
        self.reports = Path(self.tmp.name) / "reports"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_matrix(self, **environment: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["VIVADO"] = str(self.fake)
        env.update(environment)
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--root",
                str(self.repo),
                "--report-dir",
                str(self.reports),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    def assert_matrix_failure(self, diagnostic: str, **environment: str) -> None:
        result = self.run_matrix(**environment)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stdout + result.stderr)

    def test_explicit_fake_vivado_routes_four_private_stages(self) -> None:
        result = self.run_matrix()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(path.name for path in self.reports.iterdir()),
            ["core", "dcache-wb", "dcache-wt", "icache"],
        )
        self.assertFalse(any(self.repo.glob("out_*")))
        for name in ("core", "icache", "dcache-wt", "dcache-wb"):
            manifest = json.loads((self.reports / name / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["part"], "xc7a35ticsg324-1L")
            self.assertEqual(manifest["clock_period_ns"], 2.0)
            self.assertEqual(manifest["tool_version"], "2025.2")
            self.assertEqual(len(manifest["source_commit"]), 40)
            self.assertEqual(manifest["source_commit"], manifest["rtl_commit"])

    def test_explicit_override_is_authoritative(self) -> None:
        env = os.environ.copy()
        env["VIVADO"] = str(Path(self.tmp.name) / "missing-vivado")
        env["PATH"] = f"{self.fake.parent}:{env.get('PATH', '')}"
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--root", str(self.repo), "--report-dir", str(self.reports)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit VIVADO does not exist", result.stderr)

    def test_wrong_vivado_version_is_rejected(self) -> None:
        self.assert_matrix_failure("Vivado 2025.2 is required", FAKE_VERSION="2024.2")

    def test_nonzero_route_is_rejected(self) -> None:
        self.assert_matrix_failure("Vivado failed for core", FAKE_MODE="nonzero")

    def test_missing_completion_marker_is_rejected(self) -> None:
        self.assert_matrix_failure("completion marker missing for core", FAKE_MODE="missing_marker")

    def test_wrong_applied_part_is_rejected(self) -> None:
        self.assert_matrix_failure("wrong applied part for core", FAKE_MODE="wrong_part")

    def test_wrong_applied_constraint_is_rejected(self) -> None:
        self.assert_matrix_failure("wrong applied clock period for core", FAKE_MODE="wrong_period")

    def test_missing_report_is_rejected(self) -> None:
        self.assert_matrix_failure("missing utilization report for core", FAKE_MODE="missing_util")

    def test_missing_timing_report_is_rejected(self) -> None:
        self.assert_matrix_failure("missing timing report for core", FAKE_MODE="missing_timing")

    def test_stale_report_is_rejected(self) -> None:
        self.assert_matrix_failure("stale utilization report for core", FAKE_MODE="stale")

    def test_missing_applied_metadata_is_rejected(self) -> None:
        self.assert_matrix_failure("build metadata missing for core", FAKE_MODE="missing_meta")

    def test_degenerate_memory_image_is_rejected(self) -> None:
        zeros = "00000000\n" * 512
        (self.repo / "syn/blank_instr.hex").write_text(zeros, encoding="utf-8")
        self.assert_matrix_failure("memory image must contain varied data")

    def test_dirty_source_checkout_is_rejected(self) -> None:
        (self.repo / "rtl/core.sv").write_text("module cpu; wire dirty; endmodule\n", encoding="utf-8")
        self.assert_matrix_failure("tracked source differs from the recorded commits")

    def test_windows_launcher_selection_and_command_are_local(self) -> None:
        candidate = Path(self.tmp.name) / "Vivado/2025.2/bin/vivado.bat"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("@echo off\n", encoding="utf-8")
        launcher, windows = run_synth.select_launcher(None, None, True, (candidate,))
        self.assertEqual(launcher, candidate)
        self.assertTrue(windows)
        command = run_synth.windows_command(
            Path("/mnt/c/Windows/System32/cmd.exe"),
            r"C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat",
            ("-mode", "batch"),
        )
        self.assertEqual(command[-2:], ["-mode", "batch"])
        self.assertNotIn("\\\\wsl$", " ".join(command).lower())

    def test_summary_calculates_fmax_and_reports_bram_units(self) -> None:
        result = self.run_matrix()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = subprocess.run(
            [sys.executable, str(SUMMARIZER), "--report-dir", str(self.reports)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(summary.returncode, 0, summary.stdout + summary.stderr)
        self.assertIn("75.301", summary.stdout)
        self.assertIn("RAMB18", summary.stdout)
        self.assertIn("BRAM tiles", summary.stdout)
        manifest = json.loads((self.reports / "core/manifest.json").read_text())
        self.assertIn(manifest["source_commit"][:12], summary.stdout)

    def test_summary_rejects_tampered_report(self) -> None:
        self.assertEqual(self.run_matrix().returncode, 0)
        path = self.reports / "core/utilization.rpt"
        path.write_text(path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SUMMARIZER), "--report-dir", str(self.reports)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("report hash mismatch", result.stderr)

    def test_summary_rejects_missing_configuration(self) -> None:
        self.assertEqual(self.run_matrix().returncode, 0)
        for path in (self.reports / "dcache-wb").iterdir():
            path.unlink()
        (self.reports / "dcache-wb").rmdir()
        result = subprocess.run(
            [sys.executable, str(SUMMARIZER), "--report-dir", str(self.reports)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("report configurations do not match", result.stderr)

    def test_summary_rejects_provenance_mismatch(self) -> None:
        self.assertEqual(self.run_matrix().returncode, 0)
        path = self.reports / "icache/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["source_commit"] = "f" * 40
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SUMMARIZER), "--report-dir", str(self.reports)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provenance mismatch", result.stderr)

    def test_make_targets_run_fake_matrix_and_summary(self) -> None:
        for name in ("run_synth.py", "summarize_reports.py"):
            (self.repo / "syn" / name).write_text(
                (ROOT / "syn" / name).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        subprocess.run(["git", "add", "syn"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add synthesis tools"], cwd=self.repo, check=True)
        matrix = subprocess.run(
            [
                "make",
                "-f",
                str(ROOT / "Makefile"),
                "synth-matrix",
                f"VIVADO={self.fake}",
                f"REPORT_DIR={self.reports}",
            ],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(matrix.returncode, 0, matrix.stdout + matrix.stderr)
        summary = subprocess.run(
            [
                "make",
                "-f",
                str(ROOT / "Makefile"),
                "synth-summary",
                f"REPORT_DIR={self.reports}",
            ],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(summary.returncode, 0, summary.stdout + summary.stderr)
        self.assertIn("# Synthesis summary", summary.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
