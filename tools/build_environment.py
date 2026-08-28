#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


class BuildEnvironmentError(RuntimeError):
    pass


def output(command: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            list(command), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=20, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BuildEnvironmentError(f"cannot identify build tool: {command[0]}") from exc
    if result.returncode != 0:
        raise BuildEnvironmentError(f"cannot identify build tool: {command[0]}")
    return result.stdout


def environment_identity() -> str:
    value = {
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "verilator": output(("verilator", "-V")),
        "compiler": output(("c++", "--version")).splitlines()[0],
        "libc": output(("ldd", "--version")).splitlines()[0],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def prepare_build_directory(root: Path, build: Path, identity: str) -> Path:
    root = root.resolve()
    build = build.resolve()
    try:
        relative = build.relative_to(root)
    except ValueError as exc:
        raise BuildEnvironmentError(f"unsafe build directory: {build}") from exc
    if len(relative.parts) != 1 or not relative.name.startswith("obj_dir"):
        raise BuildEnvironmentError(f"unsafe build directory: {build}")
    if re.fullmatch(r"[0-9a-f]{12}", identity) is None:
        raise BuildEnvironmentError("build environment identity is malformed")
    stamp = build / f".environment-{identity}"
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == identity + "\n":
        return stamp
    if build.exists():
        if not build.is_dir():
            raise BuildEnvironmentError(f"build path is not a directory: {build}")
        shutil.rmtree(build)
    build.mkdir()
    stamp.write_text(identity + "\n", encoding="utf-8")
    return stamp


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("identity")
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    prepare.add_argument("--build-dir", type=Path, required=True)
    prepare.add_argument("--identity", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "identity":
            print(environment_identity())
        else:
            build = args.build_dir
            if not build.is_absolute():
                build = args.root / build
            prepare_build_directory(args.root, build, args.identity)
        return 0
    except (BuildEnvironmentError, OSError) as exc:
        print(f"build environment error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
