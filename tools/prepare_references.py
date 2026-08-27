#!/usr/bin/env python3

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ARCH_UPSTREAM = "https://github.com/riscv-non-isa/riscv-arch-test.git"
SPIKE_UPSTREAM = "https://github.com/riscv-software-src/riscv-isa-sim.git"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class ReferenceError(RuntimeError):
    pass


def run(cwd: Path, *argv: str) -> str:
    result = subprocess.run(
        list(argv), cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        raise ReferenceError(f"{' '.join(argv)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def require_cached(path: Path, cache_root: Path) -> Path:
    cache = cache_root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(cache)
    except ValueError as exc:
        raise ReferenceError(f"path is outside reference cache: {path}") from exc
    if resolved == cache:
        raise ReferenceError("reference target cannot be the cache root")
    return resolved


def prepare_checkout(target: Path, upstream: str, commit: str, cache_root: Path) -> None:
    if SHA_RE.fullmatch(commit) is None:
        raise ReferenceError("reference identity must be a canonical commit")
    target = require_cached(target, cache_root)
    if target.exists() and (not target.is_dir() or target.is_symlink()):
        raise ReferenceError(f"reference target is not a normal directory: {target}")
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").is_dir():
        run(target, "git", "init", "-q")
    remotes = run(target, "git", "remote").splitlines()
    if "origin" in remotes:
        run(target, "git", "remote", "set-url", "origin", upstream)
    else:
        run(target, "git", "remote", "add", "origin", upstream)
    run(target, "git", "fetch", "-q", "--depth", "1", "origin", commit)
    run(target, "git", "checkout", "-q", "--detach", commit)
    run(target, "git", "reset", "-q", "--hard", commit)
    run(target, "git", "clean", "-q", "-ffd")
    if run(target, "git", "rev-parse", "HEAD") != commit:
        raise ReferenceError(f"reference checkout did not resolve to {commit}")
    symbolic = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=target,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if symbolic.returncode == 0:
        raise ReferenceError("reference checkout is not detached")
    if run(target, "git", "status", "--short", "--untracked-files=all"):
        raise ReferenceError("reference checkout is not clean")


def prepare_spike(repo: Path, commit: str, cache_root: Path) -> None:
    repo = require_cached(repo, cache_root)
    build = require_cached(repo / "build", cache_root)
    binary = build / "spike"
    stamp = build / ".source-sha"
    if binary.is_file() and os.access(binary, os.X_OK) and stamp.is_file():
        if stamp.read_text(encoding="utf-8").strip() == commit:
            return
    if build.exists():
        if not build.is_dir() or build.is_symlink():
            raise ReferenceError(f"Spike build path is not a normal directory: {build}")
        shutil.rmtree(build)
    build.mkdir()
    run(build, "../configure")
    run(build, "make", f"-j{os.cpu_count() or 1}")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ReferenceError("Spike build did not produce an executable")
    stamp.write_text(commit + "\n", encoding="utf-8")


def load_versions(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ReferenceError(f"malformed reference metadata at line {number}")
        key, value = line.split("=", 1)
        if key in values or not value:
            raise ReferenceError(f"invalid reference metadata key: {key}")
        values[key] = value
    expected = {"ARCH_TEST_SHA", "ARCH_TEST_EXPECTED", "SPIKE_SHA"}
    if set(values) != expected:
        raise ReferenceError("reference metadata has missing or unknown keys")
    return values


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        values = load_versions(root / "tools/reference_versions.env")
        cache = Path(os.environ.get("REFERENCE_CACHE", "/opt/rv32i-cache"))
        arch = Path(os.environ["ARCH_TEST"])
        spike_binary = Path(os.environ["SPIKE"])
        spike_repo = spike_binary.parent.parent
        prepare_checkout(arch, ARCH_UPSTREAM, values["ARCH_TEST_SHA"], cache)
        prepare_checkout(spike_repo, SPIKE_UPSTREAM, values["SPIKE_SHA"], cache)
        prepare_spike(spike_repo, values["SPIKE_SHA"], cache)
        print(f"reference cache ready: architecture tests {values['ARCH_TEST_SHA'][:12]}, Spike {values['SPIKE_SHA'][:12]}")
        return 0
    except (KeyError, OSError, ReferenceError, subprocess.SubprocessError) as exc:
        print(f"reference preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
