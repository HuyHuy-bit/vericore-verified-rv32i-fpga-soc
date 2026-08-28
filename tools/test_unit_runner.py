#!/usr/bin/env python3

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UnitRunnerTest(unittest.TestCase):
    def test_stale_generated_dependencies_are_not_reused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv32i-unit-runner-") as directory:
            work = Path(directory)
            shutil.copy2(ROOT / "tools/run_unit.sh", work / "run_unit.sh")
            stale = work / "obj_dir_unit_demo"
            stale.mkdir()
            (stale / "stale").write_text("container path\n", encoding="utf-8")
            tools = work / "bin"
            tools.mkdir()
            verilator = tools / "verilator"
            verilator.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "while [ \"$1\" != --Mdir ]; do shift; done\n"
                "build=$2\n"
                "[ ! -e \"$build/stale\" ] || exit 9\n"
                "mkdir -p \"$build\"\n"
                "printf '#!/usr/bin/env bash\\nexit 0\\n' > \"$build/Vdemo_tb\"\n"
                "chmod +x \"$build/Vdemo_tb\"\n",
                encoding="utf-8",
            )
            verilator.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(tools) + os.pathsep + environment["PATH"]
            result = subprocess.run(
                [str(work / "run_unit.sh"), "demo_tb", "fixture.sv"],
                cwd=work, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
