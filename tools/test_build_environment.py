#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest

from tools.build_environment import BuildEnvironmentError, prepare_build_directory


class BuildEnvironmentTest(unittest.TestCase):
    def test_changed_identity_replaces_stale_generated_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv32i-build-environment-") as directory:
            root = Path(directory)
            build = root / "obj_dir"
            build.mkdir()
            (build / ".environment-old").write_text("old\n", encoding="utf-8")
            (build / "Vcpu").write_text("container binary\n", encoding="utf-8")
            prepare_build_directory(root, build, "a" * 12)
            self.assertFalse((build / "Vcpu").exists())
            self.assertEqual((build / (".environment-" + "a" * 12)).read_text(), "a" * 12 + "\n")

    def test_matching_identity_preserves_build_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv32i-build-environment-") as directory:
            root = Path(directory)
            build = root / "obj_dir"
            prepare_build_directory(root, build, "b" * 12)
            output = build / "Vcpu"
            output.write_text("keep\n", encoding="utf-8")
            prepare_build_directory(root, build, "b" * 12)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep\n")

    def test_unsafe_build_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv32i-build-environment-") as directory:
            root = Path(directory)
            with self.assertRaisesRegex(BuildEnvironmentError, "unsafe build directory"):
                prepare_build_directory(root, root / "rtl", "c" * 12)


if __name__ == "__main__":
    unittest.main()
