#!/usr/bin/env python3
import subprocess
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArchTestCompatibilityTest(unittest.TestCase):
    def test_zero_destination_address_macro_uses_lla(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-arch-compat-") as temp:
            work = Path(temp)
            upstream = work / "upstream"
            source_dir = work / "source"
            upstream.mkdir()
            source_dir.mkdir()
            (upstream / "arch_test.h").write_text(
                "#define LA(reg, val) la reg, val\n"
                "#define TEST_JALR_OP(rd) LA(rd, 5b)\n"
            )
            source = source_dir / "test.S"
            source.write_text('#include "arch_test.h"\nTEST_JALR_OP(x0)\n')
            result = subprocess.run(
                [
                    "cc", "-E", "-P", "-x", "assembler-with-cpp",
                    "-I", str(ROOT / "compliance/riscv-target/rv32i-pipeline"),
                    "-I", str(upstream), str(source),
                ],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("lla x0, 5b", result.stdout)
            self.assertNotRegex(result.stdout, r"\bla\s+x0,\s*5b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
