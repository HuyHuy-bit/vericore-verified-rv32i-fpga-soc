#!/usr/bin/env python3
"""Check centralized reference identities and verification CI contracts.

This first checker layer intentionally uses only the Python standard library.
It parses the small workflow structures that carry repository contracts rather
than treating comments or arbitrary source substrings as evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import re
import shlex
import sys
from typing import Iterable


REFERENCE_KEYS = ("ARCH_TEST_SHA", "ARCH_TEST_EXPECTED", "SPIKE_SHA")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
COUNT_RE = re.compile(r"[1-9][0-9]*\Z")
ASSIGNMENT_RE = re.compile(r"([A-Z][A-Z0-9_]*)=([^\s#]+)\Z")
REQUIRED_PATHS = (
    "rtl/**",
    "cpu_tb.cpp",
    "Makefile",
    "compliance/**",
    "tools/**",
    "unit/**",
    "tests/**",
)
DIRECTED_MATRIX = (
    ("baseline", ""),
    ("slow-mem", "IMEM_LAT=10 DMEM_LAT=10"),
    ("icache-only", "IC_BYTES=1024 IC_WAYS=4 IMEM_LAT=10 DMEM_LAT=10"),
    (
        "wt",
        "IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=0 "
        "IMEM_LAT=10 DMEM_LAT=10",
    ),
    (
        "wb",
        "IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 "
        "IMEM_LAT=10 DMEM_LAT=10",
    ),
    (
        "assoc",
        "IC_BYTES=1024 IC_BLOCK=4 IC_WAYS=2 DC_BYTES=4096 DC_BLOCK=4 "
        "DC_WAYS=2 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10",
    ),
)


class ContractError(ValueError):
    """A repository contract is missing or internally inconsistent."""


@dataclass(frozen=True)
class YamlLine:
    indent: int
    text: str
    number: int


@dataclass
class WorkflowStep:
    values: dict[str, str] = field(default_factory=dict)
    nested: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def run(self) -> str:
        return self.values.get("run", "")


def strip_inline_comment(line: str) -> str:
    """Remove a shell/YAML comment while preserving quoted hash characters."""

    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "#":
            return line[:index]
    return line


def yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def workflow_lines(path: Path) -> list[YamlLine]:
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ContractError(f"missing workflow: {path}") from exc
    records: list[YamlLine] = []
    for number, raw in enumerate(source.splitlines(), 1):
        code = strip_inline_comment(raw).rstrip()
        if not code.strip():
            continue
        indent = len(code) - len(code.lstrip(" "))
        if "\t" in code[:indent]:
            raise ContractError(f"{path}:{number}: tabs are not valid workflow indentation")
        records.append(YamlLine(indent, code[indent:], number))
    return records


def block_after(lines: list[YamlLine], index: int) -> list[YamlLine]:
    parent_indent = lines[index].indent
    end = index + 1
    while end < len(lines) and lines[end].indent > parent_indent:
        end += 1
    return lines[index + 1:end]


def unique_key(lines: list[YamlLine], key: str, indent: int | None = None) -> int:
    wanted = f"{key}:"
    found = [
        index for index, line in enumerate(lines)
        if line.text == wanted and (indent is None or line.indent == indent)
    ]
    if len(found) != 1:
        raise ContractError(f"expected exactly one {key}: workflow key")
    return found[0]


def parse_mapping_entry(text: str) -> tuple[str, str] | None:
    if ":" not in text:
        return None
    key, value = text.split(":", 1)
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
        return None
    return key, yaml_scalar(value)


def parse_steps(lines: list[YamlLine]) -> list[WorkflowStep]:
    steps: list[WorkflowStep] = []
    for steps_index, marker in enumerate(lines):
        if marker.text != "steps:":
            continue
        section = block_after(lines, steps_index)
        item_indent = marker.indent + 2
        starts = [i for i, line in enumerate(section)
                  if line.indent == item_indent and line.text.startswith("- ")]
        for start_position, start in enumerate(starts):
            end = starts[start_position + 1] if start_position + 1 < len(starts) else len(section)
            chunk = section[start:end]
            step = WorkflowStep()
            first = parse_mapping_entry(chunk[0].text[2:])
            if first:
                step.values[first[0]] = first[1]
            index = 1
            property_indent = item_indent + 2
            while index < len(chunk):
                line = chunk[index]
                if line.indent != property_indent:
                    index += 1
                    continue
                entry = parse_mapping_entry(line.text)
                if entry is None:
                    index += 1
                    continue
                key, value = entry
                child_end = index + 1
                while child_end < len(chunk) and chunk[child_end].indent > line.indent:
                    child_end += 1
                children = chunk[index + 1:child_end]
                if key == "run" and value in ("|", ">"):
                    step.values[key] = "\n".join(child.text for child in children)
                elif children and value == "":
                    mapping: dict[str, str] = {}
                    for child in children:
                        if child.indent != line.indent + 2:
                            continue
                        child_entry = parse_mapping_entry(child.text)
                        if child_entry:
                            mapping[child_entry[0]] = child_entry[1]
                    step.nested[key] = mapping
                else:
                    step.values[key] = value
                index = child_end
            steps.append(step)
    return steps


def shell_commands(run: str) -> list[list[str]]:
    commands: list[list[str]] = []
    pending = ""
    for raw in run.splitlines():
        code = strip_inline_comment(raw).strip()
        if not code:
            continue
        if code.endswith("\\"):
            pending += code[:-1] + " "
            continue
        code = pending + code
        pending = ""
        try:
            tokens = shlex.split(code, comments=False, posix=True)
        except ValueError:
            tokens = code.split()
        if tokens:
            commands.append(tokens)
    if pending.strip():
        commands.append(pending.split())
    return commands


def parse_reference_versions(root: Path) -> dict[str, str]:
    path = root / "tools/reference_versions.env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ContractError(f"missing reference metadata: {path}") from exc

    values: dict[str, str] = {}
    assignments = 0
    for number, raw in enumerate(lines, 1):
        if not raw or raw.startswith("#"):
            continue
        match = ASSIGNMENT_RE.fullmatch(raw)
        if match is None:
            raise ContractError(f"malformed reference metadata line {number}: {path}")
        assignments += 1
        key, value = match.groups()
        if key in values:
            raise ContractError(f"duplicate reference metadata key: {key}")
        if key not in REFERENCE_KEYS:
            raise ContractError(f"unexpected reference metadata key: {key}")
        values[key] = value

    if assignments == 0:
        raise ContractError(f"reference metadata is empty: {path}")
    missing = [key for key in REFERENCE_KEYS if key not in values]
    if missing:
        raise ContractError(f"missing reference metadata key: {missing[0]}")
    if not SHA_RE.fullmatch(values["ARCH_TEST_SHA"]):
        raise ContractError("ARCH_TEST_SHA must be a lowercase 40-hex SHA")
    if not COUNT_RE.fullmatch(values["ARCH_TEST_EXPECTED"]):
        raise ContractError("ARCH_TEST_EXPECTED must be a canonical positive integer")
    if not SHA_RE.fullmatch(values["SPIKE_SHA"]):
        raise ContractError("SPIKE_SHA must be a lowercase 40-hex SHA")
    return values


def executable_sources(root: Path) -> Iterable[Path]:
    excluded_names = {"evidence_check.py", "test_evidence_check.py"}
    allowed_suffixes = {".py", ".sh", ".yml", ".yaml"}
    skipped_dirs = {".git", ".superpowers", "docs", "__pycache__", "coverage"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        hidden_nonworkflow = any(
            part.startswith(".") and part != ".github" for part in relative.parts[:-1]
        )
        if any(part in skipped_dirs or part.startswith("obj_dir") for part in relative.parts[:-1]):
            continue
        if hidden_nonworkflow:
            continue
        if path.name in excluded_names or path == root / "tools/reference_versions.env":
            continue
        if path.name == "Makefile" or path.suffix in allowed_suffixes:
            yield path


def check_symbolic_consumers(root: Path, versions: dict[str, str]) -> None:
    literal_pins = (versions["ARCH_TEST_SHA"], versions["SPIKE_SHA"])
    for path in executable_sources(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        code = "\n".join(strip_inline_comment(line) for line in source.splitlines())
        if "ARCH_TEST_EXPECTED_CASES" in code:
            raise ContractError(f"legacy ARCH_TEST_EXPECTED_CASES in {path.relative_to(root)}")
        for pin in literal_pins:
            if re.search(rf"(?<![0-9a-f]){re.escape(pin)}(?![0-9a-f])", code):
                raise ContractError(
                    "literal reference pin duplicated in executable consumer: "
                    f"{path.relative_to(root)}"
                )
        expected = re.escape(versions["ARCH_TEST_EXPECTED"])
        if re.search(
            rf"(?<![A-Z0-9_])ARCH_TEST_EXPECTED\s*=\s*['\"]?{expected}['\"]?(?![0-9])",
            code,
        ):
            raise ContractError(
                "literal expected architecture count duplicated in executable consumer: "
                f"{path.relative_to(root)}"
            )

    required_uses = {
        "compliance/run_compliance.sh": ("ARCH_TEST_SHA", "ARCH_TEST_EXPECTED"),
        "tools/run_lockstep.sh": ("ARCH_TEST_SHA", "ARCH_TEST_EXPECTED", "SPIKE_SHA"),
        "tools/soak_lockstep.sh": ("SPIKE_SHA",),
    }
    for relative, symbols in required_uses.items():
        path = root / relative
        if not path.is_file():
            raise ContractError(f"missing reference consumer: {relative}")
        code = "\n".join(
            strip_inline_comment(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
        for symbol in symbols:
            if re.search(rf"\${{{symbol}}}|\${symbol}\b", code) is None:
                raise ContractError(f"{relative} must consume {symbol} symbolically")


def event_paths(lines: list[YamlLine], workflow: Path, event: str) -> set[str]:
    on_index = unique_key(lines, "on", 0)
    on_block = block_after(lines, on_index)
    event_lines = [
        (index, line) for index, line in enumerate(on_block)
        if line.indent == 2 and line.text == f"{event}:"
    ]
    if len(event_lines) != 1:
        raise ContractError(f"{workflow.name}: missing {event} trigger")
    if event == "workflow_dispatch":
        return set()
    event_index = event_lines[0][0]
    section = block_after(on_block, event_index)
    paths_markers = [
        (index, line) for index, line in enumerate(section)
        if line.indent == 4 and line.text == "paths:"
    ]
    if len(paths_markers) != 1:
        raise ContractError(f"{workflow.name}: {event}.paths is required")
    path_block = block_after(section, paths_markers[0][0])
    paths: set[str] = set()
    for line in path_block:
        if line.indent == 6 and line.text.startswith("- "):
            paths.add(yaml_scalar(line.text[2:]))
    return paths


def check_triggers(path: Path, lines: list[YamlLine]) -> None:
    event_paths(lines, path, "workflow_dispatch")
    required = set(REQUIRED_PATHS) | {f".github/workflows/{path.name}"}
    for event in ("push", "pull_request"):
        actual = event_paths(lines, path, event)
        missing = [value for value in required if value not in actual]
        if missing:
            raise ContractError(f"{path.name}: {event}.paths missing {sorted(missing)[0]}")


def find_metadata_step(path: Path, steps: list[WorkflowStep]) -> WorkflowStep:
    matches = [step for step in steps if step.values.get("id") == "refs"]
    if len(matches) != 1:
        raise ContractError(f"{path.name}: expected one metadata step with id refs")
    step = matches[0]
    commands = shell_commands(step.run)
    if not any(tokens[:2] in (["source", "tools/reference_versions.env"],
                              [".", "tools/reference_versions.env"])
               for tokens in commands):
        raise ContractError(f"{path.name}: refs step must load tools/reference_versions.env")
    outputs = {
        "arch_test_sha": "$ARCH_TEST_SHA",
        "arch_test_expected": "$ARCH_TEST_EXPECTED",
        "spike_sha": "$SPIKE_SHA",
    }
    for output, symbol in outputs.items():
        found = False
        for tokens in commands:
            if len(tokens) >= 4 and tokens[0] in ("echo", "printf"):
                if f"{output}={symbol}" in tokens and ">>" in tokens and "$GITHUB_OUTPUT" in tokens:
                    found = True
                    break
        if not found:
            raise ContractError(f"{path.name}: must publish {output} through GITHUB_OUTPUT")
    return step


def cache_step(steps: list[WorkflowStep], path_value: str) -> WorkflowStep | None:
    for step in steps:
        uses = step.values.get("uses", "")
        if uses.startswith("actions/cache@") and step.nested.get("with", {}).get("path") == path_value:
            return step
    return None


def expression_uses(value: str, output: str) -> bool:
    return re.fullmatch(
        rf"[^\s]*\$\{{\{{\s*steps\.refs\.outputs\.{re.escape(output)}\s*\}}\}}[^\s]*",
        value,
    ) is not None


def commands_for_steps(steps: list[WorkflowStep]) -> list[list[str]]:
    return [command for step in steps for command in shell_commands(step.run)]


def command_has(tokens: list[str], *parts: str) -> bool:
    return all(any(part == token or part in token for token in tokens) for part in parts)


def check_architecture_checkout(path: Path, steps: list[WorkflowStep]) -> None:
    cache = cache_step(steps, "~/riscv-arch-test")
    if cache is None:
        raise ContractError(f"{path.name}: architecture-test checkout must be cached")
    key = cache.nested.get("with", {}).get("key", "")
    if not expression_uses(key, "arch_test_sha"):
        raise ContractError(f"{path.name}: architecture-test cache key must use arch_test_sha output")

    commands = commands_for_steps(steps)
    if any("--branch" in command or "old-framework-2.x" in command for command in commands):
        raise ContractError(f"{path.name}: moving architecture-test reference is forbidden")
    direct_upstream_fetch = any(
        command_has(
            command,
            "riscv-arch-test",
            "fetch",
            "https://github.com/riscv-non-isa/riscv-arch-test.git",
        )
        for command in commands
    )
    upstream_origin = any(
        command_has(
            command,
            "riscv-arch-test",
            "remote",
            "origin",
            "https://github.com/riscv-non-isa/riscv-arch-test.git",
        )
        for command in commands
    )
    origin_fetch = any(command_has(command, "riscv-arch-test", "fetch", "origin", "$ARCH_TEST_SHA")
                       for command in commands)
    if not (direct_upstream_fetch or (upstream_origin and origin_fetch)):
        raise ContractError(f"{path.name}: architecture-test checkout must use the approved upstream")
    fetch = any(command_has(command, "riscv-arch-test", "fetch", "$ARCH_TEST_SHA")
                for command in commands)
    detach = any(command_has(command, "riscv-arch-test", "checkout", "--detach")
                 for command in commands)
    verify = any(command_has(command, "riscv-arch-test", "rev-parse HEAD", "$ARCH_TEST_SHA")
                 for command in commands)
    detached_verify = any(command_has(command, "riscv-arch-test", "symbolic-ref -q HEAD")
                          for command in commands)
    env_bound = any(
        step.nested.get("env", {}).get("ARCH_TEST_SHA")
        == "${{ steps.refs.outputs.arch_test_sha }}"
        for step in steps
    )
    if not (fetch and detach and verify and detached_verify and env_bound):
        raise ContractError(f"{path.name}: moving architecture-test reference; fetch and verify the detached SHA")


def check_spike_checkout(path: Path, steps: list[WorkflowStep]) -> None:
    cache = cache_step(steps, "~/riscv-isa-sim")
    if cache is None:
        raise ContractError(f"{path.name}: Spike cache must retain the verified source/build checkout")
    key = cache.nested.get("with", {}).get("key", "")
    if not expression_uses(key, "spike_sha"):
        raise ContractError(f"{path.name}: Spike cache key must use spike_sha output")
    commands = commands_for_steps(steps)
    direct_upstream_fetch = any(
        command_has(
            command,
            "riscv-isa-sim",
            "fetch",
            "https://github.com/riscv-software-src/riscv-isa-sim.git",
        )
        for command in commands
    )
    upstream_origin = any(
        command_has(
            command,
            "riscv-isa-sim",
            "remote",
            "origin",
            "https://github.com/riscv-software-src/riscv-isa-sim.git",
        )
        for command in commands
    )
    origin_fetch = any(command_has(command, "riscv-isa-sim", "fetch", "origin", "$SPIKE_SHA")
                       for command in commands)
    if not (direct_upstream_fetch or (upstream_origin and origin_fetch)):
        raise ContractError(f"{path.name}: Spike checkout must use the approved upstream")
    fetch = any(command_has(command, "riscv-isa-sim", "fetch", "$SPIKE_SHA")
                for command in commands)
    detach = any(command_has(command, "riscv-isa-sim", "checkout", "--detach")
                 for command in commands)
    verify = any(command_has(command, "riscv-isa-sim", "rev-parse HEAD", "$SPIKE_SHA")
                 for command in commands)
    detached_verify = any(command_has(command, "riscv-isa-sim", "symbolic-ref -q HEAD")
                          for command in commands)
    binary = any(command_has(command, "riscv-isa-sim/build/spike") for command in commands)
    env_bound = any(
        step.nested.get("env", {}).get("SPIKE_SHA") == "${{ steps.refs.outputs.spike_sha }}"
        for step in steps
    )
    if not (fetch and detach and verify and detached_verify and binary and env_bound):
        raise ContractError(f"{path.name}: Spike must be fetched, built, and verified at spike_sha")


def exact_make_commands(steps: list[WorkflowStep]) -> list[tuple[int, list[str]]]:
    result: list[tuple[int, list[str]]] = []
    for step_index, step in enumerate(steps):
        for command in shell_commands(step.run):
            if command and command[0] == "make":
                result.append((step_index, command))
    return result


def check_lockstep_gates(path: Path, steps: list[WorkflowStep]) -> None:
    commands = exact_make_commands(steps)
    lockstep = [index for index, command in commands if command == ["make", "lockstep"]]
    soak = [index for index, command in commands
            if command == ["make", "soak-lockstep", "SEEDS=200"]]
    any_soak = [command for _, command in commands
                if len(command) >= 2 and command[1] == "soak-lockstep"]
    if not lockstep or (soak and min(lockstep) >= min(soak)):
        raise ContractError(f"{path.name}: lockstep workflow must run make lockstep before random soak")
    if len(soak) != 1 or len(any_soak) != 1:
        raise ContractError(
            f"{path.name}: lockstep workflow must run exactly make soak-lockstep SEEDS=200"
        )
    spike_paths = [step.nested.get("env", {}).get("SPIKE") for step in steps]
    if "/home/runner/riscv-isa-sim/build/spike" not in spike_paths:
        raise ContractError(f"{path.name}: lockstep must execute Spike inside its verified checkout")


def parse_directed_matrix(lines: list[YamlLine]) -> tuple[tuple[str, str], ...]:
    include_indices = [index for index, line in enumerate(lines) if line.text == "include:"]
    if len(include_indices) != 1:
        raise ContractError("rtl-tests.yml: expected exactly one directed matrix include list")
    marker = lines[include_indices[0]]
    block = block_after(lines, include_indices[0])
    item_indent = marker.indent + 2
    items: list[tuple[str, str]] = []
    starts = [index for index, line in enumerate(block)
              if line.indent == item_indent and line.text.startswith("- ")]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(block)
        chunk = block[start:end]
        values: dict[str, str] = {}
        first = parse_mapping_entry(chunk[0].text[2:])
        if first:
            values[first[0]] = first[1]
        for line in chunk[1:]:
            if line.indent != item_indent + 2:
                continue
            entry = parse_mapping_entry(line.text)
            if entry:
                values[entry[0]] = entry[1]
        if set(values) != {"name", "args"}:
            raise ContractError("rtl-tests.yml: each directed matrix entry needs only name and args")
        items.append((values["name"], values["args"]))
    return tuple(items)


def check_workflows(root: Path) -> None:
    workflow_dir = root / ".github/workflows"
    parsed: dict[str, tuple[Path, list[YamlLine], list[WorkflowStep]]] = {}
    for name in ("rtl-tests.yml", "compliance.yml", "lockstep.yml"):
        path = workflow_dir / name
        lines = workflow_lines(path)
        check_triggers(path, lines)
        parsed[name] = (path, lines, parse_steps(lines))

    rtl_lines = parsed["rtl-tests.yml"][1]
    if parse_directed_matrix(rtl_lines) != DIRECTED_MATRIX:
        raise ContractError("directed CI matrix does not match the six approved configurations")

    for name in ("compliance.yml", "lockstep.yml"):
        path, _, steps = parsed[name]
        find_metadata_step(path, steps)
        check_architecture_checkout(path, steps)

    compliance_path, _, compliance_steps = parsed["compliance.yml"]
    if [command for _, command in exact_make_commands(compliance_steps)
            if command == ["make", "compliance"]] == []:
        raise ContractError(f"{compliance_path.name}: workflow must run make compliance")

    lockstep_path, _, lockstep_steps = parsed["lockstep.yml"]
    check_spike_checkout(lockstep_path, lockstep_steps)
    check_lockstep_gates(lockstep_path, lockstep_steps)


def check_contracts(root: Path) -> None:
    versions = parse_reference_versions(root)
    check_symbolic_consumers(root, versions)
    check_workflows(root)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to this script's repository)",
    )
    parser.add_argument(
        "--contracts-only",
        action="store_true",
        help="check reference and CI contracts only",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    try:
        check_contracts(root)
    except (ContractError, OSError) as exc:
        print(f"evidence check failed: {exc}", file=sys.stderr)
        return 1
    print("reference and CI contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
