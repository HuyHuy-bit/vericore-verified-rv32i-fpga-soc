#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import results as results_module
from tools.results import (
    BENCHMARK_FIELDS,
    SYNTHESIS_FIELDS,
    ResultError,
    collect_open,
    coverage_counts,
    load_result_set,
    validate_result_set,
    write_verification_receipt,
)
from synthesis.summarize_reports import SYNTHESIS_FIELDS as SUMMARY_SYNTHESIS_FIELDS


SHA_A = "a" * 40
SHA_B = "b" * 40


class ResultSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-results-")
        self.checkout = Path(self.tmp.name) / "repo"
        self.results = self.checkout / "results"
        (self.checkout / "tools").mkdir(parents=True)
        (self.checkout / "rtl").mkdir()
        self.results.mkdir()
        (self.results / "FORMAT.md").write_text("fixture results\n", encoding="utf-8")
        (self.checkout / "tools/reference_versions.env").write_text(
            "ARCH_TEST_SHA=" + SHA_A + "\n"
            "ARCH_TEST_EXPECTED=" + "".join(("3", "8")) + "\n"
            "SPIKE_SHA=" + SHA_B + "\n",
            encoding="utf-8",
        )
        (self.checkout / "tools/tool_versions.env").write_text(
            "ENV_SCHEMA=1\n"
            "UBUNTU_IMAGE=ubuntu:24.04\n"
            "UBUNTU_DIGEST=sha256:" + "c" * 64 + "\n"
            "VERILATOR_VERSION=5.048\n"
            "RISCV_TOOLCHAIN_VERSION=13.2.0-2024.04.12\n"
            "RISCV_BINUTILS_VERSION=2.42\n"
            "PYTHON_VERSION=3.12\n"
            "VHS_VERSION=0.11.0\n"
            "FFMPEG_VERSION=6.1.1\n"
            "VERIFY_IMAGE=ghcr.io/example/verify\n"
            "VERIFY_IMAGE_REVISION=1\n",
            encoding="utf-8",
        )
        (self.checkout / "tools/test_harness.py").write_text(
            "class HarnessTests:\n"
            "    def test_first(self): pass\n"
            "    def test_second(self): pass\n",
            encoding="utf-8",
        )
        (self.checkout / "rtl/core.sv").write_text(
            "module core;\n"
            + "\n".join(f"a{i}: assert property (1);" for i in range(25))
            + "\n"
            + "\n".join(f"i{i}: assert (1);" for i in range(2))
            + "\n"
            + "\n".join(f"c{i}: cover property (1);" for i in range(44))
            + "\nendmodule\n",
            encoding="utf-8",
        )
        self.write_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, name: str, value: object) -> None:
        (self.results / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def write_csv(self, name: str, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
        with (self.results / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def verification(self) -> dict[str, object]:
        return {
            "schema": 1,
            "measured_at": "2026-08-27T12:34:56Z",
            "tooling_commit": SHA_A,
            "rtl_commit": SHA_B,
            "status": "complete",
            "decoder_vectors": 2120,
            "hazard_vectors": 262144,
            "harness_tests": 2,
            "assertions": {"concurrent": 25, "immediate": 2},
            "cover_points": {"source": 44, "hit": 44},
            "directed_programs": 25,
            "memory_configurations": [
                {"name": name, "passed": 25}
                for name in ("baseline", "slow-mem", "icache-only", "wt", "wb", "assoc")
            ],
            "predictor_configurations": [
                {"name": name, "passed": 25}
                for name in ("gshare", "no-ras", "small-btb")
            ],
            "architecture_tests": {
                "discovered": 38,
                "passed": 38,
                "failed": 0,
                "missing": 0,
                "infrastructure": 0,
            },
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
            "commands": {
                "fast": "make check",
                "directed": "python3 tools/verification.py run --profile directed-memory",
                "predictor": "make predictor-test",
                "python_random": "make soak SEEDS=1000",
                "architecture_tests": "make compliance",
                "architecture_lockstep": "make lockstep",
                "spike_random": "make soak-lockstep SEEDS=200",
                "coverage": "make coverage",
            },
        }

    def benchmark_rows(self) -> list[dict[str, object]]:
        configurations = (
            ("slow-memory", 10, 10, 0, 1, 0, 1, "none"),
            ("icache", 10, 10, 1024, 4, 0, 1, "none"),
            ("write-back", 10, 10, 1024, 4, 4096, 4, "write-back"),
            ("ideal-memory", 1, 1, 0, 1, 0, 1, "none"),
        )
        rows: list[dict[str, object]] = []
        for config_index, config in enumerate(configurations):
            name, imem, dmem, ic_bytes, ic_ways, dc_bytes, dc_ways, policy = config
            for kernel_index, kernel in enumerate(("crc32", "matmul", "sort", "llist", "interp")):
                instret = 1000 + kernel_index
                rows.append({
                    "schema": 1,
                    "tooling_commit": SHA_A,
                    "rtl_commit": SHA_B,
                    "configuration": name,
                    "imem_latency": imem,
                    "dmem_latency": dmem,
                    "icache_bytes": ic_bytes,
                    "icache_block_words": 4,
                    "icache_ways": ic_ways,
                    "dcache_bytes": dc_bytes,
                    "dcache_block_words": 4,
                    "dcache_ways": dc_ways,
                    "dcache_policy": policy,
                    "btb_index_bits": 6,
                    "btb_tag_bits": 10,
                    "gshare": 0,
                    "ras_depth": 8,
                    "kernel": kernel,
                    "status": "pass",
                    "cycles": instret * (config_index + 1),
                    "instructions_retired": instret,
                    "memory_stall_cycles": config_index * 100,
                    "branches": 100,
                    "mispredictions": 5,
                    "icache_accesses": 0 if ic_bytes == 0 else 800,
                    "icache_misses": 0 if ic_bytes == 0 else 20,
                    "dcache_accesses": 0 if dc_bytes == 0 else 200,
                    "dcache_misses": 0 if dc_bytes == 0 else 10,
                })
        return rows

    def synthesis_rows(self) -> list[dict[str, object]]:
        configs = (
            ("core", 0, 1, 0, 1, "none"),
            ("icache", 1024, 4, 0, 1, "none"),
            ("dcache-wt", 1024, 4, 4096, 4, "write-through"),
            ("dcache-wb", 1024, 4, 4096, 4, "write-back"),
        )
        rows = []
        for index, (name, ic_bytes, ic_ways, dc_bytes, dc_ways, policy) in enumerate(configs):
            wns = -10.0 - index
            critical = 2.0 - wns
            rows.append({
                "schema": 1,
                "tooling_commit": SHA_A,
                "rtl_commit": SHA_B,
                "measurement_date": "2026-08-27",
                "configuration": name,
                "imem_words": 512,
                "dmem_words": 512,
                "icache_bytes": ic_bytes,
                "icache_block_words": 4,
                "icache_ways": ic_ways,
                "dcache_bytes": dc_bytes,
                "dcache_block_words": 4,
                "dcache_ways": dc_ways,
                "dcache_policy": policy,
                "vivado_version": "2025.2",
                "vivado_build": "1234567",
                "platform": "linux",
                "part": "xc7a35ticsg324-1L",
                "clock_period_ns": "2.000",
                "lut": 4000 + index,
                "ff": 5000 + index,
                "bram_tiles": "2.0",
                "ramb18": 4,
                "wns_ns": f"{wns:.3f}",
                "critical_path_ns": f"{critical:.3f}",
                "fmax_mhz": f"{1000.0 / critical:.3f}",
                "utilization_sha256": "d" * 64,
                "timing_sha256": "e" * 64,
            })
        return rows

    def tool_versions(self) -> dict[str, object]:
        return {
            "schema": 1,
            "tooling_commit": SHA_A,
            "rtl_commit": SHA_B,
            "container": {
                "image": "ghcr.io/example/verify",
                "digest": "sha256:" + "f" * 64,
                "base": "ubuntu:24.04@sha256:" + "c" * 64,
                "revision": 1,
            },
            "ubuntu": "24.04",
            "verilator": "5.048",
            "riscv_gcc": "13.2.0-2024.04.12",
            "riscv_as": "2.42",
            "python": "3.12",
            "spike_commit": SHA_B,
            "architecture_test_commit": SHA_A,
            "architecture_test_expected": 38,
            "vivado": {"version": "2025.2", "build": "1234567", "platform": "linux"},
            "vhs": "0.11.0",
            "ffmpeg": "6.1.1",
        }

    def write_fixture(self) -> None:
        self.write_json("verification.json", self.verification())
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, self.benchmark_rows())
        self.write_csv("synthesis.csv", SYNTHESIS_FIELDS, self.synthesis_rows())
        self.write_json("tool_versions.json", self.tool_versions())
        files = ("verification.json", "benchmarks.csv", "synthesis.csv", "tool_versions.json")
        manifest = {
            "schema": 1,
            "measured_at": "2026-08-27T12:34:56Z",
            "tooling_commit": SHA_A,
            "rtl_commit": SHA_B,
            "status": "complete",
            "files": list(files),
            "sha256": {
                name: hashlib.sha256((self.results / name).read_bytes()).hexdigest()
                for name in files
            },
            "expected": {
                "benchmark_rows": 20,
                "synthesis_rows": 4,
                "directed_programs": 25,
                "memory_configurations": 6,
                "predictor_configurations": 3,
                "architecture_tests": 38,
                "architecture_lockstep": 38,
                "spike_random": 200,
                "cover_points": 44,
            },
        }
        self.write_json("manifest.json", manifest)

    def refresh_manifest(self) -> None:
        manifest = json.loads((self.results / "manifest.json").read_text(encoding="utf-8"))
        for name in manifest["files"]:
            manifest["sha256"][name] = hashlib.sha256((self.results / name).read_bytes()).hexdigest()
        self.write_json("manifest.json", manifest)

    def test_loads_complete_result_set(self) -> None:
        self.assertEqual(SYNTHESIS_FIELDS, SUMMARY_SYNTHESIS_FIELDS)
        loaded = load_result_set(self.results)
        self.assertEqual(len(loaded.benchmarks), 20)
        self.assertEqual(len(loaded.synthesis), 4)
        self.assertEqual(validate_result_set(self.results, self.checkout), [])

    def test_historical_rtl_uses_recorded_source_counts(self) -> None:
        rtl = self.checkout / "rtl/core.sv"
        rtl.write_text(
            "module core;\n"
            + "\n".join(f"a{i}: assert property (1);" for i in range(25))
            + "\n"
            + "\n".join(f"i{i}: assert (1);" for i in range(2))
            + "\n"
            + "\n".join(f"c{i}: cover property (1);" for i in range(44))
            + "\nendmodule\n",
            encoding="utf-8",
        )
        (self.checkout / "sim").mkdir()
        (self.checkout / "sim/cpu_tb.cpp").write_text("int main() {}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.checkout, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.checkout, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=self.checkout, check=True)
        subprocess.run(["git", "add", "."], cwd=self.checkout, check=True)
        subprocess.run(["git", "commit", "-qm", "measured source"], cwd=self.checkout, check=True)
        measured = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.checkout, text=True
        ).strip()

        verification = self.verification()
        verification["tooling_commit"] = measured
        verification["rtl_commit"] = measured
        self.write_json("verification.json", verification)
        benchmarks = self.benchmark_rows()
        synthesis = self.synthesis_rows()
        for row in (*benchmarks, *synthesis):
            row["tooling_commit"] = measured
            row["rtl_commit"] = measured
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, benchmarks)
        self.write_csv("synthesis.csv", SYNTHESIS_FIELDS, synthesis)
        versions = self.tool_versions()
        versions["tooling_commit"] = measured
        versions["rtl_commit"] = measured
        self.write_json("tool_versions.json", versions)
        manifest = json.loads((self.results / "manifest.json").read_text(encoding="utf-8"))
        manifest["tooling_commit"] = measured
        manifest["rtl_commit"] = measured
        self.write_json("manifest.json", manifest)
        self.refresh_manifest()
        subprocess.run(["git", "add", "results"], cwd=self.checkout, check=True)
        subprocess.run(["git", "commit", "-qm", "publish results"], cwd=self.checkout, check=True)

        self.assertTrue(hasattr(results_module, "evidence_state"), "evidence state is missing")
        self.assertEqual(results_module.evidence_state(self.checkout, measured), "current")
        self.assertEqual(validate_result_set(self.results, self.checkout), [])

        rtl.write_text(rtl.read_text(encoding="utf-8") + "// later RTL change\n", encoding="utf-8")
        subprocess.run(["git", "add", "rtl/core.sv"], cwd=self.checkout, check=True)
        subprocess.run(["git", "commit", "-qm", "change rtl"], cwd=self.checkout, check=True)
        self.assertEqual(results_module.evidence_state(self.checkout, measured), "historical")
        self.assertEqual(validate_result_set(self.results, self.checkout), [])

    def test_duplicate_json_key_is_rejected(self) -> None:
        path = self.results / "verification.json"
        path.write_text('{"schema":1,"schema":1}\n', encoding="utf-8")
        with self.assertRaisesRegex(ResultError, "duplicate JSON key"):
            load_result_set(self.results)

    def test_unknown_json_field_is_rejected(self) -> None:
        value = self.verification()
        value["unknown"] = 1
        self.write_json("verification.json", value)
        self.refresh_manifest()
        self.assertTrue(any("unknown field" in error for error in validate_result_set(self.results, self.checkout)))

    def test_harness_count_must_match_the_current_test_source(self) -> None:
        value = self.verification()
        value["harness_tests"] = 3
        self.write_json("verification.json", value)
        self.refresh_manifest()
        self.assertTrue(
            any(
                "harness test count" in error
                for error in validate_result_set(self.results, self.checkout)
            )
        )

    def test_duplicate_csv_heading_is_rejected(self) -> None:
        path = self.results / "benchmarks.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[0] += ",kernel"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ResultError, "duplicate CSV heading"):
            load_result_set(self.results)

    def test_duplicate_benchmark_row_is_rejected(self) -> None:
        rows = self.benchmark_rows()
        rows[-1] = rows[0]
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, rows)
        self.refresh_manifest()
        self.assertTrue(any("duplicate benchmark row" in error for error in validate_result_set(self.results, self.checkout)))

    def test_wrong_population_is_rejected(self) -> None:
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, self.benchmark_rows()[:-1])
        self.refresh_manifest()
        self.assertTrue(any("20 benchmark rows" in error for error in validate_result_set(self.results, self.checkout)))

    def test_noncanonical_number_is_rejected(self) -> None:
        rows = self.benchmark_rows()
        rows[0]["cycles"] = "01000"
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, rows)
        self.refresh_manifest()
        self.assertTrue(any("canonical integer" in error for error in validate_result_set(self.results, self.checkout)))

    def test_counter_relationship_is_rejected(self) -> None:
        rows = self.benchmark_rows()
        rows[0]["mispredictions"] = 101
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, rows)
        self.refresh_manifest()
        self.assertTrue(any("mispredictions" in error for error in validate_result_set(self.results, self.checkout)))

    def test_synthesis_arithmetic_is_rejected(self) -> None:
        rows = self.synthesis_rows()
        rows[0]["fmax_mhz"] = "99.999"
        self.write_csv("synthesis.csv", SYNTHESIS_FIELDS, rows)
        self.refresh_manifest()
        self.assertTrue(any("fmax" in error for error in validate_result_set(self.results, self.checkout)))

    def test_mixed_commits_are_rejected(self) -> None:
        rows = self.benchmark_rows()
        rows[0]["rtl_commit"] = SHA_A
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, rows)
        self.refresh_manifest()
        self.assertTrue(any("RTL commit" in error for error in validate_result_set(self.results, self.checkout)))

    def test_invalid_manifest_hash_is_rejected(self) -> None:
        path = self.results / "verification.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertTrue(any("SHA-256" in error for error in validate_result_set(self.results, self.checkout)))

    def test_reference_pin_mismatch_is_rejected(self) -> None:
        value = self.tool_versions()
        value["architecture_test_commit"] = SHA_B
        self.write_json("tool_versions.json", value)
        self.refresh_manifest()
        self.assertTrue(any("architecture-test commit" in error for error in validate_result_set(self.results, self.checkout)))

    def test_assembler_version_mismatch_is_rejected(self) -> None:
        value = self.tool_versions()
        value["riscv_as"] = "2.41"
        self.write_json("tool_versions.json", value)
        self.refresh_manifest()
        self.assertTrue(any("assembler version" in error for error in validate_result_set(self.results, self.checkout)))

    def test_collection_publishes_only_a_complete_set(self) -> None:
        output = self.checkout / "published"
        collect_open(self.results, output, SHA_A)
        self.assertEqual(validate_result_set(output, self.checkout), [])
        self.assertEqual(len(load_result_set(output).benchmarks), 20)

    def test_failed_collection_preserves_previous_set(self) -> None:
        output = self.checkout / "published"
        collect_open(self.results, output, SHA_A)
        previous = (output / "manifest.json").read_bytes()
        rows = self.benchmark_rows()
        rows.pop()
        self.write_csv("benchmarks.csv", BENCHMARK_FIELDS, rows)
        with self.assertRaisesRegex(ResultError, "20 benchmark rows"):
            collect_open(self.results, output, SHA_A)
        self.assertEqual((output / "manifest.json").read_bytes(), previous)
        self.assertEqual(validate_result_set(output, self.checkout), [])


class VerificationReceiptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-receipt-")
        self.checkout = Path(self.tmp.name)
        for name in ("coverage", "rtl", "tools", "sim/unit"):
            (self.checkout / name).mkdir(parents=True)
        (self.checkout / "tools/reference_versions.env").write_text(
            f"ARCH_TEST_SHA={SHA_A}\nARCH_TEST_EXPECTED="
            + "".join(("3", "8")) + f"\nSPIKE_SHA={SHA_B}\n",
            encoding="utf-8",
        )
        (self.checkout / "sim/unit/control_tb.sv").write_text(
            '$display("PASS control: 2120 vectors");\n', encoding="utf-8"
        )
        (self.checkout / "sim/unit/hazard_detect_tb.sv").write_text(
            '$display("PASS hazard: 262144 vectors");\n', encoding="utf-8"
        )
        (self.checkout / "tools/test_harness.py").write_text(
            "class Tests:\n    def test_one(self): pass\n    def test_two(self): pass\n",
            encoding="utf-8",
        )
        (self.checkout / "rtl/checks.sv").write_text(
            "a: assert property (@(posedge clk) value);\n"
            "always_comb assert (value);\n",
            encoding="utf-8",
        )
        records = []
        for category in ("line", "branch", "expr", "toggle", "user"):
            records.append(
                "C '" + chr(1) + "t" + chr(2) + category
                + chr(1) + "h" + chr(2) + "TOP.point' 1"
            )
        (self.checkout / "coverage/merged.dat").write_text(
            "\n".join(records) + "\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @mock.patch("tools.results.git_text", side_effect=(SHA_A, SHA_B))
    def test_complete_profile_writes_atomic_receipt(self, git: mock.Mock) -> None:
        output = self.checkout / "run/verification.json"
        write_verification_receipt(self.checkout, output)
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(value["status"], "complete")
        self.assertEqual(value["tooling_commit"], SHA_A)
        self.assertEqual(value["rtl_commit"], SHA_B)
        self.assertEqual(value["harness_tests"], 2)
        self.assertEqual(value["assertions"], {"concurrent": 1, "immediate": 1})
        self.assertEqual(value["coverage"]["user"], {"hit": 1, "total": 1})
        self.assertEqual(git.call_count, 2)
        self.assertFalse(output.with_name(".verification.json.tmp").exists())

    def test_missing_coverage_preserves_existing_receipt(self) -> None:
        output = self.checkout / "verification.json"
        output.write_text("previous\n", encoding="utf-8")
        (self.checkout / "coverage/merged.dat").unlink()
        with self.assertRaisesRegex(ResultError, "coverage result is missing"):
            write_verification_receipt(self.checkout, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous\n")

    def test_incomplete_coverage_is_rejected(self) -> None:
        path = self.checkout / "coverage/merged.dat"
        path.write_text(
            "C '" + chr(1) + "t" + chr(2) + "user"
            + chr(1) + "h" + chr(2) + "TOP.point' 0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ResultError, "every required category"):
            coverage_counts(path)


if __name__ == "__main__":
    unittest.main()
