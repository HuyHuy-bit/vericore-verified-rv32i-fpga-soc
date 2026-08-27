#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest

from tools.tool_environment import ContractError, TOOL_KEYS, load_manifest, validate_manifest


ROOT = Path(__file__).resolve().parents[1]


VALID = """ENV_SCHEMA=1
UBUNTU_IMAGE=ubuntu:24.04
UBUNTU_DIGEST=sha256:1111111111111111111111111111111111111111111111111111111111111111
VERILATOR_VERSION=5.048
VERILATOR_URL=https://github.com/verilator/verilator/archive/refs/tags/v5.048.tar.gz
VERILATOR_SHA256=2222222222222222222222222222222222222222222222222222222222222222
RISCV_TOOLCHAIN_VERSION=13.2.0-2024.04.12
RISCV_TOOLCHAIN_URL=https://github.com/riscv-collab/riscv-gnu-toolchain/releases/download/2024.04.12/riscv64-elf-ubuntu-22.04-gcc-nightly-2024.04.12-nightly.tar.gz
RISCV_TOOLCHAIN_SHA256=3333333333333333333333333333333333333333333333333333333333333333
PYTHON_VERSION=3.12
VHS_VERSION=0.11.0
VHS_URL=https://github.com/charmbracelet/vhs/releases/download/v0.11.0/vhs_0.11.0_amd64.deb
VHS_SHA256=4444444444444444444444444444444444444444444444444444444444444444
FFMPEG_VERSION=6.1.1
VERIFY_IMAGE=ghcr.io/huyhuy-bit/rv32i-verify
VERIFY_IMAGE_REVISION=1
"""


class ToolManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-tool-env-")
        self.path = Path(self.tmp.name) / "tool_versions.env"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, source: str = VALID) -> Path:
        self.path.write_text(source, encoding="utf-8")
        return self.path

    def assert_error(self, source: str, diagnostic: str) -> None:
        with self.assertRaisesRegex(ContractError, diagnostic):
            load_manifest(self.write(source))

    def test_valid_manifest_has_exact_key_order(self):
        values = load_manifest(self.write())
        self.assertEqual(tuple(values), TOOL_KEYS)
        self.assertEqual(validate_manifest(values), [])

    def test_missing_manifest_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "missing tool version manifest"):
            load_manifest(self.path)

    def test_empty_manifest_is_rejected(self):
        self.assert_error("", "tool version manifest is empty")

    def test_malformed_assignment_is_rejected(self):
        self.assert_error(VALID.replace("ENV_SCHEMA=1", "ENV_SCHEMA 1"), "malformed tool version line 1")

    def test_duplicate_key_is_rejected(self):
        self.assert_error(VALID + "ENV_SCHEMA=1\n", "duplicate tool version key: ENV_SCHEMA")

    def test_unknown_key_is_rejected(self):
        self.assert_error(VALID + "MOVING_TAG=latest\n", "unknown tool version key: MOVING_TAG")

    def test_missing_key_is_rejected(self):
        self.assert_error(VALID.replace("PYTHON_VERSION=3.12\n", ""), "missing tool version key: PYTHON_VERSION")

    def test_out_of_order_key_is_rejected(self):
        source = VALID.replace("ENV_SCHEMA=1\nUBUNTU_IMAGE=ubuntu:24.04\n", "UBUNTU_IMAGE=ubuntu:24.04\nENV_SCHEMA=1\n")
        self.assert_error(source, "tool version keys are not in canonical order")

    def test_empty_value_is_rejected(self):
        self.assert_error(VALID.replace("ENV_SCHEMA=1", "ENV_SCHEMA="), "empty tool version value: ENV_SCHEMA")

    def test_noncanonical_schema_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("ENV_SCHEMA=1", "ENV_SCHEMA=01")))
        self.assertIn("ENV_SCHEMA must be 1", validate_manifest(values))

    def test_bad_digest_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("sha256:" + "1" * 64, "sha256:abc")))
        self.assertIn("UBUNTU_DIGEST must be a sha256 digest", validate_manifest(values))

    def test_bad_sha256_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("2" * 64, "ABC")))
        self.assertIn("VERILATOR_SHA256 must be 64 lowercase hexadecimal characters", validate_manifest(values))

    def test_version_url_mismatch_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("v5.048.tar.gz", "v5.046.tar.gz")))
        self.assertIn("VERILATOR_URL does not contain VERILATOR_VERSION", validate_manifest(values))

    def test_non_https_url_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("https://github.com/verilator", "http://github.com/verilator")))
        self.assertIn("VERILATOR_URL must use https", validate_manifest(values))

    def test_noncanonical_image_name_is_rejected(self):
        values = load_manifest(self.write(VALID.replace("ghcr.io/huyhuy-bit/rv32i-verify", "RV32I/Verify")))
        self.assertIn("VERIFY_IMAGE is not canonical", validate_manifest(values))


class ContainerContractTest(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_dockerfile_uses_pinned_base_and_checksum_gates(self):
        source = self.text("containers/verify/Dockerfile")
        self.assertIn("FROM ${UBUNTU_IMAGE}@${UBUNTU_DIGEST} AS toolchain", source)
        self.assertGreaterEqual(source.count("sha256sum -c -"), 3)
        self.assertIn("AS verify", source)
        self.assertIn("AS demo", source)

    def test_repository_source_is_not_baked_into_image(self):
        source = self.text("containers/verify/Dockerfile")
        self.assertNotRegex(source, r"(?m)^\s*(COPY|ADD)\s+\.\s")
        self.assertNotRegex(source, r"(?m)^\s*(COPY|ADD)\s+[^-].*\s+/work")
        self.assertIn("WORKDIR /work", source)

    def test_entrypoint_checks_container_marker(self):
        source = self.text("containers/verify/entrypoint.sh")
        self.assertIn("tool_environment.py container", source)
        self.assertIn("RV32I_ENVIRONMENT_MARKER", source)
        self.assertIn('exec "$@"', source)

    def test_devcontainer_uses_the_verify_dockerfile(self):
        payload = __import__("json").loads(self.text(".devcontainer/devcontainer.json"))
        self.assertEqual(payload["build"]["dockerfile"], "../containers/verify/Dockerfile")
        self.assertEqual(payload["build"]["target"], "verify")
        self.assertEqual(payload["workspaceFolder"], "/work")
        manifest = load_manifest(ROOT / "tools/tool_versions.env")
        for key, value in payload["build"]["args"].items():
            self.assertEqual(value, manifest[key])

    def test_dockerignore_excludes_generated_artifacts(self):
        entries = set(self.text(".dockerignore").splitlines())
        for entry in ("obj_dir*", "coverage/", "syn/reports/", "*.vcd", ".git/"):
            self.assertIn(entry, entries)

    def test_every_manifest_key_has_an_executable_consumer(self):
        source = self.text("tools/tool_environment.py") + self.text("containers/verify/Dockerfile")
        for key in TOOL_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, source)


if __name__ == "__main__":
    unittest.main()
