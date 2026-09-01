#!/usr/bin/env python3

from __future__ import annotations

import csv
import copy
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
    write_profile_receipt,
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

    def test_current_verification_cannot_omit_an_rtl_assertion(self) -> None:
        value = self.verification()
        value["assertions"]["concurrent"] -= 1
        self.write_json("verification.json", value)
        self.refresh_manifest()
        self.assertTrue(
            any("assertion counts" in error for error in validate_result_set(
                self.results, self.checkout
            ))
        )

    def test_current_verification_and_manifest_cannot_omit_a_cover(self) -> None:
        value = self.verification()
        value["cover_points"] = {"source": 43, "hit": 43}
        self.write_json("verification.json", value)
        manifest = json.loads(
            (self.results / "manifest.json").read_text(encoding="utf-8")
        )
        manifest["expected"]["cover_points"] = 43
        self.write_json("manifest.json", manifest)
        self.refresh_manifest()
        errors = validate_result_set(self.results, self.checkout)
        self.assertTrue(any("cover-point counts" in error for error in errors))
        self.assertTrue(any("manifest expected cover_points" in error for error in errors))

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


class SocResultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-soc-result-")
        self.checkout = Path(self.tmp.name) / "repo"
        self.results = self.checkout / "results"
        (self.checkout / "rtl").mkdir(parents=True)
        (self.checkout / "tools").mkdir()
        (self.checkout / "boards").mkdir()
        self.results.mkdir()
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
        (self.checkout / "tools/test_harness.py").write_text(
            "class HarnessTests:\n"
            "    def test_first(self): pass\n"
            "    def test_second(self): pass\n",
            encoding="utf-8",
        )
        (self.checkout / "tools/reference_versions.env").write_text(
            f"ARCH_TEST_SHA={SHA_A}\nARCH_TEST_EXPECTED="
            + "".join(("3", "8"))
            + "\n"
            f"DIGILENT_XDC_SHA={'c' * 40}\nSPIKE_SHA={SHA_B}\n",
            encoding="utf-8",
        )
        (self.checkout / "boards/arty_a7_35t.xdc").write_text(
            "# https://github.com/Digilent/digilent-xdc/blob/"
            + "c" * 40
            + "/Arty-A7-35-Master.xdc\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=self.checkout, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=self.checkout, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.com"],
            cwd=self.checkout,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=self.checkout, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "rtl"], cwd=self.checkout, check=True
        )
        self.rtl_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.checkout, text=True
        ).strip()
        (self.checkout / "tool.txt").write_text("collector\n", encoding="utf-8")
        subprocess.run(["git", "add", "tool.txt"], cwd=self.checkout, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "tooling"], cwd=self.checkout, check=True
        )
        self.tooling_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.checkout, text=True
        ).strip()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def value(self) -> dict[str, object]:
        return {
            "schema": 1,
            "measured_at": "2026-08-30T12:34:56Z",
            "tooling_commit": self.tooling_commit,
            "rtl_commit": self.rtl_commit,
            "board": "arty-a7-35t",
            "part": "xc7a35ticsg324-1L",
            "digilent_xdc_sha": "c" * 40,
            "firmware_sha256": {
                "elf": "1" * 64,
                "imem": "2" * 64,
                "dmem": "3" * 64,
            },
            "bitstream_sha256": "4" * 64,
            "vivado": {
                "version": "2025.2",
                "build": "6299465",
                "platform": "wsl-windows",
            },
            "route": {
                "input_clock_period_ns": "10.000",
                "soc_clock_period_ns": "20.000",
                "wns_ns": "0.250",
                "critical_path_ns": "19.750",
                "fmax_mhz": "50.633",
                "lut": 10000,
                "ff": 14000,
                "bram_tiles": "20.0",
                "timing_sha256": "5" * 64,
                "utilization_sha256": "6" * 64,
                "drc_sha256": "7" * 64,
            },
            "verification": {
                "full_status": "complete",
                "soc_status": "complete",
                "full_receipt_sha256": "8" * 64,
                "soc_receipt_sha256": "9" * 64,
            },
            "uart": {
                "transcript_sha256": "a" * 64,
                "lines": ["rv32i soc ready", "external irq", "external irq"],
            },
            "manual_observations": {
                "reset_banner": True,
                "button_presses": 2,
                "led_transitions": 2,
                "release_transitions": 0,
            },
        }

    def write(self, value: object) -> None:
        (self.results / "soc.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def validate(self) -> list[str]:
        self.assertTrue(hasattr(results_module, "validate_soc_result"))
        return results_module.validate_soc_result(self.results, self.checkout)

    def test_optional_soc_result_is_absent_or_strictly_valid(self) -> None:
        self.assertEqual(self.validate(), [])
        self.write(self.value())
        self.assertEqual(self.validate(), [])

    def test_soc_result_rejects_missing_unknown_and_duplicate_fields(self) -> None:
        value = self.value()
        del value["board"]
        self.write(value)
        self.assertTrue(any("missing field" in error for error in self.validate()))
        value = self.value()
        value["unknown"] = 1
        self.write(value)
        self.assertTrue(any("unknown field" in error for error in self.validate()))
        (self.results / "soc.json").write_text(
            '{"schema":1,"schema":1}\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(ResultError, "duplicate JSON key"):
            self.validate()

    def test_soc_result_rejects_invalid_identity_timing_and_observations(self) -> None:
        cases = (
            (("part",), "xc7a100tcsg324-1", "part"),
            (("digilent_xdc_sha",), "C" * 40, "Digilent"),
            (("route", "input_clock_period_ns"), "9.000", "10.000"),
            (("route", "soc_clock_period_ns"), "19.000", "20.000"),
            (("route", "wns_ns"), "-0.100", "nonnegative"),
            (("uart", "lines"), ["rv32i soc ready"], "UART"),
            (("manual_observations", "button_presses"), 1, "button"),
        )
        for path, replacement, diagnostic in cases:
            with self.subTest(path=path):
                value = copy.deepcopy(self.value())
                target = value
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                self.write(value)
                self.assertTrue(
                    any(diagnostic in error for error in self.validate()),
                    self.validate(),
                )

    def test_soc_result_requires_recorded_commits_and_unchanged_rtl(self) -> None:
        value = self.value()
        value["tooling_commit"] = "f" * 40
        self.write(value)
        self.assertTrue(any("tooling commit does not exist" in e for e in self.validate()))
        (self.checkout / "rtl/core.sv").write_text(
            "module core; logic changed; endmodule\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "rtl/core.sv"], cwd=self.checkout, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "change rtl"], cwd=self.checkout, check=True
        )
        changed = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.checkout, text=True
        ).strip()
        value = self.value()
        value["tooling_commit"] = changed
        self.write(value)
        self.assertTrue(any("RTL differs" in e for e in self.validate()))

    def collection_inputs(self) -> dict[str, Path]:
        raw = self.checkout / "raw"
        board = raw / "board"
        firmware = raw / "firmware"
        receipts = raw / "receipts"
        for path in (board, firmware, receipts):
            path.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "bitstream": board / "rv32i-soc-arty-a7-35t.bit",
            "utilization": board / "utilization.rpt",
            "timing": board / "timing_summary.rpt",
            "drc": board / "drc.rpt",
            "placement": board / "placement.tsv",
        }
        artifacts["bitstream"].write_bytes(b"bitstream\n")
        artifacts["utilization"].write_text(
            "| Slice LUTs | 10,000 |\n"
            "| Slice Registers | 14,000 |\n"
            "| Block RAM Tile | 20.0 |\n"
            "| RAMB18 | 40 |\n",
            encoding="utf-8",
        )
        artifacts["timing"].write_text("WNS(ns)\n--------\n0.250\n", encoding="utf-8")
        artifacts["drc"].write_text("DRC clean\n", encoding="utf-8")
        artifacts["placement"].write_text(
            "placement_schema\t1\npart\txc7a35ticsg324-1L\n"
            "bounds\t0\t1\t0\t1\n"
            "cell\tprimitive\tsite\tbel\ttile\ttile_x\ttile_y\n"
            "soc/u_core/u_backend/value_reg\tFDRE\tSLICE_X0Y0\tAFF\t"
            "CLBLL_L_X0Y0\t0\t0\n",
            encoding="utf-8",
        )
        image = "00000000\n" * 8192
        elf = firmware / "firmware.elf"
        imem = firmware / "firmware-imem.hex"
        dmem = firmware / "firmware-dmem.hex"
        elf.write_bytes(b"ELF fixture\n")
        imem.write_text(image, encoding="ascii")
        dmem.write_text(image, encoding="ascii")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        firmware_manifest = firmware / "manifest.json"
        firmware_manifest.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "status": "complete",
                    "entry": 0,
                    "elf": {"path": str(elf), "sha256": digest(elf)},
                    "imem": {
                        "path": str(imem), "words": 8192, "sha256": digest(imem)
                    },
                    "dmem": {
                        "path": str(dmem), "words": 8192, "sha256": digest(dmem)
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        board_manifest = board / "manifest.json"
        board_manifest.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "status": "complete",
                    "measured_at": "2026-08-30T12:34:56Z",
                    "source_commit": self.tooling_commit,
                    "rtl_commit": self.rtl_commit,
                    "part": "xc7a35ticsg324-1L",
                    "top": "arty_a7_35t_top",
                    "input_clock_period_ns": 10.0,
                    "soc_clock_period_ns": 20.0,
                    "wns_ns": 0.25,
                    "firmware": {
                        "imem_sha256": digest(imem), "dmem_sha256": digest(dmem)
                    },
                    "xdc_sha256": digest(self.checkout / "boards/arty_a7_35t.xdc"),
                    "vivado": {
                        "version": "2025.2",
                        "build": "6299465",
                        "platform": "wsl-windows",
                        "launcher": "/tools/vivado",
                    },
                    "invocation": ["-mode", "batch"],
                    "outputs": {name: digest(path) for name, path in artifacts.items()},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        full = ResultSetTest.verification(self)
        full["tooling_commit"] = self.tooling_commit
        full["rtl_commit"] = self.rtl_commit
        full_receipt = receipts / "full.json"
        full_receipt.write_text(
            json.dumps(full, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        soc_receipt = receipts / "soc.json"
        soc_receipt.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "measured_at": "2026-08-30T12:30:00Z",
                    "profile": "soc",
                    "status": "complete",
                    "tooling_commit": self.tooling_commit,
                    "rtl_commit": self.rtl_commit,
                    "commands": ["make soc-check"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        uart = raw / "uart.txt"
        uart.write_text(
            "rv32i soc ready\nexternal irq\nexternal irq\n", encoding="utf-8"
        )
        observations = raw / "observations.json"
        observations.write_text(
            json.dumps(
                {
                    "reset_banner": True,
                    "button_presses": 2,
                    "led_transitions": 2,
                    "release_transitions": 0,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "board": board_manifest,
            "firmware": firmware_manifest,
            "verification": full_receipt,
            "soc_verification": soc_receipt,
            "uart": uart,
            "observations": observations,
            "bitstream": artifacts["bitstream"],
        }

    def collect(self, inputs: dict[str, Path], output: Path | None = None) -> int:
        return results_module.main([
            "collect-soc",
            "--board-manifest", str(inputs["board"]),
            "--firmware-manifest", str(inputs["firmware"]),
            "--verification", str(inputs["verification"]),
            "--soc-verification", str(inputs["soc_verification"]),
            "--uart", str(inputs["uart"]),
            "--observations", str(inputs["observations"]),
            "--output", str(output or self.results / "soc.json"),
        ])

    def test_collect_soc_derives_and_validates_the_complete_record(self) -> None:
        inputs = self.collection_inputs()
        inputs["uart"].write_bytes(
            b"rv32i soc ready\r\nexternal irq\r\nexternal irq\r\n"
        )
        self.assertEqual(self.collect(inputs), 0)
        value = json.loads((self.results / "soc.json").read_text(encoding="utf-8"))
        self.assertEqual(value["uart"]["lines"], [
            "rv32i soc ready", "external irq", "external irq"
        ])
        self.assertEqual(value["route"]["lut"], 10000)
        self.assertEqual(value["route"]["fmax_mhz"], "50.633")
        self.assertEqual(
            value["uart"]["transcript_sha256"],
            hashlib.sha256(
                b"rv32i soc ready\nexternal irq\nexternal irq\n"
            ).hexdigest(),
        )
        self.assertEqual(self.validate(), [])

    def test_collect_soc_rejects_tampering_prefixes_and_raw_destinations(self) -> None:
        inputs = self.collection_inputs()
        inputs["bitstream"].write_bytes(b"tampered\n")
        self.assertNotEqual(self.collect(inputs), 0)
        self.assertFalse((self.results / "soc.json").exists())
        inputs = self.collection_inputs()
        inputs["uart"].write_text("rv32i soc ready\n", encoding="utf-8")
        self.assertNotEqual(self.collect(inputs), 0)
        inputs = self.collection_inputs()
        self.assertNotEqual(
            self.collect(inputs, inputs["board"].parent / "soc.json"), 0
        )


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

    @mock.patch("tools.results.git_text", side_effect=(SHA_A, SHA_B))
    def test_soc_profile_writes_a_minimal_atomic_receipt(self, git: mock.Mock) -> None:
        output = self.checkout / "run/soc-verification.json"
        write_profile_receipt(self.checkout, output, "soc")
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(set(value), results_module.SOC_RECEIPT_FIELDS)
        self.assertEqual(value["profile"], "soc")
        self.assertEqual(value["status"], "complete")
        self.assertEqual(value["commands"], ["make soc-check"])
        self.assertEqual(value["tooling_commit"], SHA_A)
        self.assertEqual(value["rtl_commit"], SHA_B)
        self.assertEqual(git.call_count, 2)

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
