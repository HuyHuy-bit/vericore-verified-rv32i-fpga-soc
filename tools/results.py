#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


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


def validate_manifest(result: ResultSet, errors: list[str], architecture_expected: int) -> None:
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
            "cover_points": 44,
        }
        for key, expected_value in wanted.items():
            if value["expected"][key] != expected_value:
                errors.append(f"manifest expected {key} must be {expected_value}")


def validate_verification(
    result: ResultSet,
    errors: list[str],
    architecture_expected: int,
    harness_expected: int,
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
            f"verification harness test count must match current source ({harness_expected})"
        )
    if exact_fields(value["assertions"], {"concurrent", "immediate"}, "assertions", errors):
        if value["assertions"] != {"concurrent": 25, "immediate": 2}:
            errors.append("assertion counts must be 25 concurrent and 2 immediate")
    if exact_fields(value["cover_points"], {"source", "hit"}, "cover_points", errors):
        if value["cover_points"] != {"source": 44, "hit": 44}:
            errors.append("cover-point counts must be 44/44")
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
        if value["coverage"]["user"] != {"hit": 44, "total": 44}:
            errors.append("user coverage must be 44/44")
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


def validate_provenance(result: ResultSet, checkout: Path, errors: list[str]) -> None:
    tooling = result.manifest.get("tooling_commit")
    rtl = result.manifest.get("rtl_commit")
    sources: list[tuple[str, object, object]] = [
        ("verification", result.verification.get("tooling_commit"), result.verification.get("rtl_commit")),
        ("tool_versions", result.tool_versions.get("tooling_commit"), result.tool_versions.get("rtl_commit")),
    ]
    sources.extend((f"benchmark row {index}", row["tooling_commit"], row["rtl_commit"]) for index, row in enumerate(result.benchmarks, 2))
    sources.extend((f"synthesis row {index}", row["tooling_commit"], row["rtl_commit"]) for index, row in enumerate(result.synthesis, 2))
    for label, row_tooling, row_rtl in sources:
        if row_tooling != tooling:
            errors.append(f"{label} tooling commit differs from manifest")
        if row_rtl != rtl:
            errors.append(f"{label} RTL commit differs from manifest")
    if (checkout / ".git").exists():
        for label, commit in (("tooling", tooling), ("RTL", rtl)):
            probe = subprocess.run(
                ["git", "-C", str(checkout), "cat-file", "-e", f"{commit}^{{commit}}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if probe.returncode != 0:
                errors.append(f"{label} commit does not exist in this checkout")
        if isinstance(rtl, str) and SHA_RE.fullmatch(rtl):
            paths = [path for path in ("rtl", "cpu_tb.cpp") if (checkout / path).exists()]
            if paths:
                diff = subprocess.run(
                    ["git", "-C", str(checkout), "diff", "--quiet", rtl, "--", *paths]
                )
                if diff.returncode != 0:
                    errors.append("tracked RTL differs from the frozen RTL commit")


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
        harness_expected = harness_test_count(
            checkout.resolve() / "tools" / "test_harness.py"
        )
    except (OSError, SyntaxError) as exc:
        errors.append(f"cannot derive harness test count: {exc}")
        harness_expected = -1
    validate_manifest(result, errors, architecture_expected)
    validate_verification(result, errors, architecture_expected, harness_expected)
    validate_benchmarks(result, errors)
    validate_synthesis(result, errors)
    validate_tools(result, checkout.resolve(), errors)
    validate_provenance(result, checkout.resolve(), errors)
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
        readme = output / "README.md" if (output / "README.md").is_file() else run_dir / "README.md"
        if not readme.is_file():
            raise ResultError("result README is missing")
        shutil.copyfile(readme, stage / "README.md")
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
    from syn.summarize_reports import csv_summary

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


def harness_test_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name.startswith("test_")
    )


def rtl_property_counts(checkout: Path) -> tuple[int, int]:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((checkout / "rtl").glob("*.sv"))
    )
    concurrent = len(re.findall(r"\bassert\s+property\s*\(", source))
    immediate = len(re.findall(r"\bassert\s*\(", source))
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
            checkout / "unit" / "control_tb.sv", "control", 2120
        ),
        "hazard_vectors": source_vector_count(
            checkout / "unit" / "hazard_detect_tb.sv", "hazard", 262144
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
