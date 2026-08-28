#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


PART = "xc7a35ticsg324-1L"
PERIOD_NS = 2.0
VIVADO_VERSION = "2025.2"
WINDOWS_CANDIDATES = (
    Path("/mnt/c/AMDDesignTools/2025.2/Vivado/bin/vivado.bat"),
    Path("/mnt/c/Xilinx/Vivado/2025.2/bin/vivado.bat"),
)


class SynthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Configuration:
    name: str
    ic_bytes: int
    ic_block: int
    ic_ways: int
    dc_bytes: int
    dc_block: int
    dc_ways: int
    dc_wb: int
    imem_depth: int = 512
    dmem_depth: int = 512

    def tclargs(self) -> tuple[str, ...]:
        return tuple(str(value) for value in asdict(self).values())


CONFIGURATIONS = (
    Configuration("core", 0, 4, 1, 0, 4, 1, 0),
    Configuration("icache", 1024, 4, 4, 0, 4, 1, 0),
    Configuration("dcache-wt", 1024, 4, 4, 4096, 4, 4, 0),
    Configuration("dcache-wb", 1024, 4, 4, 4096, 4, 4, 1),
)


@dataclass(frozen=True)
class VivadoTool:
    launcher: Path
    windows: bool
    version: str
    build: str
    command_launcher: str
    cmd_exe: Path | None = None

    def command(self, arguments: tuple[str, ...]) -> list[str]:
        if self.windows:
            if self.cmd_exe is None:
                raise SynthError("Windows Vivado requires cmd.exe")
            return windows_command(self.cmd_exe, self.command_launcher, arguments)
        return [str(self.launcher), *arguments]


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return False
    return "microsoft" in release.lower()


def select_launcher(
    explicit: str | None,
    native: str | None,
    wsl: bool,
    candidates: tuple[Path, ...] = WINDOWS_CANDIDATES,
) -> tuple[Path, bool]:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise SynthError(f"explicit VIVADO does not exist: {path}")
        return path, path.suffix.lower() == ".bat"
    if native:
        path = Path(native)
        if path.is_file():
            return path, False
    if wsl:
        for path in candidates:
            if path.is_file():
                return path, True
    raise SynthError("Vivado 2025.2 was not found")


def windows_command(cmd_exe: Path, launcher: str, arguments: tuple[str, ...]) -> list[str]:
    return [str(cmd_exe), "/d", "/c", launcher, *arguments]


def command_output(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def wslpath(path: Path, mode: str) -> str:
    result = subprocess.run(
        ["wslpath", mode, str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SynthError(f"wslpath failed for {path}: {result.stderr.strip()}")
    return result.stdout.strip()


def find_cmd() -> Path:
    candidates = (
        shutil.which("cmd.exe"),
        "/mnt/c/Windows/System32/cmd.exe",
        "/mnt/c/windows/system32/cmd.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SynthError("cmd.exe was not found for Windows Vivado")


def windows_temp(cmd_exe: Path) -> Path:
    probe_cwd = Path("/mnt/c/Windows/Temp")
    if not probe_cwd.is_dir():
        raise SynthError("Windows temporary directory is unavailable")
    result = command_output(
        [str(cmd_exe), "/d", "/c", "echo %TEMP%"], probe_cwd, 30
    )
    value = result.stdout.strip().splitlines()
    if result.returncode != 0 or not value:
        raise SynthError(f"failed to resolve Windows TEMP: {result.stderr.strip()}")
    path = Path(wslpath(Path(value[-1].rstrip("\r")), "-u"))
    if not path.is_dir():
        raise SynthError(f"Windows TEMP does not map to a directory: {path}")
    return path


def parse_version(output: str) -> tuple[str, str]:
    version = re.search(r"\bvivado\s+v([0-9]{4}\.[0-9]+)\b", output, re.IGNORECASE)
    build = re.search(r"\bSW Build\s+([0-9]+)", output, re.IGNORECASE)
    if version is None:
        raise SynthError("unable to parse Vivado version")
    if version.group(1) != VIVADO_VERSION:
        raise SynthError(
            f"Vivado {VIVADO_VERSION} is required, found {version.group(1)}"
        )
    return version.group(1), build.group(1) if build else "unknown"


def discover_tool(environment: dict[str, str]) -> tuple[VivadoTool, Path | None]:
    explicit = environment.get("VIVADO", "").strip() or None
    if explicit and os.sep not in explicit and "/" not in explicit and "\\" not in explicit:
        explicit = shutil.which(explicit) or explicit
    launcher, windows = select_launcher(
        explicit,
        shutil.which("vivado"),
        is_wsl(),
    )
    if windows:
        cmd_exe = find_cmd()
        temp = windows_temp(cmd_exe)
        command_launcher = wslpath(launcher, "-w")
        result = command_output(
            windows_command(cmd_exe, command_launcher, ("-version",)), temp, 60
        )
    else:
        cmd_exe = None
        temp = None
        command_launcher = str(launcher)
        result = command_output([str(launcher), "-version"], launcher.parent, 60)
        if result.returncode != 0:
            raise SynthError(f"Vivado version probe failed: {result.stderr.strip()}")
    version, build = parse_version(result.stdout + "\n" + result.stderr)
    return VivadoTool(launcher, windows, version, build, command_launcher, cmd_exe), temp


def validate_image(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SynthError(f"missing memory image: {path}") from exc
    if len(lines) != 512 or any(re.fullmatch(r"[0-9a-fA-F]{8}", line) is None for line in lines):
        raise SynthError(f"memory image must contain 512 32-bit words: {path}")
    if len(set(lines)) < 2:
        raise SynthError(f"memory image must contain varied data: {path}")


def git_output(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SynthError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def source_identity(root: Path, verified_rtl: str | None = None) -> tuple[str, str]:
    source = git_output(root, "rev-parse", "HEAD")
    rtl = verified_rtl or git_output(root, "log", "-1", "--format=%H", "--", "rtl")
    if not re.fullmatch(r"[0-9a-f]{40}", source) or not re.fullmatch(r"[0-9a-f]{40}", rtl):
        raise SynthError("source commit identity is invalid")
    git_output(root, "cat-file", "-e", f"{rtl}^{{commit}}")
    for arguments in (
        ("diff", "--quiet", rtl, source, "--", "rtl"),
        ("diff", "--quiet"),
        ("diff", "--cached", "--quiet"),
    ):
        result = subprocess.run(["git", "-C", str(root), *arguments])
        if result.returncode != 0:
            raise SynthError("tracked source differs from the recorded commits")
    if git_output(root, "status", "--porcelain", "--untracked-files=normal"):
        raise SynthError("source checkout must be clean before synthesis")
    return source, rtl


def create_stage(root: Path, parent: Path | None) -> tempfile.TemporaryDirectory[str]:
    stage = tempfile.TemporaryDirectory(prefix="rv32i-vivado-", dir=parent)
    destination = Path(stage.name)
    (destination / "rtl").mkdir()
    rtl_files = sorted((root / "rtl").rglob("*.sv"))
    if not rtl_files:
        stage.cleanup()
        raise SynthError("no RTL sources found")
    for source in rtl_files:
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for name in ("build.tcl", "cpu.xdc", "blank_instr.hex", "blank_data.hex"):
        source = root / "syn" / name
        if not source.is_file():
            stage.cleanup()
            raise SynthError(f"missing synthesis input: {source}")
        shutil.copy2(source, destination / name)
    return stage


def read_build_meta(path: Path, name: str) -> tuple[str, float]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SynthError(f"build metadata missing for {name}") from exc
    values: dict[str, str] = {}
    for line in lines:
        if line.count("=") != 1:
            raise SynthError(f"malformed build metadata for {name}")
        key, value = line.split("=", 1)
        if key in values:
            raise SynthError(f"duplicate build metadata for {name}: {key}")
        values[key] = value
    if set(values) != {"config", "part", "clock_period_ns"} or values["config"] != name:
        raise SynthError(f"malformed build metadata for {name}")
    try:
        period = float(values["clock_period_ns"])
    except ValueError as exc:
        raise SynthError(f"malformed clock period for {name}") from exc
    return values["part"], period


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_configuration(
    tool: VivadoTool,
    stage: Path,
    output_root: Path,
    config: Configuration,
    source_commit: str,
    rtl_commit: str,
    measurement_date: str,
    timeout: int,
) -> None:
    started = time.time()
    arguments = (
        "-mode",
        "batch",
        "-source",
        "build.tcl",
        "-tclargs",
        *config.tclargs(),
    )
    try:
        result = command_output(tool.command(arguments), stage, timeout)
    except subprocess.TimeoutExpired as exc:
        raise SynthError(f"Vivado timed out for {config.name}") from exc
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise SynthError(f"Vivado failed for {config.name} ({result.returncode}):\n{output}")
    if f"===BUILD_DONE:{config.name}===" not in output:
        raise SynthError(f"completion marker missing for {config.name}")

    route_dir = stage / f"out_{config.name}"
    reports = {
        "utilization.rpt": route_dir / "utilization.rpt",
        "timing_summary.rpt": route_dir / "timing_summary.rpt",
    }
    for filename, path in reports.items():
        description = "utilization report" if filename.startswith("utilization") else "timing report"
        if not path.is_file():
            raise SynthError(f"missing {description} for {config.name}")
        if path.stat().st_mtime < started - 1.0:
            raise SynthError(f"stale {description} for {config.name}")

    part, period = read_build_meta(route_dir / "build_meta.txt", config.name)
    if part != PART:
        raise SynthError(f"wrong applied part for {config.name}: {part}")
    if abs(period - PERIOD_NS) > 0.0001:
        raise SynthError(f"wrong applied clock period for {config.name}: {period}")

    destination = output_root / config.name
    destination.mkdir()
    hashes: dict[str, str] = {}
    for filename, path in reports.items():
        copied = destination / filename
        shutil.copy2(path, copied)
        hashes[filename] = sha256(copied)
    manifest = {
        "schema": 1,
        "status": "complete",
        "configuration": asdict(config),
        "source_commit": source_commit,
        "rtl_commit": rtl_commit,
        "measurement_date": measurement_date,
        "tool": "Vivado",
        "tool_version": tool.version,
        "tool_build": tool.build,
        "launcher": str(tool.launcher),
        "platform": "wsl-windows" if tool.windows else "native",
        "invocation": list(arguments),
        "part": part,
        "clock_period_ns": period,
        "reports": hashes,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{config.name}: route complete")


def replace_report_directory(staged: Path, destination: Path) -> None:
    if destination.exists():
        if not destination.is_dir():
            raise SynthError(f"report destination is not a directory: {destination}")
        shutil.rmtree(destination)
    staged.replace(destination)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--rtl-commit")
    parser.add_argument("--timeout", type=int, default=7200)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    report_dir = (args.report_dir or root / "syn/reports").resolve()
    if args.timeout <= 0:
        print("synthesis failed: timeout must be positive", file=sys.stderr)
        return 1
    try:
        validate_image(root / "syn/blank_instr.hex")
        validate_image(root / "syn/blank_data.hex")
        source_commit, rtl_commit = source_identity(root, args.rtl_commit)
        tool, stage_parent = discover_tool(dict(os.environ))
        measurement_date = datetime.now(timezone.utc).date().isoformat()
        report_dir.parent.mkdir(parents=True, exist_ok=True)
        if report_dir in (Path("/"), root, root / "syn"):
            raise SynthError(f"unsafe report destination: {report_dir}")
        output = Path(tempfile.mkdtemp(prefix=".synth-reports-", dir=report_dir.parent))
        try:
            with create_stage(root, stage_parent) as stage_name:
                stage = Path(stage_name)
                for config in CONFIGURATIONS:
                    run_configuration(
                        tool,
                        stage,
                        output,
                        config,
                        source_commit,
                        rtl_commit,
                        measurement_date,
                        args.timeout,
                    )
            replace_report_directory(output, report_dir)
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise
    except (SynthError, OSError, subprocess.SubprocessError) as exc:
        print(f"synthesis failed: {exc}", file=sys.stderr)
        return 1
    print(f"reports: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
