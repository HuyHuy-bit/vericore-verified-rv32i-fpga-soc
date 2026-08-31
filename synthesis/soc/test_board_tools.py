from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from synthesis.soc import run_board


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "synthesis/soc/run_board.py"
XDC_SHA = "00a3404901f35aa9567b01ecb3f2c233b6efe9f4"
EXPECTED_PINS = {
    "clk100": "E3",
    "btn[0]": "D9",
    "btn[1]": "C9",
    "led[0]": "H5",
    "led[1]": "J5",
    "led[2]": "T9",
    "led[3]": "T10",
    "uart_tx": "D10",
}


class BoardContractTest(unittest.TestCase):
    def test_constraints_use_the_approved_pin_map(self) -> None:
        source = (ROOT / "boards/arty_a7_35t.xdc").read_text(encoding="utf-8")
        self.assertIn(XDC_SHA, source)
        pins = {}
        for pin, braced, plain in re.findall(
            r"PACKAGE_PIN\s+(\S+)\s+IOSTANDARD\s+LVCMOS33}\s+"
            r"\[get_ports\s+(?:{([^}]+)}|([^\]]+))\]",
            source,
        ):
            pins[(braced or plain).strip()] = pin
        self.assertEqual(pins, EXPECTED_PINS)
        referenced_groups = {
            (braced or plain).strip()
            for braced, plain in re.findall(
                r"\[get_ports\s+(?:{([^}]+)}|([^\]]+))\]", source
            )
        }
        referenced_ports = set()
        for group in referenced_groups:
            for port in group.split():
                if port == "btn[*]":
                    referenced_ports.update(("btn[0]", "btn[1]"))
                elif port == "led[*]":
                    referenced_ports.update((f"led[{index}]" for index in range(4)))
                else:
                    referenced_ports.add(port)
        self.assertEqual(referenced_ports, set(EXPECTED_PINS))
        clocks = re.findall(
            r"create_clock\s+-period\s+(\S+)\s+-name\s+(\S+)\s+"
            r"\[get_ports\s+(\S+)\]",
            source,
        )
        self.assertEqual(clocks, [("10.000", "clk100", "clk100")])
        self.assertIn("set_false_path -from [get_ports {btn[*]}]", source)
        self.assertIn("set_false_path -to [get_ports {led[*] uart_tx}]", source)

    def test_board_top_exposes_only_physical_ports(self) -> None:
        source = (ROOT / "rtl/boards/arty_a7_35t_top.sv").read_text(
            encoding="utf-8"
        )
        header = re.search(
            r"module\s+arty_a7_35t_top\s*#\(.*?\)\s*\((.*?)\);",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(header)
        ports = re.findall(
            r"(?:input|output)\s+var\s+logic(?:\s+\[[^]]+\])?\s+(\w+)",
            header.group(1),
        )
        self.assertEqual(ports, ["clk100", "btn", "led", "uart_tx"])
        self.assertRegex(header.group(1), r"input\s+var\s+logic\s+\[1:0\]\s+btn")
        self.assertRegex(header.group(1), r"output\s+var\s+logic\s+\[3:0\]\s+led")

    def test_board_flow_sources_exist(self) -> None:
        for relative in (
            "synthesis/soc/build.tcl",
            "synthesis/soc/program.tcl",
            "synthesis/soc/run_board.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_make_exposes_board_build_and_program_commands(self) -> None:
        build = subprocess.run(
            ["make", "-n", "soc-bitstream", "VIVADO=/tools/vivado"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        self.assertIn("python3 -m synthesis.soc.run_board build", build.stdout)
        self.assertNotIn("--rtl-commit", build.stdout)
        pinned = subprocess.run(
            [
                "make",
                "-n",
                "soc-bitstream",
                "VIVADO=/tools/vivado",
                "SOC_RTL_COMMIT=0123456789abcdef0123456789abcdef01234567",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(pinned.returncode, 0, pinned.stdout + pinned.stderr)
        self.assertIn(
            '--rtl-commit "0123456789abcdef0123456789abcdef01234567"',
            pinned.stdout,
        )
        program = subprocess.run(
            ["make", "-n", "soc-program", "VIVADO=/tools/vivado"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(program.returncode, 0, program.stdout + program.stderr)
        self.assertIn("python3 -m synthesis.soc.run_board program", program.stdout)

    def test_program_tcl_checks_the_jtag_visible_die_and_done_bit(self) -> None:
        source = (ROOT / "synthesis/soc/program.tcl").read_text(encoding="utf-8")
        self.assertIn(
            'string tolower [get_property PART $device]] ne "xc7a35t"',
            source,
        )
        self.assertIn("REGISTER.IR.BIT5_DONE", source)
        self.assertNotIn("REGISTER.CONFIG_STATUS.CFG_DONE", source)
        self.assertIn('error "FPGA configuration did not complete"', source)


class BoardRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-board-tools-")
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        for directory in (
            "rtl/core",
            "rtl/memory",
            "rtl/bus",
            "rtl/soc",
            "rtl/boards",
            "boards",
            "synthesis/soc",
        ):
            (self.repo / directory).mkdir(parents=True, exist_ok=True)
        for relative in (
            "rtl/core/core.sv",
            "rtl/memory/memory.sv",
            "rtl/bus/bus.sv",
            "rtl/soc/soc.sv",
            "rtl/boards/arty_a7_35t_top.sv",
        ):
            module = Path(relative).stem.replace("-", "_")
            (self.repo / relative).write_text(
                f"module {module}; endmodule\n", encoding="utf-8"
            )
        for relative in (
            "boards/arty_a7_35t.xdc",
            "synthesis/soc/build.tcl",
            "synthesis/soc/program.tcl",
        ):
            source = ROOT / relative
            (self.repo / relative).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
        (self.repo / "rtl/rv32i_pkg.sv").write_text(
            "package rv32i_pkg; endpackage\n", encoding="utf-8"
        )
        image = "".join(f"{index:08x}\n" for index in range(8192))
        self.imem = self.repo / "firmware-imem.hex"
        self.dmem = self.repo / "firmware-dmem.hex"
        self.imem.write_text(image, encoding="ascii")
        self.dmem.write_text(image[::-1][::-1], encoding="ascii")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.com"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Fixture"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True
        )
        self.commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        self.output = base / "board"
        self.fake = base / "fake-vivado"
        self.fake.write_text(
            "#!/usr/bin/env bash\n"
            "set -u\n"
            "if [ \"${1:-}\" = -version ]; then\n"
            "  echo \"vivado v${FAKE_VERSION:-2025.2} (64-bit)\"\n"
            "  echo \"SW Build 7654321\"\n"
            "  exit 0\n"
            "fi\n"
            "mode=${FAKE_MODE:-ok}\n"
            "[ \"$mode\" != timeout ] || { sleep 3; exit 0; }\n"
            "[ \"$mode\" != nonzero ] || exit 9\n"
            "script=\n"
            "out=\n"
            "while [ $# -gt 0 ]; do\n"
            "  if [ \"$1\" = -source ]; then shift; script=$1; fi\n"
            "  if [ \"$1\" = -tclargs ]; then shift; out=$1; break; fi\n"
            "  shift\n"
            "done\n"
            "if [[ \"$script\" = *program.tcl ]]; then\n"
            "  [ \"$mode\" = program_missing_marker ] || echo '===SOC_PROGRAM_DONE==='\n"
            "  exit 0\n"
            "fi\n"
            "[ -n \"$out\" ] || exit 90\n"
            "[ -f rtl/rv32i_pkg.sv ] && [ -f boards/arty_a7_35t.xdc ] || exit 91\n"
            "mkdir -p \"$out\"\n"
            "part=xc7a35ticsg324-1L\n"
            "period=10.000\n"
            "wns=0.250\n"
            "top=arty_a7_35t_top\n"
            "[ \"$mode\" != wrong_part ] || part=xc7a100tcsg324-1\n"
            "[ \"$mode\" != wrong_period ] || period=9.000\n"
            "[ \"$mode\" != negative_wns ] || wns=-0.100\n"
            "[ \"$mode\" != wrong_top ] || top=wrong_top\n"
            "printf 'part=%s\\nclock_period_ns=%s\\nwns_ns=%s\\ntop=%s\\n' \"$part\" \"$period\" \"$wns\" \"$top\" > \"$out/build_meta.txt\"\n"
            "[ \"$mode\" != missing_meta ] || rm -f \"$out/build_meta.txt\"\n"
            "[ \"$mode\" = missing_util ] || printf '| Slice LUTs | 1 |\\n' > \"$out/utilization.rpt\"\n"
            "[ \"$mode\" = missing_timing ] || printf 'WNS(ns) 0.250\\n' > \"$out/timing_summary.rpt\"\n"
            "[ \"$mode\" = unconstrained ] && printf 'Unconstrained Paths 1\\n' >> \"$out/timing_summary.rpt\"\n"
            "[ \"$mode\" = missing_drc ] || printf 'DRC clean\\n' > \"$out/drc.rpt\"\n"
            "[ \"$mode\" = drc_error ] && printf 'CRITICAL WARNING test\\n' > \"$out/drc.rpt\"\n"
            "[ \"$mode\" = missing_bitstream ] || printf 'bitstream\\n' > \"$out/rv32i-soc-arty-a7-35t.bit\"\n"
            "printf 'do not publish\\n' > \"$out/extra.log\"\n"
            "[ \"$mode\" != stale ] || touch -t 200001010000 \"$out/rv32i-soc-arty-a7-35t.bit\"\n"
            "[ \"$mode\" = missing_marker ] || echo '===SOC_BUILD_DONE==='\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_build(self, **environment: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["VIVADO"] = str(self.fake)
        env.update(environment)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "synthesis.soc.run_board",
                "build",
                "--root",
                str(self.repo),
                "--imem",
                str(self.imem),
                "--dmem",
                str(self.dmem),
                "--output",
                str(self.output),
                "--rtl-commit",
                self.commit,
                "--timeout",
                "1",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )

    def assert_build_failure(self, diagnostic: str, **environment: str) -> None:
        result = self.run_build(**environment)
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn(diagnostic, output)
        self.assertNotIn("Traceback", output)

    def test_firmware_images_are_canonical_and_bounded(self) -> None:
        digest = run_board.validate_firmware_image(self.imem)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.imem.write_text("0000000A\n" * 8192, encoding="ascii")
        with self.assertRaisesRegex(run_board.BoardError, "8192 lowercase"):
            run_board.validate_firmware_image(self.imem)

    def test_success_publishes_only_validated_artifacts(self) -> None:
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()),
            [
                "drc.rpt",
                "manifest.json",
                "rv32i-soc-arty-a7-35t.bit",
                "timing_summary.rpt",
                "utilization.rpt",
            ],
        )
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["part"], "xc7a35ticsg324-1L")
        self.assertEqual(manifest["clock_period_ns"], 10.0)
        self.assertEqual(manifest["wns_ns"], 0.25)
        self.assertEqual(manifest["source_commit"], self.commit)
        self.assertEqual(manifest["rtl_commit"], self.commit)
        self.assertEqual(manifest["vivado"]["version"], "2025.2")
        self.assertRegex(
            manifest["measured_at"],
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
        )

    def test_stage_contains_only_required_inputs(self) -> None:
        with run_board.create_board_stage(
            self.repo, None, self.imem, self.dmem
        ) as stage_name:
            stage = Path(stage_name)
            files = sorted(
                path.relative_to(stage).as_posix()
                for path in stage.rglob("*")
                if path.is_file()
            )
        self.assertEqual(
            files,
            [
                "boards/arty_a7_35t.xdc",
                "firmware-dmem.hex",
                "firmware-imem.hex",
                "rtl/boards/arty_a7_35t_top.sv",
                "rtl/bus/bus.sv",
                "rtl/core/core.sv",
                "rtl/memory/memory.sv",
                "rtl/rv32i_pkg.sv",
                "rtl/soc/soc.sv",
                "synthesis/soc/build.tcl",
                "synthesis/soc/program.tcl",
            ],
        )

    def test_explicit_override_is_authoritative(self) -> None:
        missing = Path(self.tmp.name) / "missing-vivado"
        self.assert_build_failure("explicit VIVADO does not exist", VIVADO=str(missing))

    def test_wrong_vivado_version_is_rejected(self) -> None:
        self.assert_build_failure("Vivado 2025.2 is required", FAKE_VERSION="2024.2")

    def test_build_failure_modes_are_rejected(self) -> None:
        cases = {
            "nonzero": "Vivado build failed",
            "timeout": "Vivado build timed out",
            "missing_marker": "completion marker missing",
            "missing_bitstream": "bitstream is missing",
            "missing_util": "utilization report is missing",
            "missing_timing": "timing report is missing",
            "missing_drc": "DRC report is missing",
            "missing_meta": "build metadata is missing",
            "stale": "bitstream is stale",
            "wrong_part": "wrong applied part",
            "wrong_period": "wrong applied clock period",
            "negative_wns": "negative WNS",
            "wrong_top": "wrong applied top",
            "unconstrained": "unconstrained timing",
            "drc_error": "DRC contains",
        }
        for mode, diagnostic in cases.items():
            with self.subTest(mode=mode):
                self.assert_build_failure(diagnostic, FAKE_MODE=mode)

    def test_failure_preserves_existing_output(self) -> None:
        self.output.mkdir()
        for name in run_board.PUBLISHED_FILES:
            (self.output / name).write_text(f"old {name}\n", encoding="utf-8")
        marker = self.output / "manifest.json"
        self.assert_build_failure("completion marker missing", FAKE_MODE="missing_marker")
        self.assertEqual(marker.read_text(encoding="utf-8"), "old manifest.json\n")

    def test_success_refuses_an_unrecognized_existing_destination(self) -> None:
        self.output.mkdir()
        marker = self.output / "unrelated.txt"
        marker.write_text("keep\n", encoding="utf-8")
        self.assert_build_failure("existing board output has unexpected entries")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_output_destination_cannot_be_a_symbolic_link(self) -> None:
        target = Path(self.tmp.name) / "other-board"
        target.mkdir()
        for name in run_board.PUBLISHED_FILES:
            (target / name).write_text(f"old {name}\n", encoding="utf-8")
        self.output.symlink_to(target, target_is_directory=True)
        self.assert_build_failure("board output cannot be a symbolic link")
        self.assertEqual(
            (target / "manifest.json").read_text(encoding="utf-8"),
            "old manifest.json\n",
        )

    def test_dirty_tracked_source_is_rejected(self) -> None:
        (self.repo / "rtl/core/core.sv").write_text(
            "module core; wire dirty; endmodule\n", encoding="utf-8"
        )
        self.assert_build_failure("tracked source differs")

    def test_program_requires_completion_marker(self) -> None:
        bitstream = Path(self.tmp.name) / "image.bit"
        bitstream.write_bytes(b"bitstream\n")
        env = os.environ.copy()
        env["VIVADO"] = str(self.fake)
        env["FAKE_MODE"] = "program_missing_marker"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "synthesis.soc.run_board",
                "program",
                "--root",
                str(self.repo),
                "--bitstream",
                str(bitstream),
                "--timeout",
                "1",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("program completion marker missing", result.stderr)

    def test_program_rejects_a_non_bitstream_file(self) -> None:
        image = Path(self.tmp.name) / "image.bin"
        image.write_bytes(b"not a bitstream\n")
        env = os.environ.copy()
        env["VIVADO"] = str(self.fake)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "synthesis.soc.run_board",
                "program",
                "--root",
                str(self.repo),
                "--bitstream",
                str(image),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bitstream must use the .bit extension", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
