#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.render_portfolio import (
    RenderError,
    check_documents,
    render_documents,
    replace_block,
    soc_status,
    write_documents,
)
from tools.results import ResultSet

ROOT = Path(__file__).resolve().parents[1]


class PortfolioRendererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-render-")
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        self.write_documents()
        self.result = self.result_set()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_documents(self) -> None:
        blocks = {
            "README.md": ("facts", "status", "soc", "snapshot", "verification", "benchmarks", "synthesis", "provenance"),
            "docs/evidence.md": ("overview", "facts", "status", "soc", "verification", "benchmarks", "synthesis", "synthesis-hashes", "provenance"),
            "docs/architecture.md": ("facts", "status", "benchmarks", "synthesis"),
            "docs/verification.md": ("facts", "status", "summary"),
        }
        for relative, names in blocks.items():
            body = [f"# {relative}", ""]
            for name in names:
                body.extend((f"<!-- portfolio:{name}:start -->", "stale", f"<!-- portfolio:{name}:end -->", ""))
            (self.root / relative).write_text("\n".join(body), encoding="utf-8")
        (self.root / "docs/coverage.md").write_text(
            "# Coverage\n\n**Evidence status: current.**\n\n**44/44 cover points hit (100.0%)**\n",
            encoding="utf-8",
        )

    def result_set(self) -> ResultSet:
        verification = {
            "tooling_commit": "a" * 40,
            "rtl_commit": "b" * 40,
            "measured_at": "2026-08-27T12:34:56Z",
            "decoder_vectors": 2120,
            "hazard_vectors": 262144,
            "harness_tests": 106,
            "assertions": {"concurrent": 25, "immediate": 2},
            "cover_points": {"source": 44, "hit": 44},
            "directed_programs": 25,
            "memory_configurations": [{"name": name, "passed": 25} for name in ("baseline", "slow-mem", "icache-only", "wt", "wb", "assoc")],
            "predictor_configurations": [{"name": name, "passed": 25} for name in ("gshare", "no-ras", "small-btb")],
            "architecture_tests": {"discovered": 38, "passed": 38, "failed": 0, "missing": 0, "infrastructure": 0},
            "architecture_lockstep": {"discovered": 38, "passed": 38, "failed": 0},
            "python_random": {
                "baseline": {"requested": 1000, "passed": 1000},
                "cached": {"requested": 1000, "passed": 1000},
            },
            "spike_random": {"requested": 200, "passed": 200, "instructions": 60},
            "coverage": {
                "line": {"hit": 260, "total": 278},
                "branch": {"hit": 186, "total": 198},
                "expression": {"hit": 202, "total": 221},
                "toggle": {"hit": 0, "total": 0},
                "user": {"hit": 44, "total": 44},
            },
        }
        benchmarks = []
        for configuration in ("slow-memory", "icache", "write-back", "ideal-memory"):
            for index, kernel in enumerate(("crc32", "matmul", "sort", "llist", "interp")):
                benchmarks.append({
                    "configuration": configuration,
                    "kernel": kernel,
                    "cycles": str(2000 + index),
                    "instructions_retired": "1000",
                    "branches": "100",
                    "mispredictions": "5",
                    "icache_accesses": "800",
                    "icache_misses": "20",
                    "dcache_accesses": "200",
                    "dcache_misses": "10",
                })
        synthesis = []
        for index, configuration in enumerate(("core", "icache", "dcache-wt", "dcache-wb")):
            synthesis.append({
                "configuration": configuration,
                "lut": str(4000 + index),
                "ff": str(5000 + index),
                "bram_tiles": "2.0",
                "wns_ns": f"{-10.0 - index:.3f}",
                "critical_path_ns": f"{12.0 + index:.3f}",
                "fmax_mhz": f"{1000.0 / (12.0 + index):.3f}",
                "measurement_date": "2026-08-27",
                "vivado_version": "2025.2",
                "vivado_build": "1234567",
                "part": "xc7a35ticsg324-1L",
                "utilization_sha256": str(index) * 64,
                "timing_sha256": str(index + 4) * 64,
            })
        return ResultSet(
            self.root / "results",
            {"tooling_commit": "a" * 40, "rtl_commit": "b" * 40, "measured_at": "2026-08-27T12:34:56Z"},
            verification,
            tuple(benchmarks),
            tuple(synthesis),
            {
                "container": {
                    "image": "ghcr.io/example/verify",
                    "revision": 1,
                    "digest": "sha256:" + "e" * 64,
                    "base": "ubuntu:24.04@sha256:" + "f" * 64,
                },
                "ubuntu": "24.04",
                "verilator": "5.048",
                "riscv_gcc": "13.2.0",
                "riscv_as": "2.42",
                "python": "3.12",
                "spike_commit": "c" * 40,
                "architecture_test_commit": "d" * 40,
                "architecture_test_expected": 38,
                "vivado": {"version": "2025.2", "build": "1234567", "platform": "linux"},
                "vhs": "0.11.0",
                "ffmpeg": "6.1.1",
            },
        )

    def test_replace_block_rejects_missing_duplicate_reversed_and_nested_markers(self) -> None:
        cases = (
            ("plain\n", "missing marker"),
            ("<!-- portfolio:x:start -->\na\n<!-- portfolio:x:start -->\nb\n<!-- portfolio:x:end -->\n", "exactly one"),
            ("<!-- portfolio:x:end -->\na\n<!-- portfolio:x:start -->\n", "before its end"),
            ("<!-- portfolio:x:start -->\n<!-- portfolio:y:start -->\n<!-- portfolio:x:end -->\n", "nested marker"),
        )
        for source, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(RenderError, diagnostic):
                    replace_block(source, "x", "new")

    def test_absent_soc_evidence_renders_only_the_pending_state(self) -> None:
        status = soc_status(self.root / "results")
        self.assertEqual(status, "Physical-board evidence: not published")
        self.assertNotIn("LUT", status)
        self.assertNotIn("MHz", status)
        self.assertNotIn("passed", status.lower())

    def test_render_replaces_every_known_block(self) -> None:
        rendered = render_documents(self.root, self.result)
        self.assertEqual(set(rendered), {
            self.root / "README.md",
            self.root / "docs/evidence.md",
            self.root / "docs/architecture.md",
            self.root / "docs/verification.md",
            self.root / "docs/coverage.md",
        })
        self.assertIn("25 directed tests × 6 memory configurations", rendered[self.root / "README.md"])
        self.assertIn("66.7–83.3 MHz routed Artix-7 implementations", rendered[self.root / "README.md"])
        self.assertIn("RISC-V assembler 2.42", rendered[self.root / "README.md"])
        self.assertIn("38/38", rendered[self.root / "docs/evidence.md"])
        self.assertIn(
            "Physical-board evidence: not published",
            rendered[self.root / "README.md"],
        )
        self.assertIn(
            "Physical-board evidence: not published",
            rendered[self.root / "docs/evidence.md"],
        )
        self.assertIn("`" + "a" * 40 + "`", rendered[self.root / "docs/evidence.md"])
        self.assertIn("`" + "b" * 40 + "`", rendered[self.root / "docs/evidence.md"])
        self.assertIn("`" + "0" * 64 + "` / `" + "4" * 64 + "`", rendered[self.root / "docs/evidence.md"])
        for path, value in rendered.items():
            if path.name != "coverage.md":
                self.assertEqual(value.count("<!-- evidence-facts:begin -->"), 1)
                self.assertEqual(value.count("<!-- evidence-facts:end -->"), 1)
            self.assertFalse(any(line != line.rstrip() for line in value.splitlines()))
        self.assertNotIn("\nstale\n", "".join(rendered.values()))

    def test_historical_results_are_labeled_in_every_document(self) -> None:
        (self.root / "rtl").mkdir()
        (self.root / "rtl/core.sv").write_text("module core; endmodule\n", encoding="utf-8")
        (self.root / "sim").mkdir()
        (self.root / "sim/cpu_tb.cpp").write_text("int main() {}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.com"], cwd=self.root, check=True
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "measured source"], cwd=self.root, check=True)
        measured = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self.result.manifest["rtl_commit"] = measured
        (self.root / "rtl/core.sv").write_text(
            "module core; logic later; endmodule\n", encoding="utf-8"
        )
        notice = (
            "Historical measurements — validated for RTL "
            + measured
            + "; current RTL changes are not yet remeasured."
        )
        rendered = render_documents(self.root, self.result)
        for relative in (
            "README.md",
            "docs/evidence.md",
            "docs/architecture.md",
            "docs/verification.md",
        ):
            self.assertIn(notice, rendered[self.root / relative])
            self.assertIn("EVIDENCE_FACT EVIDENCE_STATUS=historical", rendered[self.root / relative])
        self.assertIn(
            "**Evidence status: historical.**",
            rendered[self.root / "docs/coverage.md"],
        )

    def test_check_detects_stale_content_and_write_is_idempotent(self) -> None:
        with mock.patch("tools.render_portfolio.load_validated", return_value=self.result):
            self.assertTrue(check_documents(self.root))
            write_documents(self.root)
            self.assertEqual(check_documents(self.root), [])
            first = {path: path.read_bytes() for path in render_documents(self.root, self.result)}
            write_documents(self.root)
            self.assertEqual(first, {path: path.read_bytes() for path in first})

    def test_invalid_results_are_rejected_before_document_changes(self) -> None:
        before = (self.root / "README.md").read_bytes()
        with self.assertRaisesRegex(RenderError, "result records"):
            write_documents(self.root)
        self.assertEqual((self.root / "README.md").read_bytes(), before)


class SocDocumentationContractTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_readme_links_the_soc_guide_and_labels_the_recording(self) -> None:
        source = self.read("README.md")
        self.assertIn("[Board-ready SoC](docs/soc.md)", source)
        self.assertIn("![Actual post-route physical placement]", source)
        self.assertIn("docs/images/soc-floorplan.svg", source)
        self.assertIn("actual Vivado post-route primitive locations", source)
        self.assertIn("![Native Vivado implemented-device view", source)
        self.assertIn("docs/images/soc-vivado-device.png", source)
        self.assertIn("docs/images/soc-vivado-device.json", source)
        self.assertIn("not proof of operation on a physical board", source)
        self.assertIn("not a conceptual CPU illustration", source)
        self.assertIn("verification workflow", source)
        self.assertIn("not FPGA board footage", source)
        self.assertIn("make soc-check", source)
        self.assertIn("make soc-bitstream", source)

    def test_soc_guide_records_the_complete_board_contract(self) -> None:
        source = self.read("docs/soc.md")
        required = (
            "0x0000_0000–0x0000_7FFF",
            "0x1000_0000–0x1000_000F",
            "0x1000_1000–0x1000_101F",
            "0x2000_0000–0x2000_7FFF",
            "TXDATA",
            "STATUS",
            "IRQ_PENDING",
            "IRQ_ENABLE",
            "115200 8-N-1",
            "BTN0",
            "BTN1",
            "make soc-check",
            "make soc-bitstream",
            "make soc-floorplan",
            "make soc-post-route-sim",
            "make soc-program",
            "not architectural access-fault traps",
            "transmit-only",
            "no bootloader",
            "no external memory",
            "no PLIC",
            "no operating system",
            "Physical-board evidence: not published",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, source)

    def test_architecture_names_every_integration_boundary(self) -> None:
        source = self.read("docs/architecture.md")
        for name in ("`cpu`", "`rv32i_core`", "`rv32i_soc`", "`arty_a7_35t_top`"):
            with self.subTest(name=name):
                self.assertIn(name, source)

    def test_verification_names_soc_units_and_complete_uart_output(self) -> None:
        source = self.read("docs/verification.md")
        for name in (
            "core_external",
            "csr_external_irq",
            "wb_master_adapter",
            "wb_arbiter",
            "wb_interconnect",
            "wb_memory",
            "uart_tx",
            "wb_uart",
            "button_debounce",
            "wb_gpio_irq",
            "reset_controller",
            "soc_smoke",
        ):
            with self.subTest(name=name):
                self.assertIn(name, source)
        self.assertIn("rv32i soc ready\\nexternal irq\\nexternal irq\\n", source)

    def test_unpublished_board_state_and_coverage_scope_are_explicit(self) -> None:
        evidence = self.read("docs/evidence.md")
        coverage = self.read("docs/coverage.md")
        self.assertIn("Physical-board evidence: not published", evidence)
        self.assertNotIn("Physical-board evidence: published and validated", evidence)
        self.assertIn(
            "SoC unit and integration checks are not part of this core coverage database",
            coverage,
        )


if __name__ == "__main__":
    unittest.main()
