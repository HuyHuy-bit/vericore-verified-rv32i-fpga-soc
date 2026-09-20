#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import tempfile

if __package__:
    from .results import (
        ResultSet, evidence_state, load_json, load_result_set, synthesis_commits,
        validate_result_set,
    )
else:
    from results import (
        ResultSet, evidence_state, load_json, load_result_set, synthesis_commits,
        validate_result_set,
    )


DOCUMENT_BLOCKS = {
    "README.md": ("facts", "status", "soc", "snapshot", "verification", "benchmarks", "synthesis", "provenance"),
    "docs/evidence.md": ("overview", "facts", "status", "soc", "verification", "benchmarks", "synthesis", "synthesis-hashes", "provenance"),
    "docs/architecture.md": ("facts", "status", "benchmarks", "synthesis"),
    "docs/verification.md": ("facts", "status", "summary"),
}
MARKER_RE = re.compile(r"<!-- portfolio:([a-z][a-z0-9-]*):(start|end) -->")


class RenderError(ValueError):
    pass


def replace_block(source: str, name: str, contents: str) -> str:
    start = f"<!-- portfolio:{name}:start -->"
    end = f"<!-- portfolio:{name}:end -->"
    if source.count(start) == 0 or source.count(end) == 0:
        raise RenderError(f"missing marker for portfolio block {name}")
    if source.count(start) != 1 or source.count(end) != 1:
        raise RenderError(f"portfolio block {name} must have exactly one marker pair")
    start_index = source.index(start)
    end_index = source.index(end)
    if start_index > end_index:
        raise RenderError(f"portfolio block {name} start must appear before its end")
    inner_start = start_index + len(start)
    if MARKER_RE.search(source[inner_start:end_index]):
        raise RenderError(f"nested marker in portfolio block {name}")
    return source[:inner_start] + "\n" + contents.strip() + "\n" + source[end_index:]


def percentage(numerator: int, denominator: int) -> str:
    return "n/a" if denominator == 0 else f"{100.0 * numerator / denominator:.1f}%"


def soc_status(result_root: Path) -> str:
    path = result_root / "soc.json"
    if not path.exists():
        return "Physical-board evidence: not published"
    value = load_json(path)
    route = value["route"]
    return "\n".join((
        "Physical-board evidence: published and validated",
        "",
        "| Board | Part | LUT | FF | BRAM tiles | WNS (ns) | fmax (MHz) |",
        "|---|---|---:|---:|---:|---:|---:|",
        f"| {value['board']} | `{value['part']}` | {route['lut']:,} | "
        f"{route['ff']:,} | {route['bram_tiles']} | {route['wns_ns']} | "
        f"{route['fmax_mhz']} |",
    ))


def benchmark_table(result: ResultSet) -> str:
    names = ("slow-memory", "icache", "write-back", "ideal-memory")
    labels = ("10-cycle uncached", "+1KB 4-way I$", "+4KB 4-way WB D$", "1-cycle uncached")
    rows = {(row["kernel"], row["configuration"]): row for row in result.benchmarks}
    lines = [
        "| Kernel | " + " | ".join(labels) + " |",
        "|---|" + "---:|" * len(labels),
    ]
    for kernel in ("crc32", "matmul", "sort", "llist", "interp"):
        cells = []
        for name in names:
            row = rows[(kernel, name)]
            cycles = int(row["cycles"])
            retired = int(row["instructions_retired"])
            cells.append(f"{cycles:,} / {cycles / retired:.5f}")
        lines.append(f"| {kernel} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def synthesis_table(result: ResultSet) -> str:
    labels = {
        "core": "Core",
        "icache": "+1KB 4-way I$",
        "dcache-wt": "+4KB 4-way WT D$",
        "dcache-wb": "+4KB 4-way WB D$",
    }
    lines = [
        "| Configuration | LUT | FF | BRAM tiles | WNS (ns) | Critical path (ns) | fmax (MHz) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result.synthesis:
        lines.append(
            f"| {labels[row['configuration']]} | {int(row['lut']):,} | {int(row['ff']):,} | "
            f"{row['bram_tiles']} | {row['wns_ns']} | {row['critical_path_ns']} | {row['fmax_mhz']} |"
        )
    return "\n".join(lines)


def snapshot(result: ResultSet) -> str:
    verification = result.verification
    assertions = verification["assertions"]["concurrent"] + verification["assertions"]["immediate"]
    frequencies = [float(row["fmax_mhz"]) for row in result.synthesis]
    return (
        f"> **Portfolio Snapshot** — 5-stage `RV32I_Zicsr_Zifencei` • {verification['directed_programs']} directed tests × "
        f"{len(verification['memory_configurations'])} memory configurations • "
        f"{len(verification['predictor_configurations'])} predictor configurations • "
        f"{verification['architecture_tests']['passed']}/{verification['architecture_tests']['discovered']} architecture signatures • "
        f"{verification['architecture_lockstep']['passed']}/{verification['architecture_lockstep']['discovered']} Spike lockstep • "
        f"{verification['spike_random']['passed']}/{verification['spike_random']['requested']} random Spike seeds • "
        f"{assertions} assertions • {verification['cover_points']['hit']}/{verification['cover_points']['source']} functional cover points • "
        f"{min(frequencies):.1f}–{max(frequencies):.1f} MHz routed Artix-7 implementations"
    )


def verification_table(result: ResultSet) -> str:
    value = result.verification
    return "\n".join((
        "| Metric | Value | How measured |",
        "|---|---:|---|",
        f"| Decoder unit vectors | {value['decoder_vectors']:,}/{value['decoder_vectors']:,} | `make unit` |",
        f"| Hazard unit vectors | {value['hazard_vectors']:,}/{value['hazard_vectors']:,} | `make unit` |",
        f"| Harness tests | {value['harness_tests']}/{value['harness_tests']} | `make harness-test` |",
        f"| Directed memory matrix | {sum(item['passed'] for item in value['memory_configurations'])}/{value['directed_programs'] * len(value['memory_configurations'])} | `make verify` |",
        f"| Predictor matrix | {sum(item['passed'] for item in value['predictor_configurations'])}/{value['directed_programs'] * len(value['predictor_configurations'])} | `make predictor-test` |",
        f"| Architecture signatures | {value['architecture_tests']['passed']}/{value['architecture_tests']['discovered']} | `make compliance` |",
        f"| Architecture Spike lockstep | {value['architecture_lockstep']['passed']}/{value['architecture_lockstep']['discovered']} | `make lockstep` |",
        f"| Python-model random | {value['python_random']['baseline']['passed'] + value['python_random']['cached']['passed']}/{value['python_random']['baseline']['requested'] + value['python_random']['cached']['requested']} | `make soak SEEDS=1000` |",
        f"| Random Spike lockstep | {value['spike_random']['passed']}/{value['spike_random']['requested']} | `make soak-lockstep SEEDS=200` |",
        f"| Functional cover points | {value['cover_points']['hit']}/{value['cover_points']['source']} | `make coverage` |",
    ))


def facts(result: ResultSet, state: str, synthesis_state: str) -> str:
    value = result.verification
    assertions = value["assertions"]["concurrent"] + value["assertions"]["immediate"]
    matrix = ",".join(item["name"] for item in value["memory_configurations"])
    rows = "\n".join((
        "EVIDENCE_FACT ISA=RV32I_Zicsr_Zifencei",
        f"EVIDENCE_FACT DIRECTED_TESTS={value['directed_programs']}",
        f"EVIDENCE_FACT ASSERTIONS_TOTAL={assertions}",
        f"EVIDENCE_FACT ASSERTIONS_CONCURRENT={value['assertions']['concurrent']}",
        f"EVIDENCE_FACT ASSERTIONS_IMMEDIATE={value['assertions']['immediate']}",
        f"EVIDENCE_FACT SOURCE_COVER_POINTS={value['cover_points']['source']}",
        f"EVIDENCE_FACT TRACKED_COVERAGE_HIT={value['cover_points']['hit']}",
        f"EVIDENCE_FACT TRACKED_COVERAGE_TOTAL={value['cover_points']['source']}",
        f"EVIDENCE_FACT TRACKED_COVERAGE_STATUS={state}",
        f"EVIDENCE_FACT EVIDENCE_STATUS={state}",
        f"EVIDENCE_FACT SYNTHESIS_STATUS={synthesis_state}",
        f"EVIDENCE_FACT CI_CONFIGS={len(value['memory_configurations'])}",
        f"EVIDENCE_FACT CI_MATRIX={matrix}",
        f"EVIDENCE_FACT ARCH_TEST_SHA={result.tool_versions['architecture_test_commit']}",
        f"EVIDENCE_FACT ARCH_TEST_EXPECTED={result.tool_versions['architecture_test_expected']}",
        f"EVIDENCE_FACT SPIKE_SHA={result.tool_versions['spike_commit']}",
        f"EVIDENCE_FACT SPIKE_RANDOM_SEEDS={value['spike_random']['requested']}",
    ))
    return f"<!-- evidence-facts:begin -->\n{rows}\n<!-- evidence-facts:end -->"


def evidence_notice(result: ResultSet, state: str, synthesis_state: str) -> str:
    if state == "current":
        lines = ["Current measurements — validated for the checked-out RTL."]
    else:
        lines = [
            "Historical measurements — validated for RTL "
            f"{result.manifest['rtl_commit']}; current RTL changes are not yet remeasured."
        ]
    # Synthesis needs Vivado, so the implementation table can lag the
    # open-source evidence. Say so separately rather than letting one status
    # speak for measurements taken at two different commits.
    if synthesis_state == "historical":
        commits = synthesis_commits(result)
        measured = commits[1] if commits else result.manifest["rtl_commit"]
        lines.append(
            "Historical synthesis — the implementation table was measured for RTL "
            f"{measured}; current RTL changes are not yet resynthesised."
        )
    return "\n".join(lines)


def provenance(result: ResultSet) -> str:
    tools = result.tool_versions
    synth = result.synthesis[0]
    return "\n".join((
        f"- Measurement timestamp: `{result.manifest['measured_at']}`",
        f"- Tooling commit: `{result.manifest['tooling_commit']}`",
        f"- Frozen RTL commit: `{result.manifest['rtl_commit']}`",
        f"- Canonical container: `{tools['container']['image']}:{tools['container']['revision']}`",
        f"- Open tools: Ubuntu {tools['ubuntu']}; Verilator {tools['verilator']}; RISC-V GCC {tools['riscv_gcc']}; RISC-V assembler {tools['riscv_as']}; Python {tools['python']}",
        f"- Vivado: {synth['vivado_version']} build {synth['vivado_build']}; `{synth['part']}`; measured {synth['measurement_date']}",
        "- Reproduce verification: `make verify`",
        "- Reproduce benchmarks: `make bench` with the recorded headline configuration",
        "- Reproduce implementation: `make synth-matrix && make synth-summary`",
    ))


def evidence_overview(result: ResultSet) -> str:
    tools = result.tool_versions
    synth = result.synthesis[0]
    container = tools["container"]
    return "\n\n".join((
        (
            "This ledger separates source-derived facts, pinned external inputs, "
            "current measurements, and historical design studies. Open-source gates "
            f"were measured at `{result.verification['measured_at']}`; the compact "
            f"result set was published at `{result.manifest['measured_at']}`; Vivado "
            f"manifests record `{synth['measurement_date']}`. The tooling commit is "
            f"`{result.manifest['tooling_commit']}`, and the frozen RTL baseline is "
            f"`{result.manifest['rtl_commit']}`."
        ),
        (
            f"The pinned environment is Ubuntu {tools['ubuntu']} in "
            f"`{container['image']}:{container['revision']}` "
            f"(`{container['digest']}`), Verilator {tools['verilator']}, Python "
            f"{tools['python']}, RISC-V GCC {tools['riscv_gcc']} with assembler "
            f"{tools['riscv_as']}, Spike `{tools['spike_commit']}`, architecture tests "
            f"`{tools['architecture_test_commit']}`, and Vivado "
            f"{synth['vivado_version']} build {synth['vivado_build']}."
        ),
    ))


def synthesis_hashes(result: ResultSet) -> str:
    labels = {
        "core": "core",
        "icache": "I$",
        "dcache-wt": "D$ write-through",
        "dcache-wb": "D$ write-back",
    }
    lines = [
        "The SHA-256 pairs below are `utilization.rpt` / `timing_summary.rpt`:",
        "",
        "| Configuration | Report hashes |",
        "|---|---|",
    ]
    for row in result.synthesis:
        lines.append(
            f"| {labels[row['configuration']]} | `{row['utilization_sha256']}` / "
            f"`{row['timing_sha256']}` |"
        )
    return "\n".join(lines)


def summary(result: ResultSet) -> str:
    value = result.verification
    user = value["coverage"]["user"]
    return (
        f"The release gate runs {value['directed_programs']} programs across "
        f"{len(value['memory_configurations'])} memory configurations and "
        f"{len(value['predictor_configurations'])} predictor configurations. "
        f"Pinned architecture signatures and complete Spike traces both pass "
        f"{value['architecture_tests']['passed']}/{value['architecture_tests']['discovered']}; "
        f"random Spike lockstep passes {value['spike_random']['passed']}/{value['spike_random']['requested']}; "
        f"functional coverage is {user['hit']}/{user['total']} ({percentage(user['hit'], user['total'])})."
    )


def block_contents(result: ResultSet, state: str, synthesis_state: str) -> dict[str, str]:
    return {
        "overview": evidence_overview(result),
        "snapshot": snapshot(result),
        "verification": verification_table(result),
        "benchmarks": benchmark_table(result),
        "synthesis": synthesis_table(result),
        "synthesis-hashes": synthesis_hashes(result),
        "facts": facts(result, state, synthesis_state),
        "status": evidence_notice(result, state, synthesis_state),
        "provenance": provenance(result),
        "summary": summary(result),
        "soc": soc_status(result.root),
    }


def render_documents(root: Path, result_set: ResultSet) -> dict[Path, str]:
    root = root.resolve()
    state = evidence_state(root, result_set.manifest["rtl_commit"])
    # Disagreeing rows are validate_provenance's error, not the renderer's.
    synthesis = synthesis_commits(result_set)
    synthesis_rtl = synthesis[1] if synthesis else result_set.manifest["rtl_commit"]
    synthesis_state = evidence_state(root, synthesis_rtl)
    contents = block_contents(result_set, state, synthesis_state)
    rendered: dict[Path, str] = {}
    for relative, names in DOCUMENT_BLOCKS.items():
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RenderError(f"missing portfolio document: {relative}") from exc
        found = {name for name, _ in MARKER_RE.findall(source)}
        if found != set(names):
            extra = found - set(names)
            missing = set(names) - found
            detail = f"unknown block {sorted(extra)[0]}" if extra else f"missing block {sorted(missing)[0]}"
            raise RenderError(f"{relative}: {detail}")
        for name in names:
            source = replace_block(source, name, contents[name])
        rendered[path] = source
    coverage = root / "docs/coverage.md"
    try:
        coverage_source = coverage.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RenderError("missing portfolio document: docs/coverage.md") from exc
    status_pattern = re.compile(r"\*\*Evidence status: (?:historical|current)\.\*\*")
    if len(status_pattern.findall(coverage_source)) != 1:
        raise RenderError("docs/coverage.md: expected one evidence status")
    rendered[coverage] = status_pattern.sub(
        f"**Evidence status: {state}.**", coverage_source
    )
    return rendered


def load_validated(root: Path) -> ResultSet:
    errors = validate_result_set(root / "results", root)
    if errors:
        raise RenderError("result records are invalid: " + "; ".join(errors))
    return load_result_set(root / "results")


def check_documents(root: Path) -> list[str]:
    root = root.resolve()
    try:
        rendered = render_documents(root, load_validated(root))
    except (RenderError, OSError) as exc:
        return [str(exc)]
    return [f"stale generated portfolio block: {path.relative_to(root)}" for path, value in rendered.items() if path.read_text(encoding="utf-8") != value]


def write_documents(root: Path) -> None:
    root = root.resolve()
    rendered = render_documents(root, load_validated(root))
    staged: dict[Path, Path] = {}
    try:
        for path, value in rendered.items():
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", delete=False,
            ) as handle:
                handle.write(value)
                staged[path] = Path(handle.name)
            staged[path].chmod(path.stat().st_mode)
        for path, temporary in staged.items():
            temporary.replace(path)
    finally:
        for temporary in staged.values():
            if temporary.exists():
                temporary.unlink()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.write:
            write_documents(args.root)
            print("rendered portfolio documentation")
            return 0
        errors = check_documents(args.root)
        if errors:
            for error in errors:
                print(f"portfolio render check failed: {error}", file=sys.stderr)
            return 1
        print("portfolio documentation matches result records")
        return 0
    except (RenderError, OSError, ValueError) as exc:
        print(f"portfolio rendering failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
