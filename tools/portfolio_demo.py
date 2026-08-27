#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if __package__:
    from .render_portfolio import benchmark_table, load_validated, synthesis_table
    from .results import ResultSet
else:
    from render_portfolio import benchmark_table, load_validated, synthesis_table
    from results import ResultSet


class DemoError(RuntimeError):
    pass


def sections(result: ResultSet) -> tuple[str, ...]:
    value = result.verification
    tools = result.tool_versions
    return (
        "RV32I PIPELINE — VERIFIED PORTFOLIO SNAPSHOT",
        (
            f"tooling {result.manifest['tooling_commit'][:12]} | RTL {result.manifest['rtl_commit'][:12]}\n"
            f"Ubuntu {tools['ubuntu']} | Verilator {tools['verilator']} | RISC-V GCC {tools['riscv_gcc']} | Python {tools['python']}"
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
        "All displayed values passed schema, provenance, population, arithmetic, and hash checks.",
    )


def summary_text(result: ResultSet) -> str:
    return "\n\n".join(sections(result)) + "\n"


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


def run_gate(root: Path, name: str, command: tuple[str, ...], timeout: int) -> None:
    print(f"running {name}...", flush=True)
    result = subprocess.run(
        list(command), cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-30:])
        raise DemoError(f"{name} failed ({result.returncode}):\n{tail}")
    print(f"{name}: PASS", flush=True)


def check_artifacts(root: Path, result: ResultSet) -> list[str]:
    errors = []
    transcript = root / "docs/portfolio-demo.txt"
    try:
        if transcript.read_text(encoding="utf-8") != summary_text(result):
            errors.append("portfolio demo transcript is stale")
    except FileNotFoundError:
        errors.append("portfolio demo transcript is missing")
    tape = root / "docs/portfolio-demo.tape"
    try:
        source = tape.read_text(encoding="utf-8")
        for token in ("Output docs/portfolio-demo.gif", "python3 tools/portfolio_demo.py --paced"):
            if source.count(token) != 1:
                errors.append(f"portfolio demo tape must contain {token}")
    except FileNotFoundError:
        errors.append("portfolio demo tape is missing")
    gif = root / "docs/portfolio-demo.gif"
    try:
        data = gif.read_bytes()
        if len(data) < 1024 or data[:6] not in (b"GIF87a", b"GIF89a"):
            errors.append("portfolio demo GIF is invalid")
    except FileNotFoundError:
        errors.append("portfolio demo GIF is missing")
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--summary", action="store_true")
    group.add_argument("--paced", action="store_true")
    group.add_argument("--live", action="store_true")
    group.add_argument("--write-transcript", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    try:
        result = load_validated(root)
        if args.live:
            run_gate(root, "fast correctness", ("make", "check"), 1800)
            run_gate(root, "Spike architecture lockstep", ("make", "lockstep"), 3600)
        if args.write_transcript:
            atomic_write(root / "docs/portfolio-demo.txt", summary_text(result))
            print("wrote docs/portfolio-demo.txt")
            return 0
        if args.check:
            errors = check_artifacts(root, result)
            if errors:
                raise DemoError("; ".join(errors))
            print("portfolio demo artifacts match validated results")
            return 0
        if args.paced:
            for section in sections(result):
                print(section, flush=True)
                print(flush=True)
                time.sleep(1.25)
        else:
            print(summary_text(result), end="")
        return 0
    except (DemoError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"portfolio demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
