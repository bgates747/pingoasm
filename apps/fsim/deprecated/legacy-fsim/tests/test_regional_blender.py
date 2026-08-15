from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regional_blender as regional_blender  # noqa: E402

from pingo_terrain.hex_terrain import HEX_CELL_COUNT, HexCell  # noqa: E402


class RegionalBlenderReviewTests(unittest.TestCase):
    def test_complete_preview_has_exact_corpus_coverage(self) -> None:
        topology = regional_blender.build_preview_topology()
        summary = regional_blender.topology_summary(topology)
        self.assertEqual(summary["hex_cells"], HEX_CELL_COUNT)
        self.assertEqual(
            (summary["cell_id_min"], summary["cell_id_max"]),
            (0, HEX_CELL_COUNT - 1),
        )
        self.assertEqual(summary["vertices"], 151_446)
        self.assertEqual(summary["faces"], 301_098)
        self.assertEqual(summary["hex_boundary_edges"], 151_445)
        self.assertEqual(
            summary["boundary_policy"],
            "six straight plan-view sides per cell; no sawtooth approximation",
        )
        self.assertEqual(
            summary["projected_bounds_m"],
            [521_664, 4_100_077, 624_544, 4_229_327],
        )

    def test_adjacent_cells_share_exact_boundary_and_face_identity(self) -> None:
        topology = regional_blender.build_preview_topology(
            (HexCell(0, 0), HexCell(0, 1))
        )
        self.assertEqual(len(topology.points_m), 12)
        self.assertEqual(len(topology.faces), 12)
        self.assertEqual(len(topology.boundary_edges), 11)
        self.assertEqual(list(topology.face_cell_ids), [0] * 6 + [1] * 6)
        self.assertEqual(list(topology.face_q), [0] * 12)
        self.assertEqual(list(topology.face_r), [0] * 6 + [1] * 6)
        self.assertEqual(list(topology.face_sectors), list(range(6)) * 2)

        for face in topology.faces:
            center, first, second = (
                topology.points_m[index] for index in face
            )
            signed_area_twice = (
                (first[0] - center[0]) * (second[1] - center[1])
                - (first[1] - center[1]) * (second[0] - center[0])
            )
            self.assertGreater(signed_area_twice, 0)

    def test_plan_only_cli_is_host_python_safe(self) -> None:
        arguments = regional_blender.parse_arguments(
            ["--plan-only", "--display-scale", "0.002"]
        )
        self.assertTrue(arguments.plan_only)
        self.assertEqual(arguments.display_scale, 0.002)


if __name__ == "__main__":
    unittest.main()
