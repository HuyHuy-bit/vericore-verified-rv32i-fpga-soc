#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__:
    from .run_synth import CONFIGURATIONS, PART, PERIOD_NS
else:
    from run_synth import CONFIGURATIONS, PART, PERIOD_NS


class SummaryError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_number(source: str, label: str, integer: bool = True) -> int | float:
    match = re.search(
        rf"^\|\s*{label}\s*\|\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\|",
        source,
        re.MULTILINE,
    )
    if match is None:
        raise SummaryError(f"missing utilization row: {label}")
    value = match.group(1).replace(",", "")
    return int(float(value)) if integer else float(value)


def parse_utilization(path: Path) -> tuple[int, int, float, int]:
    source = path.read_text(encoding="utf-8", errors="replace")
    luts = int(table_number(source, r"Slice LUTs\*?"))
    ffs = int(table_number(source, "Slice Registers"))
    bram_tiles = float(table_number(source, "Block RAM Tile", integer=False))
    ramb18 = int(table_number(source, r"(?:RAMB18|RAMB18E1 only)"))
    return luts, ffs, bram_tiles, ramb18


def parse_wns(path: Path) -> float:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if "WNS(ns)" in line), None)
    if header is None:
        raise SummaryError("timing report is missing WNS(ns)")
    for line in lines[header + 1:]:
        fields = line.split()
        if fields and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", fields[0]):
            return float(fields[0])
    raise SummaryError("timing report is missing a WNS value")


def load_manifest(directory: Path, expected_name: str) -> dict[str, object]:
    path = directory / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SummaryError(f"invalid manifest for {expected_name}") from exc
    if manifest.get("schema") != 1 or manifest.get("status") != "complete":
        raise SummaryError(f"incomplete manifest for {expected_name}")
    configuration = manifest.get("configuration")
    expected = next(config for config in CONFIGURATIONS if config.name == expected_name)
    if configuration != {
        "name": expected.name,
        "ic_bytes": expected.ic_bytes,
        "ic_block": expected.ic_block,
        "ic_ways": expected.ic_ways,
        "dc_bytes": expected.dc_bytes,
        "dc_block": expected.dc_block,
        "dc_ways": expected.dc_ways,
        "dc_wb": expected.dc_wb,
        "imem_depth": expected.imem_depth,
        "dmem_depth": expected.dmem_depth,
    }:
        raise SummaryError(f"configuration mismatch for {expected_name}")
    if manifest.get("part") != PART or manifest.get("clock_period_ns") != PERIOD_NS:
        raise SummaryError(f"target or clock mismatch for {expected_name}")
    reports = manifest.get("reports")
    if not isinstance(reports, dict) or set(reports) != {
        "utilization.rpt",
        "timing_summary.rpt",
    }:
        raise SummaryError(f"report manifest mismatch for {expected_name}")
    for filename, expected_hash in reports.items():
        report = directory / filename
        if not report.is_file():
            raise SummaryError(f"missing report for {expected_name}: {filename}")
        if sha256(report) != expected_hash:
            raise SummaryError(f"report hash mismatch for {expected_name}: {filename}")
    return manifest


def summarize(report_dir: Path) -> str:
    expected_names = tuple(config.name for config in CONFIGURATIONS)
    actual_names = tuple(sorted(path.name for path in report_dir.iterdir() if path.is_dir()))
    if set(actual_names) != set(expected_names):
        raise SummaryError(
            f"report configurations do not match: expected {sorted(expected_names)}, found {list(actual_names)}"
        )
    manifests = {
        name: load_manifest(report_dir / name, name) for name in expected_names
    }
    provenance_keys = (
        "source_commit",
        "rtl_commit",
        "measurement_date",
        "tool",
        "tool_version",
        "tool_build",
        "part",
        "clock_period_ns",
    )
    baseline = manifests[expected_names[0]]
    for name, manifest in manifests.items():
        if any(manifest.get(key) != baseline.get(key) for key in provenance_keys):
            raise SummaryError(f"provenance mismatch for {name}")

    rows = []
    for config in CONFIGURATIONS:
        directory = report_dir / config.name
        luts, ffs, bram_tiles, ramb18 = parse_utilization(directory / "utilization.rpt")
        wns = parse_wns(directory / "timing_summary.rpt")
        critical = PERIOD_NS - wns
        if critical <= 0.0:
            raise SummaryError(f"invalid critical path for {config.name}")
        fmax = 1000.0 / critical
        rows.append(
            f"| {config.name} | {luts} | {ffs} | {bram_tiles:g} | {ramb18} | "
            f"{wns:.3f} | {critical:.3f} | {fmax:.3f} |"
        )

    lines = [
        "# Synthesis summary",
        "",
        f"- Measurement date: {baseline['measurement_date']}",
        f"- Source commit: {baseline['source_commit']}",
        f"- RTL commit: {baseline['rtl_commit']}",
        f"- Tool: {baseline['tool']} {baseline['tool_version']} build {baseline['tool_build']}",
        f"- Target: {baseline['part']}",
        f"- Clock constraint: {float(baseline['clock_period_ns']):.3f} ns",
        "",
        "| Configuration | LUT | FF | BRAM tiles | RAMB18 | WNS (ns) | Critical path (ns) | fmax (MHz) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=Path(__file__).parent / "reports")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        output = summarize(args.report_dir.resolve())
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (SummaryError, OSError, TypeError, ValueError) as exc:
        print(f"synthesis summary failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
