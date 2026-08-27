#!/usr/bin/env python3
"""Validate the pinned verification environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping, Sequence


TOOL_KEYS = (
    "ENV_SCHEMA",
    "UBUNTU_IMAGE",
    "UBUNTU_DIGEST",
    "VERILATOR_VERSION",
    "VERILATOR_URL",
    "VERILATOR_SHA256",
    "RISCV_TOOLCHAIN_VERSION",
    "RISCV_BINUTILS_VERSION",
    "RISCV_TOOLCHAIN_URL",
    "RISCV_TOOLCHAIN_SHA256",
    "PYTHON_VERSION",
    "VHS_VERSION",
    "VHS_URL",
    "VHS_SHA256",
    "FFMPEG_VERSION",
    "VERIFY_IMAGE",
    "VERIFY_IMAGE_REVISION",
)
ASSIGNMENT_RE = re.compile(r"([A-Z][A-Z0-9_]*)=([^\s#]+)\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){1,2}(?:-[0-9A-Za-z.]+)?\Z")
IMAGE_RE = re.compile(r"[a-z0-9.-]+(?:/[a-z0-9._-]+)+\Z")


class ContractError(ValueError):
    pass


def load_manifest(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ContractError(f"missing tool version manifest: {path}") from exc
    values: dict[str, str] = {}
    order: list[str] = []
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT_RE.fullmatch(line)
        if match is None:
            if "=" in line:
                key, value = line.split("=", 1)
                if key in TOOL_KEYS and not value:
                    raise ContractError(f"empty tool version value: {key}")
            raise ContractError(f"malformed tool version line {number}")
        key, value = match.groups()
        if key not in TOOL_KEYS:
            raise ContractError(f"unknown tool version key: {key}")
        if key in values:
            raise ContractError(f"duplicate tool version key: {key}")
        values[key] = value
        order.append(key)
    if not values:
        raise ContractError("tool version manifest is empty")
    missing = [key for key in TOOL_KEYS if key not in values]
    if missing:
        raise ContractError(f"missing tool version key: {missing[0]}")
    if tuple(order) != TOOL_KEYS:
        raise ContractError("tool version keys are not in canonical order")
    return values


def validate_manifest(values: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    if set(values) != set(TOOL_KEYS):
        errors.append("tool version keys do not match the schema")
        return errors
    if values["ENV_SCHEMA"] != "1":
        errors.append("ENV_SCHEMA must be 1")
    if values["UBUNTU_IMAGE"] != "ubuntu:24.04":
        errors.append("UBUNTU_IMAGE must be ubuntu:24.04")
    if DIGEST_RE.fullmatch(values["UBUNTU_DIGEST"]) is None:
        errors.append("UBUNTU_DIGEST must be a sha256 digest")
    for key in ("VERILATOR_SHA256", "RISCV_TOOLCHAIN_SHA256", "VHS_SHA256"):
        if SHA256_RE.fullmatch(values[key]) is None:
            errors.append(f"{key} must be 64 lowercase hexadecimal characters")
    for key in ("VERILATOR_VERSION", "RISCV_TOOLCHAIN_VERSION", "RISCV_BINUTILS_VERSION", "PYTHON_VERSION", "VHS_VERSION", "FFMPEG_VERSION"):
        if VERSION_RE.fullmatch(values[key]) is None:
            errors.append(f"{key} is not canonical")
    for prefix in ("VERILATOR", "RISCV_TOOLCHAIN", "VHS"):
        url = values[f"{prefix}_URL"]
        version = values[f"{prefix}_VERSION"]
        if not url.startswith("https://"):
            errors.append(f"{prefix}_URL must use https")
        url_version = version.rsplit("-", 1)[-1] if prefix == "RISCV_TOOLCHAIN" else version
        if url_version not in url:
            errors.append(f"{prefix}_URL does not contain {prefix}_VERSION")
    if IMAGE_RE.fullmatch(values["VERIFY_IMAGE"]) is None:
        errors.append("VERIFY_IMAGE is not canonical")
    if re.fullmatch(r"[1-9][0-9]*", values["VERIFY_IMAGE_REVISION"]) is None:
        errors.append("VERIFY_IMAGE_REVISION must be a positive canonical integer")
    return errors


def command_output(command: Sequence[str], timeout: int = 20) -> tuple[int, str]:
    try:
        result = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"command timed out: {command[0]}"
    return result.returncode, result.stdout.strip()


def git_output(path: Path, *arguments: str) -> tuple[int, str]:
    return command_output(("git", "-C", str(path), *arguments))


def inspect_checkout(path: Path, expected_sha: str, label: str) -> list[str]:
    errors: list[str] = []
    if not path.is_dir():
        return [f"{label} checkout is missing: {path}"]
    rc, head = git_output(path, "rev-parse", "HEAD")
    if rc != 0:
        return [f"{label} checkout is invalid: {head}"]
    if head != expected_sha:
        errors.append(f"{label} checkout is {head}, expected {expected_sha}")
    rc, status = git_output(path, "status", "--porcelain", "--untracked-files=all")
    if rc != 0:
        errors.append(f"cannot inspect {label} checkout: {status}")
    elif status:
        errors.append(f"{label} checkout is dirty")
    return errors


def reference_values(root: Path) -> tuple[dict[str, str], list[str]]:
    path = root / "tools" / "reference_versions.env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, [f"missing reference version manifest: {path}"]
    values: dict[str, str] = {}
    for line in lines:
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    required = ("ARCH_TEST_SHA", "ARCH_TEST_EXPECTED", "SPIKE_SHA")
    missing = [key for key in required if key not in values]
    return values, [f"missing reference version key: {key}" for key in missing]


def inspect_native(
    root: Path,
    environment: Mapping[str, str],
    require_references: bool = False,
) -> list[str]:
    values = load_manifest(root / "tools" / "tool_versions.env")
    errors = validate_manifest(values)
    probes = (
        (("python3", "--version"), f"Python {values['PYTHON_VERSION']}"),
        (("verilator", "--version"), f"Verilator {values['VERILATOR_VERSION']}"),
        (("riscv64-unknown-elf-gcc", "--version"), values["RISCV_TOOLCHAIN_VERSION"].split("-", 1)[0]),
        (("riscv64-unknown-elf-as", "--version"), values["RISCV_BINUTILS_VERSION"]),
    )
    for command, expected in probes:
        rc, output = command_output(command)
        if rc != 0:
            errors.append(output)
        elif expected not in output:
            errors.append(f"{command[0]} version mismatch: expected {expected}, found {output.splitlines()[0]}")
    refs, ref_errors = reference_values(root)
    errors.extend(ref_errors)
    if require_references and not ref_errors:
        arch = Path(environment.get("ARCH_TEST", ""))
        spike = Path(environment.get("SPIKE", ""))
        errors.extend(inspect_checkout(arch, refs["ARCH_TEST_SHA"], "architecture-test"))
        errors.extend(inspect_checkout(spike.parent.parent, refs["SPIKE_SHA"], "Spike"))
    return errors


def inspect_container(
    root: Path,
    environment: Mapping[str, str],
    require_references: bool = False,
) -> list[str]:
    values = load_manifest(root / "tools" / "tool_versions.env")
    errors = validate_manifest(values)
    marker = Path(environment.get("RV32I_ENVIRONMENT_MARKER", "/opt/rv32i/environment.json"))
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        errors.append(f"invalid container environment marker: {marker}: {exc}")
        return errors
    expected = {"schema": 1, "image_revision": int(values["VERIFY_IMAGE_REVISION"])}
    if payload != expected:
        errors.append("container environment marker does not match the manifest")
    errors.extend(inspect_native(root, environment, require_references))
    return errors


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("manifest", "native", "container"))
    parser.add_argument("--require-references", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.mode == "manifest":
            errors = validate_manifest(load_manifest(root / "tools" / "tool_versions.env"))
        elif args.mode == "native":
            errors = inspect_native(root, os.environ, args.require_references)
        else:
            errors = inspect_container(root, os.environ, args.require_references)
    except (ContractError, OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"environment check failed: {error}", file=sys.stderr)
        return 1
    print(f"verification environment {args.mode}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
