#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Literal


SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
UINT_RE = re.compile(r"0|[1-9][0-9]*\Z")
DECIMAL_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]+\Z")
TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

RESULT_FILES = (
    "verification.json",
    "benchmarks.csv",
    "synthesis.csv",
    "tool_versions.json",
)

BENCHMARK_FIELDS = (
    "schema",
    "tooling_commit",
    "rtl_commit",
    "configuration",
    "imem_latency",
    "dmem_latency",
    "icache_bytes",
    "icache_block_words",
    "icache_ways",
    "dcache_bytes",
    "dcache_block_words",
    "dcache_ways",
    "dcache_policy",
    "btb_index_bits",
    "btb_tag_bits",
    "gshare",
    "ras_depth",
    "kernel",
    "status",
    "cycles",
    "instructions_retired",
    "memory_stall_cycles",
    "branches",
    "mispredictions",
    "icache_accesses",
    "icache_misses",
    "dcache_accesses",
    "dcache_misses",
)

SYNTHESIS_FIELDS = (
    "schema",
    "tooling_commit",
    "rtl_commit",
    "measurement_date",
    "configuration",
    "imem_words",
    "dmem_words",
    "icache_bytes",
    "icache_block_words",
    "icache_ways",
    "dcache_bytes",
    "dcache_block_words",
    "dcache_ways",
    "dcache_policy",
    "vivado_version",
    "vivado_build",
    "platform",
    "part",
    "clock_period_ns",
    "lut",
    "ff",
    "bram_tiles",
    "ramb18",
    "wns_ns",
    "critical_path_ns",
    "fmax_mhz",
    "utilization_sha256",
    "timing_sha256",
)

VERIFICATION_FIELDS = {
    "schema",
    "measured_at",
    "tooling_commit",
    "rtl_commit",
    "status",
    "decoder_vectors",
    "hazard_vectors",
    "harness_tests",
    "assertions",
    "cover_points",
    "directed_programs",
    "memory_configurations",
    "predictor_configurations",
    "architecture_tests",
    "architecture_lockstep",
    "python_random",
    "spike_random",
    "coverage",
    "commands",
}

TOOL_FIELDS = {
    "schema",
    "tooling_commit",
    "rtl_commit",
    "container",
    "ubuntu",
    "verilator",
    "riscv_gcc",
    "riscv_as",
    "python",
    "spike_commit",
    "architecture_test_commit",
    "architecture_test_expected",
    "vivado",
    "vhs",
    "ffmpeg",
}

MANIFEST_FIELDS = {
    "schema",
    "measured_at",
    "tooling_commit",
    "rtl_commit",
    "status",
    "files",
    "sha256",
    "expected",
}

SOC_FIELDS = {
    "schema", "measured_at", "tooling_commit", "rtl_commit", "board", "part",
    "digilent_xdc_sha", "firmware_sha256", "bitstream_sha256", "vivado",
    "route", "verification", "uart", "manual_observations",
}
SOC_FIRMWARE_FIELDS = {"elf", "imem", "dmem"}
SOC_VIVADO_FIELDS = {"version", "build", "platform"}
SOC_ROUTE_FIELDS = {
    "input_clock_period_ns", "soc_clock_period_ns", "wns_ns",
    "critical_path_ns", "fmax_mhz", "lut", "ff", "bram_tiles",
    "timing_sha256", "utilization_sha256", "drc_sha256",
}
SOC_VERIFICATION_FIELDS = {
    "full_status", "soc_status", "full_receipt_sha256", "soc_receipt_sha256",
}
SOC_UART_FIELDS = {"transcript_sha256", "lines"}
SOC_OBSERVATION_FIELDS = {
    "reset_banner", "button_presses", "led_transitions", "release_transitions",
}
SOC_RECEIPT_FIELDS = {
    "schema", "measured_at", "profile", "status", "tooling_commit",
    "rtl_commit", "commands",
}

MEMORY_CONFIGURATIONS = ("baseline", "slow-mem", "icache-only", "wt", "wb", "assoc")
PREDICTOR_CONFIGURATIONS = ("gshare", "no-ras", "small-btb")
KERNELS = ("crc32", "matmul", "sort", "llist", "interp")
BENCHMARK_CONFIGURATIONS = {
    "slow-memory": (10, 10, 0, 4, 1, 0, 4, 1, "none"),
    "icache": (10, 10, 1024, 4, 4, 0, 4, 1, "none"),
    "write-back": (10, 10, 1024, 4, 4, 4096, 4, 4, "write-back"),
    "ideal-memory": (1, 1, 0, 4, 1, 0, 4, 1, "none"),
}
SYNTHESIS_CONFIGURATIONS = {
    "core": (0, 4, 1, 0, 4, 1, "none"),
    "icache": (1024, 4, 4, 0, 4, 1, "none"),
    "dcache-wt": (1024, 4, 4, 4096, 4, 4, "write-through"),
    "dcache-wb": (1024, 4, 4, 4096, 4, 4, "write-back"),
}


class ResultError(ValueError):
    pass


@dataclass(frozen=True)
class ResultSet:
    root: Path
    manifest: dict[str, Any]
    verification: dict[str, Any]
    benchmarks: tuple[dict[str, str], ...]
    synthesis: tuple[dict[str, str], ...]
    tool_versions: dict[str, Any]


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResultError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except FileNotFoundError as exc:
        raise ResultError(f"missing result file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ResultError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResultError(f"{path.name} must contain a JSON object")
    return value


def load_csv(path: Path, fields: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except FileNotFoundError as exc:
        raise ResultError(f"missing result file: {path.name}") from exc
    with handle:
        reader = csv.DictReader(handle)
        headings = reader.fieldnames
        if headings is None:
            raise ResultError(f"missing CSV heading in {path.name}")
        if len(set(headings)) != len(headings):
            raise ResultError(f"duplicate CSV heading in {path.name}")
        if tuple(headings) != fields:
            raise ResultError(f"unexpected CSV headings in {path.name}")
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ResultError(f"malformed CSV row in {path.name}:{number}")
            rows.append(row)
    return tuple(rows)


def load_result_set(root: Path) -> ResultSet:
    root = root.resolve()
    return ResultSet(
        root=root,
        manifest=load_json(root / "manifest.json"),
        verification=load_json(root / "verification.json"),
        benchmarks=load_csv(root / "benchmarks.csv", BENCHMARK_FIELDS),
        synthesis=load_csv(root / "synthesis.csv", SYNTHESIS_FIELDS),
        tool_versions=load_json(root / "tool_versions.json"),
    )


def exact_fields(value: object, fields: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing:
        errors.append(f"{label} missing field: {sorted(missing)[0]}")
    if unknown:
        errors.append(f"{label} unknown field: {sorted(unknown)[0]}")
    return not missing and not unknown


def require_uint(value: object, label: str, errors: list[str], minimum: int = 0) -> int | None:
    if isinstance(value, bool):
        errors.append(f"{label} must be an integer")
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and UINT_RE.fullmatch(value):
        number = int(value)
    else:
        errors.append(f"{label} must be a canonical integer")
        return None
    if number < minimum:
        errors.append(f"{label} must be at least {minimum}")
        return None
    return number


def require_decimal(value: object, label: str, errors: list[str]) -> float | None:
    if not isinstance(value, str) or DECIMAL_RE.fullmatch(value) is None:
        errors.append(f"{label} must be a canonical decimal")
        return None
    return float(value)


def require_sha(value: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        errors.append(f"{label} must be a canonical 40-character SHA")
        return None
    return value


def require_hash(value: object, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        errors.append(f"{label} must be a canonical SHA-256")
        return None
    return value


def require_timestamp(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        errors.append(f"{label} must be a UTC timestamp")
        return
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        errors.append(f"{label} must be a valid UTC timestamp")
        return
    if parsed > datetime.now(timezone.utc):
        errors.append(f"{label} must not be in the future")


def require_date(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or DATE_RE.fullmatch(value) is None:
        errors.append(f"{label} must be a UTC date")
        return
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{label} must be a valid UTC date")
        return
    if parsed > datetime.now(timezone.utc).date():
        errors.append(f"{label} must not be in the future")


def load_env(path: Path, errors: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        errors.append(f"missing metadata file: {path}")
        return values
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            errors.append(f"malformed metadata assignment: {path}:{number}")
            continue
        key, value = stripped.split("=", 1)
        if key in values:
            errors.append(f"duplicate metadata key: {key}")
        values[key] = value
    return values


def validate_manifest(
    result: ResultSet,
    errors: list[str],
    architecture_expected: int,
    cover_expected: int,
) -> None:
    value = result.manifest
    if not exact_fields(value, MANIFEST_FIELDS, "manifest", errors):
        return
    if value["schema"] != 1:
        errors.append("manifest schema must be 1")
    if value["status"] != "complete":
        errors.append("manifest status must be complete")
    require_timestamp(value["measured_at"], "manifest measured_at", errors)
    require_sha(value["tooling_commit"], "manifest tooling commit", errors)
    require_sha(value["rtl_commit"], "manifest RTL commit", errors)
    if value["files"] != list(RESULT_FILES):
        errors.append("manifest files must contain the four required files in order")
    hashes = value["sha256"]
    if not isinstance(hashes, dict) or set(hashes) != set(RESULT_FILES):
        errors.append("manifest SHA-256 map must contain the four required files")
    else:
        for name in RESULT_FILES:
            expected = require_hash(hashes[name], f"manifest SHA-256 for {name}", errors)
            if expected is not None:
                actual = hashlib.sha256((result.root / name).read_bytes()).hexdigest()
                if expected != actual:
                    errors.append(f"manifest SHA-256 mismatch for {name}")
    expected_fields = {
        "benchmark_rows",
        "synthesis_rows",
        "directed_programs",
        "memory_configurations",
        "predictor_configurations",
        "architecture_tests",
        "architecture_lockstep",
        "spike_random",
        "cover_points",
    }
    if exact_fields(value["expected"], expected_fields, "manifest expected", errors):
        wanted = {
            "benchmark_rows": 20,
            "synthesis_rows": 4,
            "directed_programs": 25,
            "memory_configurations": 6,
            "predictor_configurations": 3,
            "architecture_tests": architecture_expected,
            "architecture_lockstep": architecture_expected,
            "spike_random": 200,
            "cover_points": cover_expected,
        }
        for key, expected_value in wanted.items():
            if value["expected"][key] != expected_value:
                errors.append(f"manifest expected {key} must be {expected_value}")


def validate_verification(
    result: ResultSet,
    errors: list[str],
    architecture_expected: int,
    harness_expected: int,
    concurrent_expected: int,
    immediate_expected: int,
    cover_expected: int,
) -> None:
    value = result.verification
    if not exact_fields(value, VERIFICATION_FIELDS, "verification", errors):
        return
    if value["schema"] != 1:
        errors.append("verification schema must be 1")
    if value["status"] != "complete":
        errors.append("verification status must be complete")
    require_timestamp(value["measured_at"], "verification measured_at", errors)
    exact_counts = {
        "decoder_vectors": 2120,
        "hazard_vectors": 262144,
        "directed_programs": 25,
    }
    for key, expected in exact_counts.items():
        if value[key] != expected:
            errors.append(f"verification {key} must be {expected}")
    if value["harness_tests"] != harness_expected:
        errors.append(
            f"verification harness test count must match recorded source ({harness_expected})"
        )
    if exact_fields(value["assertions"], {"concurrent", "immediate"}, "assertions", errors):
        expected = {
            "concurrent": concurrent_expected,
            "immediate": immediate_expected,
        }
        if value["assertions"] != expected:
            errors.append("assertion counts must match recorded RTL source")
    if exact_fields(value["cover_points"], {"source", "hit"}, "cover_points", errors):
        if value["cover_points"] != {"source": cover_expected, "hit": cover_expected}:
            errors.append("cover-point counts must match recorded RTL source")
    validate_configurations(
        value["memory_configurations"], MEMORY_CONFIGURATIONS, "memory", errors
    )
    validate_configurations(
        value["predictor_configurations"], PREDICTOR_CONFIGURATIONS, "predictor", errors
    )
    count_groups = (
        ("architecture_tests", {"discovered": architecture_expected, "passed": architecture_expected, "failed": 0, "missing": 0, "infrastructure": 0}),
        ("architecture_lockstep", {"discovered": architecture_expected, "passed": architecture_expected, "failed": 0}),
        ("spike_random", {"requested": 200, "passed": 200, "instructions": 60}),
    )
    for name, expected in count_groups:
        if exact_fields(value[name], set(expected), name, errors) and value[name] != expected:
            errors.append(f"{name} counts do not describe a complete run")
    if exact_fields(value["python_random"], {"baseline", "cached"}, "python_random", errors):
        for name in ("baseline", "cached"):
            expected = {"requested": 1000, "passed": 1000}
            group = value["python_random"].get(name)
            if exact_fields(group, set(expected), f"python_random {name}", errors) and group != expected:
                errors.append(f"python_random {name} counts do not describe 1000 passing seeds")
    coverage_names = {"line", "branch", "expression", "toggle", "user"}
    if exact_fields(value["coverage"], coverage_names, "coverage", errors):
        for name in sorted(coverage_names):
            group = value["coverage"][name]
            if exact_fields(group, {"hit", "total"}, f"coverage {name}", errors):
                hit = require_uint(group["hit"], f"coverage {name} hit", errors)
                total = require_uint(group["total"], f"coverage {name} total", errors)
                if hit is not None and total is not None and hit > total:
                    errors.append(f"coverage {name} hit exceeds total")
        if value["coverage"]["user"] != {"hit": cover_expected, "total": cover_expected}:
            errors.append("user coverage must match recorded RTL source")
    command_names = {
        "fast", "directed", "predictor", "python_random", "architecture_tests",
        "architecture_lockstep", "spike_random", "coverage",
    }
    if exact_fields(value["commands"], command_names, "commands", errors):
        if any(not isinstance(command, str) or not command.strip() for command in value["commands"].values()):
            errors.append("verification commands must be nonempty strings")


def validate_configurations(
    value: object, names: tuple[str, ...], label: str, errors: list[str]
) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} configurations must be an array")
        return
    actual = []
    for index, entry in enumerate(value):
        if not exact_fields(entry, {"name", "passed"}, f"{label} configuration {index}", errors):
            continue
        actual.append(entry["name"])
        if entry["passed"] != 25:
            errors.append(f"{label} configuration {entry['name']} must pass 25 programs")
    if tuple(actual) != names:
        errors.append(f"{label} configurations must be ordered as {','.join(names)}")


def row_uint(row: dict[str, str], key: str, label: str, errors: list[str]) -> int | None:
    return require_uint(row[key], f"{label} {key}", errors)


def validate_benchmarks(result: ResultSet, errors: list[str]) -> None:
    rows = result.benchmarks
    if len(rows) != 20:
        errors.append("results must contain exactly 20 benchmark rows")
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, 2):
        label = f"benchmarks.csv:{number}"
        key = (row["configuration"], row["kernel"])
        if key in seen:
            errors.append(f"duplicate benchmark row: {key[0]}/{key[1]}")
        seen.add(key)
        if row["schema"] != "1":
            errors.append(f"{label} schema must be 1")
        for commit_name in ("tooling_commit", "rtl_commit"):
            require_sha(row[commit_name], f"{label} {commit_name}", errors)
        if row["status"] != "pass":
            errors.append(f"{label} status must be pass")
        if row["kernel"] not in KERNELS:
            errors.append(f"{label} unknown kernel")
        configuration = BENCHMARK_CONFIGURATIONS.get(row["configuration"])
        numeric_fields = (
            "imem_latency", "dmem_latency", "icache_bytes", "icache_block_words",
            "icache_ways", "dcache_bytes", "dcache_block_words", "dcache_ways",
            "btb_index_bits", "btb_tag_bits", "gshare", "ras_depth", "cycles",
            "instructions_retired", "memory_stall_cycles", "branches", "mispredictions",
            "icache_accesses", "icache_misses", "dcache_accesses", "dcache_misses",
        )
        numbers = {field: row_uint(row, field, label, errors) for field in numeric_fields}
        if configuration is None:
            errors.append(f"{label} unknown benchmark configuration")
        elif all(numbers[field] is not None for field in numeric_fields[:8]):
            actual = tuple(numbers[field] for field in numeric_fields[:8]) + (row["dcache_policy"],)
            if actual != configuration:
                errors.append(f"{label} geometry does not match {row['configuration']}")
        if (numbers["btb_index_bits"], numbers["btb_tag_bits"], numbers["gshare"], numbers["ras_depth"]) != (6, 10, 0, 8):
            errors.append(f"{label} predictor parameters do not match the headline configuration")
        relationships = (
            ("mispredictions", "branches"),
            ("icache_misses", "icache_accesses"),
            ("dcache_misses", "dcache_accesses"),
        )
        for child, parent in relationships:
            if numbers[child] is not None and numbers[parent] is not None and numbers[child] > numbers[parent]:
                errors.append(f"{label} {child} exceeds {parent}")
        if numbers["cycles"] == 0 or numbers["instructions_retired"] == 0:
            errors.append(f"{label} cycles and instructions_retired must be positive")
    expected = {(configuration, kernel) for configuration in BENCHMARK_CONFIGURATIONS for kernel in KERNELS}
    if seen != expected:
        errors.append("benchmark row population does not match five kernels across four configurations")


def validate_synthesis(result: ResultSet, errors: list[str]) -> None:
    rows = result.synthesis
    if len(rows) != 4:
        errors.append("results must contain exactly four synthesis rows")
    seen: set[str] = set()
    timestamps: set[str] = set()
    for number, row in enumerate(rows, 2):
        label = f"synthesis.csv:{number}"
        name = row["configuration"]
        if name in seen:
            errors.append(f"duplicate synthesis row: {name}")
        seen.add(name)
        timestamps.add(row["measurement_date"])
        require_date(row["measurement_date"], f"{label} measurement_date", errors)
        if row["schema"] != "1":
            errors.append(f"{label} schema must be 1")
        for commit_name in ("tooling_commit", "rtl_commit"):
            require_sha(row[commit_name], f"{label} {commit_name}", errors)
        numeric_fields = (
            "imem_words", "dmem_words", "icache_bytes", "icache_block_words", "icache_ways",
            "dcache_bytes", "dcache_block_words", "dcache_ways", "lut", "ff", "ramb18",
        )
        numbers = {field: row_uint(row, field, label, errors) for field in numeric_fields}
        configuration = SYNTHESIS_CONFIGURATIONS.get(name)
        geometry_fields = (
            "icache_bytes", "icache_block_words", "icache_ways",
            "dcache_bytes", "dcache_block_words", "dcache_ways",
        )
        if configuration is None:
            errors.append(f"{label} unknown synthesis configuration")
        elif all(numbers[field] is not None for field in geometry_fields):
            actual = tuple(numbers[field] for field in geometry_fields) + (row["dcache_policy"],)
            if actual != configuration:
                errors.append(f"{label} geometry does not match {name}")
        if numbers["imem_words"] != 512 or numbers["dmem_words"] != 512:
            errors.append(f"{label} backing memories must contain 512 words")
        if row["vivado_version"] != "2025.2" or not UINT_RE.fullmatch(row["vivado_build"]):
            errors.append(f"{label} must identify Vivado 2025.2 and a numeric build")
        if row["part"] != "xc7a35ticsg324-1L":
            errors.append(f"{label} FPGA part mismatch")
        period = require_decimal(row["clock_period_ns"], f"{label} clock_period_ns", errors)
        bram = require_decimal(row["bram_tiles"], f"{label} bram_tiles", errors)
        wns = require_decimal(row["wns_ns"], f"{label} wns_ns", errors)
        critical = require_decimal(row["critical_path_ns"], f"{label} critical_path_ns", errors)
        fmax = require_decimal(row["fmax_mhz"], f"{label} fmax_mhz", errors)
        if period is not None and period != 2.0:
            errors.append(f"{label} clock period must be 2.000 ns")
        if bram is not None and bram < 0.0:
            errors.append(f"{label} BRAM tiles must be nonnegative")
        if None not in (period, wns, critical, fmax):
            expected_critical = period - wns
            expected_fmax = 1000.0 / expected_critical if expected_critical > 0 else -1.0
            if abs(critical - expected_critical) > 0.0005:
                errors.append(f"{label} critical path does not equal period minus WNS")
            if abs(fmax - expected_fmax) > 0.0005:
                errors.append(f"{label} fmax does not match the critical path")
        require_hash(row["utilization_sha256"], f"{label} utilization SHA-256", errors)
        require_hash(row["timing_sha256"], f"{label} timing SHA-256", errors)
    if seen != set(SYNTHESIS_CONFIGURATIONS):
        errors.append("synthesis row population does not match the four routed configurations")
    if len(timestamps) != 1:
        errors.append("synthesis rows must share one measurement timestamp")


def validate_tools(result: ResultSet, checkout: Path, errors: list[str]) -> None:
    value = result.tool_versions
    if not exact_fields(value, TOOL_FIELDS, "tool_versions", errors):
        return
    if value["schema"] != 1:
        errors.append("tool_versions schema must be 1")
    require_sha(value["tooling_commit"], "tool_versions tooling commit", errors)
    require_sha(value["rtl_commit"], "tool_versions RTL commit", errors)
    references = load_env(checkout / "tools/reference_versions.env", errors)
    tools = load_env(checkout / "tools/tool_versions.env", errors)
    comparisons = (
        (value["architecture_test_commit"], references.get("ARCH_TEST_SHA"), "architecture-test commit"),
        (str(value["architecture_test_expected"]), references.get("ARCH_TEST_EXPECTED"), "architecture-test expected count"),
        (value["spike_commit"], references.get("SPIKE_SHA"), "Spike commit"),
        (value["ubuntu"], tools.get("UBUNTU_IMAGE", "").removeprefix("ubuntu:"), "Ubuntu version"),
        (value["verilator"], tools.get("VERILATOR_VERSION"), "Verilator version"),
        (value["riscv_gcc"], tools.get("RISCV_TOOLCHAIN_VERSION"), "RISC-V GCC version"),
        (value["riscv_as"], tools.get("RISCV_BINUTILS_VERSION"), "RISC-V assembler version"),
        (value["python"], tools.get("PYTHON_VERSION"), "Python version"),
        (value["vhs"], tools.get("VHS_VERSION"), "VHS version"),
        (value["ffmpeg"], tools.get("FFMPEG_VERSION"), "ffmpeg version"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            errors.append(f"tool_versions {label} does not match pinned metadata")
    if exact_fields(value["container"], {"image", "digest", "base", "revision"}, "container", errors):
        expected_base = f"{tools.get('UBUNTU_IMAGE')}@{tools.get('UBUNTU_DIGEST')}"
        if value["container"]["image"] != tools.get("VERIFY_IMAGE"):
            errors.append("container image does not match pinned metadata")
        if value["container"]["base"] != expected_base:
            errors.append("container base does not match pinned metadata")
        if str(value["container"]["revision"]) != tools.get("VERIFY_IMAGE_REVISION"):
            errors.append("container revision does not match pinned metadata")
        digest = value["container"]["digest"]
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            errors.append("container digest must be a SHA-256 image identifier")
    exact_fields(value["vivado"], {"version", "build", "platform"}, "Vivado", errors)


def synthesis_commits(result: ResultSet) -> tuple[str, str] | None:
    """The (tooling, RTL) commit pair every synthesis row was measured at.

    Returns None when the rows disagree, which is a provenance error rather
    than a lagging table.
    """
    stamped = [
        row for row in result.synthesis
        if "tooling_commit" in row and "rtl_commit" in row
    ]
    if len(stamped) != len(result.synthesis):
        return None
    pairs = {
        (str(row["tooling_commit"]), str(row["rtl_commit"])) for row in stamped
    }
    if len(pairs) != 1:
        return None
    return next(iter(pairs))


def validate_provenance(result: ResultSet, checkout: Path, errors: list[str]) -> None:
    tooling = result.manifest.get("tooling_commit")
    rtl = result.manifest.get("rtl_commit")
    sources: list[tuple[str, object, object]] = [
        ("verification", result.verification.get("tooling_commit"), result.verification.get("rtl_commit")),
        ("tool_versions", result.tool_versions.get("tooling_commit"), result.tool_versions.get("rtl_commit")),
    ]
    sources.extend((f"benchmark row {index}", row["tooling_commit"], row["rtl_commit"]) for index, row in enumerate(result.benchmarks, 2))
    for label, row_tooling, row_rtl in sources:
        if row_tooling != tooling:
            errors.append(f"{label} tooling commit differs from manifest")
        if row_rtl != rtl:
            errors.append(f"{label} RTL commit differs from manifest")
    # Synthesis rows carry their own provenance. Vivado is proprietary and is
    # often unavailable when the open-source evidence is remeasured, so the
    # implementation table legitimately lags the functional results. It must
    # still be one self-consistent measurement of an ancestor of the published
    # RTL, so it can never describe code that does not precede this set.
    synthesis = synthesis_commits(result)
    if result.synthesis and synthesis is None:
        errors.append("synthesis rows disagree on the measured commit")
    probes = [("tooling", tooling), ("RTL", rtl)]
    if synthesis is not None:
        probes.extend(
            (("synthesis tooling", synthesis[0]), ("synthesis RTL", synthesis[1]))
        )
    if (checkout / ".git").exists():
        missing = set()
        for label, commit in probes:
            probe = subprocess.run(
                ["git", "-C", str(checkout), "cat-file", "-e", f"{commit}^{{commit}}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode != 0:
                errors.append(f"{label} commit does not exist in this checkout")
                missing.add(commit)
        if (
            synthesis is not None
            and synthesis[1] != rtl
            and not missing & {synthesis[1], rtl}
        ):
            ancestry = subprocess.run(
                [
                    "git", "-C", str(checkout), "merge-base",
                    "--is-ancestor", str(synthesis[1]), str(rtl),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ancestry.returncode != 0:
                errors.append(
                    "synthesis RTL commit is not an ancestor of the published RTL commit"
                )


def validate_soc_fields(
    value: dict[str, Any], checkout: Path, errors: list[str]
) -> None:
    if value["schema"] != 1:
        errors.append("SoC result schema must be 1")
    require_timestamp(value["measured_at"], "SoC measured_at", errors)
    tooling = require_sha(value["tooling_commit"], "SoC tooling commit", errors)
    rtl = require_sha(value["rtl_commit"], "SoC RTL commit", errors)
    if value["board"] != "arty-a7-35t":
        errors.append("SoC board must be arty-a7-35t")
    if value["part"] != "xc7a35ticsg324-1L":
        errors.append("SoC part must be xc7a35ticsg324-1L")

    metadata_errors: list[str] = []
    references = load_env(checkout / "tools/reference_versions.env", metadata_errors)
    errors.extend(metadata_errors)
    digilent = require_sha(value["digilent_xdc_sha"], "SoC Digilent XDC SHA", errors)
    if digilent is not None and digilent != references.get("DIGILENT_XDC_SHA"):
        errors.append("SoC Digilent XDC SHA does not match pinned metadata")

    if exact_fields(
        value["firmware_sha256"], SOC_FIRMWARE_FIELDS, "SoC firmware hashes", errors
    ):
        for name in sorted(SOC_FIRMWARE_FIELDS):
            require_hash(
                value["firmware_sha256"][name], f"SoC firmware {name}", errors
            )
    require_hash(value["bitstream_sha256"], "SoC bitstream", errors)

    if exact_fields(value["vivado"], SOC_VIVADO_FIELDS, "SoC Vivado", errors):
        if value["vivado"]["version"] != "2025.2":
            errors.append("SoC Vivado version must be 2025.2")
        if not isinstance(value["vivado"]["build"], str) or not UINT_RE.fullmatch(
            value["vivado"]["build"]
        ):
            errors.append("SoC Vivado build must be a canonical integer string")
        if value["vivado"]["platform"] not in {"native", "wsl-windows"}:
            errors.append("SoC Vivado platform is unsupported")

    if exact_fields(value["route"], SOC_ROUTE_FIELDS, "SoC route", errors):
        input_period = require_decimal(
            value["route"]["input_clock_period_ns"],
            "SoC route input clock period", errors
        )
        soc_period = require_decimal(
            value["route"]["soc_clock_period_ns"],
            "SoC route SoC clock period", errors
        )
        wns = require_decimal(value["route"]["wns_ns"], "SoC route WNS", errors)
        critical = require_decimal(
            value["route"]["critical_path_ns"], "SoC route critical path", errors
        )
        fmax = require_decimal(value["route"]["fmax_mhz"], "SoC route fmax", errors)
        if input_period is not None and abs(input_period - 10.0) > 0.0001:
            errors.append("SoC route input clock period must be 10.000 ns")
        if soc_period is not None and abs(soc_period - 20.0) > 0.0001:
            errors.append("SoC route SoC clock period must be 20.000 ns")
        if wns is not None and wns < 0.0:
            errors.append("SoC route WNS must be nonnegative")
        if critical is not None and critical <= 0.0:
            errors.append("SoC route critical path must be positive")
        if None not in (soc_period, wns, critical) and abs(
            critical - (soc_period - wns)
        ) > 0.001:
            errors.append("SoC route critical path does not match period minus WNS")
        if critical is not None and critical > 0.0 and fmax is not None:
            if abs(fmax - 1000.0 / critical) > 0.001:
                errors.append("SoC route fmax does not match the critical path")
        require_uint(value["route"]["lut"], "SoC route LUT", errors)
        require_uint(value["route"]["ff"], "SoC route FF", errors)
        bram = require_decimal(value["route"]["bram_tiles"], "SoC route BRAM", errors)
        if bram is not None and bram < 0.0:
            errors.append("SoC route BRAM must be nonnegative")
        for name in ("timing_sha256", "utilization_sha256", "drc_sha256"):
            require_hash(value["route"][name], f"SoC route {name}", errors)

    if exact_fields(
        value["verification"], SOC_VERIFICATION_FIELDS, "SoC verification", errors
    ):
        if value["verification"]["full_status"] != "complete":
            errors.append("SoC full verification must be complete")
        if value["verification"]["soc_status"] != "complete":
            errors.append("SoC integration verification must be complete")
        require_hash(
            value["verification"]["full_receipt_sha256"],
            "SoC full verification receipt",
            errors,
        )
        require_hash(
            value["verification"]["soc_receipt_sha256"],
            "SoC integration verification receipt",
            errors,
        )

    if exact_fields(value["uart"], SOC_UART_FIELDS, "SoC UART", errors):
        require_hash(value["uart"]["transcript_sha256"], "SoC UART transcript", errors)
        if value["uart"]["lines"] != [
            "rv32i soc ready", "external irq", "external irq"
        ]:
            errors.append("SoC UART lines must contain the complete demo transcript")

    if exact_fields(
        value["manual_observations"],
        SOC_OBSERVATION_FIELDS,
        "SoC manual observations",
        errors,
    ):
        observations = value["manual_observations"]
        if observations["reset_banner"] is not True:
            errors.append("SoC reset banner must be observed")
        counts = {
            "button_presses": 2,
            "led_transitions": 2,
            "release_transitions": 0,
        }
        for name, expected in counts.items():
            count = require_uint(observations[name], f"SoC {name}", errors)
            if count is not None and count != expected:
                errors.append(f"SoC {name.replace('_', ' ')} must be {expected}")

    if (checkout / ".git").exists() and tooling is not None and rtl is not None:
        existing: dict[str, bool] = {}
        for label, commit in (("tooling", tooling), ("RTL", rtl)):
            probe = subprocess.run(
                ["git", "-C", str(checkout), "cat-file", "-e", f"{commit}^{{commit}}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            existing[label] = probe.returncode == 0
            if not existing[label]:
                errors.append(f"SoC {label} commit does not exist in this checkout")
        if all(existing.values()):
            ancestor = subprocess.run(
                ["git", "-C", str(checkout), "merge-base", "--is-ancestor", rtl, tooling]
            )
            if ancestor.returncode != 0:
                errors.append("SoC RTL commit must be an ancestor of tooling commit")
            rtl_diff = subprocess.run(
                ["git", "-C", str(checkout), "diff", "--quiet", rtl, tooling, "--", "rtl"]
            )
            if rtl_diff.returncode != 0:
                errors.append("SoC RTL differs between the recorded commits")


def validate_soc_result(root: Path, checkout: Path) -> list[str]:
    path = root / "soc.json"
    if not path.exists():
        return []
    value = load_json(path)
    errors: list[str] = []
    if exact_fields(value, SOC_FIELDS, "SoC result", errors):
        validate_soc_fields(value, checkout.resolve(), errors)
    return errors


def result_source_counts(
    result: ResultSet,
    checkout: Path,
) -> tuple[int, int, int, int]:
    rtl_commit = result.manifest.get("rtl_commit")
    tooling_commit = result.manifest.get("tooling_commit")
    if not isinstance(rtl_commit, str) or SHA_RE.fullmatch(rtl_commit) is None:
        raise ResultError("manifest RTL commit is invalid")
    if not isinstance(tooling_commit, str) or SHA_RE.fullmatch(tooling_commit) is None:
        raise ResultError("manifest tooling commit is invalid")
    if evidence_state(checkout, rtl_commit) == "historical":
        harness = harness_test_count_text(
            git_blob(checkout, tooling_commit, "tools/test_harness.py"),
            f"{tooling_commit}:tools/test_harness.py",
        )
        paths = tuple(
            path for path in git_paths(checkout, rtl_commit, "rtl")
            if path.endswith(".sv")
        )
        if not paths:
            raise ResultError("recorded RTL commit contains no SystemVerilog sources")
        source = "\n".join(git_blob(checkout, rtl_commit, path) for path in paths)
        concurrent, immediate, covers = sv_property_counts(source)
        return harness, concurrent, immediate, covers
    harness = harness_test_count(checkout / "tools/test_harness.py")
    concurrent, immediate, covers = checkout_property_counts(checkout)
    return harness, concurrent, immediate, covers


def validate_result_set(root: Path, checkout: Path) -> list[str]:
    try:
        result = load_result_set(root)
    except (ResultError, OSError) as exc:
        return [str(exc)]
    errors: list[str] = []
    references = load_env(checkout.resolve() / "tools/reference_versions.env", errors)
    expected_text = references.get("ARCH_TEST_EXPECTED", "")
    architecture_expected = int(expected_text) if UINT_RE.fullmatch(expected_text) else 0
    if architecture_expected <= 0:
        errors.append("ARCH_TEST_EXPECTED must be a positive canonical integer")
    try:
        source_counts = result_source_counts(result, checkout.resolve())
    except (OSError, ResultError, SyntaxError) as exc:
        errors.append(f"cannot derive recorded source counts: {exc}")
        source_counts = (-1, -1, -1, -1)
    harness_expected, concurrent_expected, immediate_expected, cover_expected = source_counts
    validate_manifest(result, errors, architecture_expected, cover_expected)
    validate_verification(
        result,
        errors,
        architecture_expected,
        harness_expected,
        concurrent_expected,
        immediate_expected,
        cover_expected,
    )
    validate_benchmarks(result, errors)
    validate_synthesis(result, errors)
    validate_tools(result, checkout.resolve(), errors)
    validate_provenance(result, checkout.resolve(), errors)
    try:
        errors.extend(validate_soc_result(root, checkout.resolve()))
    except (ResultError, OSError) as exc:
        errors.append(str(exc))
    return errors


def git_text(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ResultError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git_blob(checkout: Path, commit: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), "show", f"{commit}:{relative}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ResultError(f"cannot read recorded source {commit}:{relative}")
    return result.stdout


def git_paths(checkout: Path, commit: str, prefix: str) -> tuple[str, ...]:
    prefix = prefix.strip("/")
    if not prefix or prefix == "." or ".." in Path(prefix).parts:
        raise ResultError("recorded source prefix is invalid")
    output = git_text(
        checkout, "ls-tree", "-r", "--name-only", commit, "--", prefix
    )
    paths = tuple(output.splitlines()) if output else ()
    if any(path != prefix and not path.startswith(prefix + "/") for path in paths):
        raise ResultError("recorded source path escaped its prefix")
    return paths


def evidence_state(
    checkout: Path,
    rtl_commit: str,
) -> Literal["current", "historical"]:
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        return "current"
    paths = ("rtl", "sim/cpu_tb.cpp")
    diff = subprocess.run(
        ["git", "-C", str(checkout), "diff", "--quiet", rtl_commit, "--", *paths],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if diff.returncode not in (0, 1):
        raise ResultError(f"cannot compare RTL with recorded commit: {diff.stderr.strip()}")
    status = subprocess.run(
        [
            "git", "-C", str(checkout), "status", "--porcelain",
            "--untracked-files=all", "--", *paths,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if status.returncode != 0:
        raise ResultError(f"cannot inspect RTL checkout state: {status.stderr.strip()}")
    return "current" if diff.returncode == 0 and not status.stdout.strip() else "historical"


def require_clean_checkout(checkout: Path, source_commit: str) -> None:
    if not (checkout / ".git").exists():
        return
    if git_text(checkout, "rev-parse", "HEAD") != source_commit:
        raise ResultError("source commit must equal checkout HEAD")
    if git_text(checkout, "status", "--short", "--untracked-files=no"):
        raise ResultError("tracked checkout must be clean before result collection")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def benchmark_inputs(run_dir: Path) -> list[Path]:
    combined = run_dir / "benchmarks.csv"
    if combined.is_file():
        return [combined]
    paths = sorted((run_dir / "benchmarks").glob("*.csv")) if (run_dir / "benchmarks").is_dir() else []
    if not paths:
        paths = sorted(run_dir.glob("benchmarks-*.csv"))
    if len(paths) != 4:
        raise ResultError("run directory must contain one combined or four benchmark CSV files")
    return paths


def publish_directory(staged: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output in (Path("/"), output.parent):
        raise ResultError(f"unsafe result destination: {output}")
    backup: Path | None = None
    try:
        if output.exists():
            if not output.is_dir():
                raise ResultError(f"result destination is not a directory: {output}")
            backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.backup-", dir=output.parent))
            backup.rmdir()
            output.replace(backup)
        staged.replace(output)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if not output.exists() and backup is not None and backup.exists():
            backup.replace(output)
        raise


def collect_open(root: Path, output: Path, source_commit: str) -> None:
    run_dir = root.resolve()
    output = output.resolve()
    checkout = output.parent
    if SHA_RE.fullmatch(source_commit) is None:
        raise ResultError("invalid source commit")
    require_clean_checkout(checkout, source_commit)
    metadata_errors: list[str] = []
    reference_metadata = load_env(checkout / "tools/reference_versions.env", metadata_errors)
    expected_text = reference_metadata.get("ARCH_TEST_EXPECTED", "")
    if metadata_errors or UINT_RE.fullmatch(expected_text) is None or int(expected_text) <= 0:
        raise ResultError("invalid architecture-test expected-count metadata")
    architecture_expected = int(expected_text)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        format_doc = output / "FORMAT.md" if (output / "FORMAT.md").is_file() else run_dir / "FORMAT.md"
        if not format_doc.is_file():
            raise ResultError("result format documentation is missing")
        shutil.copyfile(format_doc, stage / "FORMAT.md")
        for name in ("verification.json", "tool_versions.json", "synthesis.csv"):
            source = run_dir / name
            if not source.is_file():
                raise ResultError(f"run directory is missing {name}")
            shutil.copyfile(source, stage / name)
        rows: list[dict[str, str]] = []
        for source in benchmark_inputs(run_dir):
            rows.extend(load_csv(source, BENCHMARK_FIELDS))
        write_csv(stage / "benchmarks.csv", BENCHMARK_FIELDS, rows)
        verification = load_json(stage / "verification.json")
        tooling = load_json(stage / "tool_versions.json")
        if verification.get("tooling_commit") != source_commit or tooling.get("tooling_commit") != source_commit:
            raise ResultError("run records do not match the source commit")
        rtl_commit = verification.get("rtl_commit")
        if tooling.get("rtl_commit") != rtl_commit or not isinstance(rtl_commit, str):
            raise ResultError("run records do not share one RTL commit")
        measured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = {
            "schema": 1,
            "measured_at": measured_at,
            "tooling_commit": source_commit,
            "rtl_commit": rtl_commit,
            "status": "complete",
            "files": list(RESULT_FILES),
            "sha256": {
                name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
                for name in RESULT_FILES
            },
            "expected": {
                "benchmark_rows": 20,
                "synthesis_rows": 4,
                "directed_programs": 25,
                "memory_configurations": 6,
                "predictor_configurations": 3,
                "architecture_tests": architecture_expected,
                "architecture_lockstep": architecture_expected,
                "spike_random": 200,
                "cover_points": 44,
            },
        }
        write_json(stage / "manifest.json", manifest)
        errors = validate_result_set(stage, checkout)
        if errors:
            raise ResultError("; ".join(errors))
        publish_directory(stage, output)
        stage = Path()
    finally:
        if stage != Path() and stage.exists():
            shutil.rmtree(stage)


def collect_synthesis(root: Path, report_dir: Path, output: Path) -> None:
    checkout = root.resolve()
    report_dir = report_dir.resolve()
    output = output.resolve()
    sys.path.insert(0, str(checkout))
    from synthesis.summarize_reports import csv_summary

    destination = output if output.suffix == ".csv" else output / "synthesis.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    contents = csv_summary(report_dir)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", delete=False,
        ) as handle:
            handle.write(contents)
            temporary = Path(handle.name)
        load_csv(temporary, SYNTHESIS_FIELDS)
        temporary.replace(destination)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def artifact_path(value: object, checkout: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ResultError(f"{label} path is invalid")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (checkout / path).resolve()


def sha256_file(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ResultError(f"cannot read {label}: {path}") from exc


def require_artifact_hash(path: Path, expected: object, label: str) -> str:
    if not isinstance(expected, str) or HASH_RE.fullmatch(expected) is None:
        raise ResultError(f"{label} manifest hash is invalid")
    actual = sha256_file(path, label)
    if actual != expected:
        raise ResultError(f"{label} hash mismatch")
    return actual


def validate_collection_receipts(
    full: dict[str, Any],
    soc: dict[str, Any],
    checkout: Path,
) -> tuple[str, str]:
    errors: list[str] = []
    if exact_fields(full, VERIFICATION_FIELDS, "full verification receipt", errors):
        references = load_env(checkout / "tools/reference_versions.env", errors)
        expected_text = references.get("ARCH_TEST_EXPECTED", "")
        architecture_expected = int(expected_text) if UINT_RE.fullmatch(expected_text) else 0
        harness = harness_test_count(checkout / "tools/test_harness.py")
        concurrent, immediate, covers = checkout_property_counts(checkout)
        receipt = ResultSet(Path(), {}, full, (), (), {})
        validate_verification(
            receipt,
            errors,
            architecture_expected,
            harness,
            concurrent,
            immediate,
            covers,
        )
    if exact_fields(soc, SOC_RECEIPT_FIELDS, "SoC verification receipt", errors):
        if soc["schema"] != 1 or soc["profile"] != "soc":
            errors.append("SoC verification receipt profile is invalid")
        if soc["status"] != "complete":
            errors.append("SoC verification receipt is not complete")
        require_timestamp(soc["measured_at"], "SoC verification measured_at", errors)
        require_sha(soc["tooling_commit"], "SoC receipt tooling commit", errors)
        require_sha(soc["rtl_commit"], "SoC receipt RTL commit", errors)
        if soc["commands"] != ["make soc-check"]:
            errors.append("SoC verification receipt command is not canonical")
    if errors:
        raise ResultError("; ".join(errors))
    return str(full["tooling_commit"]), str(full["rtl_commit"])


def collect_soc(
    board_manifest_path: Path,
    firmware_manifest_path: Path,
    full_receipt_path: Path,
    soc_receipt_path: Path,
    uart_path: Path,
    observations_path: Path,
    output: Path,
) -> None:
    inputs = tuple(
        path.resolve()
        for path in (
            board_manifest_path,
            firmware_manifest_path,
            full_receipt_path,
            soc_receipt_path,
            uart_path,
            observations_path,
        )
    )
    output = output.resolve()
    if output.name != "soc.json" or output.parent.name != "results":
        raise ResultError("SoC result output must be results/soc.json")
    for source in inputs:
        if output == source or output.is_relative_to(source.parent):
            raise ResultError("SoC result destination cannot be inside a raw input directory")
    checkout = output.parent.parent.resolve()
    board = load_json(inputs[0])
    firmware = load_json(inputs[1])
    full = load_json(inputs[2])
    soc = load_json(inputs[3])
    observations = load_json(inputs[5])

    board_fields = {
        "schema", "status", "measured_at", "source_commit", "rtl_commit", "part",
        "top", "input_clock_period_ns", "soc_clock_period_ns", "wns_ns",
        "firmware", "xdc_sha256", "vivado", "invocation", "outputs",
    }
    errors: list[str] = []
    if not exact_fields(board, board_fields, "board manifest", errors):
        raise ResultError("; ".join(errors))
    if board["schema"] != 1 or board["status"] != "complete":
        raise ResultError("board manifest is not complete")
    require_timestamp(board["measured_at"], "board measured_at", errors)
    source_commit = require_sha(board["source_commit"], "board source commit", errors)
    rtl_commit = require_sha(board["rtl_commit"], "board RTL commit", errors)
    if board["part"] != "xc7a35ticsg324-1L" or board["top"] != "arty_a7_35t_top":
        errors.append("board manifest target is incorrect")
    board_input_period = board["input_clock_period_ns"]
    if (
        not isinstance(board_input_period, (int, float))
        or isinstance(board_input_period, bool)
        or not math.isfinite(float(board_input_period))
        or abs(float(board_input_period) - 10.0) > 0.0001
    ):
        errors.append("board manifest input clock period must be 10 ns")
    board_soc_period = board["soc_clock_period_ns"]
    if (
        not isinstance(board_soc_period, (int, float))
        or isinstance(board_soc_period, bool)
        or not math.isfinite(float(board_soc_period))
        or abs(float(board_soc_period) - 20.0) > 0.0001
    ):
        errors.append("board manifest SoC clock period must be 20 ns")
    board_wns = board["wns_ns"]
    if (
        not isinstance(board_wns, (int, float))
        or isinstance(board_wns, bool)
        or not math.isfinite(float(board_wns))
        or float(board_wns) < 0.0
    ):
        errors.append("board manifest WNS must be nonnegative")
    board_vivado_fields = {"version", "build", "platform", "launcher"}
    if exact_fields(board["vivado"], board_vivado_fields, "board Vivado", errors):
        if board["vivado"]["version"] != "2025.2":
            errors.append("board Vivado version must be 2025.2")
        if board["vivado"]["platform"] not in {"native", "wsl-windows"}:
            errors.append("board Vivado platform is unsupported")
        if not isinstance(board["vivado"]["build"], str) or UINT_RE.fullmatch(
            board["vivado"]["build"]
        ) is None:
            errors.append("board Vivado build is invalid")
        if not isinstance(board["vivado"]["launcher"], str) or not board["vivado"][
            "launcher"
        ]:
            errors.append("board Vivado launcher is invalid")
    if not isinstance(board["invocation"], list) or any(
        not isinstance(argument, str) or not argument for argument in board["invocation"]
    ):
        errors.append("board invocation is invalid")
    if errors:
        raise ResultError("; ".join(errors))

    board_dir = inputs[0].parent
    board_artifacts = {
        "bitstream": board_dir / "rv32i-soc-arty-a7-35t.bit",
        "utilization": board_dir / "utilization.rpt",
        "timing": board_dir / "timing_summary.rpt",
        "drc": board_dir / "drc.rpt",
        "placement": board_dir / "placement.tsv",
    }
    if not isinstance(board["outputs"], dict) or set(board["outputs"]) != set(
        board_artifacts
    ):
        raise ResultError("board output manifest is malformed")
    artifact_hashes = {
        name: require_artifact_hash(path, board["outputs"][name], f"board {name}")
        for name, path in board_artifacts.items()
    }
    xdc_hash = sha256_file(checkout / "boards/arty_a7_35t.xdc", "board constraints")
    if board["xdc_sha256"] != xdc_hash:
        raise ResultError("board constraint hash mismatch")
    drc = board_artifacts["drc"].read_text(encoding="utf-8", errors="replace")
    if re.search(r"\b(?:CRITICAL WARNING|ERROR)\b", drc, re.IGNORECASE):
        raise ResultError("board DRC report contains a failure")

    firmware_fields = {"schema", "status", "entry", "elf", "imem", "dmem"}
    if not exact_fields(firmware, firmware_fields, "firmware manifest", errors):
        raise ResultError("; ".join(errors))
    if firmware["schema"] != 1 or firmware["status"] != "complete":
        raise ResultError("firmware manifest is not complete")
    if firmware["entry"] != 0:
        raise ResultError("firmware entry must be zero")
    firmware_hashes: dict[str, str] = {}
    for name in ("elf", "imem", "dmem"):
        artifact = firmware[name]
        expected_fields = {"path", "sha256"} | ({"words"} if name != "elf" else set())
        nested_errors: list[str] = []
        if not exact_fields(artifact, expected_fields, f"firmware {name}", nested_errors):
            raise ResultError("; ".join(nested_errors))
        path = artifact_path(artifact["path"], checkout, f"firmware {name}")
        firmware_hashes[name] = require_artifact_hash(
            path, artifact["sha256"], f"firmware {name}"
        )
        if name != "elf":
            if artifact["words"] != 8192:
                raise ResultError(f"firmware {name} must contain 8192 words")
            try:
                lines = path.read_text(encoding="ascii").splitlines()
            except (OSError, UnicodeError) as exc:
                raise ResultError(f"firmware {name} image is invalid") from exc
            if len(lines) != 8192 or any(
                re.fullmatch(r"[0-9a-f]{8}", line) is None for line in lines
            ):
                raise ResultError(f"firmware {name} image is not canonical")
    if not isinstance(board["firmware"], dict) or board["firmware"] != {
        "imem_sha256": firmware_hashes["imem"],
        "dmem_sha256": firmware_hashes["dmem"],
    }:
        raise ResultError("board and firmware manifests do not match")

    full_tooling, full_rtl = validate_collection_receipts(full, soc, checkout)
    identities = {
        source_commit,
        full_tooling,
        soc.get("tooling_commit"),
    }
    rtl_identities = {rtl_commit, full_rtl, soc.get("rtl_commit")}
    if len(identities) != 1 or len(rtl_identities) != 1:
        raise ResultError("board and verification records do not share commits")

    try:
        from synthesis.summarize_reports import SummaryError, parse_utilization, parse_wns
        lut, ff, bram, _ = parse_utilization(board_artifacts["utilization"])
        report_wns = parse_wns(board_artifacts["timing"])
    except (OSError, SummaryError) as exc:
        raise ResultError(f"board report parsing failed: {exc}") from exc
    if abs(report_wns - float(board["wns_ns"])) > 0.0001:
        raise ResultError("board timing report and manifest WNS differ")
    input_period = float(board["input_clock_period_ns"])
    period = float(board["soc_clock_period_ns"])
    critical = period - report_wns
    if critical <= 0.0:
        raise ResultError("board critical path is invalid")

    try:
        transcript = inputs[4].read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as exc:
        raise ResultError("UART transcript is unreadable") from exc
    expected_transcript = "rv32i soc ready\nexternal irq\nexternal irq\n"
    if "\r" in transcript or transcript != expected_transcript:
        raise ResultError("UART transcript is not the complete expected output")
    observation_errors: list[str] = []
    if not exact_fields(
        observations,
        SOC_OBSERVATION_FIELDS,
        "manual observations",
        observation_errors,
    ):
        raise ResultError("; ".join(observation_errors))
    if observations != {
        "reset_banner": True,
        "button_presses": 2,
        "led_transitions": 2,
        "release_transitions": 0,
    }:
        raise ResultError("manual observations do not describe the approved demo")

    references = load_env(checkout / "tools/reference_versions.env", errors)
    digilent = references.get("DIGILENT_XDC_SHA")
    if errors or not isinstance(digilent, str) or SHA_RE.fullmatch(digilent) is None:
        raise ResultError("Digilent XDC metadata is invalid")
    value = {
        "schema": 1,
        "measured_at": board["measured_at"],
        "tooling_commit": source_commit,
        "rtl_commit": rtl_commit,
        "board": "arty-a7-35t",
        "part": board["part"],
        "digilent_xdc_sha": digilent,
        "firmware_sha256": firmware_hashes,
        "bitstream_sha256": artifact_hashes["bitstream"],
        "vivado": {
            "version": board["vivado"]["version"],
            "build": board["vivado"]["build"],
            "platform": board["vivado"]["platform"],
        },
        "route": {
            "input_clock_period_ns": f"{input_period:.3f}",
            "soc_clock_period_ns": f"{period:.3f}",
            "wns_ns": f"{report_wns:.3f}",
            "critical_path_ns": f"{critical:.3f}",
            "fmax_mhz": f"{1000.0 / critical:.3f}",
            "lut": lut,
            "ff": ff,
            "bram_tiles": f"{bram:.1f}",
            "timing_sha256": artifact_hashes["timing"],
            "utilization_sha256": artifact_hashes["utilization"],
            "drc_sha256": artifact_hashes["drc"],
        },
        "verification": {
            "full_status": full["status"],
            "soc_status": soc["status"],
            "full_receipt_sha256": sha256_file(inputs[2], "full verification receipt"),
            "soc_receipt_sha256": sha256_file(inputs[3], "SoC verification receipt"),
        },
        "uart": {
            "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            "lines": transcript.rstrip("\n").split("\n"),
        },
        "manual_observations": observations,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        write_json(temporary, value)
        staged_errors: list[str] = []
        if exact_fields(value, SOC_FIELDS, "SoC result", staged_errors):
            validate_soc_fields(value, checkout, staged_errors)
        if staged_errors:
            raise ResultError("; ".join(staged_errors))
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_tool_versions(
    checkout: Path,
    output: Path,
    rtl_commit: str,
    vivado_build: str,
    vivado_platform: str,
    container_digest: str,
) -> None:
    errors: list[str] = []
    tools = load_env(checkout / "tools/tool_versions.env", errors)
    references = load_env(checkout / "tools/reference_versions.env", errors)
    if errors:
        raise ResultError("; ".join(errors))
    source_commit = git_text(checkout, "rev-parse", "HEAD")
    value = {
        "schema": 1,
        "tooling_commit": source_commit,
        "rtl_commit": rtl_commit,
        "container": {
            "image": tools["VERIFY_IMAGE"],
            "digest": container_digest,
            "base": f"{tools['UBUNTU_IMAGE']}@{tools['UBUNTU_DIGEST']}",
            "revision": int(tools["VERIFY_IMAGE_REVISION"]),
        },
        "ubuntu": tools["UBUNTU_IMAGE"].removeprefix("ubuntu:"),
        "verilator": tools["VERILATOR_VERSION"],
        "riscv_gcc": tools["RISCV_TOOLCHAIN_VERSION"],
        "riscv_as": tools["RISCV_BINUTILS_VERSION"],
        "python": tools["PYTHON_VERSION"],
        "spike_commit": references["SPIKE_SHA"],
        "architecture_test_commit": references["ARCH_TEST_SHA"],
        "architecture_test_expected": int(references["ARCH_TEST_EXPECTED"]),
        "vivado": {"version": "2025.2", "build": vivado_build, "platform": vivado_platform},
        "vhs": tools["VHS_VERSION"],
        "ffmpeg": tools["FFMPEG_VERSION"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        write_json(temporary, value)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def source_vector_count(path: Path, label: str, expected: int) -> int:
    match = re.search(
        rf"PASS {re.escape(label)}: (?:(?P<count>[1-9][0-9]*)|%0d) vectors",
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise ResultError(f"cannot derive {label} vector count")
    if match.group("count") is not None and int(match.group("count")) != expected:
        raise ResultError(f"unexpected {label} vector count")
    return expected


def harness_test_count_text(source: str, filename: str) -> int:
    tree = ast.parse(source, filename=filename)
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name.startswith("test_")
    )


def harness_test_count(path: Path) -> int:
    return harness_test_count_text(path.read_text(encoding="utf-8"), str(path))


def strip_sv_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", source)


def sv_property_counts(source: str) -> tuple[int, int, int]:
    source = strip_sv_comments(source)
    return (
        len(re.findall(r"\bassert\s+property\s*\(", source)),
        len(re.findall(r"\bassert\s*\(", source)),
        len(re.findall(r"\bcover\s+property\s*\(", source)),
    )


def checkout_property_counts(checkout: Path) -> tuple[int, int, int]:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((checkout / "rtl").rglob("*.sv"))
    )
    return sv_property_counts(source)


def rtl_property_counts(checkout: Path) -> tuple[int, int]:
    concurrent, immediate, _ = checkout_property_counts(checkout)
    return concurrent, immediate


def coverage_counts(path: Path) -> dict[str, dict[str, int]]:
    line_re = re.compile(r"^C '(.*)' ([0-9]+)$")
    field_re = re.compile(r"\x01(\w+)\x02([^\x01]*)")
    counts: dict[str, dict[str, int]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ResultError("coverage result is missing") from exc
    for line in lines:
        match = line_re.fullmatch(line)
        if match is None:
            continue
        category = dict(field_re.findall(match.group(1))).get("t")
        if category not in {"line", "branch", "expr", "toggle", "user"}:
            continue
        group = counts.setdefault(category, {"hit": 0, "total": 0})
        group["total"] += 1
        group["hit"] += int(match.group(2)) > 0
    expected = {"line", "branch", "expr", "toggle", "user"}
    if set(counts) != expected or any(group["total"] == 0 for group in counts.values()):
        raise ResultError("coverage result does not contain every required category")
    return counts


def write_verification_receipt(checkout: Path, output: Path) -> None:
    checkout = checkout.resolve()
    output = output.resolve()
    coverage = coverage_counts(checkout / "coverage" / "merged.dat")
    concurrent, immediate = rtl_property_counts(checkout)
    source_cover_points = coverage["user"]["total"]
    metadata_errors: list[str] = []
    references = load_env(checkout / "tools" / "reference_versions.env", metadata_errors)
    expected_text = references.get("ARCH_TEST_EXPECTED", "")
    if metadata_errors or UINT_RE.fullmatch(expected_text) is None:
        raise ResultError("invalid architecture-test expected-count metadata")
    architecture_expected = int(expected_text)
    if coverage["user"]["hit"] != source_cover_points:
        raise ResultError("functional coverage is incomplete")
    value = {
        "schema": 1,
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tooling_commit": git_text(checkout, "rev-parse", "HEAD"),
        "rtl_commit": git_text(checkout, "log", "-1", "--format=%H", "--", "rtl"),
        "status": "complete",
        "decoder_vectors": source_vector_count(
            checkout / "sim" / "unit" / "control_tb.sv", "control", 2120
        ),
        "hazard_vectors": source_vector_count(
            checkout / "sim" / "unit" / "hazard_detect_tb.sv", "hazard", 262144
        ),
        "harness_tests": harness_test_count(checkout / "tools" / "test_harness.py"),
        "assertions": {"concurrent": concurrent, "immediate": immediate},
        "cover_points": {"source": source_cover_points, "hit": coverage["user"]["hit"]},
        "directed_programs": 25,
        "memory_configurations": [
            {"name": name, "passed": 25} for name in MEMORY_CONFIGURATIONS
        ],
        "predictor_configurations": [
            {"name": name, "passed": 25} for name in PREDICTOR_CONFIGURATIONS
        ],
        "architecture_tests": {
            "discovered": architecture_expected, "passed": architecture_expected,
            "failed": 0, "missing": 0, "infrastructure": 0,
        },
        "architecture_lockstep": {
            "discovered": architecture_expected, "passed": architecture_expected, "failed": 0,
        },
        "python_random": {
            "baseline": {"requested": 1000, "passed": 1000},
            "cached": {"requested": 1000, "passed": 1000},
        },
        "spike_random": {"requested": 200, "passed": 200, "instructions": 60},
        "coverage": {
            "line": coverage["line"],
            "branch": coverage["branch"],
            "expression": coverage["expr"],
            "toggle": coverage["toggle"],
            "user": coverage["user"],
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
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        write_json(temporary, value)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_profile_receipt(checkout: Path, output: Path, profile: str) -> None:
    if profile != "soc":
        raise ResultError(f"unsupported receipt profile: {profile}")
    checkout = checkout.resolve()
    output = output.resolve()
    value = {
        "schema": 1,
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": "soc",
        "status": "complete",
        "tooling_commit": git_text(checkout, "rev-parse", "HEAD"),
        "rtl_commit": git_text(checkout, "log", "-1", "--format=%H", "--", "rtl"),
        "commands": ["make soc-check"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        write_json(temporary, value)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    collect_open_parser = subparsers.add_parser("collect-open")
    collect_open_parser.add_argument("--run-dir", type=Path, required=True)
    collect_open_parser.add_argument("--output", type=Path, required=True)
    collect_open_parser.add_argument("--source-commit")
    collect_synth_parser = subparsers.add_parser("collect-synthesis")
    collect_synth_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    collect_synth_parser.add_argument("--report-dir", type=Path, required=True)
    collect_synth_parser.add_argument("--output", type=Path, required=True)
    collect_soc_parser = subparsers.add_parser("collect-soc")
    collect_soc_parser.add_argument("--board-manifest", type=Path, required=True)
    collect_soc_parser.add_argument("--firmware-manifest", type=Path, required=True)
    collect_soc_parser.add_argument("--verification", type=Path, required=True)
    collect_soc_parser.add_argument("--soc-verification", type=Path, required=True)
    collect_soc_parser.add_argument("--uart", type=Path, required=True)
    collect_soc_parser.add_argument("--observations", type=Path, required=True)
    collect_soc_parser.add_argument("--output", type=Path, required=True)
    versions = subparsers.add_parser("tool-versions")
    versions.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    versions.add_argument("--output", type=Path, required=True)
    versions.add_argument("--rtl-commit", required=True)
    versions.add_argument("--vivado-build", required=True)
    versions.add_argument("--vivado-platform", required=True)
    versions.add_argument("--container-digest", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "check":
        errors = validate_result_set(args.root / "results", args.root)
        if errors:
            for error in errors:
                print(f"result check failed: {error}", file=sys.stderr)
            return 1
        print("result records are complete and internally consistent")
        return 0
    if args.command == "collect-open":
        try:
            checkout = args.output.resolve().parent
            source_commit = args.source_commit or git_text(checkout, "rev-parse", "HEAD")
            collect_open(args.run_dir, args.output, source_commit)
            print(f"published result records: {args.output}")
            return 0
        except (ResultError, OSError, ValueError) as exc:
            print(f"result collection failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-synthesis":
        try:
            collect_synthesis(args.root, args.report_dir, args.output)
            print(f"wrote synthesis records under {args.output}")
            return 0
        except (ResultError, OSError, ValueError) as exc:
            print(f"synthesis collection failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-soc":
        try:
            collect_soc(
                args.board_manifest,
                args.firmware_manifest,
                args.verification,
                args.soc_verification,
                args.uart,
                args.observations,
                args.output,
            )
            print(f"wrote SoC result: {args.output}")
            return 0
        except (ResultError, OSError, ValueError) as exc:
            print(f"SoC result collection failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "tool-versions":
        try:
            write_tool_versions(
                args.root.resolve(), args.output.resolve(), args.rtl_commit,
                args.vivado_build, args.vivado_platform, args.container_digest,
            )
            print(f"wrote tool versions: {args.output}")
            return 0
        except (ResultError, OSError, ValueError, KeyError) as exc:
            print(f"tool-version collection failed: {exc}", file=sys.stderr)
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
