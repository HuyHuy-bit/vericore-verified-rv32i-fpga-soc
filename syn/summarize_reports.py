#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile

if __package__:
    from .run_synth import CONFIGURATIONS, PART, PERIOD_NS
else:
    from run_synth import CONFIGURATIONS, PART, PERIOD_NS

SYNTHESIS_FIELDS = (
    "schema", "tooling_commit", "rtl_commit", "measurement_date", "configuration",
    "imem_words", "dmem_words", "icache_bytes", "icache_block_words", "icache_ways",
    "dcache_bytes", "dcache_block_words", "dcache_ways", "dcache_policy",
    "vivado_version", "vivado_build", "platform", "part", "clock_period_ns", "lut",
    "ff", "bram_tiles", "ramb18", "wns_ns", "critical_path_ns", "fmax_mhz",
    "utilization_sha256", "timing_sha256",
)


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


def collect_rows(report_dir: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
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

    rows: list[dict[str, object]] = []
    for config in CONFIGURATIONS:
        directory = report_dir / config.name
        luts, ffs, bram_tiles, ramb18 = parse_utilization(directory / "utilization.rpt")
        wns = parse_wns(directory / "timing_summary.rpt")
        critical = PERIOD_NS - wns
        if critical <= 0.0:
            raise SummaryError(f"invalid critical path for {config.name}")
        fmax = 1000.0 / critical
        rows.append({
            "schema": 1,
            "tooling_commit": baseline["source_commit"],
            "rtl_commit": baseline["rtl_commit"],
            "measurement_date": baseline["measurement_date"],
            "configuration": config.name,
            "imem_words": config.imem_depth,
            "dmem_words": config.dmem_depth,
            "icache_bytes": config.ic_bytes,
            "icache_block_words": config.ic_block,
            "icache_ways": config.ic_ways,
            "dcache_bytes": config.dc_bytes,
            "dcache_block_words": config.dc_block,
            "dcache_ways": config.dc_ways,
            "dcache_policy": "none" if config.dc_bytes == 0 else ("write-back" if config.dc_wb else "write-through"),
            "vivado_version": baseline["tool_version"],
            "vivado_build": baseline["tool_build"],
            "platform": baseline["platform"],
            "part": baseline["part"],
            "clock_period_ns": f"{float(baseline['clock_period_ns']):.3f}",
            "lut": luts,
            "ff": ffs,
            "bram_tiles": f"{bram_tiles:.1f}",
            "ramb18": ramb18,
            "wns_ns": f"{wns:.3f}",
            "critical_path_ns": f"{critical:.3f}",
            "fmax_mhz": f"{fmax:.3f}",
            "utilization_sha256": manifests[config.name]["reports"]["utilization.rpt"],
            "timing_sha256": manifests[config.name]["reports"]["timing_summary.rpt"],
        })
    return baseline, rows


def summarize(report_dir: Path) -> str:
    baseline, records = collect_rows(report_dir)
    rows = [
        f"| {row['configuration']} | {row['lut']} | {row['ff']} | {float(str(row['bram_tiles'])):g} | "
        f"{row['ramb18']} | {row['wns_ns']} | {row['critical_path_ns']} | {row['fmax_mhz']} |"
        for row in records
    ]

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


def csv_summary(report_dir: Path) -> str:
    _, rows = collect_rows(report_dir)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=SYNTHESIS_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            handle.write(contents)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=Path(__file__).parent / "reports")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--csv", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        output = summarize(args.report_dir.resolve())
        if args.output:
            atomic_write(args.output, output)
        if args.csv:
            atomic_write(args.csv, csv_summary(args.report_dir.resolve()))
        if not args.output and not args.csv:
            print(output, end="")
    except (SummaryError, OSError, TypeError, ValueError) as exc:
        print(f"synthesis summary failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
