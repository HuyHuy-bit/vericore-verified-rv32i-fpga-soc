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
FACT_KEYS = (
    "ISA",
    "DIRECTED_TESTS",
    "ASSERTIONS_TOTAL",
    "ASSERTIONS_CONCURRENT",
    "ASSERTIONS_IMMEDIATE",
    "SOURCE_COVER_POINTS",
    "TRACKED_COVERAGE_HIT",
    "TRACKED_COVERAGE_TOTAL",
    "TRACKED_COVERAGE_STATUS",
    "CI_CONFIGS",
    "CI_MATRIX",
    "ARCH_TEST_SHA",
    "ARCH_TEST_EXPECTED",
    "SPIKE_SHA",
    "SPIKE_RANDOM_SEEDS",
)
FACT_DOCUMENTS = (
    "README.md",
    "docs/architecture.md",
    "docs/verification.md",
    "docs/evidence.md",
)
RESULT_RECORDS = (
    "manifest.json",
    "verification.json",
    "benchmarks.csv",
    "synthesis.csv",
    "tool_versions.json",
)
CANONICAL_ISA = "RV32I_Zicsr_Zifencei"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
COUNT_RE = re.compile(r"[1-9][0-9]*\Z")
ASSIGNMENT_RE = re.compile(r"([A-Z][A-Z0-9_]*)=([^\s#]+)\Z")
REQUIRED_PATHS = (
    "rtl/**",
    "sim/**",
    "Makefile",
    "bench/**",
    "compliance/**",
    "containers/**",
    ".devcontainer/**",
    "tools/**",
    "tests/**",
    "results/**",
)
EVIDENCE_PATHS = ("README.md", "docs/**")
CHECKOUT_ACTION = "actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955"
CACHE_ACTION = "actions/cache@0400d5f644dc74513175e3cd8d07132dd4860809"
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
STEP_NAMES = {
    "compliance": (
        "Check out rv32i-pipeline",
        "Install RISC-V toolchain",
        "Install Verilator (conda-forge)",
        "Install verilator package",
        "Load reference versions",
        "Cache riscv-arch-test",
        "Fetch pinned riscv-arch-test checkout",
        "Build simulator",
        "Run compliance suite",
    ),
    "lockstep": (
        "Check out repo",
        "Install toolchain",
        "Install Verilator (conda-forge)",
        "Install verilator package",
        "Load reference versions",
        "Cache riscv-arch-test",
        "Fetch pinned riscv-arch-test checkout",
        "Cache Spike source and build",
        "Fetch and build pinned Spike",
        "Run complete architecture-test traces against Spike",
        "Random programs against Spike (with control flow)",
    ),
    "test-matrix": (
        "Check out repo",
        "Install Verilator (conda-forge)",
        "Install verilator package",
        "Run full test suite (${{ matrix.name }})",
    ),
}
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
    'test -z "$(git -C "$HOME/riscv-arch-test" status --short --untracked-files=all)"',
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
    'test -z "$(git -C "$HOME/riscv-isa-sim" status --short --untracked-files=all)"',
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
    if key[:1] in ("'", '"'):
        if len(key) < 2 or key[-1] != key[0]:
            raise ContractError(f"unsupported quoted workflow key: {key}")
        key = key[1:-1]
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
                    raise ContractError(f"unsupported workflow step property: {line.text}")
                key, value = entry
                if key in step.values or key in step.nested:
                    raise ContractError(f"duplicate workflow step property: {key}")
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
                        if child_entry is None:
                            raise ContractError(
                                f"unsupported nested workflow property: {child.text}"
                            )
                        if child_entry[0] in mapping:
                            raise ContractError(
                                f"duplicate nested workflow property: {child_entry[0]}"
                            )
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
            if entry is None:
                raise ContractError(f"{path.name}: unsupported job property: {line.text}")
            if entry[0] in values:
                raise ContractError(f"{path.name}: duplicate job property: {entry[0]}")
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
        Path(".verify-cache"),
        Path(".portfolio-runs"),
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
        hex_stream = "".join(re.findall(r"[0-9a-f]+", code.lower()))
        if "ARCH_TEST_EXPECTED_CASES" in code:
            raise ContractError(f"legacy ARCH_TEST_EXPECTED_CASES in {path.relative_to(root)}")
        for pin in literal_pins:
            if (
                re.search(rf"(?<![0-9a-f]){re.escape(pin)}(?![0-9a-f])", code)
                or pin in hex_stream
            ):
                raise ContractError(
                    "literal reference pin duplicated in executable consumer: "
                    f"{path.relative_to(root)}"
                )
        expected = re.escape(versions["ARCH_TEST_EXPECTED"])
        assignment = re.compile(
            rf"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
            rf"['\"]?{expected}['\"]?(?![0-9])"
        )
        for match in assignment.finditer(code):
            name = match.group(1)
            if name != "ARCH_TEST_EXPECTED" and alternate_count_name(name):
                message = "alternate expected architecture count duplicated"
            else:
                message = "literal expected architecture count duplicated"
            raise ContractError(
                f"{message} in executable consumer: {path.relative_to(root)}"
            )
        for match in re.finditer(
            r"(?<![A-Z0-9_])([A-Z][A-Z0-9_]*)\s*(?:\+?=)", code
        ):
            name = match.group(1)
            if name != "ARCH_TEST_EXPECTED" and alternate_count_name(name):
                raise ContractError(
                    "alternate expected architecture count assignment in executable consumer: "
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
    event_index = event_lines[0][0]
    section = block_after(on_block, event_index)
    if event == "workflow_dispatch":
        if section:
            raise ContractError(f"{workflow.name}: workflow_dispatch event must be empty")
        return []
    direct_entries = []
    for line in section:
        if line.indent != 4:
            continue
        entry = parse_mapping_entry(line.text)
        if entry is None:
            raise ContractError(f"{workflow.name}: malformed {event} event property")
        direct_entries.append(entry[0])
    if direct_entries != ["paths"]:
        raise ContractError(f"{workflow.name}: {event} event may contain only paths")
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
            raw = line.text[2:].strip()
            if re.search(r"(^|\s)[&*][^\s]+", raw) or raw.startswith("!!"):
                raise ContractError(
                    f"{workflow.name}: event paths must not use YAML anchors or aliases"
                )
            paths.append(yaml_scalar(raw))
    return paths


def check_triggers(path: Path, lines: list[YamlLine]) -> None:
    event_paths(lines, path, "workflow_dispatch")
    required = set(REQUIRED_PATHS) | {f".github/workflows/{path.name}"}
    if path.name == "rtl-tests.yml":
        required.update(EVIDENCE_PATHS)
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


def step_description(job_name: str, step: WorkflowStep) -> str:
    name = step.values.get("name", "")
    if name == "Run compliance suite":
        return "compliance gate"
    if name == "Run complete architecture-test traces against Spike":
        return "lockstep gate"
    if name == "Random programs against Spike (with control flow)":
        return "lockstep soak gate"
    return "required step"


def validate_required_job(path: Path, name: str, job: WorkflowJob) -> None:
    allowed = {"runs-on", "defaults", "steps"}
    if name == "test-matrix":
        allowed.add("strategy")
    if set(job.values) != allowed:
        raise ContractError(f"{name} job has unsupported properties")
    if job.values["runs-on"] != "ubuntu-latest":
        raise ContractError(f"{name} job must run on ubuntu-latest")

    defaults = []
    for index, line in enumerate(job.lines):
        if line.indent != 4:
            continue
        entry = parse_mapping_entry(line.text)
        if entry and entry[0] == "defaults":
            defaults.append(index)
    if len(defaults) != 1:
        raise ContractError(f"{name} job must use the canonical defaults shell")
    default_lines = block_after(job.lines, defaults[0])
    if [(line.indent, line.text) for line in default_lines] != [
        (6, "run:"),
        (8, "shell: bash -l {0}"),
    ]:
        raise ContractError(f"{name} job must use the canonical defaults shell")

    for step in job.steps:
        reject_step_controls(step)
        if not set(step.values) <= {"name", "id", "uses", "run"} or not set(
            step.nested
        ) <= {"env", "with"}:
            description = step_description(name, step)
            raise ContractError(f"{description} has unsupported properties")


def validate_step_sequence(name: str, job: WorkflowJob) -> None:
    actual = tuple(step.values.get("name", "") for step in job.steps)
    if actual != STEP_NAMES[name]:
        raise ContractError(f"{name} job step sequence is not canonical")


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
        if (
            any("status --short --untracked-files=" in line for line in run)
            and ARCH_SETUP_RUN[-1] not in run
        ):
            raise ContractError(
                f"{path.name}: architecture-test setup must verify a fully clean checkout"
            )
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


def check_container_job(
    path: Path,
    jobs: dict[str, WorkflowJob],
    name: str,
    commands: tuple[str, ...],
    cache: bool,
    full_history: bool = False,
) -> None:
    job = required_job(path, jobs, name)
    if set(job.values) != {"runs-on", "timeout-minutes", "steps"}:
        raise ContractError(f"{path.name}: {name} job has unsupported properties")
    if job.values["runs-on"] != "ubuntu-24.04":
        raise ContractError(f"{path.name}: {name} job must use ubuntu-24.04")
    timeout = int(job.values["timeout-minutes"])
    if timeout < 60 or timeout > 180:
        raise ContractError(f"{path.name}: {name} timeout is outside the approved range")
    for step in job.steps:
        reject_step_controls(step)
        if not set(step.values) <= {"name", "uses", "run"} or not set(step.nested) <= {"with"}:
            raise ContractError(f"{path.name}: unsupported container workflow step")
    uses = [step for step in job.steps if "uses" in step.values]
    expected_uses = [CHECKOUT_ACTION] + ([CACHE_ACTION] if cache else [])
    if [step.values["uses"] for step in uses] != expected_uses:
        raise ContractError(f"{path.name}: action dependencies must use approved immutable commits")
    if not job.steps or job.steps[0].values.get("uses") != CHECKOUT_ACTION:
        raise ContractError(f"{path.name}: checkout must be the first step")
    checkout_with = job.steps[0].nested.get("with", {})
    expected_checkout_with = {"fetch-depth": "0"} if full_history else {}
    if checkout_with != expected_checkout_with:
        if full_history:
            raise ContractError(f"{path.name}: evidence checkout must fetch full history")
        raise ContractError(f"{path.name}: checkout properties are not canonical")
    command_steps = [step for step in job.steps if "run" in step.values]
    if tuple(step.run.strip() for step in command_steps) != commands:
        raise ContractError(f"{path.name}: container verification commands are not canonical")
    if cache:
        cache_steps = [step for step in uses if step.values["uses"] == CACHE_ACTION]
        if len(cache_steps) != 1 or cache_steps[0].nested.get("with") != {
            "path": ".verify-cache",
            "key": "verify-references-${{ hashFiles('tools/reference_versions.env', 'tools/tool_versions.env') }}",
        }:
            raise ContractError(f"{path.name}: reference cache contract is not canonical")


def check_container_workflows(
    parsed: dict[str, tuple[Path, list[YamlLine], dict[str, WorkflowJob]]]
) -> None:
    rtl_path, _, rtl_jobs = parsed["rtl-tests.yml"]
    check_container_job(
        rtl_path,
        rtl_jobs,
        "verification",
        (
            "python3 tools/verification.py container --profile fast",
            "python3 tools/verification.py container --profile directed-memory",
            "python3 tools/verification.py container --profile directed-predictor",
            "python3 tools/verification.py container --profile portfolio",
        ),
        False,
        True,
    )
    compliance_path, _, compliance_jobs = parsed["compliance.yml"]
    check_container_job(
        compliance_path,
        compliance_jobs,
        "compliance",
        ("python3 tools/verification.py container --profile compliance",),
        True,
    )
    lockstep_path, _, lockstep_jobs = parsed["lockstep.yml"]
    check_container_job(
        lockstep_path,
        lockstep_jobs,
        "lockstep",
        (
            "python3 tools/verification.py container --profile lockstep",
            "python3 tools/verification.py container --profile random-spike",
        ),
        True,
    )


def check_workflows(root: Path) -> None:
    workflow_dir = root / ".github/workflows"
    parsed: dict[str, tuple[Path, list[YamlLine], dict[str, WorkflowJob]]] = {}
    for name in ("rtl-tests.yml", "compliance.yml", "lockstep.yml"):
        path = workflow_dir / name
        lines = workflow_lines(path)
        check_triggers(path, lines)
        parsed[name] = (path, lines, parse_jobs(path, lines))

    if "verification" in parsed["rtl-tests.yml"][2]:
        check_container_workflows(parsed)
        return

    rtl_path, _, rtl_jobs = parsed["rtl-tests.yml"]
    fast_job = required_job(rtl_path, rtl_jobs, "lint-and-test")
    validate_required_job(rtl_path, "lint-and-test", fast_job)
    _, fast_gate = direct_gate_step(
        rtl_path,
        fast_job.steps,
        "make check",
        "fast workflow gate",
    )
    if set(fast_gate.values) != {"name", "run"} or fast_gate.nested:
        raise ContractError("fast workflow gate has unsupported properties")
    rtl_job = required_job(rtl_path, rtl_jobs, "test-matrix")
    validate_required_job(rtl_path, "test-matrix", rtl_job)
    if parse_directed_matrix(rtl_job.lines) != DIRECTED_MATRIX:
        raise ContractError("directed CI matrix does not match the six approved configurations")
    direct_gate_step(
        rtl_path,
        rtl_job.steps,
        "make all ${{ matrix.args }}",
        "test-matrix gate",
    )
    validate_step_sequence("test-matrix", rtl_job)

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
    validate_required_job(compliance_path, "compliance", compliance_job)
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
    validate_step_sequence("compliance", compliance_job)

    lockstep_path, _, lockstep_jobs = parsed["lockstep.yml"]
    lockstep_job = required_job(lockstep_path, lockstep_jobs, "lockstep")
    validate_required_job(lockstep_path, "lockstep", lockstep_job)
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
    validate_step_sequence("lockstep", lockstep_job)


def check_contracts(root: Path) -> None:
    versions = parse_reference_versions(root)
    check_symbolic_consumers(root, versions)
    check_workflows(root)


def make_test_names(root: Path) -> tuple[str, ...]:
    path = root / "Makefile"
    source = path.read_text(encoding="utf-8")
    logical: list[str] = []
    pending = ""
    for raw in source.splitlines():
        line = strip_inline_comment(raw).rstrip()
        if line.endswith("\\"):
            pending += line[:-1].strip() + " "
            continue
        logical.append((pending + line.strip()).strip())
        pending = ""
    matches = []
    for line in logical:
        match = re.fullmatch(r"TESTS\s*=\s*(.*)", line)
        if match:
            matches.append(match.group(1).split())
    if len(matches) != 1 or not matches[0]:
        raise ContractError("Makefile must define one nonempty directed TESTS list")
    names = tuple(matches[0])
    if len(names) != len(set(names)) or any(
        re.fullmatch(r"t[0-9][0-9]_[A-Za-z0-9_]+", name) is None for name in names
    ):
        raise ContractError("Makefile directed TESTS list is malformed or duplicated")
    return names


def make_target(root: Path, name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    lines = (root / "Makefile").read_text(encoding="utf-8").splitlines()
    matches = []
    for index, line in enumerate(lines):
        match = re.fullmatch(rf"{re.escape(name)}\s*:\s*(.*)", line)
        if match:
            matches.append((index, tuple(match.group(1).split())))
    if len(matches) != 1:
        raise ContractError(f"Makefile must define exactly one {name} target")
    index, dependencies = matches[0]
    recipes: list[str] = []
    for line in lines[index + 1:]:
        if line.startswith("\t"):
            recipes.append(line[1:].strip())
        elif line.strip():
            break
    return dependencies, tuple(recipes)


def check_build_surface(root: Path) -> None:
    evidence_dependencies, evidence_recipes = make_target(root, "evidence-check")
    if evidence_dependencies or evidence_recipes != (
        "python3 -m unittest -v tools.test_evidence_check",
        "python3 tools/evidence_check.py",
    ):
        raise ContractError("evidence-check target must run its tests and checker")
    check_dependencies, check_recipes = make_target(root, "check")
    if check_dependencies != ("unit", "harness-test", "lint", "evidence-check") or check_recipes:
        raise ContractError("check target must depend on exact fast gates")


def check_directed_inventory(root: Path) -> tuple[str, ...]:
    names = make_test_names(root)
    test_dir = root / "tests"
    sources = {path.stem for path in test_dir.glob("*.s")}
    references = {path.stem for path in test_dir.glob("*.ref")}
    listed = set(names)
    if listed != sources or listed != references:
        details = {
            "missing_source": sorted(listed - sources),
            "missing_reference": sorted(listed - references),
            "unlisted_source": sorted(sources - listed),
            "unlisted_reference": sorted(references - listed),
        }
        raise ContractError(f"directed test inventory mismatch: {details}")
    return names


def strip_sv_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", source)


def rtl_property_counts(root: Path) -> tuple[int, int, int]:
    source = "\n".join(
        strip_sv_comments(path.read_text(encoding="utf-8", errors="replace"))
        for path in sorted((root / "rtl").rglob("*.sv"))
    )
    concurrent = len(re.findall(r"\bassert\s+property\s*\(", source))
    immediate = len(re.findall(r"\bassert\s*\(", source))
    covers = len(re.findall(r"\bcover\s+property\s*\(", source))
    return concurrent, immediate, covers


def coverage_facts(root: Path) -> tuple[int, int, str]:
    path = root / "docs/coverage.md"
    source = path.read_text(encoding="utf-8")
    statuses = re.findall(r"\*\*Evidence status: (historical|current)\.\*\*", source)
    summaries = re.findall(
        r"\*\*([0-9]+)/([0-9]+) cover points hit \(([0-9]+(?:\.[0-9]+)?)%\)\*\*",
        source,
    )
    if len(statuses) != 1 or len(summaries) != 1:
        raise ContractError("docs/coverage.md must contain one status and one coverage summary")
    hit, total, percentage = summaries[0]
    hit_value = int(hit)
    total_value = int(total)
    if total_value <= 0 or hit_value > total_value:
        raise ContractError("docs/coverage.md contains an invalid coverage count")
    expected_percentage = 100.0 * hit_value / total_value
    if abs(float(percentage) - expected_percentage) > 0.05:
        raise ContractError("docs/coverage.md coverage percentage does not match its counts")
    return hit_value, total_value, statuses[0]


def document_facts(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    begin = "<!-- evidence-facts:begin -->"
    end = "<!-- evidence-facts:end -->"
    if (
        source.count(begin) != 1
        or source.count(end) != 1
        or source.find(begin) > source.find(end)
    ):
        raise ContractError(f"{relative}: expected one evidence fact block")
    block = source.split(begin, 1)[1].split(end, 1)[0]
    facts: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.fullmatch(r"EVIDENCE_FACT ([A-Z][A-Z0-9_]*)=(\S+)", line)
        if match is None:
            raise ContractError(f"{relative}: malformed evidence fact: {line}")
        key, value = match.groups()
        if key in facts:
            raise ContractError(f"{relative}: duplicate evidence fact {key}")
        facts[key] = value
    missing = [key for key in FACT_KEYS if key not in facts]
    extra = [key for key in facts if key not in FACT_KEYS]
    if missing:
        raise ContractError(f"{relative}: missing evidence fact {missing[0]}")
    if extra:
        raise ContractError(f"{relative}: unknown evidence fact {extra[0]}")
    return facts


def workflow_seed(root: Path) -> int:
    path = root / ".github/workflows/lockstep.yml"
    jobs = parse_jobs(path, workflow_lines(path))
    job = required_job(path, jobs, "lockstep")
    seeds = []
    for step in job.steps:
        match = re.fullmatch(r"make soak-lockstep SEEDS=([1-9][0-9]*)", step.run.strip())
        if match:
            seeds.append(int(match.group(1)))
        if step.run.strip() == "python3 tools/verification.py container --profile random-spike":
            source = (root / "tools/verification.py").read_text(encoding="utf-8")
            matches = re.findall(
                r'Command\("random-spike".*?"SEEDS=([1-9][0-9]*)"',
                source,
                re.DOTALL,
            )
            if len(matches) != 1:
                raise ContractError("random-spike profile must expose one seed count")
            seeds.append(int(matches[0]))
    if len(seeds) != 1:
        raise ContractError("lockstep workflow must expose one Spike random seed count")
    return seeds[0]


def check_published_portfolio(
    root: Path,
    record_validator: Callable[[Path, Path], list[str]] | None = None,
    document_checker: Callable[[Path], list[str]] | None = None,
) -> None:
    result_root = root / "results"
    present = {name for name in RESULT_RECORDS if (result_root / name).is_file()}
    if not present:
        return
    if present != set(RESULT_RECORDS):
        missing = sorted(set(RESULT_RECORDS) - present)
        raise ContractError(f"result records are incomplete: missing {missing[0]}")
    if record_validator is None or document_checker is None:
        if __package__:
            from .render_portfolio import check_documents
            from .results import validate_result_set
        else:
            from render_portfolio import check_documents
            from results import validate_result_set
        record_validator = record_validator or validate_result_set
        document_checker = document_checker or check_documents
    for errors in (
        record_validator(result_root, root),
        document_checker(root),
    ):
        if errors:
            raise ContractError(errors[0])


def check_repository_evidence(root: Path) -> None:
    versions = parse_reference_versions(root)
    check_build_surface(root)
    tests = check_directed_inventory(root)
    concurrent, immediate, covers = rtl_property_counts(root)
    hit, coverage_total, coverage_status = coverage_facts(root)
    if coverage_status == "current" and coverage_total != covers:
        raise ContractError(
            f"current coverage total {coverage_total} does not match source cover count {covers}"
        )

    rtl_path = root / ".github/workflows/rtl-tests.yml"
    rtl_jobs = parse_jobs(rtl_path, workflow_lines(rtl_path))
    if "verification" in rtl_jobs:
        matrix = DIRECTED_MATRIX
    else:
        matrix = parse_directed_matrix(required_job(rtl_path, rtl_jobs, "test-matrix").lines)
    expected = {
        "ISA": CANONICAL_ISA,
        "DIRECTED_TESTS": str(len(tests)),
        "ASSERTIONS_TOTAL": str(concurrent + immediate),
        "ASSERTIONS_CONCURRENT": str(concurrent),
        "ASSERTIONS_IMMEDIATE": str(immediate),
        "SOURCE_COVER_POINTS": str(covers),
        "TRACKED_COVERAGE_HIT": str(hit),
        "TRACKED_COVERAGE_TOTAL": str(coverage_total),
        "TRACKED_COVERAGE_STATUS": coverage_status,
        "CI_CONFIGS": str(len(matrix)),
        "CI_MATRIX": ",".join(name for name, _ in matrix),
        "ARCH_TEST_SHA": versions["ARCH_TEST_SHA"],
        "ARCH_TEST_EXPECTED": versions["ARCH_TEST_EXPECTED"],
        "SPIKE_SHA": versions["SPIKE_SHA"],
        "SPIKE_RANDOM_SEEDS": str(workflow_seed(root)),
    }
    documents = {relative: document_facts(root, relative) for relative in FACT_DOCUMENTS}
    for key in FACT_KEYS:
        values = {relative: facts[key] for relative, facts in documents.items()}
        if len(set(values.values())) != 1:
            raise ContractError(f"conflicting evidence fact {key}: {values}")
        actual = next(iter(values.values()))
        if actual != expected[key]:
            raise ContractError(
                f"evidence fact {key}={actual} does not match derived value {expected[key]}"
            )
    check_published_portfolio(root)


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
        if not args.contracts_only:
            check_repository_evidence(root)
    except (ContractError, OSError) as exc:
        print(f"evidence check failed: {exc}", file=sys.stderr)
        return 1
    if args.contracts_only:
        print("reference and CI contracts: OK")
    else:
        print("repository evidence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
