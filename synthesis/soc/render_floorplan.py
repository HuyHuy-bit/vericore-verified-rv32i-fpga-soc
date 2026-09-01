#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


PART = "xc7a35ticsg324-1L"
FIELDS = ("cell", "primitive", "site", "bel", "tile", "tile_x", "tile_y")
SHA_RE = re.compile(r"[0-9a-f]{40}")


class FloorplanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    color: str


GROUPS = (
    Group("core", "Pipeline, CSR & predictor", "#38bdf8"),
    Group("icache", "Instruction cache", "#a78bfa"),
    Group("dcache", "Data cache", "#f472b6"),
    Group("fabric", "Wishbone & peripherals", "#fbbf24"),
    Group("imem", "Instruction BRAM", "#34d399"),
    Group("dmem", "Data BRAM", "#fb7185"),
    Group("board", "Clock, reset & board I/O", "#94a3b8"),
)
GROUP_BY_KEY = {group.key: group for group in GROUPS}


@dataclass(frozen=True)
class PlacedCell:
    cell: str
    primitive: str
    site: str
    bel: str
    tile: str
    tile_x: int
    tile_y: int


@dataclass(frozen=True)
class Placement:
    part: str
    bounds: tuple[int, int, int, int]
    cells: tuple[PlacedCell, ...]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_placement(path: Path) -> Placement:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeError) as exc:
        raise FloorplanError(f"placement data is missing or invalid: {exc}") from exc
    if len(lines) < 5 or lines[0] != "placement_schema\t1":
        raise FloorplanError("placement data has an invalid schema")
    part_fields = lines[1].split("\t")
    if part_fields != ["part", PART]:
        raise FloorplanError("placement data has the wrong FPGA part")
    bounds_fields = lines[2].split("\t")
    if len(bounds_fields) != 5 or bounds_fields[0] != "bounds":
        raise FloorplanError("placement data has invalid bounds")
    try:
        bounds = tuple(int(value) for value in bounds_fields[1:])
    except ValueError as exc:
        raise FloorplanError("placement data has invalid bounds") from exc
    min_x, max_x, min_y, max_y = bounds
    if min_x >= max_x or min_y >= max_y:
        raise FloorplanError("placement data has invalid bounds")
    if tuple(lines[3].split("\t")) != FIELDS:
        raise FloorplanError("placement data has invalid fields")
    cells: list[PlacedCell] = []
    names: set[str] = set()
    for line_number, line in enumerate(lines[4:], 5):
        values = line.split("\t")
        if len(values) != len(FIELDS) or any(not value for value in values):
            raise FloorplanError(f"placement data row {line_number} is malformed")
        if any(any(ord(character) < 32 for character in value) for value in values):
            raise FloorplanError(f"placement data row {line_number} has control data")
        cell, primitive, site, bel, tile, raw_x, raw_y = values
        if cell in names:
            raise FloorplanError(f"placement data duplicates cell {cell}")
        try:
            tile_x = int(raw_x)
            tile_y = int(raw_y)
        except ValueError as exc:
            raise FloorplanError(
                f"placement data row {line_number} has invalid coordinates"
            ) from exc
        if not min_x <= tile_x <= max_x or not min_y <= tile_y <= max_y:
            raise FloorplanError(
                f"placement data row {line_number} is outside the device"
            )
        names.add(cell)
        cells.append(
            PlacedCell(cell, primitive, site, bel, tile, tile_x, tile_y)
        )
    if not cells:
        raise FloorplanError("placement data has no placed primitives")
    return Placement(PART, bounds, tuple(cells))


def classify_cell(cell: str) -> str:
    path = "/" + cell.lower().strip("/") + "/"
    if "/u_core/" in path:
        if (
            "/u_icache/" in path
            or "/g_icache/" in path
            or "g_icache.u_icache" in path
        ):
            return "icache"
        if (
            "/u_dcache/" in path
            or "/g_dcache/" in path
            or "g_dcache.u_dcache" in path
        ):
            return "dcache"
        return "core"
    if "/instruction_memory/" in path:
        return "imem"
    if "/data_memory/" in path:
        return "dmem"
    if path.startswith("/soc/"):
        return "fabric"
    return "board"


def resource_kind(primitive: str) -> str:
    name = primitive.upper()
    if name.startswith("RAMB"):
        return "memory"
    if name.startswith("DSP"):
        return "dsp"
    if "MMCME" in name or name.startswith("BUFG"):
        return "clock"
    if name.startswith(("IBUF", "OBUF", "IOB")):
        return "io"
    return "logic"


def load_manifest(path: Path, placement_hash: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError) as exc:
        raise FloorplanError(f"board manifest is missing or invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise FloorplanError("board manifest must be an object")
    if value.get("schema") != 1 or value.get("status") != "complete":
        raise FloorplanError("board manifest is not complete")
    if value.get("part") != PART or value.get("top") != "arty_a7_35t_top":
        raise FloorplanError("board manifest target is incorrect")
    for name in ("source_commit", "rtl_commit"):
        if not isinstance(value.get(name), str) or SHA_RE.fullmatch(value[name]) is None:
            raise FloorplanError(f"board manifest {name} is invalid")
    for name, expected in (
        ("input_clock_period_ns", 10.0),
        ("soc_clock_period_ns", 20.0),
    ):
        measured = value.get(name)
        if (
            not isinstance(measured, (int, float))
            or isinstance(measured, bool)
            or not math.isfinite(float(measured))
            or abs(float(measured) - expected) > 0.0001
        ):
            raise FloorplanError(f"board manifest {name} is invalid")
    wns = value.get("wns_ns")
    if (
        not isinstance(wns, (int, float))
        or isinstance(wns, bool)
        or not math.isfinite(float(wns))
        or float(wns) < 0.0
    ):
        raise FloorplanError("board manifest WNS is invalid")
    vivado = value.get("vivado")
    if (
        not isinstance(vivado, dict)
        or vivado.get("version") != "2025.2"
        or not isinstance(vivado.get("build"), str)
        or not vivado["build"].isdigit()
    ):
        raise FloorplanError("board manifest Vivado identity is invalid")
    outputs = value.get("outputs")
    if not isinstance(outputs, dict) or outputs.get("placement") != placement_hash:
        raise FloorplanError("placement hash mismatch")
    return value


def _svg_text(x: float, y: float, text: str, css: str) -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{css}">{escape(text)}</text>'


def render_svg(placement: Placement, manifest: dict[str, object]) -> bytes:
    width, height = 1280, 820
    chip_x, chip_y, chip_w, chip_h = 58.0, 126.0, 804.0, 616.0
    min_x, max_x, min_y, max_y = placement.bounds
    span_x = max_x - min_x
    span_y = max_y - min_y

    def px(tile_x: int) -> float:
        return chip_x + 12.0 + (tile_x - min_x) * (chip_w - 24.0) / span_x

    def py(tile_y: int) -> float:
        return chip_y + 12.0 + (max_y - tile_y) * (chip_h - 24.0) / span_y

    counts = Counter(classify_cell(cell.cell) for cell in placement.cells)
    buckets: dict[tuple[str, int, int, str], int] = defaultdict(int)
    for cell in placement.cells:
        buckets[
            (
                classify_cell(cell.cell),
                cell.tile_x,
                cell.tile_y,
                resource_kind(cell.primitive),
            )
        ] += 1
    occupied_tiles = len({(cell.tile_x, cell.tile_y) for cell in placement.cells})
    source = str(manifest["source_commit"])
    rtl = str(manifest["rtl_commit"])
    vivado = manifest["vivado"]
    wns = float(manifest["wns_ns"])
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-labelledby="title desc" viewBox="0 0 {width} {height}">',
        '<title id="title">RV32I SoC post-route physical placement</title>',
        '<desc id="desc">Actual Vivado routed primitive locations for the '
        'Arty A7-35T implementation, grouped by RTL hierarchy.</desc>',
        "<defs>",
        '<linearGradient id="background" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0" stop-color="#07111f"/>',
        '<stop offset="1" stop-color="#111827"/>',
        "</linearGradient>",
        '<filter id="glow"><feGaussianBlur stdDeviation="2.2" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>'
        "</feMerge></filter>",
        "<style>",
        ".title{font:700 28px ui-monospace,SFMono-Regular,Consolas,monospace;fill:#f8fafc}",
        ".subtitle{font:15px ui-monospace,SFMono-Regular,Consolas,monospace;fill:#94a3b8}",
        ".label{font:600 15px ui-monospace,SFMono-Regular,Consolas,monospace;fill:#e2e8f0}",
        ".small{font:13px ui-monospace,SFMono-Regular,Consolas,monospace;fill:#94a3b8}",
        ".count{font:700 14px ui-monospace,SFMono-Regular,Consolas,monospace;fill:#f8fafc;text-anchor:end}",
        "</style>",
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="24" fill="url(#background)"/>',
        _svg_text(58, 54, "RV32I SoC — Post-route physical placement", "title"),
        _svg_text(
            58,
            86,
            f"{PART}  •  Vivado {vivado['version']} build {vivado['build']}  •  WNS {wns:+.3f} ns",
            "subtitle",
        ),
        f'<rect x="{chip_x}" y="{chip_y}" width="{chip_w}" height="{chip_h}" '
        'rx="14" fill="#0b1526" stroke="#334155" stroke-width="2"/>',
    ]
    for index in range(1, 10):
        grid_x = chip_x + chip_w * index / 10
        lines.append(
            f'<line x1="{grid_x:.1f}" y1="{chip_y}" x2="{grid_x:.1f}" '
            f'y2="{chip_y + chip_h}" stroke="#1e293b" stroke-width="1"/>'
        )
    for index in range(1, 8):
        grid_y = chip_y + chip_h * index / 8
        lines.append(
            f'<line x1="{chip_x}" y1="{grid_y:.1f}" x2="{chip_x + chip_w}" '
            f'y2="{grid_y:.1f}" stroke="#1e293b" stroke-width="1"/>'
        )
    order = {group.key: index for index, group in enumerate(GROUPS)}
    for (key, tile_x, tile_y, kind), count in sorted(
        buckets.items(), key=lambda item: (order[item[0][0]], item[0][2], item[0][1])
    ):
        color = GROUP_BY_KEY[key].color
        x, y = px(tile_x), py(tile_y)
        size = min(7.0, 1.8 + math.log2(count + 1) * 0.72)
        title = escape(
            f"{GROUP_BY_KEY[key].label}: {count} primitive"
            f"{'s' if count != 1 else ''} at tile ({tile_x}, {tile_y})"
        )
        if kind == "memory":
            lines.append(
                f'<rect x="{x - size:.2f}" y="{y - size * 1.5:.2f}" '
                f'width="{size * 2:.2f}" height="{size * 3:.2f}" rx="1" '
                f'fill="{color}" fill-opacity="0.88"><title>{title}</title></rect>'
            )
        elif kind == "clock":
            lines.append(
                f'<path d="M {x:.2f} {y - size:.2f} L {x + size:.2f} {y:.2f} '
                f'L {x:.2f} {y + size:.2f} L {x - size:.2f} {y:.2f} Z" '
                f'fill="{color}" filter="url(#glow)"><title>{title}</title></path>'
            )
        else:
            opacity = "0.94" if kind in {"dsp", "io"} else "0.72"
            lines.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{size:.2f}" '
                f'fill="{color}" fill-opacity="{opacity}"><title>{title}</title></circle>'
            )
    lines.extend(
        [
            _svg_text(904, 146, "HIERARCHY LEGEND", "label"),
            _svg_text(
                904,
                177,
                f"{len(placement.cells):,} placed primitives",
                "small",
            ),
            _svg_text(904, 199, f"{occupied_tiles:,} occupied physical tiles", "small"),
        ]
    )
    for index, group in enumerate(GROUPS):
        y = 244 + index * 48
        lines.append(
            f'<rect x="904" y="{y - 13}" width="18" height="18" rx="4" fill="{group.color}"/>'
        )
        lines.append(_svg_text(934, y + 1, group.label, "small"))
        lines.append(_svg_text(1218, y + 1, f"{counts[group.key]:,}", "count"))
    lines.extend(
        [
            _svg_text(904, 620, f"Source {source[:12]}", "small"),
            _svg_text(904, 644, f"RTL {rtl[:12]}", "small"),
            _svg_text(904, 678, "100 MHz board input • 50 MHz SoC", "small"),
            _svg_text(904, 712, "Derived from actual routed primitive locations", "small"),
            _svg_text(904, 734, "and RTL hierarchy — not an illustration.", "small"),
            "</svg>",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_floorplan(
    placement_path: Path, manifest_path: Path
) -> tuple[bytes, dict[str, object]]:
    placement_hash = sha256(placement_path)
    placement = load_placement(placement_path)
    manifest = load_manifest(manifest_path, placement_hash)
    counts = Counter(classify_cell(cell.cell) for cell in placement.cells)
    missing = [group.label for group in GROUPS if counts[group.key] == 0]
    if missing:
        raise FloorplanError("placement is missing hierarchy groups: " + ", ".join(missing))
    svg = render_svg(placement, manifest)
    metadata: dict[str, object] = {
        "schema": 1,
        "part": PART,
        "source_commit": manifest["source_commit"],
        "rtl_commit": manifest["rtl_commit"],
        "vivado": manifest["vivado"],
        "input_clock_period_ns": manifest["input_clock_period_ns"],
        "soc_clock_period_ns": manifest["soc_clock_period_ns"],
        "wns_ns": manifest["wns_ns"],
        "placed_primitives": len(placement.cells),
        "occupied_tiles": len(
            {(cell.tile_x, cell.tile_y) for cell in placement.cells}
        ),
        "groups": {group.key: counts[group.key] for group in GROUPS},
        "placement_sha256": placement_hash,
        "svg_sha256": hashlib.sha256(svg).hexdigest(),
    }
    return svg, metadata


def validate_published(svg_path: Path, metadata_path: Path, root: Path) -> None:
    try:
        svg = svg_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError) as exc:
        raise FloorplanError(f"published floorplan is missing or invalid: {exc}") from exc
    fields = {
        "schema",
        "part",
        "source_commit",
        "rtl_commit",
        "vivado",
        "input_clock_period_ns",
        "soc_clock_period_ns",
        "wns_ns",
        "placed_primitives",
        "occupied_tiles",
        "groups",
        "placement_sha256",
        "svg_sha256",
    }
    if not isinstance(metadata, dict) or set(metadata) != fields:
        raise FloorplanError("published floorplan metadata has invalid fields")
    if metadata["schema"] != 1 or metadata["part"] != PART:
        raise FloorplanError("published floorplan metadata has an invalid identity")
    for name in ("source_commit", "rtl_commit"):
        if not isinstance(metadata[name], str) or SHA_RE.fullmatch(metadata[name]) is None:
            raise FloorplanError(f"published floorplan {name} is invalid")
    if not isinstance(metadata["groups"], dict) or set(metadata["groups"]) != set(
        GROUP_BY_KEY
    ):
        raise FloorplanError("published floorplan groups are invalid")
    group_total = 0
    for value in metadata["groups"].values():
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FloorplanError("published floorplan group count is invalid")
        group_total += value
    if metadata["placed_primitives"] != group_total:
        raise FloorplanError("published floorplan primitive count is inconsistent")
    if (
        not isinstance(metadata["occupied_tiles"], int)
        or isinstance(metadata["occupied_tiles"], bool)
        or not 0 < metadata["occupied_tiles"] <= group_total
    ):
        raise FloorplanError("published floorplan tile count is invalid")
    for name in ("placement_sha256", "svg_sha256"):
        if not isinstance(metadata[name], str) or re.fullmatch(
            r"[0-9a-f]{64}", metadata[name]
        ) is None:
            raise FloorplanError(f"published floorplan {name} is invalid")
    if hashlib.sha256(svg).hexdigest() != metadata["svg_sha256"]:
        raise FloorplanError("published floorplan SVG hash mismatch")
    source = svg.decode("utf-8")
    required = (
        "Post-route physical placement",
        PART,
        str(metadata["source_commit"])[:12],
        str(metadata["rtl_commit"])[:12],
        "actual routed primitive locations",
        "not an illustration",
    )
    if any(text not in source for text in required):
        raise FloorplanError("published floorplan SVG lacks provenance")
    if re.search(r"<script\b|\bhref\s*=", source, re.IGNORECASE):
        raise FloorplanError("published floorplan SVG contains external behavior")
    root = root.resolve()
    source_commit = str(metadata["source_commit"])
    rtl_commit = str(metadata["rtl_commit"])
    for commit in (source_commit, rtl_commit):
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise FloorplanError("published floorplan commit does not exist")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0:
        raise FloorplanError("published floorplan source is not an ancestor")
    recorded_rtl = subprocess.run(
        ["git", "log", "-1", "--format=%H", source_commit, "--", "rtl"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if recorded_rtl.returncode != 0:
        raise FloorplanError("published floorplan RTL identity cannot be resolved")
    recorded_rtl = recorded_rtl.stdout.strip()
    if recorded_rtl != rtl_commit:
        raise FloorplanError("published floorplan RTL identity is inconsistent")
    unchanged = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            source_commit,
            "HEAD",
            "--",
            "rtl",
            "boards",
            "firmware",
            "synthesis/soc/build.tcl",
        ],
        cwd=root,
    )
    if unchanged.returncode != 0:
        raise FloorplanError("physical design inputs changed after floorplan routing")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--placement", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        svg, metadata = build_floorplan(args.placement, args.manifest)
        metadata_bytes = (
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != svg:
                raise FloorplanError("published floorplan SVG is stale")
            if not args.metadata.is_file() or args.metadata.read_bytes() != metadata_bytes:
                raise FloorplanError("published floorplan metadata is stale")
            print("physical floorplan matches routed placement")
        else:
            write_atomic(args.output, svg)
            write_atomic(args.metadata, metadata_bytes)
            print(f"rendered physical floorplan: {args.output}")
    except (FloorplanError, OSError) as exc:
        print(f"floorplan failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
