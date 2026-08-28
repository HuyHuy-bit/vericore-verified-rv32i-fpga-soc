#!/usr/bin/env python3
"""Behavioral tests for repository evidence-contract validation.

The approved reference tuple below is deliberately a test-only oracle, not an
operational input.  Production scripts and workflows must consume
``tools/reference_versions.env`` symbolically.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tools.evidence_check import ContractError, check_published_portfolio


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools/evidence_check.py"
APPROVED_REFERENCES = {
    "ARCH_TEST_SHA": "6f7f47bdc61c0c51c0cbf75789678a1235eeefc2",
    "ARCH_TEST_EXPECTED": "38",
    "SPIKE_SHA": "55b4658dbf574ba0b714083ec436ce2cb5be1998",
}


class PublishedPortfolioTest(unittest.TestCase):
    def test_media_can_be_absent_while_recording_the_first_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv32i-published-evidence-") as directory:
            root = Path(directory)
            (root / "results").mkdir()
            for name in (
                "manifest.json", "verification.json", "benchmarks.csv",
                "synthesis.csv", "tool_versions.json",
            ):
                (root / "results" / name).write_text("fixture\n", encoding="utf-8")
            check_published_portfolio(
                root,
                record_validator=lambda result_root, checkout: [],
                document_checker=lambda checkout: [],
            )


class EvidenceContractTest(unittest.TestCase):
    """Exercise the checker against isolated, mutable repository trees."""

    ARCH_SHA = "a" * 40
    SPIKE_SHA = "b" * 40
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
    MATRIX = (
        ("baseline", ""),
        ("slow-mem", "IMEM_LAT=10 DMEM_LAT=10"),
        ("icache-only", "IC_BYTES=1024 IC_WAYS=4 IMEM_LAT=10 DMEM_LAT=10"),
        ("wt", "IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=0 IMEM_LAT=10 DMEM_LAT=10"),
        ("wb", "IC_BYTES=1024 IC_WAYS=4 DC_BYTES=4096 DC_WAYS=4 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10"),
        ("assoc", "IC_BYTES=1024 IC_BLOCK=4 IC_WAYS=2 DC_BYTES=4096 DC_BLOCK=4 DC_WAYS=2 DC_WB=1 IMEM_LAT=10 DMEM_LAT=10"),
    )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-evidence-contract-")
        self.repo = Path(self.tmp.name)
        for directory in (
            "tools",
            "compliance",
            ".github/workflows",
        ):
            (self.repo / directory).mkdir(parents=True, exist_ok=True)
        self.write_metadata()
        self.write_consumers()
        self.write_workflow("rtl-tests.yml", self.rtl_workflow())
        self.write_workflow("compliance.yml", self.reference_workflow("compliance"))
        self.write_workflow("lockstep.yml", self.reference_workflow("lockstep"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, relative: str, contents: str, *, executable: bool = False) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
        if executable:
            path.chmod(path.stat().st_mode | 0o111)
        return path

    def write_metadata(self, contents: str | None = None) -> None:
        if contents is None:
            contents = (
                "# Shared external verification identities.\n"
                f"ARCH_TEST_SHA={self.ARCH_SHA}\n"
                "ARCH_TEST_EXPECTED=7\n"
                f"SPIKE_SHA={self.SPIKE_SHA}\n"
            )
        self.write("tools/reference_versions.env", contents)

    def write_consumers(self) -> None:
        self.write(
            "compliance/run_compliance.sh",
            """
            #!/usr/bin/env bash
            source tools/reference_versions.env
            test "$ARCH_TEST_SHA" = "$(git -C "$ARCH_TEST" rev-parse HEAD)"
            test "$PASS" -eq "$ARCH_TEST_EXPECTED"
            """,
            executable=True,
        )
        self.write(
            "tools/run_lockstep.sh",
            """
            #!/usr/bin/env bash
            source tools/reference_versions.env
            test "$ARCH_TEST_SHA" = "$(git -C "$ARCH_TEST" rev-parse HEAD)"
            test "$SPIKE_SHA" = "$(git -C "$SPIKE_REPO" rev-parse HEAD)"
            test "$PASS" -eq "$ARCH_TEST_EXPECTED"
            """,
            executable=True,
        )
        self.write(
            "tools/soak_lockstep.sh",
            """
            #!/usr/bin/env bash
            source tools/reference_versions.env
            test "$SPIKE_SHA" = "$(git -C "$SPIKE_REPO" rev-parse HEAD)"
            """,
            executable=True,
        )

    def trigger_block(self, workflow: str) -> str:
        paths = self.REQUIRED_PATHS + (f".github/workflows/{workflow}",)
        if workflow == "rtl-tests.yml":
            paths += ("README.md", "docs/**")
        rendered = "\n".join(f"      - '{path}'" for path in paths)
        return (
            "on:\n"
            "  workflow_dispatch:\n"
            "  push:\n"
            "    paths:\n"
            f"{rendered}\n"
            "  pull_request:\n"
            "    paths:\n"
            f"{rendered}\n"
        )

    def metadata_step(self) -> str:
        return textwrap.indent(textwrap.dedent("""
              - name: Load reference versions
                id: refs
                run: |
                  set -eu
                  source tools/reference_versions.env
                  echo "arch_test_sha=$ARCH_TEST_SHA" >> "$GITHUB_OUTPUT"
                  echo "arch_test_expected=$ARCH_TEST_EXPECTED" >> "$GITHUB_OUTPUT"
                  echo "spike_sha=$SPIKE_SHA" >> "$GITHUB_OUTPUT"
            """).lstrip(), "      ")

    def arch_steps(self) -> str:
        return textwrap.indent(textwrap.dedent("""
              - name: Cache riscv-arch-test
                id: arch-test-cache
                uses: actions/cache@v4
                with:
                  path: ~/riscv-arch-test
                  key: riscv-arch-test-${{ steps.refs.outputs.arch_test_sha }}
              - name: Fetch pinned riscv-arch-test checkout
                env:
                  ARCH_TEST_SHA: ${{ steps.refs.outputs.arch_test_sha }}
                run: |
                  set -eu
                  if [ ! -d "$HOME/riscv-arch-test/.git" ]; then
                    git init -q "$HOME/riscv-arch-test"
                  fi
                  git -C "$HOME/riscv-arch-test" remote remove origin 2>/dev/null || true
                  git -C "$HOME/riscv-arch-test" remote add origin https://github.com/riscv-non-isa/riscv-arch-test.git
                  git -C "$HOME/riscv-arch-test" fetch -q --depth 1 origin "$ARCH_TEST_SHA"
                  git -C "$HOME/riscv-arch-test" checkout -q --detach "$ARCH_TEST_SHA"
                  git -C "$HOME/riscv-arch-test" reset -q --hard "$ARCH_TEST_SHA"
                  test "$(git -C "$HOME/riscv-arch-test" rev-parse HEAD)" = "$ARCH_TEST_SHA"
                  test -z "$(git -C "$HOME/riscv-arch-test" symbolic-ref -q HEAD || true)"
                  test -z "$(git -C "$HOME/riscv-arch-test" status --short --untracked-files=all)"
            """).lstrip(), "      ")

    def spike_steps(self) -> str:
        return textwrap.indent(textwrap.dedent("""
              - name: Cache Spike source and build
                id: spike-cache
                uses: actions/cache@v4
                with:
                  path: ~/riscv-isa-sim
                  key: spike-${{ steps.refs.outputs.spike_sha }}
              - name: Fetch and build pinned Spike
                env:
                  SPIKE_SHA: ${{ steps.refs.outputs.spike_sha }}
                run: |
                  set -eu
                  if [ ! -d "$HOME/riscv-isa-sim/.git" ]; then
                    git init -q "$HOME/riscv-isa-sim"
                  fi
                  git -C "$HOME/riscv-isa-sim" remote remove origin 2>/dev/null || true
                  git -C "$HOME/riscv-isa-sim" remote add origin https://github.com/riscv-software-src/riscv-isa-sim.git
                  git -C "$HOME/riscv-isa-sim" fetch -q --depth 1 origin "$SPIKE_SHA"
                  git -C "$HOME/riscv-isa-sim" checkout -q --detach "$SPIKE_SHA"
                  git -C "$HOME/riscv-isa-sim" reset -q --hard "$SPIKE_SHA"
                  test "$(git -C "$HOME/riscv-isa-sim" rev-parse HEAD)" = "$SPIKE_SHA"
                  test -z "$(git -C "$HOME/riscv-isa-sim" symbolic-ref -q HEAD || true)"
                  test -z "$(git -C "$HOME/riscv-isa-sim" status --short --untracked-files=all)"
                  if [ ! -x "$HOME/riscv-isa-sim/build/spike" ] || [ ! -f "$HOME/riscv-isa-sim/build/.source-sha" ] || [ "$(cat "$HOME/riscv-isa-sim/build/.source-sha" 2>/dev/null || true)" != "$SPIKE_SHA" ]; then
                    rm -rf "$HOME/riscv-isa-sim/build"
                    mkdir -p "$HOME/riscv-isa-sim/build"
                    cd "$HOME/riscv-isa-sim/build"
                    ../configure
                    make -j"$(nproc)"
                    printf '%s\\n' "$SPIKE_SHA" > .source-sha
                  fi
                  test -x "$HOME/riscv-isa-sim/build/spike"
                  test "$(cat "$HOME/riscv-isa-sim/build/.source-sha")" = "$SPIKE_SHA"
            """).lstrip(), "      ")

    def reference_workflow(self, kind: str) -> str:
        workflow = f"{kind}.yml"
        extra = self.spike_steps() if kind == "lockstep" else ""
        if kind == "lockstep":
            prefix = textwrap.indent(textwrap.dedent("""
                  - name: Check out repo
                    uses: actions/checkout@v4
                  - name: Install toolchain
                    run: echo toolchain
                  - name: Install Verilator (conda-forge)
                    uses: conda-incubator/setup-miniconda@v3
                  - name: Install verilator package
                    run: echo verilator
                """).lstrip(), "      ")
            gates = textwrap.indent(textwrap.dedent("""
                  - name: Run complete architecture-test traces against Spike
                    env:
                      ARCH_TEST: /home/runner/riscv-arch-test
                      ARCH_TEST_EXPECTED: ${{ steps.refs.outputs.arch_test_expected }}
                      SPIKE: /home/runner/riscv-isa-sim/build/spike
                    run: make lockstep
                  - name: Random programs against Spike (with control flow)
                    env:
                      SPIKE: /home/runner/riscv-isa-sim/build/spike
                    run: make soak-lockstep SEEDS=200
                """).lstrip(), "      ")
        else:
            prefix = textwrap.indent(textwrap.dedent("""
                  - name: Check out rv32i-pipeline
                    uses: actions/checkout@v4
                  - name: Install RISC-V toolchain
                    run: echo toolchain
                  - name: Install Verilator (conda-forge)
                    uses: conda-incubator/setup-miniconda@v3
                  - name: Install verilator package
                    run: echo verilator
                """).lstrip(), "      ")
            gates = textwrap.indent(textwrap.dedent("""
                  - name: Build simulator
                    run: echo build
                  - name: Run compliance suite
                    env:
                      ARCH_TEST: /home/runner/riscv-arch-test
                      ARCH_TEST_EXPECTED: ${{ steps.refs.outputs.arch_test_expected }}
                    run: make compliance
                """).lstrip(), "      ")
        return (
            self.trigger_block(workflow)
            + f"\nname: {kind}\n\njobs:\n  {kind}:\n    runs-on: ubuntu-latest\n"
            + "    defaults:\n      run:\n        shell: bash -l {0}\n    steps:\n"
            + prefix
            + self.metadata_step()
            + self.arch_steps()
            + extra
            + gates
        )

    def rtl_workflow(self) -> str:
        matrix = "\n".join(
            f'          - name: {name}\n            args: "{args}"'
            for name, args in self.MATRIX
        )
        return (
            self.trigger_block("rtl-tests.yml")
            + "\nname: RTL Tests\n\njobs:\n"
            + "  lint-and-test:\n    runs-on: ubuntu-latest\n"
            + "    defaults:\n      run:\n        shell: bash -l {0}\n"
            + "    steps:\n      - name: Fast correctness checks\n        run: make check\n"
            + "  test-matrix:\n    runs-on: ubuntu-latest\n"
            + "    defaults:\n      run:\n        shell: bash -l {0}\n"
            + "    strategy:\n      fail-fast: false\n      matrix:\n        include:\n"
            + matrix
            + "\n    steps:\n"
            + "      - name: Check out repo\n        uses: actions/checkout@v4\n"
            + "      - name: Install Verilator (conda-forge)\n        uses: conda-incubator/setup-miniconda@v3\n"
            + "      - name: Install verilator package\n        run: echo verilator\n"
            + "      - name: Run full test suite (${{ matrix.name }})\n"
            + "        run: make all ${{ matrix.args }}\n"
        )

    def write_workflow(self, name: str, contents: str) -> None:
        self.write(f".github/workflows/{name}", contents)

    def evidence_facts(self, **overrides: str) -> dict[str, str]:
        facts = {
            "ISA": "RV32I_Zicsr_Zifencei",
            "DIRECTED_TESTS": "2",
            "ASSERTIONS_TOTAL": "2",
            "ASSERTIONS_CONCURRENT": "1",
            "ASSERTIONS_IMMEDIATE": "1",
            "SOURCE_COVER_POINTS": "2",
            "TRACKED_COVERAGE_HIT": "1",
            "TRACKED_COVERAGE_TOTAL": "2",
            "TRACKED_COVERAGE_STATUS": "historical",
            "CI_CONFIGS": "6",
            "CI_MATRIX": ",".join(name for name, _ in self.MATRIX),
            "ARCH_TEST_SHA": self.ARCH_SHA,
            "ARCH_TEST_EXPECTED": "7",
            "SPIKE_SHA": self.SPIKE_SHA,
            "SPIKE_RANDOM_SEEDS": "200",
        }
        facts.update(overrides)
        return facts

    def fact_block(self, **overrides: str) -> str:
        facts = self.evidence_facts(**overrides)
        rows = "\n".join(f"EVIDENCE_FACT {key}={value}" for key, value in facts.items())
        return f"<!-- evidence-facts:begin -->\n{rows}\n<!-- evidence-facts:end -->\n"

    def write_evidence_tree(self) -> None:
        self.write(
            "Makefile",
            "TESTS = t01_alpha t02_beta\n\n"
            ".PHONY: evidence-check check\n\n"
            "evidence-check:\n"
            "\tpython3 -m unittest -v tools.test_evidence_check\n"
            "\tpython3 tools/evidence_check.py\n\n"
            "check: unit harness-test lint evidence-check\n",
        )
        for name in ("t01_alpha", "t02_beta"):
            self.write(f"tests/{name}.s", "addi x1, x0, 1\n")
            self.write(f"tests/{name}.ref", "cycles=10\nx1=1\n")
        self.write(
            "rtl/core.sv",
            "module core(input logic clk, rst, value);\n"
            "  a_concurrent: assert property (@(posedge clk) disable iff (rst) value);\n"
            "  always_comb begin\n"
            "    a_immediate: assert (value || rst);\n"
            "  end\n"
            "  c_one: cover property (@(posedge clk) value);\n"
            "  c_two: cover property (@(posedge clk) !value);\n"
            "endmodule\n",
        )
        self.write(
            "docs/coverage.md",
            "# Functional coverage report\n\n"
            "**Evidence status: historical.**\n\n"
            "**1/2 cover points hit (50.0%)**, from a recorded run.\n",
        )
        block = self.fact_block()
        for relative in (
            "README.md",
            "docs/MICROARCHITECTURE.md",
            "docs/VERIFICATION_PLAN.md",
            "docs/EVIDENCE.md",
        ):
            self.write(relative, f"# Evidence fixture\n\n{block}")

    def replace_all_fact_values(self, old: str, new: str) -> None:
        for relative in (
            "README.md",
            "docs/MICROARCHITECTURE.md",
            "docs/VERIFICATION_PLAN.md",
            "docs/EVIDENCE.md",
        ):
            path = self.repo / relative
            path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    def run_checker(self, *extra: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(root or self.repo),
             "--contracts-only", *extra],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

    def run_evidence_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(self.repo)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

    def assert_evidence_failure(self, diagnostic: str) -> subprocess.CompletedProcess[str]:
        result = self.run_evidence_checker()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn(diagnostic, combined)
        return result

    def assert_contract_failure(self, diagnostic: str) -> subprocess.CompletedProcess[str]:
        result = self.run_checker()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn(diagnostic, combined)
        return result

    def test_valid_contract_tree_passes(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("reference and CI contracts: OK", result.stdout)

    def use_container_workflows(self) -> None:
        for name in ("rtl-tests.yml", "compliance.yml", "lockstep.yml"):
            self.write_workflow(
                name,
                (ROOT / ".github/workflows" / name).read_text(encoding="utf-8"),
            )

    def test_container_workflow_contract_passes(self) -> None:
        self.use_container_workflows()
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_container_workflow_rejects_moving_action_tag(self) -> None:
        self.use_container_workflows()
        path = self.repo / ".github/workflows/rtl-tests.yml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955",
                "actions/checkout@v4",
            ),
            encoding="utf-8",
        )
        self.assert_contract_failure("approved immutable commits")

    def test_container_workflow_rejects_shallow_evidence_checkout(self) -> None:
        self.use_container_workflows()
        path = self.repo / ".github/workflows/rtl-tests.yml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "        with:\n          fetch-depth: 0\n",
                "",
                1,
            ),
            encoding="utf-8",
        )
        self.assert_contract_failure("evidence checkout must fetch full history")

    def test_container_workflow_rejects_missing_predictor_profile(self) -> None:
        self.use_container_workflows()
        path = self.repo / ".github/workflows/rtl-tests.yml"
        source = path.read_text(encoding="utf-8")
        source = source.replace(
            "      - name: Run three predictor configurations\n"
            "        run: python3 tools/verification.py container --profile directed-predictor\n",
            "",
        )
        path.write_text(source, encoding="utf-8")
        self.assert_contract_failure("commands are not canonical")

    def test_container_workflow_rejects_a_missing_portfolio_media_profile(self) -> None:
        self.use_container_workflows()
        path = self.repo / ".github/workflows/rtl-tests.yml"
        source = path.read_text(encoding="utf-8").replace(
            "      - name: Validate committed portfolio artifacts\n"
            "        run: python3 tools/verification.py container --profile portfolio\n",
            "",
        )
        path.write_text(source, encoding="utf-8")
        self.assert_contract_failure("commands are not canonical")

    def test_real_repository_metadata_matches_test_only_oracle(self) -> None:
        parsed = {}
        for line in (ROOT / "tools/reference_versions.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                parsed[key] = value
        self.assertEqual(parsed, APPROVED_REFERENCES)

    def test_missing_metadata_file_is_rejected(self) -> None:
        (self.repo / "tools/reference_versions.env").unlink()
        self.assert_contract_failure("missing reference metadata")

    def test_empty_metadata_file_is_rejected(self) -> None:
        self.write_metadata("\n# no values\n")
        self.assert_contract_failure("reference metadata is empty")

    def test_duplicate_metadata_key_is_rejected(self) -> None:
        self.write_metadata(
            f"ARCH_TEST_SHA={self.ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=7\n"
            "ARCH_TEST_EXPECTED=8\n"
            f"SPIKE_SHA={self.SPIKE_SHA}\n"
        )
        self.assert_contract_failure("duplicate reference metadata key: ARCH_TEST_EXPECTED")

    def test_unknown_metadata_key_is_rejected(self) -> None:
        self.write_metadata(
            f"ARCH_TEST_SHA={self.ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=7\n"
            f"SPIKE_SHA={self.SPIKE_SHA}\n"
            "ARCH_TEST_BRANCH=old-framework-2.x\n"
        )
        self.assert_contract_failure("unexpected reference metadata key: ARCH_TEST_BRANCH")

    def test_malformed_metadata_assignment_is_rejected(self) -> None:
        self.write_metadata(
            f"ARCH_TEST_SHA = {self.ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=7\n"
            f"SPIKE_SHA={self.SPIKE_SHA}\n"
        )
        self.assert_contract_failure("malformed reference metadata line 1")

    def test_wrong_metadata_value_format_is_rejected(self) -> None:
        self.write_metadata(
            "ARCH_TEST_SHA=old-framework-2.x\n"
            "ARCH_TEST_EXPECTED=0\n"
            f"SPIKE_SHA={self.SPIKE_SHA}\n"
        )
        self.assert_contract_failure("ARCH_TEST_SHA must be a lowercase 40-hex SHA")

    def test_literal_pin_in_executable_consumer_is_rejected(self) -> None:
        self.write(
            "tools/bad_consumer.sh",
            f"#!/usr/bin/env bash\nPIN={self.SPIKE_SHA}\necho \"$PIN\"\n",
            executable=True,
        )
        self.assert_contract_failure("literal reference pin duplicated in executable consumer")

    def test_literal_expected_count_in_executable_consumer_is_rejected(self) -> None:
        self.write(
            "tools/bad_count.py",
            'fixture = "\\nARCH_TEST_EXPECTED=7\\n"\n',
        )
        self.assert_contract_failure(
            "literal expected architecture count duplicated in executable consumer"
        )

    def test_comments_cannot_satisfy_or_violate_contracts(self) -> None:
        self.write(
            "tools/comment_only.sh",
            f"#!/usr/bin/env bash\n# {self.SPIKE_SHA}\ntrue\n",
            executable=True,
        )
        lockstep = self.reference_workflow("lockstep").replace(
            "run: make soak-lockstep SEEDS=200",
            "run: make soak-lockstep SEEDS=199\n                # make soak-lockstep SEEDS=200",
        )
        self.write_workflow("lockstep.yml", lockstep)
        self.assert_contract_failure("lockstep workflow must run exactly make soak-lockstep SEEDS=200")

    def test_auxiliary_hidden_worktrees_are_not_operational_consumers(self) -> None:
        self.write(
            ".claude/worktrees/stale/tools/run_lockstep.sh",
            f"#!/usr/bin/env bash\nARCH_TEST_EXPECTED_CASES=7\nPIN={self.SPIKE_SHA}\n",
            executable=True,
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_private_verification_cache_is_not_repository_source(self) -> None:
        self.write(
            ".verify-cache/upstream/tool.py",
            f'PIN = "{self.SPIKE_SHA}"\n',
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_expected_count_symbol_is_rejected(self) -> None:
        path = self.repo / "tools/run_lockstep.sh"
        path.write_text(path.read_text().replace(
            "ARCH_TEST_EXPECTED", "ARCH_TEST_EXPECTED_CASES"), encoding="utf-8")
        self.assert_contract_failure("legacy ARCH_TEST_EXPECTED_CASES")

    def test_moving_architecture_checkout_is_rejected(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            'git -C "$HOME/riscv-arch-test" fetch -q --depth 1 origin "$ARCH_TEST_SHA"',
            'git clone --branch old-framework-2.x https://github.com/riscv-non-isa/riscv-arch-test.git "$HOME/riscv-arch-test"',
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("moving architecture-test reference")

    def test_architecture_checkout_must_fetch_from_expected_upstream(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "https://github.com/riscv-non-isa/riscv-arch-test.git",
            "https://example.invalid/lookalike.git",
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test checkout must use the approved upstream")

    def test_spike_checkout_must_fetch_from_expected_upstream(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "https://github.com/riscv-software-src/riscv-isa-sim.git",
            "https://example.invalid/lookalike.git",
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("Spike checkout must use the approved upstream")

    def test_missing_metadata_output_step_is_rejected(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            'echo "arch_test_sha=$ARCH_TEST_SHA" >> "$GITHUB_OUTPUT"',
            'echo "arch_test_sha=$ARCH_TEST_SHA"',
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("must publish arch_test_sha through GITHUB_OUTPUT")

    def test_missing_required_event_is_rejected(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "  pull_request:\n    paths:\n", "  schedule:\n    paths:\n", 1)
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("missing pull_request trigger")

    def test_missing_required_path_is_rejected_for_each_filtered_event(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "      - 'sim/**'\n", "", 1)
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("push.paths missing sim/**")

    def test_wrong_directed_matrix_is_rejected(self) -> None:
        workflow = self.rtl_workflow().replace(
            "IC_BYTES=1024 IC_WAYS=4 IMEM_LAT=10 DMEM_LAT=10",
            "IC_BYTES=2048 IC_WAYS=4 IMEM_LAT=10 DMEM_LAT=10",
            1,
        )
        self.write_workflow("rtl-tests.yml", workflow)
        self.assert_contract_failure("directed CI matrix does not match the six approved configurations")

    def test_lockstep_requires_complete_architecture_gate_before_soak(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "run: make lockstep", "run: make test", 1)
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("lockstep workflow must run make lockstep before random soak")

    def test_lockstep_requires_exact_two_hundred_seed_command(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "run: make soak-lockstep SEEDS=200", "run: make soak-lockstep SEEDS=201")
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("lockstep workflow must run exactly make soak-lockstep SEEDS=200")

    def test_spike_cache_must_retain_verified_source_checkout(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "path: ~/riscv-isa-sim", "path: ~/.local/spike")
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("Spike cache must retain the verified source/build checkout")

    def test_required_job_cannot_be_disabled(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "  compliance:\n    runs-on:", "  compliance:\n    if: false\n    runs-on:", 1
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job must not use if")

    def test_contract_must_be_bound_to_the_exact_required_job_name(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "  compliance:\n", "  verify:\n", 1
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance.yml: missing required job compliance")

    def test_compliance_gate_cannot_continue_on_error(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "        run: make compliance",
            "        continue-on-error: true\n        run: make compliance",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("required step must not use continue-on-error")

    def test_lockstep_gate_cannot_continue_on_error(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "        run: make lockstep",
            "        continue-on-error: true\n        run: make lockstep",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("required step must not use continue-on-error")

    def test_lockstep_soak_gate_cannot_continue_on_error(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "        run: make soak-lockstep SEEDS=200",
            "        continue-on-error: true\n        run: make soak-lockstep SEEDS=200",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("required step must not use continue-on-error")

    def test_required_gate_step_cannot_be_conditionally_skipped(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "        run: make lockstep",
            "        if: false\n        run: make lockstep",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("required step must not use if")

    def test_required_gate_must_be_the_direct_run_scalar(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "        run: make soak-lockstep SEEDS=200",
            "        run: |\n          ./tools/soak_lockstep.sh 5\n          exit 0\n          make soak-lockstep SEEDS=200",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure(
            "lockstep soak gate run must be exactly make soak-lockstep SEEDS=200"
        )

    def test_required_contract_cannot_be_assembled_across_jobs(self) -> None:
        full = self.reference_workflow("compliance")
        prefix, contract = full.split("jobs:\n  compliance:\n", 1)
        workflow = (
            prefix
            + "jobs:\n  compliance:\n    runs-on: ubuntu-latest\n    steps:\n"
            + "      - run: \"true\"\n"
            + "  disabled-contract:\n    if: false\n"
            + contract
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job is missing its required contract chain")

    def test_reference_setup_must_precede_verification_gate(self) -> None:
        workflow = self.reference_workflow("compliance")
        gate = textwrap.indent(textwrap.dedent("""
              - name: Run compliance suite
                env:
                  ARCH_TEST: /home/runner/riscv-arch-test
                  ARCH_TEST_EXPECTED: ${{ steps.refs.outputs.arch_test_expected }}
                run: make compliance
            """).lstrip(), "      ")
        workflow = workflow.replace(gate, "", 1)
        workflow = workflow.replace(self.metadata_step(), gate + self.metadata_step(), 1)
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance required steps are out of order")

    def test_directed_matrix_job_must_consume_matrix_arguments(self) -> None:
        workflow = self.rtl_workflow().replace(
            "run: make all ${{ matrix.args }}", "run: echo matrix configured"
        )
        self.write_workflow("rtl-tests.yml", workflow)
        self.assert_contract_failure(
            "test-matrix gate run must be exactly make all ${{ matrix.args }}"
        )

    def test_approved_upstream_url_cannot_have_a_suffix(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "https://github.com/riscv-non-isa/riscv-arch-test.git",
            "https://github.com/riscv-non-isa/riscv-arch-test.git.evil",
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test checkout must use the approved upstream")

    def test_approved_upstream_url_token_cannot_be_embedded_on_wrong_host(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "https://github.com/riscv-software-src/riscv-isa-sim.git",
            "https://evil.invalid/https://github.com/riscv-software-src/riscv-isa-sim.git",
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("Spike checkout must use the approved upstream")

    def test_architecture_head_verification_must_enforce_equality(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            'test "$(git -C "$HOME/riscv-arch-test" rev-parse HEAD)" = "$ARCH_TEST_SHA"',
            'echo "$(git -C "$HOME/riscv-arch-test" rev-parse HEAD)" "$ARCH_TEST_SHA"',
        ).replace(
            'test -z "$(git -C "$HOME/riscv-arch-test" symbolic-ref -q HEAD || true)"',
            'echo "$(git -C "$HOME/riscv-arch-test" symbolic-ref -q HEAD || true)"',
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test setup must exactly verify the pinned checkout")

    def test_negated_path_cannot_neutralize_required_path(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "      - 'rtl/**'\n", "      - 'rtl/**'\n      - '!rtl/**'\n", 1
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("must not negate or duplicate required path rtl/**")

    def test_duplicate_required_path_is_rejected(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "      - 'rtl/**'\n", "      - 'rtl/**'\n      - 'rtl/**'\n", 1
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("must not negate or duplicate required path rtl/**")

    def test_metadata_output_must_expand_the_symbol(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            'echo "arch_test_sha=$ARCH_TEST_SHA" >> "$GITHUB_OUTPUT"',
            "echo 'arch_test_sha=$ARCH_TEST_SHA' >> \"$GITHUB_OUTPUT\"",
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("metadata step must publish exact expanding output lines")

    def test_split_quoted_pin_is_still_a_literal_duplicate(self) -> None:
        self.write(
            "tools/split-pin.sh",
            f"#!/usr/bin/env bash\nPIN='{self.SPIKE_SHA[:20]}''{self.SPIKE_SHA[20:]}'\nprintf '%s\\n' \"$PIN\"\n",
            executable=True,
        )
        self.assert_contract_failure("literal reference pin duplicated in executable consumer")

    def test_alternate_expected_count_assignment_is_rejected(self) -> None:
        self.write(
            "tools/alternate-count.sh",
            "#!/usr/bin/env bash\nEXPECTED_CASES=7\ntest \"$PASS\" -eq \"$EXPECTED_CASES\"\n",
            executable=True,
        )
        self.assert_contract_failure(
            "alternate expected architecture count duplicated in executable consumer"
        )

    def test_hidden_ci_consumer_is_scanned(self) -> None:
        self.write(
            ".ci/reference.sh",
            f"#!/usr/bin/env bash\nPIN={self.ARCH_SHA}\necho \"$PIN\"\n",
            executable=True,
        )
        workflow = self.reference_workflow("compliance").replace(
            "      - name: Run compliance suite\n",
            "      - name: Invoke hidden reference helper\n"
            "        run: ./.ci/reference.sh\n"
            "      - name: Run compliance suite\n",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("literal reference pin duplicated in executable consumer")

    def test_extensionless_executable_consumer_is_scanned(self) -> None:
        self.write(
            "tools/reference-runner",
            f"#!/usr/bin/env bash\nPIN={self.SPIKE_SHA}\necho \"$PIN\"\n",
            executable=True,
        )
        self.assert_contract_failure("literal reference pin duplicated in executable consumer")

    def test_spike_cached_binary_must_be_bound_to_source_sha_stamp(self) -> None:
        workflow = self.reference_workflow("lockstep")
        workflow = workflow.replace(
            'if [ ! -x "$HOME/riscv-isa-sim/build/spike" ] || [ ! -f "$HOME/riscv-isa-sim/build/.source-sha" ] || [ "$(cat "$HOME/riscv-isa-sim/build/.source-sha" 2>/dev/null || true)" != "$SPIKE_SHA" ]; then',
            'if [ ! -x "$HOME/riscv-isa-sim/build/spike" ]; then',
        ).replace(
            "                    printf '%s\\n' \"$SPIKE_SHA\" > .source-sha\n",
            "",
        ).replace(
            '                  test "$(cat "$HOME/riscv-isa-sim/build/.source-sha")" = "$SPIKE_SHA"\n',
            "",
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("Spike build must be bound to spike_sha with .source-sha")

    def test_cached_source_must_be_reset_and_verified_clean(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            '          git -C "$HOME/riscv-arch-test" reset -q --hard "$ARCH_TEST_SHA"\n',
            "",
        ).replace(
            '          test -z "$(git -C "$HOME/riscv-arch-test" status --short --untracked-files=all)"\n',
            "",
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test setup must exactly verify the pinned checkout")

    def test_quoted_job_if_key_is_rejected(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "  compliance:\n    runs-on:",
            '  compliance:\n    "if": false\n    runs-on:',
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job must not use if")

    def test_quoted_step_continue_on_error_key_is_rejected(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "        run: make lockstep",
            '        "continue-on-error": true\n        run: make lockstep',
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("required step must not use continue-on-error")

    def test_required_job_cannot_need_a_disabled_prerequisite(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "jobs:\n  compliance:\n",
            "jobs:\n"
            "  disabled-prerequisite:\n"
            "    if: false\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo disabled\n"
            "  compliance:\n"
            "    needs: disabled-prerequisite\n",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job has unsupported properties")

    def test_required_step_cannot_override_shell_with_noop(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "        run: make compliance",
            "        shell: /bin/true {0}\n        run: make compliance",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance gate has unsupported properties")

    def test_required_job_defaults_shell_cannot_be_noop(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "shell: bash -l {0}", "shell: /bin/true {0}", 1
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("lockstep job must use the canonical defaults shell")

    def test_gate_cannot_run_in_a_fake_working_directory(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "        run: make compliance",
            "        working-directory: fake\n        run: make compliance",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance gate has unsupported properties")

    def test_pull_request_types_cannot_narrow_the_required_trigger(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "  pull_request:\n    paths:",
            "  pull_request:\n    types: [closed]\n    paths:",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("pull_request event may contain only paths")

    def test_push_branches_ignore_cannot_narrow_the_required_trigger(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "  push:\n    paths:",
            "  push:\n    branches-ignore:\n      - '**'\n    paths:",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("push event may contain only paths")

    def test_yaml_anchor_cannot_hide_a_negated_required_path(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "      - 'rtl/**'\n",
            "      - 'rtl/**'\n      - &drop '!rtl/**'\n",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("event paths must not use YAML anchors or aliases")

    def test_architecture_source_cannot_be_mutated_after_verification(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "      - name: Build simulator\n",
            "      - name: Mutate architecture source\n"
            "        run: echo mutation >> /home/runner/riscv-arch-test/README.md\n"
            "      - name: Build simulator\n",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job step sequence is not canonical")

    def test_spike_binary_cannot_be_replaced_after_verification(self) -> None:
        workflow = self.reference_workflow("lockstep").replace(
            "      - name: Run complete architecture-test traces against Spike\n",
            "      - name: Replace verified Spike\n"
            "        run: cp /bin/true /home/runner/riscv-isa-sim/build/spike\n"
            "      - name: Run complete architecture-test traces against Spike\n",
            1,
        )
        self.write_workflow("lockstep.yml", workflow)
        self.assert_contract_failure("lockstep job step sequence is not canonical")

    def test_checkout_verification_requires_full_clean_status(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "status --short --untracked-files=all",
            "status --short --untracked-files=no",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test setup must verify a fully clean checkout")

    def test_alternate_count_assignment_is_rejected_for_any_expression(self) -> None:
        self.write(
            "tools/alternate-expression.sh",
            "#!/usr/bin/env bash\nEXPECTED_CASES=$((19*2))\necho \"$EXPECTED_CASES\"\n",
            executable=True,
        )
        self.assert_contract_failure(
            "alternate expected architecture count assignment in executable consumer"
        )

    def test_literal_expected_count_is_rejected_for_any_variable_name(self) -> None:
        self.write_metadata(
            f"ARCH_TEST_SHA={self.ARCH_SHA}\n"
            "ARCH_TEST_EXPECTED=38\n"
            f"SPIKE_SHA={self.SPIKE_SHA}\n"
        )
        self.write(
            "tools/opaque-count.sh",
            "#!/usr/bin/env bash\nN=38\necho \"$N\"\n",
            executable=True,
        )
        self.assert_contract_failure(
            "literal expected architecture count duplicated in executable consumer"
        )

    def test_pin_split_across_append_assignments_is_rejected(self) -> None:
        self.write(
            "tools/appended-pin.sh",
            f"#!/usr/bin/env bash\nPIN={self.SPIKE_SHA[:20]}\n"
            f"PIN+={self.SPIKE_SHA[20:]}\necho \"$PIN\"\n",
            executable=True,
        )
        self.assert_contract_failure("literal reference pin duplicated in executable consumer")

    def test_excluded_worktree_consumer_cannot_be_invoked_by_required_job(self) -> None:
        self.write(
            ".claude/worktrees/stale/pinned-helper.sh",
            f"#!/usr/bin/env bash\nPIN={self.ARCH_SHA}\necho \"$PIN\"\n",
            executable=True,
        )
        workflow = self.reference_workflow("compliance").replace(
            "      - name: Build simulator\n",
            "      - name: Invoke excluded helper\n"
            "        run: ./.claude/worktrees/stale/pinned-helper.sh\n"
            "      - name: Build simulator\n",
            1,
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("compliance job step sequence is not canonical")

    def test_valid_evidence_tree_passes(self) -> None:
        self.write_evidence_tree()
        result = self.run_evidence_checker()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("repository evidence: OK", result.stdout)

    def test_partial_result_set_is_rejected(self) -> None:
        self.write_evidence_tree()
        self.write("results/manifest.json", "{}\n")
        self.assert_evidence_failure("result records are incomplete")

    def test_directed_test_requires_source_and_reference_pair(self) -> None:
        self.write_evidence_tree()
        (self.repo / "tests/t02_beta.ref").unlink()
        self.assert_evidence_failure("directed test inventory mismatch")

    def test_unlisted_directed_pair_is_rejected(self) -> None:
        self.write_evidence_tree()
        self.write("tests/t03_extra.s", "addi x1, x0, 1\n")
        self.write("tests/t03_extra.ref", "cycles=10\nx1=1\n")
        self.assert_evidence_failure("directed test inventory mismatch")

    def test_assertion_fact_must_match_rtl_source(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values("ASSERTIONS_TOTAL=2", "ASSERTIONS_TOTAL=3")
        self.assert_evidence_failure("ASSERTIONS_TOTAL")

    def test_cover_fact_must_match_rtl_source(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values("SOURCE_COVER_POINTS=2", "SOURCE_COVER_POINTS=3")
        self.assert_evidence_failure("SOURCE_COVER_POINTS")

    def test_historical_coverage_fact_must_match_report(self) -> None:
        self.write_evidence_tree()
        path = self.repo / "docs/coverage.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("1/2", "2/2").replace("50.0%", "100.0%"),
            encoding="utf-8",
        )
        self.assert_evidence_failure("TRACKED_COVERAGE_HIT")

    def test_current_coverage_total_must_match_source(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values(
            "TRACKED_COVERAGE_STATUS=historical",
            "TRACKED_COVERAGE_STATUS=current",
        )
        path = self.repo / "docs/coverage.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "Evidence status: historical", "Evidence status: current"
            ),
            encoding="utf-8",
        )
        self.write(
            "rtl/core.sv",
            (self.repo / "rtl/core.sv").read_text(encoding="utf-8").replace(
                "endmodule",
                "  c_three: cover property (@(posedge clk) rst);\nendmodule",
            ),
        )
        self.assert_evidence_failure("current coverage total")

    def test_ci_configuration_fact_must_match_workflow(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values("CI_CONFIGS=6", "CI_CONFIGS=5")
        self.assert_evidence_failure("CI_CONFIGS")

    def test_spike_seed_fact_must_match_workflow(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values("SPIKE_RANDOM_SEEDS=200", "SPIKE_RANDOM_SEEDS=199")
        self.assert_evidence_failure("SPIKE_RANDOM_SEEDS")

    def test_isa_fact_must_use_canonical_name(self) -> None:
        self.write_evidence_tree()
        self.replace_all_fact_values("ISA=RV32I_Zicsr_Zifencei", "ISA=RV32I")
        self.assert_evidence_failure("ISA")

    def test_conflicting_document_fact_is_rejected(self) -> None:
        self.write_evidence_tree()
        path = self.repo / "README.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("DIRECTED_TESTS=2", "DIRECTED_TESTS=9"),
            encoding="utf-8",
        )
        self.assert_evidence_failure("conflicting evidence fact DIRECTED_TESTS")

    def test_duplicate_document_fact_is_rejected(self) -> None:
        self.write_evidence_tree()
        path = self.repo / "docs/EVIDENCE.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "EVIDENCE_FACT DIRECTED_TESTS=2",
                "EVIDENCE_FACT DIRECTED_TESTS=2\nEVIDENCE_FACT DIRECTED_TESTS=2",
            ),
            encoding="utf-8",
        )
        self.assert_evidence_failure("duplicate evidence fact DIRECTED_TESTS")

    def test_fast_workflow_must_run_make_check(self) -> None:
        self.write_evidence_tree()
        workflow = self.rtl_workflow().replace("run: make check", "run: make lint", 1)
        self.write_workflow("rtl-tests.yml", workflow)
        self.assert_evidence_failure("fast workflow gate run must be exactly make check")

    def test_fast_workflow_must_trigger_for_portfolio_documents(self) -> None:
        self.write_evidence_tree()
        workflow = self.rtl_workflow().replace("      - 'docs/**'\n", "", 1)
        self.write_workflow("rtl-tests.yml", workflow)
        self.assert_evidence_failure("push.paths missing docs/**")

    def test_make_check_requires_every_fast_gate(self) -> None:
        self.write_evidence_tree()
        path = self.repo / "Makefile"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "check: unit harness-test lint evidence-check",
                "check: unit lint evidence-check",
            ),
            encoding="utf-8",
        )
        self.assert_evidence_failure("check target must depend on exact fast gates")

    def test_make_evidence_check_runs_tests_and_checker(self) -> None:
        self.write_evidence_tree()
        path = self.repo / "Makefile"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "\tpython3 -m unittest -v tools.test_evidence_check\n",
                "",
            ),
            encoding="utf-8",
        )
        self.assert_evidence_failure("evidence-check target must run its tests and checker")

    def test_architecture_cache_key_must_use_metadata_output(self) -> None:
        workflow = self.reference_workflow("compliance").replace(
            "key: riscv-arch-test-${{ steps.refs.outputs.arch_test_sha }}",
            "key: arch-old-framework-2.x",
        )
        self.write_workflow("compliance.yml", workflow)
        self.assert_contract_failure("architecture-test cache key must use arch_test_sha output")


if __name__ == "__main__":
    unittest.main()
