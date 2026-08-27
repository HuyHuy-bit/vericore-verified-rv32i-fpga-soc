#!/usr/bin/env python3

from pathlib import Path
import subprocess
import tempfile
import unittest

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
            "results-check",
            "portfolio-render-check",
            "portfolio-check",
        )
        positions = tuple(names.index(name) for name in boundaries)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertEqual(len(names), len(set(names)))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(VerificationError, "unknown verification profile"):
            commands_for("quickish", ROOT)


class RunnerTest(unittest.TestCase):
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
    def test_build_uses_every_manifest_value_and_selected_target(self):
        command = build_image_command(ROOT, "demo")
        self.assertEqual(command[:3], ("docker", "build", "--target"))
        self.assertIn("demo", command)
        self.assertIn("containers/verify/Dockerfile", command)
        self.assertTrue(command[-1].endswith("rv32i-pipeline"))
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
        self.assertEqual(command[-4:], ("--profile", "fast", "--inside-container", "1"))


if __name__ == "__main__":
    unittest.main()
