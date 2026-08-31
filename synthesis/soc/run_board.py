#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from synthesis.run_synth import (
    SynthError,
    VivadoTool,
    command_output,
    discover_tool,
    sha256,
    source_identity,
    wslpath,
)


PART = "xc7a35ticsg324-1L"
INPUT_PERIOD_NS = 10.0
SOC_PERIOD_NS = 20.0
IMAGE_WORDS = 8192
BUILD_MARKER = "===SOC_BUILD_DONE==="
PROGRAM_MARKER = "===SOC_PROGRAM_DONE==="
PUBLISHED_FILES = {
    "drc.rpt",
    "manifest.json",
    "rv32i-soc-arty-a7-35t.bit",
    "timing_summary.rpt",
    "utilization.rpt",
}


class BoardError(RuntimeError):
    pass


@dataclass(frozen=True)
class BoardArtifacts:
    bitstream: Path
    utilization: Path
    timing: Path
    drc: Path
    metadata: Path


def validate_firmware_image(path: Path) -> str:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, UnicodeError) as exc:
        raise BoardError(f"invalid firmware image {path}: {exc}") from exc
    if len(lines) != IMAGE_WORDS or any(
        re.fullmatch(r"[0-9a-f]{8}", line) is None for line in lines
    ):
        raise BoardError(
            f"firmware image must contain exactly {IMAGE_WORDS} lowercase "
            f"32-bit words: {path}"
        )
    return sha256(path)


def create_board_stage(
    root: Path,
    parent: Path | None,
    imem: Path,
    dmem: Path,
) -> tempfile.TemporaryDirectory[str]:
    stage = tempfile.TemporaryDirectory(prefix="rv32i-soc-board-", dir=parent)
    destination = Path(stage.name)
    try:
        rtl_files = sorted((root / "rtl").rglob("*.sv"))
        if not rtl_files:
            raise BoardError("no RTL sources found")
        for source in rtl_files:
            target = destination / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for relative in (
            Path("boards/arty_a7_35t.xdc"),
            Path("synthesis/soc/build.tcl"),
            Path("synthesis/soc/program.tcl"),
        ):
            source = root / relative
            if not source.is_file():
                raise BoardError(f"missing board input: {source}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(imem, destination / "firmware-imem.hex")
        shutil.copy2(dmem, destination / "firmware-dmem.hex")
    except Exception:
        stage.cleanup()
        raise
    return stage


def read_build_metadata(path: Path) -> tuple[str, float, float, float, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise BoardError("build metadata is missing") from exc
    values: dict[str, str] = {}
    for line in lines:
        if line.count("=") != 1:
            raise BoardError("build metadata is malformed")
        key, value = line.split("=", 1)
        if key in values:
            raise BoardError(f"build metadata duplicates {key}")
        values[key] = value
    if set(values) != {
        "part", "input_clock_period_ns", "soc_clock_period_ns", "wns_ns", "top"
    }:
        raise BoardError("build metadata is malformed")
    try:
        input_period = float(values["input_clock_period_ns"])
        soc_period = float(values["soc_clock_period_ns"])
        wns = float(values["wns_ns"])
    except ValueError as exc:
        raise BoardError("build timing metadata is malformed") from exc
    return values["part"], input_period, soc_period, wns, values["top"]


def validate_timing_constraints(report: str) -> None:
    counts: dict[str, list[int]] = {}
    for name in ("no_clock", "unconstrained_internal_endpoints"):
        counts[name] = [
            int(value)
            for value in re.findall(
                rf"^\s*(?:[0-9]+\.\s+)?checking\s+{name}\s+\(([0-9]+)\)\s*$",
                report,
                re.IGNORECASE | re.MULTILINE,
            )
        ]
    if any(not values for values in counts.values()):
        raise BoardError("timing constraint checks are missing")
    if any(counts["no_clock"]):
        raise BoardError("unclocked timing endpoint reported")
    if any(counts["unconstrained_internal_endpoints"]):
        raise BoardError("unconstrained timing endpoint reported")


def validate_artifacts(directory: Path, started: float) -> tuple[BoardArtifacts, float]:
    artifacts = BoardArtifacts(
        bitstream=directory / "rv32i-soc-arty-a7-35t.bit",
        utilization=directory / "utilization.rpt",
        timing=directory / "timing_summary.rpt",
        drc=directory / "drc.rpt",
        metadata=directory / "build_meta.txt",
    )
    labels = {
        artifacts.bitstream: "bitstream",
        artifacts.utilization: "utilization report",
        artifacts.timing: "timing report",
        artifacts.drc: "DRC report",
        artifacts.metadata: "build metadata",
    }
    for path, label in labels.items():
        if not path.is_file():
            raise BoardError(f"{label} is missing")
        if path.stat().st_mtime < started - 1.0:
            raise BoardError(f"{label} is stale")
    part, input_period, soc_period, wns, top = read_build_metadata(artifacts.metadata)
    if part != PART:
        raise BoardError(f"wrong applied part: {part}")
    if abs(input_period - INPUT_PERIOD_NS) > 0.0001:
        raise BoardError(f"wrong applied input clock period: {input_period}")
    if abs(soc_period - SOC_PERIOD_NS) > 0.0001:
        raise BoardError(f"wrong applied SoC clock period: {soc_period}")
    if wns < 0.0:
        raise BoardError(f"negative WNS: {wns}")
    if top != "arty_a7_35t_top":
        raise BoardError(f"wrong applied top: {top}")
    timing = artifacts.timing.read_text(encoding="utf-8", errors="replace")
    validate_timing_constraints(timing)
    drc = artifacts.drc.read_text(encoding="utf-8", errors="replace")
    if re.search(r"\b(?:CRITICAL WARNING|ERROR)\b", drc, re.IGNORECASE):
        raise BoardError("DRC contains a critical warning or error")
    return artifacts, wns


def replace_directory(staged: Path, destination: Path) -> None:
    backup = destination.parent / f".{destination.name}-backup-{uuid.uuid4().hex}"
    moved_old = False
    try:
        if destination.exists():
            if not destination.is_dir():
                raise BoardError(f"board output is not a directory: {destination}")
            os.replace(destination, backup)
            moved_old = True
        os.replace(staged, destination)
    except Exception:
        if moved_old and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if moved_old:
        shutil.rmtree(backup)


def validate_output_destination(path: Path) -> None:
    if path.is_symlink():
        raise BoardError(f"board output cannot be a symbolic link: {path}")
    if not path.exists():
        return
    if not path.is_dir():
        raise BoardError(f"board output is not a directory: {path}")
    children = tuple(path.iterdir())
    entries = {entry.name for entry in children}
    if entries != PUBLISHED_FILES or any(
        entry.is_symlink() or not entry.is_file() for entry in children
    ):
        raise BoardError("existing board output has unexpected entries")


def run_vivado(
    tool: VivadoTool,
    arguments: tuple[str, ...],
    cwd: Path,
    timeout: int,
    operation: str,
) -> str:
    try:
        result = command_output(tool.command(arguments), cwd, timeout)
    except subprocess.TimeoutExpired as exc:
        raise BoardError(f"Vivado {operation} timed out") from exc
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise BoardError(
            f"Vivado {operation} failed ({result.returncode}):\n{output}"
        )
    return output


def run_build(
    root: Path,
    output: Path,
    imem: Path,
    dmem: Path,
    rtl_commit: str | None,
    timeout: int,
) -> None:
    if timeout <= 0:
        raise BoardError("timeout must be positive")
    root = root.resolve()
    validate_output_destination(output)
    output = output.resolve()
    imem = imem.resolve()
    dmem = dmem.resolve()
    if output in (Path("/"), root, root / "synthesis", root / "build"):
        raise BoardError(f"unsafe board output: {output}")
    imem_hash = validate_firmware_image(imem)
    dmem_hash = validate_firmware_image(dmem)
    source_commit, verified_rtl = source_identity(root, rtl_commit)
    tool, stage_parent = discover_tool(dict(os.environ))
    output.parent.mkdir(parents=True, exist_ok=True)

    with create_board_stage(root, stage_parent, imem, dmem) as stage_name:
        stage = Path(stage_name)
        route = stage / "board-out"
        arguments = (
            "-mode",
            "batch",
            "-source",
            "synthesis/soc/build.tcl",
            "-tclargs",
            "board-out",
            "firmware-imem.hex",
            "firmware-dmem.hex",
        )
        started = time.time()
        console = run_vivado(tool, arguments, stage, timeout, "build")
        if BUILD_MARKER not in console:
            raise BoardError("build completion marker missing")
        artifacts, wns = validate_artifacts(route, started)
        publish = Path(
            tempfile.mkdtemp(prefix=".soc-board-", dir=output.parent)
        )
        try:
            copied = {
                "bitstream": publish / artifacts.bitstream.name,
                "utilization": publish / artifacts.utilization.name,
                "timing": publish / artifacts.timing.name,
                "drc": publish / artifacts.drc.name,
            }
            shutil.copy2(artifacts.bitstream, copied["bitstream"])
            shutil.copy2(artifacts.utilization, copied["utilization"])
            shutil.copy2(artifacts.timing, copied["timing"])
            shutil.copy2(artifacts.drc, copied["drc"])
            manifest = {
                "schema": 1,
                "status": "complete",
                "measured_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "source_commit": source_commit,
                "rtl_commit": verified_rtl,
                "part": PART,
                "top": "arty_a7_35t_top",
                "input_clock_period_ns": INPUT_PERIOD_NS,
                "soc_clock_period_ns": SOC_PERIOD_NS,
                "wns_ns": wns,
                "firmware": {"imem_sha256": imem_hash, "dmem_sha256": dmem_hash},
                "xdc_sha256": sha256(root / "boards/arty_a7_35t.xdc"),
                "vivado": {
                    "version": tool.version,
                    "build": tool.build,
                    "platform": "wsl-windows" if tool.windows else "native",
                    "launcher": str(tool.launcher),
                },
                "invocation": list(arguments),
                "outputs": {
                    name: sha256(path) for name, path in copied.items()
                },
            }
            (publish / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            replace_directory(publish, output)
        except Exception:
            shutil.rmtree(publish, ignore_errors=True)
            raise


def run_program(root: Path, bitstream: Path, timeout: int) -> None:
    if timeout <= 0:
        raise BoardError("timeout must be positive")
    root = root.resolve()
    bitstream = bitstream.resolve()
    if not bitstream.is_file():
        raise BoardError(f"bitstream does not exist: {bitstream}")
    if bitstream.suffix.lower() != ".bit":
        raise BoardError("bitstream must use the .bit extension")
    script = root / "synthesis/soc/program.tcl"
    if not script.is_file():
        raise BoardError(f"programming script does not exist: {script}")
    tool, stage_parent = discover_tool(dict(os.environ))
    with tempfile.TemporaryDirectory(
        prefix="rv32i-soc-program-", dir=stage_parent
    ) as stage_name:
        stage = Path(stage_name)
        shutil.copy2(script, stage / "program.tcl")
        shutil.copy2(bitstream, stage / "image.bit")
        arguments = (
            "-mode",
            "batch",
            "-source",
            "program.tcl",
            "-tclargs",
            wslpath(stage / "image.bit", "-w")
            if tool.windows else str((stage / "image.bit").resolve()),
        )
        console = run_vivado(tool, arguments, stage, timeout, "programming")
        if PROGRAM_MARKER not in console:
            raise BoardError("program completion marker missing")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    build.add_argument("--imem", type=Path, required=True)
    build.add_argument("--dmem", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--rtl-commit")
    build.add_argument("--timeout", type=int, default=7200)

    program = subparsers.add_parser("program")
    program.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    program.add_argument("--bitstream", type=Path, required=True)
    program.add_argument("--timeout", type=int, default=600)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "build":
            run_build(
                args.root,
                args.output,
                args.imem,
                args.dmem,
                args.rtl_commit,
                args.timeout,
            )
            print(f"board artifacts: {args.output.resolve()}")
        else:
            run_program(args.root, args.bitstream, args.timeout)
            print(f"programmed: {args.bitstream.resolve()}")
    except (BoardError, SynthError, OSError, subprocess.SubprocessError) as exc:
        print(f"board flow failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
