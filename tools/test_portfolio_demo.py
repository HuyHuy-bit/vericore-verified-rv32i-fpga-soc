#!/usr/bin/env python3

from __future__ import annotations

from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from tools.portfolio_demo import (
    DemoError,
    demo_steps,
    run_demo,
    summary_text,
    validate_media,
    write_media_manifest,
)
from tools import test_render_portfolio as render_fixture


ROOT = Path(__file__).resolve().parents[1]


def animated_gif() -> bytes:
    data = bytearray(b"GIF89a\x00\x05\xd0\x02\x80\x00\x00\x00\x00\x00\xff\xff\xff")
    data.extend(b"\x21\xfe\xff" + b"x" * 255 + b"\xff" + b"y" * 255 + b"\x00")
    for _ in range(30):
        data.extend(b"\x21\xf9\x04\x00\x64\x00\x00\x00")
        data.extend(b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00")
        data.extend(b"\x02\x02\x44\x01\x00")
    data.extend(b"\x3b")
    return bytes(data)


class PortfolioDemoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = render_fixture.PortfolioRendererTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.result = self.fixture.result

    def test_production_steps_use_repository_entry_points(self) -> None:
        steps = demo_steps(self.root)
        self.assertEqual([step.name for step in steps], ["fast correctness", "Spike lockstep sample"])
        self.assertEqual(steps[0].command, ("python3", "tools/verification.py", "run", "--profile", "fast"))
        self.assertEqual(steps[1].command, ("make", "--no-print-directory", "lockstep-sample"))

    def test_successful_run_executes_steps_in_order(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, **kwargs):
            calls.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, "ok\n", "")

        transcript = StringIO()
        with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
            status = run_demo(self.root, transcript, live=True, runner=runner)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [step.command for step in demo_steps(self.root)])
        self.assertEqual(transcript.getvalue(), summary_text(self.result))

    def test_subprocess_failure_and_timeout_propagate(self) -> None:
        def failed(command, **kwargs):
            return subprocess.CompletedProcess(command, 9, "deliberate failure\n", "")

        with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
            output = StringIO()
            self.assertEqual(run_demo(self.root, output, runner=failed), 9)
            self.assertIn("deliberate failure", output.getvalue())

            def timed_out(command, **kwargs):
                raise subprocess.TimeoutExpired(command, 3, output="late\n")

            output = StringIO()
            self.assertEqual(run_demo(self.root, output, runner=timed_out), 124)
            self.assertIn("timed out", output.getvalue())

    def test_unverified_result_set_is_rejected(self) -> None:
        with self.assertRaisesRegex(DemoError, "result records"):
            run_demo(self.root, StringIO(), live=False)

    def test_make_exposes_live_record_and_container_targets(self) -> None:
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", "portfolio-gif"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("portfolio-demo-record", result.stdout)
        self.assertIn("--target demo", result.stdout)

    def test_tape_holds_the_result_for_portfolio_length(self) -> None:
        source = (ROOT / "docs/media/portfolio-demo.tape").read_text(encoding="utf-8")
        self.assertIn("Sleep 30s", source)

    def write_media(self) -> None:
        (self.root / "README.md").write_text(
            "![Portfolio verification demo](docs/media/portfolio-demo.gif)\n", encoding="utf-8"
        )
        (self.root / "docs/media").mkdir()
        (self.root / "docs/media/portfolio-demo.txt").write_text(summary_text(self.result), encoding="utf-8")
        (self.root / "docs/media/portfolio-demo.tape").write_text(
            "Output docs/media/portfolio-demo.gif\nSet Width 1280\nSet Height 720\n"
            "Type \"python3 tools/portfolio_demo.py --live\"\n",
            encoding="utf-8",
        )
        (self.root / "docs/media/portfolio-demo.gif").write_bytes(animated_gif())
        write_media_manifest(self.root)

    def test_media_validation_checks_dimensions_frames_duration_hashes_and_link(self) -> None:
        self.write_media()
        with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
            self.assertEqual(validate_media(self.root), [])

        transcript = self.root / "docs/media/portfolio-demo.txt"
        transcript.write_text(transcript.read_text(encoding="utf-8") + "stale\n", encoding="utf-8")
        with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
            errors = validate_media(self.root)
        self.assertTrue(any("transcript" in error for error in errors))

    def test_media_manifest_rejects_damaged_gif(self) -> None:
        self.write_media()
        path = self.root / "docs/media/portfolio-demo.gif"
        path.write_bytes(path.read_bytes()[:-1])
        with mock.patch("tools.portfolio_demo.load_validated", return_value=self.result):
            errors = validate_media(self.root)
        self.assertTrue(any("GIF" in error or "hash" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
