#!/usr/bin/env python3

from pathlib import Path
import subprocess
import unittest

from tools.configuration import ConfigurationError, PredictorConfiguration


ROOT = Path(__file__).resolve().parents[1]


class PredictorConfigurationTest(unittest.TestCase):
    def test_defaults_are_valid(self):
        config = PredictorConfiguration(6, 10, 0, 8)
        self.assertEqual(config.errors(), [])
        self.assertEqual(config.identity(), "bp6_10_0_8")

    def test_invalid_fields_are_rejected(self):
        cases = (
            (("bad", "10", "0", "8"), "BTB_IDX_BITS must be a canonical integer"),
            (("4", "10", "1", "8"), "GSHARE requires BTB_IDX_BITS >= 6"),
            (("6", "25", "0", "8"), "BTB_TAG_BITS must be between 1 and 24"),
            (("8", "24", "0", "8"), "BTB index and tag bits exceed the PC width"),
            (("6", "10", "2", "8"), "GSHARE must be 0 or 1"),
            (("6", "10", "0", "3"), "RAS_DEPTH must be zero or a power of two up to 64"),
        )
        for values, diagnostic in cases:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ConfigurationError, diagnostic):
                    PredictorConfiguration.parse(*values)


class MakeConfigurationTest(unittest.TestCase):
    def make(self, *arguments):
        return subprocess.run(
            ["make", "--no-print-directory", *arguments],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

    def test_default_build_identity_is_unchanged(self):
        result = self.make("config-id")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "obj_dir")

    def test_predictor_parameters_change_build_identity(self):
        cases = (
            ("BTB_IDX_BITS=4", "bp4_10_0_8"),
            ("BTB_TAG_BITS=6", "bp6_6_0_8"),
            ("GSHARE=1", "bp6_10_1_8"),
            ("RAS_DEPTH=0", "bp6_10_0_0"),
        )
        for argument, suffix in cases:
            with self.subTest(argument=argument):
                result = self.make("config-id", argument)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(suffix, result.stdout.strip())

    def test_invalid_configuration_fails_before_verilator(self):
        result = self.make("config-check", "BTB_IDX_BITS=bad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BTB_IDX_BITS must be a canonical integer", result.stderr)
        self.assertNotIn("verilator", result.stdout + result.stderr)

    def test_predictor_parameters_reach_verilator(self):
        source = (ROOT / "Makefile").read_text(encoding="utf-8")
        for argument in (
            "-GBTB_IDX_BITS=$(BTB_IDX_BITS)",
            "-GBTB_TAG_BITS=$(BTB_TAG_BITS)",
            "-GGSHARE=$(GSHARE)",
            "-GRAS_DEPTH=$(RAS_DEPTH)",
        ):
            self.assertIn(argument, source)
        self.assertIn("obj_dir_ic0_4_1_dc4096_4_4_0_L1_10_bp6_10_0_8/Vcpu", source)

    def test_ci_has_the_three_predictor_configurations(self):
        workflow = (ROOT / ".github/workflows/rtl-tests.yml").read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn(
            "python3 tools/verification.py container --profile directed-predictor",
            workflow,
        )
        for arguments in (
            "GSHARE=1",
            "RAS_DEPTH=0",
            "BTB_IDX_BITS=4 BTB_TAG_BITS=6",
        ):
            self.assertIn(f"$(MAKE) --no-print-directory all {arguments}", makefile)


if __name__ == "__main__":
    unittest.main()
