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
import sys
from typing import Callable, Iterable


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
ARCH_UPSTREAM = "https://github.com/riscv-non-isa/riscv-arch-test.git"
SPIKE_UPSTREAM = "https://github.com/riscv-software-src/riscv-isa-sim.git"
METADATA_RUN = (
    "set -eu",
    "source tools/reference_versions.env",
    'echo "arch_test_sha=$ARCH_TEST_SHA" >> "$GITHUB_OUTPUT"',
    'echo "arch_test_expected=$ARCH_TEST_EXPECTED" >> "$GITHUB_OUTPUT"',
    'echo "spike_sha=$SPIKE_SHA" >> "$GITHUB_OUTPUT"',
)
ARCH_SETUP_RUN = (
    "set -eu",
    'if [ ! -d "$HOME/riscv-arch-test/.git" ]; then',
    'git init -q "$HOME/riscv-arch-test"',
    "fi",
    'git -C "$HOME/riscv-arch-test" remote remove origin 2>/dev/null || true',
    f'git -C "$HOME/riscv-arch-test" remote add origin {ARCH_UPSTREAM}',
    'git -C "$HOME/riscv-arch-test" fetch -q --depth 1 origin "$ARCH_TEST_SHA"',
    'git -C "$HOME/riscv-arch-test" checkout -q --detach "$ARCH_TEST_SHA"',
    'git -C "$HOME/riscv-arch-test" reset -q --hard "$ARCH_TEST_SHA"',
    'test "$(git -C "$HOME/riscv-arch-test" rev-parse HEAD)" = "$ARCH_TEST_SHA"',
    'test -z "$(git -C "$HOME/riscv-arch-test" symbolic-ref -q HEAD || true)"',
    'test -z "$(git -C "$HOME/riscv-arch-test" status --short --untracked-files=no)"',
)
SPIKE_STAMP_CONDITION = (
    'if [ ! -x "$HOME/riscv-isa-sim/build/spike" ] || '
    '[ ! -f "$HOME/riscv-isa-sim/build/.source-sha" ] || '
    '[ "$(cat "$HOME/riscv-isa-sim/build/.source-sha" 2>/dev/null || true)" '
    '!= "$SPIKE_SHA" ]; then'
)
SPIKE_STAMP_WRITE = "printf '%s\\n' \"$SPIKE_SHA\" > .source-sha"
SPIKE_STAMP_VERIFY = (
    'test "$(cat "$HOME/riscv-isa-sim/build/.source-sha")" = "$SPIKE_SHA"'
)
SPIKE_SETUP_RUN = (
    "set -eu",
    'if [ ! -d "$HOME/riscv-isa-sim/.git" ]; then',
    'git init -q "$HOME/riscv-isa-sim"',
    "fi",
    'git -C "$HOME/riscv-isa-sim" remote remove origin 2>/dev/null || true',
    f'git -C "$HOME/riscv-isa-sim" remote add origin {SPIKE_UPSTREAM}',
    'git -C "$HOME/riscv-isa-sim" fetch -q --depth 1 origin "$SPIKE_SHA"',
    'git -C "$HOME/riscv-isa-sim" checkout -q --detach "$SPIKE_SHA"',
    'git -C "$HOME/riscv-isa-sim" reset -q --hard "$SPIKE_SHA"',
    'test "$(git -C "$HOME/riscv-isa-sim" rev-parse HEAD)" = "$SPIKE_SHA"',
    'test -z "$(git -C "$HOME/riscv-isa-sim" symbolic-ref -q HEAD || true)"',
    'test -z "$(git -C "$HOME/riscv-isa-sim" status --short --untracked-files=no)"',
    SPIKE_STAMP_CONDITION,
    'rm -rf "$HOME/riscv-isa-sim/build"',
    'mkdir -p "$HOME/riscv-isa-sim/build"',
    'cd "$HOME/riscv-isa-sim/build"',
    "../configure",
    'make -j"$(nproc)"',
    SPIKE_STAMP_WRITE,
    "fi",
    'test -x "$HOME/riscv-isa-sim/build/spike"',
    SPIKE_STAMP_VERIFY,
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
    block_values: set[str] = field(default_factory=set)

    @property
    def run(self) -> str:
        return self.values.get("run", "")


@dataclass
class WorkflowJob:
    values: dict[str, str] = field(default_factory=dict)
    steps: list[WorkflowStep] = field(default_factory=list)
    lines: list[YamlLine] = field(default_factory=list)


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
                    step.block_values.add(key)
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


def parse_jobs(path: Path, lines: list[YamlLine]) -> dict[str, WorkflowJob]:
    """Parse the small top-level job map used by the three required workflows."""

    jobs_index = unique_key(lines, "jobs", 0)
    section = block_after(lines, jobs_index)
    starts = [
        index
        for index, line in enumerate(section)
        if line.indent == 2 and line.text.endswith(":")
    ]
    jobs: dict[str, WorkflowJob] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(section)
        name = section[start].text[:-1]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
            raise ContractError(f"{path.name}: malformed job name {name!r}")
        if name in jobs:
            raise ContractError(f"{path.name}: duplicate job {name}")
        chunk = section[start:end]
        values: dict[str, str] = {}
        for line in chunk[1:]:
            if line.indent != 4:
                continue
            entry = parse_mapping_entry(line.text)
            if entry:
                values[entry[0]] = entry[1]
        if sum(line.indent == 4 and line.text == "steps:" for line in chunk) != 1:
            raise ContractError(f"{path.name}: job {name} must have exactly one steps list")
        jobs[name] = WorkflowJob(values=values, steps=parse_steps(chunk), lines=chunk)
    return jobs


def logical_run_lines(run: str) -> tuple[str, ...]:
    """Return normalized logical lines without interpreting shell control flow."""

    lines: list[str] = []
    pending = ""
    for raw in run.splitlines():
        code = strip_inline_comment(raw).strip()
        if not code:
            continue
        if code.endswith("\\"):
            pending += code[:-1].strip() + " "
            continue
        code = pending + code
        pending = ""
        lines.append(re.sub(r"\s+", " ", code).strip())
    if pending.strip():
        lines.append(re.sub(r"\s+", " ", pending).strip())
    return tuple(lines)


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
    excluded_paths = {
        Path("tools/evidence_check.py"),
        Path("tools/test_evidence_check.py"),
        Path("tools/reference_versions.env"),
    }
    allowed_suffixes = {".py", ".sh", ".yml", ".yaml"}
    excluded_prefixes = (
        Path(".git"),
        Path(".superpowers"),
        Path(".claude/worktrees"),
        Path("docs/superpowers"),
        Path("coverage"),
    )
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative in excluded_paths:
            continue
        if any(relative == prefix or prefix in relative.parents for prefix in excluded_prefixes):
            continue
        if any(part == "__pycache__" or part.startswith("obj_dir") for part in relative.parts):
            continue
        is_executable = bool(path.stat().st_mode & 0o111)
        if path.name == "Makefile" or path.suffix in allowed_suffixes or is_executable:
            yield path


def normalized_literal_code(source: str) -> str:
    """Expose shell-adjacent quoted literals without evaluating source."""

    code = "\n".join(strip_inline_comment(line) for line in source.splitlines())
    return re.sub(r"(?<=[0-9a-f])['\"]+(?=[0-9a-f])", "", code)


def alternate_count_name(name: str) -> bool:
    words = set(name.split("_"))
    plural = {"CASE", "CASES", "COUNT", "COUNTS"}
    return (
        ("EXPECTED" in words and bool(words & plural))
        or ({"ARCH", "TEST"} <= words and bool(words & plural))
        or ("TEST" in words and bool(words & plural))
    )


def check_symbolic_consumers(root: Path, versions: dict[str, str]) -> None:
    literal_pins = (versions["ARCH_TEST_SHA"], versions["SPIKE_SHA"])
    for path in executable_sources(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        code = normalized_literal_code(source)
        if "ARCH_TEST_EXPECTED_CASES" in code:
            raise ContractError(f"legacy ARCH_TEST_EXPECTED_CASES in {path.relative_to(root)}")
        for pin in literal_pins:
            if re.search(rf"(?<![0-9a-f]){re.escape(pin)}(?![0-9a-f])", code):
                raise ContractError(
                    "literal reference pin duplicated in executable consumer: "
                    f"{path.relative_to(root)}"
                )
        expected = re.escape(versions["ARCH_TEST_EXPECTED"])
        assignment = re.compile(
            rf"(?<![A-Z0-9_])([A-Z][A-Z0-9_]*)\s*=\s*['\"]?{expected}['\"]?(?![0-9])"
        )
        for match in assignment.finditer(code):
            name = match.group(1)
            if name == "ARCH_TEST_EXPECTED":
                raise ContractError(
                    "literal expected architecture count duplicated in executable consumer: "
                    f"{path.relative_to(root)}"
                )
            if alternate_count_name(name):
                raise ContractError(
                    "alternate expected architecture count duplicated in executable consumer: "
                    f"{path.relative_to(root)} ({name})"
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


def event_paths(lines: list[YamlLine], workflow: Path, event: str) -> list[str]:
    on_index = unique_key(lines, "on", 0)
    on_block = block_after(lines, on_index)
    event_lines = [
        (index, line) for index, line in enumerate(on_block)
        if line.indent == 2 and line.text == f"{event}:"
    ]
    if len(event_lines) != 1:
        raise ContractError(f"{workflow.name}: missing {event} trigger")
    if event == "workflow_dispatch":
        return []
    event_index = event_lines[0][0]
    section = block_after(on_block, event_index)
    paths_markers = [
        (index, line) for index, line in enumerate(section)
        if line.indent == 4 and line.text == "paths:"
    ]
    if len(paths_markers) != 1:
        raise ContractError(f"{workflow.name}: {event}.paths is required")
    path_block = block_after(section, paths_markers[0][0])
    paths: list[str] = []
    for line in path_block:
        if line.indent == 6 and line.text.startswith("- "):
            paths.append(yaml_scalar(line.text[2:]))
    return paths


def check_triggers(path: Path, lines: list[YamlLine]) -> None:
    event_paths(lines, path, "workflow_dispatch")
    required = set(REQUIRED_PATHS) | {f".github/workflows/{path.name}"}
    for event in ("push", "pull_request"):
        actual = event_paths(lines, path, event)
        for value in sorted(required):
            if actual.count(value) > 1 or f"!{value}" in actual:
                raise ContractError(
                    f"{path.name}: {event}.paths must not negate or duplicate required path {value}"
                )
        if len(actual) != len(set(actual)):
            raise ContractError(f"{path.name}: {event}.paths contains duplicate entries")
        if any(value.startswith("!") for value in actual):
            raise ContractError(f"{path.name}: {event}.paths must not contain negated entries")
        missing = [value for value in required if value not in set(actual)]
        if missing:
            raise ContractError(f"{path.name}: {event}.paths missing {sorted(missing)[0]}")


def reject_job_controls(path: Path, name: str, job: WorkflowJob) -> None:
    for key in ("if", "continue-on-error"):
        if key in job.values:
            raise ContractError(f"{name} job must not use {key}")


def reject_step_controls(step: WorkflowStep) -> None:
    for key in ("if", "continue-on-error"):
        if key in step.values:
            raise ContractError(f"required step must not use {key}")


def unique_step(
    path: Path,
    steps: list[WorkflowStep],
    description: str,
    predicate: Callable[[WorkflowStep], bool],
) -> tuple[int, WorkflowStep]:
    matches = [(index, step) for index, step in enumerate(steps) if predicate(step)]
    if len(matches) != 1:
        raise ContractError(f"{path.name}: expected exactly one {description} step")
    index, step = matches[0]
    reject_step_controls(step)
    return index, step


def find_metadata_step(path: Path, steps: list[WorkflowStep]) -> tuple[int, WorkflowStep]:
    matches = [(index, step) for index, step in enumerate(steps)
               if step.values.get("id") == "refs"]
    if len(matches) != 1:
        raise ContractError(f"{path.name}: expected one metadata step with id refs")
    index, step = matches[0]
    reject_step_controls(step)
    if logical_run_lines(step.run) != METADATA_RUN:
        raise ContractError(
            f"{path.name}: metadata step must publish exact expanding output lines; "
            "must publish arch_test_sha through GITHUB_OUTPUT"
        )
    return index, step


def cache_step(
    path: Path,
    steps: list[WorkflowStep],
    path_value: str,
    description: str,
) -> tuple[int, WorkflowStep]:
    return unique_step(
        path,
        steps,
        description,
        lambda step: (
            step.values.get("uses") == "actions/cache@v4"
            and step.nested.get("with", {}).get("path") == path_value
        ),
    )


def check_architecture_checkout(
    path: Path, steps: list[WorkflowStep]
) -> tuple[int, int]:
    cache_index, cache = cache_step(
        path, steps, "~/riscv-arch-test", "architecture-test cache"
    )
    key = cache.nested.get("with", {}).get("key", "")
    if key != "riscv-arch-test-${{ steps.refs.outputs.arch_test_sha }}":
        raise ContractError(f"{path.name}: architecture-test cache key must use arch_test_sha output")

    setup_index, setup = unique_step(
        path,
        steps,
        "architecture-test setup",
        lambda step: (
            step.nested.get("env", {}).get("ARCH_TEST_SHA")
            == "${{ steps.refs.outputs.arch_test_sha }}"
        ),
    )
    run = logical_run_lines(setup.run)
    if any("--branch" in line or "old-framework-2.x" in line for line in run):
        raise ContractError(f"{path.name}: moving architecture-test reference is forbidden")
    upstream_line = (
        f'git -C "$HOME/riscv-arch-test" remote add origin {ARCH_UPSTREAM}'
    )
    if upstream_line not in run:
        raise ContractError(f"{path.name}: architecture-test checkout must use the approved upstream")
    if run != ARCH_SETUP_RUN:
        raise ContractError(
            f"{path.name}: architecture-test setup must exactly verify the pinned checkout"
        )
    return cache_index, setup_index


def check_spike_checkout(path: Path, steps: list[WorkflowStep]) -> tuple[int, int]:
    try:
        cache_index, cache = cache_step(
            path, steps, "~/riscv-isa-sim", "Spike source/build cache"
        )
    except ContractError as exc:
        raise ContractError(
            f"{path.name}: Spike cache must retain the verified source/build checkout"
        ) from exc
    key = cache.nested.get("with", {}).get("key", "")
    if key != "spike-${{ steps.refs.outputs.spike_sha }}":
        raise ContractError(f"{path.name}: Spike cache key must use spike_sha output")

    setup_index, setup = unique_step(
        path,
        steps,
        "Spike setup",
        lambda step: (
            step.nested.get("env", {}).get("SPIKE_SHA")
            == "${{ steps.refs.outputs.spike_sha }}"
        ),
    )
    run = logical_run_lines(setup.run)
    upstream_line = (
        f'git -C "$HOME/riscv-isa-sim" remote add origin {SPIKE_UPSTREAM}'
    )
    if upstream_line not in run:
        raise ContractError(f"{path.name}: Spike checkout must use the approved upstream")
    if not {SPIKE_STAMP_CONDITION, SPIKE_STAMP_WRITE, SPIKE_STAMP_VERIFY} <= set(run):
        raise ContractError(f"{path.name}: Spike build must be bound to spike_sha with .source-sha")
    if run != SPIKE_SETUP_RUN:
        raise ContractError(
            f"{path.name}: Spike setup must exactly fetch, reset, build, and verify spike_sha"
        )
    return cache_index, setup_index


def direct_gate_step(
    path: Path,
    steps: list[WorkflowStep],
    command: str,
    description: str,
) -> tuple[int, WorkflowStep]:
    matches = [(index, step) for index, step in enumerate(steps)
               if step.run.strip() == command]
    if len(matches) != 1:
        raise ContractError(f"{path.name}: {description} run must be exactly {command}")
    index, step = matches[0]
    if "run" in step.block_values:
        raise ContractError(f"{path.name}: {description} run must be exactly {command}")
    reject_step_controls(step)
    return index, step


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


def required_job(
    path: Path, jobs: dict[str, WorkflowJob], name: str
) -> WorkflowJob:
    if name not in jobs:
        raise ContractError(f"{path.name}: missing required job {name}")
    job = jobs[name]
    reject_job_controls(path, name, job)
    return job


def require_gate_env(
    path: Path, step: WorkflowStep, required: dict[str, str], description: str
) -> None:
    actual = step.nested.get("env", {})
    for key, value in required.items():
        if actual.get(key) != value:
            raise ContractError(f"{path.name}: {description} must bind {key} to {value}")


def check_workflows(root: Path) -> None:
    workflow_dir = root / ".github/workflows"
    parsed: dict[str, tuple[Path, list[YamlLine], dict[str, WorkflowJob]]] = {}
    for name in ("rtl-tests.yml", "compliance.yml", "lockstep.yml"):
        path = workflow_dir / name
        lines = workflow_lines(path)
        check_triggers(path, lines)
        parsed[name] = (path, lines, parse_jobs(path, lines))

    rtl_path, _, rtl_jobs = parsed["rtl-tests.yml"]
    rtl_job = required_job(rtl_path, rtl_jobs, "test-matrix")
    if parse_directed_matrix(rtl_job.lines) != DIRECTED_MATRIX:
        raise ContractError("directed CI matrix does not match the six approved configurations")
    direct_gate_step(
        rtl_path,
        rtl_job.steps,
        "make all ${{ matrix.args }}",
        "test-matrix gate",
    )

    compliance_path, _, compliance_jobs = parsed["compliance.yml"]
    compliance_job = required_job(compliance_path, compliance_jobs, "compliance")
    compliance_steps = compliance_job.steps
    if not any(step.values.get("id") == "refs" for step in compliance_steps) and any(
        step.values.get("id") == "refs"
        for name, job in compliance_jobs.items()
        if name != "compliance"
        for step in job.steps
    ):
        raise ContractError("compliance job is missing its required contract chain")
    metadata_index, _ = find_metadata_step(compliance_path, compliance_steps)
    arch_cache_index, arch_setup_index = check_architecture_checkout(
        compliance_path, compliance_steps
    )
    compliance_gate_index, compliance_gate = direct_gate_step(
        compliance_path, compliance_steps, "make compliance", "compliance gate"
    )
    require_gate_env(
        compliance_path,
        compliance_gate,
        {
            "ARCH_TEST": "/home/runner/riscv-arch-test",
            "ARCH_TEST_EXPECTED": "${{ steps.refs.outputs.arch_test_expected }}",
        },
        "compliance gate",
    )
    if not (
        metadata_index < arch_cache_index < arch_setup_index < compliance_gate_index
    ):
        raise ContractError("compliance required steps are out of order")

    lockstep_path, _, lockstep_jobs = parsed["lockstep.yml"]
    lockstep_job = required_job(lockstep_path, lockstep_jobs, "lockstep")
    lockstep_steps = lockstep_job.steps
    lock_metadata_index, _ = find_metadata_step(lockstep_path, lockstep_steps)
    lock_arch_cache_index, lock_arch_setup_index = check_architecture_checkout(
        lockstep_path, lockstep_steps
    )
    spike_cache_index, spike_setup_index = check_spike_checkout(
        lockstep_path, lockstep_steps
    )
    try:
        lockstep_gate_index, lockstep_gate = direct_gate_step(
            lockstep_path, lockstep_steps, "make lockstep", "lockstep gate"
        )
    except ContractError as exc:
        raise ContractError(
            "lockstep workflow must run make lockstep before random soak; " + str(exc)
        ) from exc
    try:
        soak_gate_index, soak_gate = direct_gate_step(
            lockstep_path,
            lockstep_steps,
            "make soak-lockstep SEEDS=200",
            "lockstep soak gate",
        )
    except ContractError as exc:
        raise ContractError(
            "lockstep workflow must run exactly make soak-lockstep SEEDS=200; " + str(exc)
        ) from exc
    require_gate_env(
        lockstep_path,
        lockstep_gate,
        {
            "ARCH_TEST": "/home/runner/riscv-arch-test",
            "ARCH_TEST_EXPECTED": "${{ steps.refs.outputs.arch_test_expected }}",
            "SPIKE": "/home/runner/riscv-isa-sim/build/spike",
        },
        "lockstep gate",
    )
    require_gate_env(
        lockstep_path,
        soak_gate,
        {"SPIKE": "/home/runner/riscv-isa-sim/build/spike"},
        "lockstep soak gate",
    )
    if not (
        lock_metadata_index
        < lock_arch_cache_index
        < lock_arch_setup_index
        < spike_cache_index
        < spike_setup_index
        < lockstep_gate_index
        < soak_gate_index
    ):
        raise ContractError("lockstep required steps are out of order")


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
