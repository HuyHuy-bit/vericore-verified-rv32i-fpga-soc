#!/usr/bin/env python3

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.prepare_references import ReferenceError, prepare_checkout, prepare_spike


class ReferencePreparationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-references-")
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.upstream, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=self.upstream, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.upstream, check=True)
        (self.upstream / "tracked.txt").write_text("pinned\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.upstream, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.upstream, check=True)
        self.commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.upstream, text=True,
            stdout=subprocess.PIPE, check=True,
        ).stdout.strip()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_checkout_is_detached_clean_and_repaired(self) -> None:
        target = self.cache / "reference"
        prepare_checkout(target, str(self.upstream), self.commit, self.cache)
        (target / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        (target / "untracked.txt").write_text("stale\n", encoding="utf-8")
        prepare_checkout(target, str(self.upstream), self.commit, self.cache)
        self.assertEqual((target / "tracked.txt").read_text(encoding="utf-8"), "pinned\n")
        self.assertFalse((target / "untracked.txt").exists())
        self.assertEqual(
            subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, stdout=subprocess.PIPE, check=True).stdout.strip(),
            self.commit,
        )
        self.assertNotEqual(subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=target).returncode, 0)

    def test_checkout_outside_cache_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReferenceError, "outside reference cache"):
            prepare_checkout(self.root / "escape", str(self.upstream), self.commit, self.cache)

    def test_noncanonical_commit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReferenceError, "canonical commit"):
            prepare_checkout(self.cache / "reference", str(self.upstream), "HEAD", self.cache)

    def test_spike_build_is_stamped_and_reused(self) -> None:
        repo = self.cache / "spike"
        prepare_checkout(repo, str(self.upstream), self.commit, self.cache)
        configure = repo / "configure"
        configure.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'all:\\n\\tprintf spike > spike\\n\\tchmod +x spike\\n' > Makefile\n",
            encoding="utf-8",
        )
        configure.chmod(0o755)
        subprocess.run(["git", "add", "configure"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=fixture@example.com", "-c", "user.name=Fixture", "commit", "-qm", "configure"], cwd=repo, check=True)
        build_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
        prepare_spike(repo, build_commit, self.cache)
        binary = repo / "build/spike"
        first_mtime = binary.stat().st_mtime_ns
        prepare_spike(repo, build_commit, self.cache)
        self.assertEqual(binary.stat().st_mtime_ns, first_mtime)
        self.assertEqual((repo / "build/.source-sha").read_text(encoding="utf-8").strip(), build_commit)


if __name__ == "__main__":
    unittest.main()
