#!/usr/bin/env python3

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import verification as verification_module
from tools.verification import (
    Command,
    VerificationError,
    build_image_command,
    commands_for,
    docker_run_command,
    run_commands,
)


ROOT = Path(__file__).resolve().parents[1]


class ProfileTest(unittest.TestCase):
    def test_fast_profile_is_the_existing_fast_gate(self):
        commands = commands_for("fast", ROOT)
        self.assertEqual(tuple(command.argv for command in commands), (("make", "check"),))

    def test_memory_profile_has_six_named_configurations(self):
        commands = commands_for("directed-memory", ROOT)
        self.assertEqual(
            tuple(command.name for command in commands),
            (
                "directed-memory-baseline",
                "directed-memory-slow-mem",
                "directed-memory-icache-only",
                "directed-memory-wt",
                "directed-memory-wb",
                "directed-memory-assoc",
            ),
        )
        self.assertTrue(all(command.argv[:2] == ("make", "all") for command in commands))

    def test_full_profile_has_strict_gate_order(self):
        names = tuple(command.name for command in commands_for("full", ROOT))
        boundaries = (
            "fast",
            "directed-memory-baseline",
            "directed-predictor",
            "random-python-baseline",
            "compliance",
            "lockstep",
            "random-spike",
            "coverage",
        )
        positions = tuple(names.index(name) for name in boundaries)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertEqual(len(names), len(set(names)))

    def test_portfolio_profile_checks_published_artifacts(self):
        self.assertEqual(
            tuple(command.name for command in commands_for("portfolio", ROOT)),
            ("results-check", "portfolio-render-check", "portfolio-check"),
        )

    def test_soc_profile_runs_the_integrated_gate(self):
        commands = commands_for("soc", ROOT)
        self.assertEqual(commands, (Command("soc", ("make", "soc-check"), 1800),))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(VerificationError, "unknown verification profile"):
            commands_for("quickish", ROOT)


class RunnerTest(unittest.TestCase):
    def test_soc_profile_propagates_timeout_and_repository_root(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.assertEqual(run_commands(commands_for("soc", ROOT), ROOT, {}, runner), 0)
        self.assertEqual(calls[0][0], ["make", "soc-check"])
        self.assertEqual(calls[0][1]["cwd"], ROOT)
        self.assertEqual(calls[0][1]["timeout"], 1800)

    def test_commands_use_argument_vectors_without_shell(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        rc = run_commands((Command("one", ("printf", "%s", "a;b"), 4),), ROOT, {}, runner)
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0][0], ["printf", "%s", "a;b"])
        self.assertNotIn("shell", calls[0][1])

    def test_first_failure_stops_the_profile(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 7, "out", "err")

        commands = (
            Command("bad", ("false",), 4),
            Command("unreachable", ("true",), 4),
        )
        self.assertEqual(run_commands(commands, ROOT, {}, runner), 7)
        self.assertEqual(calls, [["false"]])

    def test_timeout_is_a_failure(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial", stderr="late")

        self.assertEqual(run_commands((Command("slow", ("slow",), 3),), ROOT, {}, runner), 124)

    def test_missing_command_is_a_failure(self):
        def runner(argv, **kwargs):
            raise FileNotFoundError(argv[0])

        self.assertEqual(run_commands((Command("missing", ("absent",), 3),), ROOT, {}, runner), 127)


class ContainerCommandTest(unittest.TestCase):
    def test_make_clean_removes_unit_build_directories(self):
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("obj_dir_unit_*", source)

    def test_soc_firmware_uses_deterministically_named_objects(self):
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("SOC_START_OBJ = $(SOC_BUILD_DIR)/start.o", source)
        self.assertIn("SOC_DEMO_OBJ = $(SOC_BUILD_DIR)/demo.o", source)
        self.assertIn('-o "$(SOC_START_OBJ)" firmware/start.S', source)
        self.assertIn('-o "$(SOC_DEMO_OBJ)" firmware/demo.c', source)
        self.assertIn('$(SOC_START_OBJ) $(SOC_DEMO_OBJ)', source)
        self.assertNotIn('-o "$(SOC_ELF)" firmware/start.S firmware/demo.c', source)

    def test_soc_firmware_reuses_complete_current_outputs(self):
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        phony = next(line for line in source.splitlines() if line.startswith(".PHONY:"))
        self.assertNotIn("soc-firmware", phony.split())
        self.assertIn(
            "$(SOC_ELF) $(SOC_IMEM) $(SOC_DMEM) $(SOC_MANIFEST) &:",
            source,
        )
        self.assertIn("soc-firmware: $(SOC_ELF) $(SOC_IMEM) $(SOC_DMEM) $(SOC_MANIFEST)", source)

    def test_build_uses_every_manifest_value_and_selected_target(self):
        command = build_image_command(ROOT, "demo")
        self.assertEqual(command[:3], ("docker", "build", "--target"))
        self.assertIn("demo", command)
        self.assertIn("containers/verify/Dockerfile", command)
        self.assertEqual(command[-1], str(ROOT.resolve()))
        self.assertIn("ghcr.io/huyhuy-bit/rv32i-verify:1-demo", command)

    def test_container_mounts_source_and_private_cache(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-verify-command-") as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            (root / "tools" / "tool_versions.env").write_text(
                (ROOT / "tools" / "tool_versions.env").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            command = docker_run_command(root, "fast", "verify", uid=123, gid=456)
        self.assertIn(f"{root}:/work", command)
        self.assertIn(f"{root / '.verify-cache'}:/opt/rv32i-cache", command)
        self.assertIn("HOST_UID=123", command)
        self.assertIn("HOST_GID=456", command)
        self.assertIn("REFERENCE_CACHE=/opt/rv32i-cache", command)
        self.assertEqual(command[-4:], ("--profile", "fast", "--inside-container", "1"))

    def test_container_forwards_full_profile_receipt(self):
        command = docker_run_command(
            ROOT, "full", "verify", uid=123, gid=456,
            receipt=Path(".portfolio-runs/current/verification.json"),
        )
        self.assertEqual(
            command[-2:],
            ("--receipt", ".portfolio-runs/current/verification.json"),
        )

    def test_demo_container_runs_an_explicit_repository_command(self):
        command = docker_run_command(
            ROOT, "fast", "demo", uid=123, gid=456,
            command=("make", "portfolio-demo-record"),
        )
        self.assertEqual(command[-2:], ("make", "portfolio-demo-record"))

    def test_soc_profile_uses_the_verification_container(self):
        command = docker_run_command(ROOT, "soc", "verify", uid=123, gid=456)
        self.assertIn("ghcr.io/huyhuy-bit/rv32i-verify:1-verify", command)
        self.assertEqual(command[-4:], ("--profile", "soc", "--inside-container", "1"))


class ReceiptCommandTest(unittest.TestCase):
    def test_soc_profile_writes_a_receipt_after_success(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-soc-receipt-") as name:
            receipt = Path(name) / "soc.json"
            with mock.patch("tools.verification.run_commands", return_value=0), mock.patch(
                "tools.verification.write_profile_receipt"
            ) as writer:
                status = verification_module.main(
                    ["run", "--profile", "soc", "--receipt", str(receipt)]
                )
            self.assertEqual(status, 0)
            writer.assert_called_once_with(ROOT, receipt, "soc")

    def test_failed_soc_profile_removes_a_stale_receipt(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-soc-receipt-") as name:
            receipt = Path(name) / "soc.json"
            receipt.write_text("stale\n", encoding="utf-8")
            with mock.patch("tools.verification.run_commands", return_value=7):
                status = verification_module.main(
                    ["run", "--profile", "soc", "--receipt", str(receipt)]
                )
            self.assertEqual(status, 7)
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
