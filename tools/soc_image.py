#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ELF_HEADER = struct.Struct("<16sHHIIIIIHHHHHH")
SECTION_HEADER = struct.Struct("<IIIIIIIIII")
EM_RISCV = 243
SHT_NOBITS = 8
SHF_ALLOC = 2
IMEM_BASE = 0x0000_0000
IMEM_LIMIT = 0x0000_8000
DMEM_BASE = 0x2000_0000
DMEM_LIMIT = 0x2000_8000
IMAGE_WORDS = 8192


class ImageError(ValueError):
    pass


@dataclass(frozen=True)
class ElfSection:
    name: str
    kind: int
    flags: int
    address: int
    offset: int
    size: int
    data: bytes


@dataclass(frozen=True)
class ElfImage:
    entry: int
    sections: tuple[ElfSection, ...]


def _fail(path: Path, message: str) -> ImageError:
    return ImageError(f"{path}: {message}")


def _bounded_slice(data: bytes, offset: int, size: int, path: Path, field: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise _fail(path, f"{field} is outside the file")
    return data[offset : offset + size]


def _section_name(table: bytes, offset: int, path: Path) -> str:
    if offset >= len(table):
        raise _fail(path, "section name offset is outside the string table")
    end = table.find(b"\0", offset)
    if end < 0:
        raise _fail(path, "section name is not terminated")
    try:
        return table[offset:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise _fail(path, "section name is not UTF-8") from error


def parse_elf(path: Path) -> ElfImage:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise _fail(path, str(error)) from error
    if len(data) < ELF_HEADER.size:
        raise _fail(path, "truncated ELF header")

    fields = ELF_HEADER.unpack_from(data)
    ident = fields[0]
    if ident[:4] != b"\x7fELF":
        raise _fail(path, "invalid ELF magic")
    if ident[4] != 1:
        raise _fail(path, "file is not ELF32")
    if ident[5] != 1:
        raise _fail(path, "file is not little-endian")
    if ident[6] != 1 or fields[3] != 1:
        raise _fail(path, "unsupported ELF version")

    machine = fields[2]
    entry = fields[4]
    section_offset = fields[6]
    header_size = fields[8]
    section_size = fields[11]
    section_count = fields[12]
    string_index = fields[13]
    if machine != EM_RISCV:
        raise _fail(path, f"wrong ELF machine {machine}")
    if header_size != ELF_HEADER.size:
        raise _fail(path, "invalid ELF header size")
    if section_size != SECTION_HEADER.size:
        raise _fail(path, "invalid section header size")
    if section_count == 0 or string_index >= section_count:
        raise _fail(path, "invalid section-name table index")
    section_bytes = section_count * section_size
    if section_offset > len(data) or section_bytes > len(data) - section_offset:
        raise _fail(path, "truncated section table")
    if not (IMEM_BASE <= entry < IMEM_LIMIT):
        raise _fail(path, "entry is outside instruction BRAM")

    headers = [
        SECTION_HEADER.unpack_from(data, section_offset + index * section_size)
        for index in range(section_count)
    ]
    string_header = headers[string_index]
    if string_header[1] == SHT_NOBITS:
        raise _fail(path, "section-name table has no file content")
    names = _bounded_slice(
        data, string_header[4], string_header[5], path, "section-name table"
    )

    sections: list[ElfSection] = []
    ranges: list[tuple[int, int, str]] = []
    for header in headers[1:]:
        name_offset, kind, flags, address, offset, size = header[:6]
        name = _section_name(names, name_offset, path)
        content = b""
        if kind != SHT_NOBITS:
            content = _bounded_slice(data, offset, size, path, f"section {name}")
        if not flags & SHF_ALLOC:
            continue
        end = address + size
        if end > 0x1_0000_0000:
            raise _fail(path, f"allocated section {name} address overflows")
        in_imem = IMEM_BASE <= address and end <= IMEM_LIMIT
        in_dmem = DMEM_BASE <= address and end <= DMEM_LIMIT
        if not (in_imem or in_dmem):
            if (IMEM_BASE <= address < IMEM_LIMIT) or (DMEM_BASE <= address < DMEM_LIMIT):
                raise _fail(path, f"allocated section {name} crosses a region boundary")
            raise _fail(path, f"allocated section {name} is in MMIO or unmapped space")
        if size:
            ranges.append((address, end, name))
        sections.append(
            ElfSection(name, kind, flags, address, offset, size, content)
        )

    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise _fail(
                path,
                f"allocated sections {previous[2]} and {current[2]} overlap",
            )
    return ElfImage(entry, tuple(sections))


def build_images(
    image: ElfImage, imem_words: int, dmem_words: int
) -> tuple[list[int], list[int]]:
    if not 0 < imem_words <= IMAGE_WORDS or not 0 < dmem_words <= IMAGE_WORDS:
        raise ImageError("image capacity must be between one and 8192 words")
    imem = bytearray(imem_words * 4)
    dmem = bytearray(dmem_words * 4)
    for section in image.sections:
        if section.address < IMEM_LIMIT:
            target = imem
            base = IMEM_BASE
            label = "instruction"
        else:
            target = dmem
            base = DMEM_BASE
            label = "data"
        start = section.address - base
        if start > len(target) or section.size > len(target) - start:
            raise ImageError(f"section {section.name} exceeds {label} image capacity")
        if section.kind != SHT_NOBITS:
            target[start : start + section.size] = section.data

    def words(data: bytearray) -> list[int]:
        return [
            int.from_bytes(data[offset : offset + 4], "little")
            for offset in range(0, len(data), 4)
        ]

    return words(imem), words(dmem)


def _atomic_write_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_hex(path: Path, words: list[int]) -> None:
    for word in words:
        if not 0 <= word <= 0xFFFF_FFFF:
            raise ImageError(f"{path}: word is outside 32 bits")
    _atomic_write_text(Path(path), "".join(f"{word:08x}\n" for word in words))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise _fail(path, str(error)) from error
    return digest.hexdigest()


def _unique_object(path: Path):
    def load(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _fail(path, f"duplicate manifest field {key}")
            result[key] = value
        return result

    return load


def _require_fields(path: Path, value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path, f"{label} must be an object")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise _fail(path, f"unknown {label} field {sorted(unknown)[0]}")
    if missing:
        raise _fail(path, f"missing {label} field {sorted(missing)[0]}")
    return value


def validate_manifest(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object(path)
        )
    except ImageError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise _fail(path, f"invalid manifest: {error}") from error
    root = _require_fields(
        path,
        manifest,
        {"schema", "status", "entry", "elf", "imem", "dmem"},
        "manifest",
    )
    if root["schema"] != 1 or root["status"] != "complete":
        raise _fail(path, "unsupported manifest schema or status")
    if not isinstance(root["entry"], int) or not IMEM_BASE <= root["entry"] < IMEM_LIMIT:
        raise _fail(path, "invalid manifest entry")

    artifacts: list[tuple[str, dict[str, Any]]] = []
    for label in ("elf", "imem", "dmem"):
        fields = {"path", "sha256"}
        if label != "elf":
            fields.add("words")
        artifact = _require_fields(path, root[label], fields, label)
        if not isinstance(artifact["path"], str) or not artifact["path"]:
            raise _fail(path, f"invalid {label} path")
        digest = artifact["sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise _fail(path, f"invalid {label} hash")
        try:
            int(digest, 16)
        except ValueError as error:
            raise _fail(path, f"invalid {label} hash") from error
        if label != "elf" and artifact["words"] != IMAGE_WORDS:
            raise _fail(path, f"invalid {label} word count")
        artifacts.append((label, artifact))

    for label, artifact in artifacts:
        artifact_path = Path(artifact["path"])
        if _sha256(artifact_path) != artifact["sha256"]:
            raise _fail(path, f"{label} hash mismatch")
        if label != "elf":
            try:
                line_count = sum(1 for _ in artifact_path.open(encoding="ascii"))
            except (OSError, UnicodeError) as error:
                raise _fail(path, f"invalid {label} image: {error}") from error
            if line_count != artifact["words"]:
                raise _fail(path, f"{label} image word count mismatch")
    return root


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--imem", type=Path, required=True)
    parser.add_argument("--dmem", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        image = parse_elf(args.elf)
        imem, dmem = build_images(image, IMAGE_WORDS, IMAGE_WORDS)
        write_hex(args.imem, imem)
        write_hex(args.dmem, dmem)
        manifest = {
            "schema": 1,
            "status": "complete",
            "entry": image.entry,
            "elf": {"path": str(args.elf), "sha256": _sha256(args.elf)},
            "imem": {
                "path": str(args.imem),
                "words": IMAGE_WORDS,
                "sha256": _sha256(args.imem),
            },
            "dmem": {
                "path": str(args.dmem),
                "words": IMAGE_WORDS,
                "sha256": _sha256(args.dmem),
            },
        }
        _write_manifest(args.manifest, manifest)
        validate_manifest(args.manifest)
    except ImageError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
