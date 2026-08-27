#!/usr/bin/env python3

import ctypes
from pathlib import Path
import random
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bench" / "rv32i_runtime.c"


class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="rv32i-runtime-")
        directory = Path(cls.tmp.name)
        library = directory / "runtime.so"
        subprocess.run(
            ["cc", "-shared", "-fPIC", "-O2", str(SOURCE), "-o", str(library)],
            check=True,
        )
        cls.runtime = ctypes.CDLL(str(library))
        for name in ("__mulsi3", "__udivsi3", "__umodsi3"):
            function = getattr(cls.runtime, name)
            function.argtypes = (ctypes.c_uint, ctypes.c_uint)
            function.restype = ctypes.c_uint
        for name in ("__divsi3", "__modsi3"):
            function = getattr(cls.runtime, name)
            function.argtypes = (ctypes.c_int, ctypes.c_int)
            function.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_unsigned_helpers(self):
        rng = random.Random(1)
        values = [0, 1, 2, 3, 31, 32, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
        pairs = [(left, right) for left in values for right in values]
        pairs.extend((rng.getrandbits(32), rng.getrandbits(32)) for _ in range(4096))
        for left, right in pairs:
            self.assertEqual(getattr(self.runtime, "__mulsi3")(left, right), (left * right) & 0xFFFFFFFF)
            quotient = 0xFFFFFFFF if right == 0 else left // right
            remainder = left if right == 0 else left % right
            self.assertEqual(getattr(self.runtime, "__udivsi3")(left, right), quotient)
            self.assertEqual(getattr(self.runtime, "__umodsi3")(left, right), remainder)

    def test_signed_helpers(self):
        rng = random.Random(2)
        values = [-0x80000000, -100, -3, -1, 0, 1, 3, 100, 0x7FFFFFFF]
        pairs = [(left, right) for left in values for right in values if right != 0]
        pairs.extend(
            (
                ctypes.c_int(rng.getrandbits(32)).value,
                ctypes.c_int(rng.getrandbits(32) or 1).value,
            )
            for _ in range(4096)
        )
        for left, right in pairs:
            quotient = abs(left) // abs(right)
            if (left < 0) != (right < 0):
                quotient = -quotient
            quotient = ctypes.c_int(quotient).value
            remainder = ctypes.c_int(left - quotient * right).value
            self.assertEqual(getattr(self.runtime, "__divsi3")(left, right), quotient)
            self.assertEqual(getattr(self.runtime, "__modsi3")(left, right), remainder)

    def test_rv32_object_has_no_helper_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="rv32i-runtime-object-") as directory:
            output = Path(directory) / "runtime.o"
            subprocess.run(
                [
                    "riscv64-unknown-elf-gcc", "-march=rv32i", "-mabi=ilp32", "-O2",
                    "-ffreestanding", "-fno-builtin", "-c", str(SOURCE), "-o", str(output),
                ],
                check=True,
            )
            result = subprocess.run(
                ["riscv64-unknown-elf-nm", "-u", str(output)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
