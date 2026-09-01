from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.soc_image import ImageError, build_images, parse_elf, validate_manifest, write_hex


SHT_PROGBITS = 1
SHT_NOBITS = 8
SHF_ALLOC = 2


def make_elf(
    sections: list[dict[str, object]],
    *,
    entry: int = 0,
    machine: int = 243,
    elf_class: int = 1,
    encoding: int = 1,
) -> bytes:
    names = bytearray(b"\0")
    name_offsets: dict[str, int] = {}
    for section in sections:
        name = str(section["name"])
        name_offsets[name] = len(names)
        names.extend(name.encode("ascii") + b"\0")
    name_offsets[".shstrtab"] = len(names)
    names.extend(b".shstrtab\0")

    ident = bytearray(b"\x7fELF" + bytes(12))
    ident[4] = elf_class
    ident[5] = encoding
    ident[6] = 1
    data = bytearray(bytes(52))
    headers: list[tuple[int, ...]] = [(0,) * 10]

    for section in sections:
        kind = int(section.get("kind", SHT_PROGBITS))
        payload = bytes(section.get("data", b""))
        size = int(section.get("size", len(payload)))
        offset = 0
        if kind != SHT_NOBITS:
            offset = len(data)
            data.extend(payload)
        headers.append(
            (
                name_offsets[str(section["name"])],
                kind,
                int(section.get("flags", SHF_ALLOC)),
                int(section["address"]),
                offset,
                size,
                0,
                0,
                4,
                0,
            )
        )

    shstr_offset = len(data)
    data.extend(names)
    headers.append(
        (name_offsets[".shstrtab"], 3, 0, 0, shstr_offset, len(names), 0, 0, 1, 0)
    )
    while len(data) % 4:
        data.append(0)
    section_offset = len(data)
    for header in headers:
        data.extend(struct.pack("<IIIIIIIIII", *header))

    elf_header = struct.pack(
        "<16sHHIIIIIHHHHHH",
        bytes(ident),
        2,
        machine,
        1,
        entry,
        0,
        section_offset,
        0,
        52,
        0,
        0,
        40,
        len(headers),
        len(headers) - 1,
    )
    data[:52] = elf_header
    return bytes(data)


class SocImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_elf(self, data: bytes, name: str = "fixture.elf") -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def valid_bytes(self) -> bytes:
        return make_elf(
            [
                {"name": ".text", "address": 0, "data": b"\x13\x00\x00\x00"},
                {
                    "name": ".data",
                    "address": 0x2000_0000,
                    "data": b"\x44\x33\x22\x11",
                },
                {
                    "name": ".bss",
                    "address": 0x2000_0004,
                    "kind": SHT_NOBITS,
                    "size": 4,
                },
            ]
        )

    def assert_rejected(self, data: bytes, text: str) -> None:
        path = self.write_elf(data)
        with self.assertRaisesRegex(ImageError, text) as caught:
            parse_elf(path)
        self.assertIn(str(path), str(caught.exception))

    def test_valid_elf_builds_instruction_and_data_images(self) -> None:
        image = parse_elf(self.write_elf(self.valid_bytes()))
        self.assertEqual(image.entry, 0)
        self.assertEqual(image.sections[0].address, 0)
        imem, dmem = build_images(image, imem_words=8, dmem_words=8)
        self.assertEqual(imem[0], 0x0000_0013)
        self.assertEqual(dmem[0], 0x1122_3344)
        self.assertEqual(dmem[1], 0)

    def test_bad_magic_is_rejected(self) -> None:
        data = bytearray(self.valid_bytes())
        data[:4] = b"NOPE"
        self.assert_rejected(bytes(data), "magic")

    def test_elf64_is_rejected(self) -> None:
        self.assert_rejected(make_elf([], elf_class=2), "ELF32")

    def test_big_endian_is_rejected(self) -> None:
        self.assert_rejected(make_elf([], encoding=2), "little-endian")

    def test_wrong_machine_is_rejected(self) -> None:
        self.assert_rejected(make_elf([], machine=3), "machine")

    def test_truncated_header_is_rejected(self) -> None:
        self.assert_rejected(self.valid_bytes()[:32], "header")

    def test_truncated_section_table_is_rejected(self) -> None:
        self.assert_rejected(self.valid_bytes()[:-20], "section table")

    def test_overlapping_allocated_sections_are_rejected(self) -> None:
        data = make_elf(
            [
                {"name": ".one", "address": 0, "data": bytes(8)},
                {"name": ".two", "address": 4, "data": bytes(4)},
            ]
        )
        self.assert_rejected(data, "overlap")

    def test_duplicate_allocated_sections_are_rejected(self) -> None:
        data = make_elf(
            [
                {"name": ".one", "address": 0, "data": bytes(4)},
                {"name": ".two", "address": 0, "data": bytes(4)},
            ]
        )
        self.assert_rejected(data, "overlap")

    def test_entry_outside_instruction_memory_is_rejected(self) -> None:
        self.assert_rejected(make_elf([], entry=0x2000_0000), "entry")

    def test_section_crossing_region_boundary_is_rejected(self) -> None:
        data = make_elf(
            [{"name": ".text", "address": 0x7FFC, "data": bytes(8)}],
            entry=0x7FFC,
        )
        self.assert_rejected(data, "region")

    def test_allocated_mmio_section_is_rejected(self) -> None:
        data = make_elf(
            [{"name": ".mmio", "address": 0x1000_0000, "data": bytes(4)}]
        )
        self.assert_rejected(data, "allocated")

    def test_image_capacity_is_enforced(self) -> None:
        image = parse_elf(
            self.write_elf(
                make_elf([{"name": ".text", "address": 0, "data": bytes(8)}])
            )
        )
        with self.assertRaisesRegex(ImageError, "capacity"):
            build_images(image, imem_words=1, dmem_words=8)

    def test_write_hex_emits_exact_lowercase_words(self) -> None:
        path = self.root / "image.hex"
        write_hex(path, [0x0000_0013, 0xDEAD_BEEF])
        self.assertEqual(path.read_text(), "00000013\ndeadbeef\n")

    def test_manifest_rejects_unknown_and_duplicate_fields(self) -> None:
        path = self.root / "manifest.json"
        path.write_text('{"schema":1,"schema":1}\n')
        with self.assertRaisesRegex(ImageError, "duplicate"):
            validate_manifest(path)
        path.write_text(json.dumps({"schema": 1, "unknown": 2}))
        with self.assertRaisesRegex(ImageError, "unknown"):
            validate_manifest(path)

    def test_manifest_rejects_hash_mismatch(self) -> None:
        artifact = self.root / "artifact.bin"
        artifact.write_bytes(b"data")
        manifest = {
            "schema": 1,
            "status": "complete",
            "entry": 0,
            "elf": {"path": str(artifact), "sha256": "0" * 64},
            "imem": {"path": str(artifact), "words": 8192, "sha256": "0" * 64},
            "dmem": {"path": str(artifact), "words": 8192, "sha256": "0" * 64},
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ImageError, "hash"):
            validate_manifest(path)

    def test_valid_manifest_checks_all_artifacts(self) -> None:
        elf = self.write_elf(self.valid_bytes(), "firmware.elf")
        imem = self.root / "imem.hex"
        dmem = self.root / "dmem.hex"
        write_hex(imem, [0] * 8192)
        write_hex(dmem, [0] * 8192)

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        manifest = {
            "schema": 1,
            "status": "complete",
            "entry": 0,
            "elf": {"path": str(elf), "sha256": digest(elf)},
            "imem": {"path": str(imem), "words": 8192, "sha256": digest(imem)},
            "dmem": {"path": str(dmem), "words": 8192, "sha256": digest(dmem)},
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest))
        self.assertEqual(validate_manifest(path), manifest)


if __name__ == "__main__":
    unittest.main()
