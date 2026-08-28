#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.render_portfolio import (
    RenderError,
    check_documents,
    render_documents,
    replace_block,
    write_documents,
)
from tools.results import ResultSet


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
            "README.md": ("facts", "snapshot", "verification", "benchmarks", "synthesis", "provenance"),
            "docs/evidence.md": ("overview", "facts", "verification", "benchmarks", "synthesis", "synthesis-hashes", "provenance"),
            "docs/architecture.md": ("facts", "benchmarks", "synthesis"),
            "docs/verification.md": ("facts", "summary"),
        }
        for relative, names in blocks.items():
            body = [f"# {relative}", ""]
            for name in names:
                body.extend((f"<!-- portfolio:{name}:start -->", "stale", f"<!-- portfolio:{name}:end -->", ""))
            (self.root / relative).write_text("\n".join(body), encoding="utf-8")

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

    def test_render_replaces_every_known_block(self) -> None:
        rendered = render_documents(self.root, self.result)
        self.assertEqual(set(rendered), {
            self.root / "README.md",
            self.root / "docs/evidence.md",
            self.root / "docs/architecture.md",
            self.root / "docs/verification.md",
        })
        self.assertIn("25 directed tests × 6 memory configurations", rendered[self.root / "README.md"])
        self.assertIn("66.7–83.3 MHz routed Artix-7 implementations", rendered[self.root / "README.md"])
        self.assertIn("RISC-V assembler 2.42", rendered[self.root / "README.md"])
        self.assertIn("38/38", rendered[self.root / "docs/evidence.md"])
        self.assertIn("`" + "a" * 40 + "`", rendered[self.root / "docs/evidence.md"])
        self.assertIn("`" + "b" * 40 + "`", rendered[self.root / "docs/evidence.md"])
        self.assertIn("`" + "0" * 64 + "` / `" + "4" * 64 + "`", rendered[self.root / "docs/evidence.md"])
        for value in rendered.values():
            self.assertEqual(value.count("<!-- evidence-facts:begin -->"), 1)
            self.assertEqual(value.count("<!-- evidence-facts:end -->"), 1)
            self.assertFalse(any(line != line.rstrip() for line in value.splitlines()))
        self.assertNotIn("\nstale\n", "".join(rendered.values()))

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


if __name__ == "__main__":
    unittest.main()
