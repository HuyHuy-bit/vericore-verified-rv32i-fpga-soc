from __future__ import annotations

import hashlib
from html import escape
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

from synthesis.soc import render_floorplan


class FloorplanRendererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rv32i-floorplan-")
        self.root = Path(self.tmp.name)
        self.placement = self.root / "placement.tsv"
        self.placement.write_text(
            "placement_schema\t1\n"
            "part\txc7a35ticsg324-1L\n"
            "bounds\t0\t1000\t0\t800\n"
            "cell\tprimitive\tsite\tbel\ttile\ttile_x\ttile_y\n"
            "soc/u_core/u_backend/u_alu/result_reg[0]\tFDRE\tSLICE_X0Y0\tAFF\tCLBLL_L_X0Y0\t100\t100\n"
            "soc/u_core/u_frontend/g_icache.u_icache/data_reg[0]\tRAMB18E1\tRAMB18_X0Y0\tRAMB18E1\tBRAM_L_X0Y0\t200\t200\n"
            "soc/u_core/u_backend/g_dcache.u_dcache/data_reg[0]\tRAMB36E1\tRAMB36_X0Y0\tRAMB36E1\tBRAM_L_X0Y1\t300\t300\n"
            "soc/arbiter/grant_reg\tFDRE\tSLICE_X1Y1\tBFF\tCLBLL_R_X1Y1\t400\t400\n"
            "soc/instruction_memory/mem_reg[0]\tRAMB36E1\tRAMB36_X1Y0\tRAMB36E1\tBRAM_R_X1Y0\t500\t500\n"
            "soc/data_memory/mem_reg[0]\tRAMB36E1\tRAMB36_X2Y0\tRAMB36E1\tBRAM_R_X2Y0\t600\t600\n"
            "clock/mmcm\tMMCME2_ADV\tMMCME2_ADV_X0Y0\tMMCME2_ADV\tCMT_TOP_X0Y0\t700\t700\n",
            encoding="utf-8",
        )
        placement_hash = hashlib.sha256(self.placement.read_bytes()).hexdigest()
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "status": "complete",
                    "source_commit": "1" * 40,
                    "rtl_commit": "2" * 40,
                    "part": "xc7a35ticsg324-1L",
                    "top": "arty_a7_35t_top",
                    "input_clock_period_ns": 10.0,
                    "soc_clock_period_ns": 20.0,
                    "wns_ns": 2.009,
                    "vivado": {"version": "2025.2", "build": "6299465"},
                    "outputs": {"placement": placement_hash},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_render_uses_every_physical_group_and_provenance_field(self) -> None:
        svg, metadata = render_floorplan.build_floorplan(
            self.placement, self.manifest
        )
        source = svg.decode("utf-8")
        self.assertIn("Post-route physical placement", source)
        self.assertIn("xc7a35ticsg324-1L", source)
        self.assertIn("Vivado 2025.2 build 6299465", source)
        self.assertIn("Source 111111111111", source)
        self.assertIn("RTL 222222222222", source)
        self.assertIn("WNS +2.009 ns", source)
        self.assertIn("actual routed primitive locations", source)
        for group in render_floorplan.GROUPS:
            self.assertIn(escape(group.label), source)
            self.assertEqual(metadata["groups"][group.key], 1)
        self.assertEqual(metadata["placed_primitives"], 7)
        self.assertEqual(metadata["occupied_tiles"], 7)
        self.assertEqual(
            metadata["placement_sha256"],
            hashlib.sha256(self.placement.read_bytes()).hexdigest(),
        )
        self.assertEqual(metadata["svg_sha256"], hashlib.sha256(svg).hexdigest())

    def test_render_is_deterministic(self) -> None:
        first = render_floorplan.build_floorplan(self.placement, self.manifest)
        second = render_floorplan.build_floorplan(self.placement, self.manifest)
        self.assertEqual(first, second)

    def test_malformed_duplicate_and_out_of_bounds_records_are_rejected(self) -> None:
        original = self.placement.read_text(encoding="utf-8")
        cases = {
            "malformed": "bad\n",
            "duplicate": original + original.splitlines()[-1] + "\n",
            "bounds": original.replace("\t700\t700\n", "\t1001\t700\n"),
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.placement.write_text(source, encoding="utf-8")
                with self.assertRaises(render_floorplan.FloorplanError):
                    render_floorplan.load_placement(self.placement)
        self.placement.write_text(original, encoding="utf-8")

    def test_manifest_must_hash_the_exact_placement(self) -> None:
        value = json.loads(self.manifest.read_text(encoding="utf-8"))
        value["outputs"]["placement"] = "0" * 64
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(
            render_floorplan.FloorplanError, "placement hash mismatch"
        ):
            render_floorplan.build_floorplan(self.placement, self.manifest)

    def test_atomic_output_is_publicly_readable(self) -> None:
        output = self.root / "artifact.svg"
        render_floorplan.write_atomic(output, b"<svg/>\n")
        self.assertEqual(os.stat(output).st_mode & 0o777, 0o644)


class PublishedFloorplanTest(unittest.TestCase):
    def test_committed_floorplan_is_bound_to_unchanged_physical_inputs(self) -> None:
        root = Path(__file__).resolve().parents[2]
        render_floorplan.validate_published(
            root / "docs/images/soc-floorplan.svg",
            root / "docs/images/soc-floorplan.json",
            root,
        )

    def test_published_vivado_capture_matches_its_provenance(self) -> None:
        root = Path(__file__).resolve().parents[2]
        image = root / "docs/images/soc-vivado-device.png"
        metadata = json.loads(
            (root / "docs/images/soc-vivado-device.json").read_text(
                encoding="utf-8"
            )
        )
        floorplan = json.loads(
            (root / "docs/images/soc-floorplan.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["schema"], 1)
        self.assertEqual(
            metadata["capture"]["image_sha256"],
            hashlib.sha256(image.read_bytes()).hexdigest(),
        )
        self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(
            struct.unpack(">II", image.read_bytes()[16:24]), (1936, 1048)
        )
        fields = (
            "part",
            "rtl_commit",
            "input_clock_period_ns",
            "soc_clock_period_ns",
            "wns_ns",
        )
        for key in fields:
            self.assertEqual(metadata[key], floorplan[key])
        self.assertEqual(metadata["vivado"]["version"], "2025.2")
        self.assertEqual(metadata["vivado"]["build"], "6299465")
        self.assertEqual(
            metadata["capture"]["highlighted_regions"],
            {
                "core": "blue",
                "data_cache": "magenta",
                "data_memory": "red",
                "instruction_memory": "green",
            },
        )
        simulation = metadata["post_route_timing_simulation"]
        self.assertEqual(simulation["status"], "complete")
        self.assertEqual(simulation["mode"], "post-implementation")
        self.assertEqual(simulation["type"], "timing")
        self.assertEqual(simulation["testbench"], "arty_post_route_tb")
        self.assertEqual(simulation["uart"], "rv32i soc ready\n")
        self.assertEqual(simulation["led"], 1)
        self.assertEqual(simulation["wns_ns"], metadata["wns_ns"])
        hashes = [
            metadata["capture"]["routed_checkpoint_sha256"],
            metadata["firmware"]["imem_sha256"],
            metadata["firmware"]["dmem_sha256"],
            simulation["generated_netlist_sha256"],
            simulation["sdf_sha256"],
            simulation["timing_report_sha256"],
            simulation["transcript_sha256"],
        ]
        self.assertTrue(all(len(value) == 64 for value in hashes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
