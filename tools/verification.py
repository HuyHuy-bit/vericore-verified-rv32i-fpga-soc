#!/usr/bin/env python3
"""Run named verification profiles locally or in the pinned container."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

if __package__:
    from .results import ResultError, write_profile_receipt, write_verification_receipt
    from .tool_environment import TOOL_KEYS, load_manifest, validate_manifest
else:
    from results import ResultError, write_profile_receipt, write_verification_receipt
    from tool_environment import TOOL_KEYS, load_manifest, validate_manifest


class VerificationError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    argv: tuple[str, ...]
    timeout: int


MEMORY_CONFIGS = (
    ("baseline", ()),
    ("slow-mem", ("IMEM_LAT=10", "DMEM_LAT=10")),
    ("icache-only", ("IC_BYTES=1024", "IC_WAYS=4", "IMEM_LAT=10", "DMEM_LAT=10")),
    (
        "wt",
        (
            "IC_BYTES=1024", "IC_WAYS=4", "DC_BYTES=4096", "DC_WAYS=4",
            "DC_WB=0", "IMEM_LAT=10", "DMEM_LAT=10",
        ),
    ),
    (
        "wb",
        (
            "IC_BYTES=1024", "IC_WAYS=4", "DC_BYTES=4096", "DC_WAYS=4",
            "DC_WB=1", "IMEM_LAT=10", "DMEM_LAT=10",
        ),
    ),
    (
        "assoc",
        (
            "IC_BYTES=1024", "IC_BLOCK=4", "IC_WAYS=2", "DC_BYTES=4096",
            "DC_BLOCK=4", "DC_WAYS=2", "DC_WB=1", "IMEM_LAT=10", "DMEM_LAT=10",
        ),
    ),
)


def profile_commands() -> dict[str, tuple[Command, ...]]:
    fast = (Command("fast", ("make", "check"), 1800),)
    directed_memory = tuple(
        Command(f"directed-memory-{name}", ("make", "all", *arguments), 1800)
        for name, arguments in MEMORY_CONFIGS
    )
    directed_predictor = (
        Command("directed-predictor", ("make", "predictor-test"), 3600),
    )
    random_python = (
        Command("random-python-baseline", ("make", "soak", "SEEDS=1000"), 3600),
        Command(
            "random-python-cached",
            (
                "make", "soak", "SEEDS=1000", "IC_BYTES=1024", "IC_WAYS=4",
                "DC_BYTES=4096", "DC_WAYS=4", "DC_WB=1", "IMEM_LAT=10", "DMEM_LAT=10",
            ),
            3600,
        ),
    )
    compliance = (Command("compliance", ("make", "compliance"), 3600),)
    lockstep = (Command("lockstep", ("make", "lockstep"), 3600),)
    random_spike = (
        Command("random-spike", ("make", "soak-lockstep", "SEEDS=200"), 3600),
    )
    coverage = (Command("coverage", ("make", "coverage"), 3600),)
    soc = (Command("soc", ("make", "soc-check"), 1800),)
    final_checks = (
        Command("results-check", ("make", "results-check"), 600),
        Command("portfolio-render-check", ("make", "portfolio-render-check"), 600),
        Command("portfolio-check", ("make", "portfolio-check"), 600),
    )
    profiles = {
        "fast": fast,
        "directed-memory": directed_memory,
        "directed-predictor": directed_predictor,
        "random-python": random_python,
        "compliance": compliance,
        "lockstep": lockstep,
        "random-spike": random_spike,
        "coverage": coverage,
        "soc": soc,
        "portfolio": final_checks,
    }
    profiles["full"] = (
        *fast,
        *directed_memory,
        *directed_predictor,
        *random_python,
        *compliance,
        *lockstep,
        *random_spike,
        *coverage,
    )
    return profiles


def commands_for(profile: str, root: Path) -> tuple[Command, ...]:
    del root
    profiles = profile_commands()
    try:
        return profiles[profile]
    except KeyError as exc:
        raise VerificationError(f"unknown verification profile: {profile}") from exc


def run_commands(
    commands: Sequence[Command],
    root: Path,
    environment: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    child_environment = os.environ.copy()
    child_environment.update(environment)
    for command in commands:
        print(f"========== {command.name} ==========", flush=True)
        try:
            result = runner(
                list(command.argv),
                cwd=root,
                env=child_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=command.timeout,
                check=False,
            )
        except FileNotFoundError:
            print(f"verification failed: command not found: {command.argv[0]}", file=sys.stderr)
            return 127
        except subprocess.TimeoutExpired as exc:
            if exc.stdout:
                print(exc.stdout, end="" if str(exc.stdout).endswith("\n") else "\n")
            if exc.stderr:
                print(exc.stderr, file=sys.stderr, end="" if str(exc.stderr).endswith("\n") else "\n")
            print(f"verification failed: {command.name} exceeded {command.timeout}s", file=sys.stderr)
            return 124
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.returncode != 0:
            print(f"verification failed: {command.name} exited {result.returncode}", file=sys.stderr)
            return result.returncode
    return 0


def image_name(values: Mapping[str, str], target: str) -> str:
    return f"{values['VERIFY_IMAGE']}:{values['VERIFY_IMAGE_REVISION']}-{target}"


def build_image_command(root: Path, target: str = "verify") -> tuple[str, ...]:
    if target not in ("verify", "demo"):
        raise VerificationError(f"unknown container target: {target}")
    values = load_manifest(root / "tools" / "tool_versions.env")
    errors = validate_manifest(values)
    if errors:
        raise VerificationError("; ".join(errors))
    build_keys = tuple(key for key in TOOL_KEYS if key != "VERIFY_IMAGE")
    arguments: list[str] = [
        "docker", "build", "--target", target,
        "--file", "containers/verify/Dockerfile",
        "--tag", image_name(values, target),
    ]
    for key in build_keys:
        arguments.extend(("--build-arg", f"{key}={values[key]}"))
    arguments.append(str(root.resolve()))
    return tuple(arguments)


def docker_run_command(
    root: Path,
    profile: str,
    target: str = "verify",
    uid: int | None = None,
    gid: int | None = None,
    receipt: Path | None = None,
    command: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    commands_for(profile, root)
    values = load_manifest(root / "tools" / "tool_versions.env")
    cache = root.resolve() / ".verify-cache"
    user_id = os.getuid() if uid is None else uid
    group_id = os.getgid() if gid is None else gid
    invocation = (
        "docker", "run", "--rm",
        "--env", f"HOST_UID={user_id}",
        "--env", f"HOST_GID={group_id}",
        "--env", "ARCH_TEST=/opt/rv32i-cache/riscv-arch-test",
        "--env", "SPIKE=/opt/rv32i-cache/riscv-isa-sim/build/spike",
        "--env", "REFERENCE_CACHE=/opt/rv32i-cache",
        "--volume", f"{root.resolve()}:/work",
        "--volume", f"{cache}:/opt/rv32i-cache",
        "--workdir", "/work",
        image_name(values, target),
    )
    if command is not None:
        if not command:
            raise VerificationError("container command must not be empty")
        return invocation + command
    invocation += (
        "python3", "tools/verification.py", "run",
        "--profile", profile,
        "--inside-container", "1",
    )
    if receipt is not None:
        invocation += ("--receipt", str(receipt))
    return invocation


def invoke(command: Sequence[str], root: Path, timeout: int) -> int:
    return run_commands((Command("container", tuple(command), timeout),), root, {})


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "container", "image"))
    parser.add_argument("--profile", default="full")
    parser.add_argument("--target", choices=("verify", "demo"), default="verify")
    parser.add_argument("--inside-container", choices=("0", "1"), default="0")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.mode == "run":
            if args.receipt is not None and args.profile not in {"full", "soc"}:
                raise VerificationError("verification receipts require the full or soc profile")
            receipt = args.receipt
            if receipt is not None and not receipt.is_absolute():
                receipt = root / receipt
            if receipt is not None:
                receipt.unlink(missing_ok=True)
            if args.inside_container == "1":
                status = run_commands(
                    (
                        Command("clean-workspace", ("make", "clean"), 300),
                        Command("prepare-references", ("python3", "tools/prepare_references.py"), 7200),
                    ),
                    root,
                    {},
                )
                if status != 0:
                    return status
            status = run_commands(commands_for(args.profile, root), root, {})
            if status == 0 and receipt is not None:
                if args.profile == "full":
                    write_verification_receipt(root, receipt)
                else:
                    write_profile_receipt(root, receipt, args.profile)
                print(f"wrote verification receipt: {receipt}")
            return status
        if args.command is not None and args.mode != "container":
            raise VerificationError("explicit commands require container mode")
        if args.receipt is not None and args.command is not None:
            raise VerificationError("explicit commands cannot produce verification receipts")
        if args.receipt is not None and args.mode == "image":
            raise VerificationError("image builds do not produce verification receipts")
        build = build_image_command(root, args.target)
        if invoke(build, root, 7200) != 0:
            return 1
        if args.mode == "image":
            return 0
        (root / ".verify-cache").mkdir(exist_ok=True)
        return invoke(
            docker_run_command(
                root, args.profile, args.target, receipt=args.receipt,
                command=tuple(args.command) if args.command is not None else None,
            ),
            root,
            86400,
        )
    except (OSError, ResultError, VerificationError, ValueError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
