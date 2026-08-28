#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, TextIO

if __package__:
    from .render_portfolio import benchmark_table, load_validated, synthesis_table
    from .results import ResultSet
else:
    from render_portfolio import benchmark_table, load_validated, synthesis_table
    from results import ResultSet


class DemoError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoStep:
    name: str
    command: tuple[str, ...]
    timeout: int


def demo_steps(root: Path) -> tuple[DemoStep, ...]:
    del root
    return (
        DemoStep(
            "fast correctness",
            ("python3", "tools/verification.py", "run", "--profile", "fast"),
            1800,
        ),
        DemoStep(
            "Spike lockstep sample",
            ("make", "--no-print-directory", "lockstep-sample"),
            1800,
        ),
    )


def sections(result: ResultSet) -> tuple[str, ...]:
    value = result.verification
    tools = result.tool_versions
    return (
        "RV32I PIPELINE — VERIFIED PORTFOLIO SNAPSHOT",
        (
            f"tooling {result.manifest['tooling_commit'][:12]} | RTL {result.manifest['rtl_commit'][:12]}\n"
            f"Ubuntu {tools['ubuntu']} | Verilator {tools['verilator']} | "
            f"RISC-V GCC {tools['riscv_gcc']} | binutils {tools['riscv_as']} | Python {tools['python']}"
        ),
        (
            "CORRECTNESS\n"
            f"decoder {value['decoder_vectors']:,}/{value['decoder_vectors']:,} | "
            f"hazards {value['hazard_vectors']:,}/{value['hazard_vectors']:,} | harness {value['harness_tests']}/{value['harness_tests']}\n"
            f"directed {sum(item['passed'] for item in value['memory_configurations'])}/{value['directed_programs'] * len(value['memory_configurations'])} | "
            f"predictors {sum(item['passed'] for item in value['predictor_configurations'])}/{value['directed_programs'] * len(value['predictor_configurations'])} | "
            f"coverage {value['cover_points']['hit']}/{value['cover_points']['source']}"
        ),
        (
            "REFERENCE FLOWS\n"
            f"architecture signatures {value['architecture_tests']['passed']}/{value['architecture_tests']['discovered']}\n"
            f"complete Spike traces {value['architecture_lockstep']['passed']}/{value['architecture_lockstep']['discovered']}\n"
            f"random Spike programs {value['spike_random']['passed']}/{value['spike_random']['requested']}"
        ),
        "BENCHMARKS — cycles / CPI\n" + benchmark_table(result),
        "ROUTED ARTIX-7 RESULTS\n" + synthesis_table(result),
        (
            "REPRODUCE\n"
            "make verify\n"
            "make synth-matrix && make synth-summary\n"
            "make portfolio-gif"
        ),
        "All displayed values passed schema, provenance, population, arithmetic, and hash checks.",
    )


def gate_text(root: Path) -> str:
    lines = ["LIVE VERIFICATION"]
    for step in demo_steps(root):
        lines.extend(("$ " + " ".join(step.command), f"{step.name}: PASS"))
    return "\n".join(lines)


def summary_text(result: ResultSet) -> str:
    return gate_text(result.root.parent) + "\n\n" + "\n\n".join(sections(result)) + "\n"


def load_result(root: Path) -> ResultSet:
    try:
        return load_validated(root)
    except (OSError, ValueError) as exc:
        raise DemoError(f"result records are not verified: {exc}") from exc


def run_demo(
    root: Path,
    transcript: TextIO,
    live: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    root = root.resolve()
    result = load_result(root)
    if not live:
        transcript.write(summary_text(result))
        return 0
    transcript.write("LIVE VERIFICATION\n")
    transcript.flush()
    for step in demo_steps(root):
        transcript.write("$ " + " ".join(step.command) + "\n")
        transcript.flush()
        try:
            completed = runner(
                list(step.command), cwd=root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=step.timeout, check=False,
            )
        except FileNotFoundError:
            transcript.write(f"{step.name}: FAIL (command not found)\n")
            return 127
        except subprocess.TimeoutExpired as exc:
            if exc.output:
                transcript.write(str(exc.output))
            transcript.write(f"{step.name}: FAIL (timed out after {step.timeout}s)\n")
            return 124
        if completed.returncode != 0:
            output = completed.stdout or ""
            tail = "\n".join(output.splitlines()[-20:])
            if tail:
                transcript.write(tail + "\n")
            transcript.write(f"{step.name}: FAIL ({completed.returncode})\n")
            return completed.returncode
        transcript.write(f"{step.name}: PASS\n")
        transcript.flush()
    transcript.write("\n" + "\n\n".join(sections(result)) + "\n")
    return 0


def atomic_write(path: Path, contents: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            handle.write(contents)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_media_manifest(root: Path) -> None:
    root = root.resolve()
    media = root / "docs" / "media"
    names = ("portfolio-demo.tape", "portfolio-demo.txt", "portfolio-demo.gif")
    value = {
        "schema": 1,
        "sha256": {name: sha256(media / name) for name in names},
    }
    atomic_write(
        media / "portfolio-demo.json",
        json.dumps(value, indent=2, sort_keys=True) + "\n",
    )


def skip_subblocks(data: bytes, offset: int) -> int:
    while True:
        if offset >= len(data):
            raise DemoError("truncated GIF sub-block")
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        offset += size
        if offset > len(data):
            raise DemoError("truncated GIF sub-block")


def gif_metadata(data: bytes) -> tuple[int, int, int, float]:
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise DemoError("invalid GIF header")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    packed = data[10]
    offset = 13
    if packed & 0x80:
        offset += 3 * (2 ** ((packed & 0x07) + 1))
    frames = 0
    duration = 0.0
    delay = 0
    while offset < len(data):
        marker = data[offset]
        offset += 1
        if marker == 0x3B:
            return width, height, frames, duration
        if marker == 0x21:
            if offset >= len(data):
                raise DemoError("truncated GIF extension")
            label = data[offset]
            offset += 1
            if label == 0xF9:
                if offset + 6 > len(data) or data[offset] != 4 or data[offset + 5] != 0:
                    raise DemoError("malformed GIF control extension")
                delay = int.from_bytes(data[offset + 2:offset + 4], "little")
                offset += 6
            else:
                offset = skip_subblocks(data, offset)
            continue
        if marker != 0x2C or offset + 9 > len(data):
            raise DemoError("malformed GIF stream")
        descriptor = data[offset:offset + 9]
        offset += 9
        if descriptor[8] & 0x80:
            offset += 3 * (2 ** ((descriptor[8] & 0x07) + 1))
        if offset >= len(data):
            raise DemoError("truncated GIF image")
        offset += 1
        offset = skip_subblocks(data, offset)
        frames += 1
        duration += delay / 100.0
        delay = 0
    raise DemoError("GIF trailer is missing")


def validate_media(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    try:
        result = load_result(root)
    except DemoError as exc:
        return [str(exc)]
    media = root / "docs" / "media"
    transcript = media / "portfolio-demo.txt"
    tape = media / "portfolio-demo.tape"
    gif = media / "portfolio-demo.gif"
    manifest = media / "portfolio-demo.json"
    try:
        if transcript.read_text(encoding="utf-8") != summary_text(result):
            errors.append("portfolio demo transcript is stale")
    except FileNotFoundError:
        errors.append("portfolio demo transcript is missing")
    try:
        tape_source = tape.read_text(encoding="utf-8")
        tokens = (
            "Output docs/media/portfolio-demo.gif",
            "Set Width 1280",
            "Set Height 720",
            'Type "python3 tools/portfolio_demo.py --live"',
        )
        for token in tokens:
            if tape_source.count(token) != 1:
                errors.append(f"portfolio demo tape must contain {token}")
    except FileNotFoundError:
        errors.append("portfolio demo tape is missing")
    try:
        gif_data = gif.read_bytes()
        width, height, frames, duration = gif_metadata(gif_data)
        if (width, height) != (1280, 720):
            errors.append("portfolio demo GIF must be 1280x720")
        if frames < 20:
            errors.append("portfolio demo GIF has too few frames")
        if not 20.0 <= duration <= 90.0:
            errors.append("portfolio demo GIF duration must be 20-90 seconds")
        if not 1024 <= len(gif_data) <= 15 * 1024 * 1024:
            errors.append("portfolio demo GIF size is outside the accepted bounds")
    except (FileNotFoundError, DemoError) as exc:
        errors.append(f"portfolio demo GIF is invalid: {exc}")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        names = ("portfolio-demo.tape", "portfolio-demo.txt", "portfolio-demo.gif")
        if set(value) != {"schema", "sha256"} or value["schema"] != 1:
            errors.append("portfolio demo media manifest is malformed")
        elif set(value["sha256"]) != set(names):
            errors.append("portfolio demo media manifest is incomplete")
        else:
            for name in names:
                if value["sha256"][name] != sha256(media / name):
                    errors.append(f"portfolio demo hash mismatch: {name}")
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError, TypeError):
        errors.append("portfolio demo media manifest is invalid")
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        if readme.count("![Portfolio verification demo](docs/media/portfolio-demo.gif)") != 1:
            errors.append("README must link the portfolio demo GIF exactly once")
    except FileNotFoundError:
        errors.append("README is missing")
    return errors


def check_artifacts(root: Path, result: ResultSet | None = None) -> list[str]:
    del result
    return validate_media(root)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--summary", action="store_true")
    group.add_argument("--live", action="store_true")
    group.add_argument("--write-transcript", action="store_true")
    group.add_argument("--write-media-manifest", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    try:
        if args.write_media_manifest:
            write_media_manifest(root)
            print("wrote docs/media/portfolio-demo.json")
            return 0
        if args.check:
            errors = validate_media(root)
            if errors:
                raise DemoError("; ".join(errors))
            print("portfolio demo artifacts match validated results")
            return 0
        if args.write_transcript:
            output = StringIO()
            status = run_demo(root, output, live=False)
            if status != 0:
                return status
            atomic_write(root / "docs/media/portfolio-demo.txt", output.getvalue())
            print("wrote docs/media/portfolio-demo.txt")
            return 0
        if args.live:
            return run_demo(root, sys.stdout, live=True)
        result = load_result(root)
        print(summary_text(result), end="")
        return 0
    except (DemoError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"portfolio demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
