from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_natural_region_blender as natural_blender  # noqa: E402

from pingo_terrain.natural_region import (
    AdaptiveRegionProfile,
    SOURCE_CORPUS_EDGE,
    SOURCE_DEM_CURVATURE,
    SOURCE_DEM_RESIDUAL,
    build_adaptive_region_plan,
    marching_water_segments,
)
from pingo_terrain.hex_terrain import HEX_CELL_COUNT, iter_cells  # noqa: E402


class NaturalRegionSelectionTests(unittest.TestCase):
    def test_complete_region_plan_has_exact_pinned_extent(self) -> None:
        cells = tuple(iter_cells())
        grid = natural_blender.analysis_grid(
            cells, natural_blender.AdaptiveRegionProfile()
        )
        self.assertEqual(len(cells), HEX_CELL_COUNT)
        self.assertEqual(grid.origin_m, (521_600, 4_099_968))
        self.assertEqual((grid.columns, grid.rows), (806, 1012))
        self.assertEqual(grid.point_count, 815_672)
        self.assertEqual(
            grid.corpus_bounds_m,
            (521_664, 4_100_077, 624_544, 4_229_327),
        )

    def test_protected_segment_may_survive_as_exact_collinear_chain(self) -> None:
        evidence, edges = natural_blender._validate_constraint_chains(
            constraints=((0, 1),),
            output_edges={(0, 2), (1, 2)},
            points=((0, 0), (128, 0), (64, 0)),
        )
        self.assertEqual(
            evidence,
            {
                "direct_segments": 0,
                "subdivided_segments": 1,
                "maximum_edge_chain_pieces": 2,
                "passed": True,
            },
        )
        self.assertEqual(edges, frozenset({(0, 2), (1, 2)}))

    def test_marching_squares_covers_all_cases_deterministically(self) -> None:
        expected_counts = (0, 1, 1, 1, 1, 2, 1, 1, 1, 1, 2, 1, 1, 1, 1, 0)
        for case, expected in enumerate(expected_counts):
            categories = [11 if case & (1 << bit) else 24 for bit in range(4)]
            # marching input order is SW, SE, NW, NE; swap the final two bits
            categories[2], categories[3] = categories[3], categories[2]
            first = marching_water_segments(
                origin_m=(0, 0),
                columns=2,
                rows=2,
                step_m=128,
                categories=categories,
            )
            second = marching_water_segments(
                origin_m=(0, 0),
                columns=2,
                rows=2,
                step_m=128,
                categories=categories,
            )
            self.assertEqual(first, second)
            self.assertEqual(len(first), expected, case)
            self.assertEqual(len(first), len(set(first)))
            self.assertTrue(all(a != b for a, b in first))

    def test_flat_grid_keeps_only_spaced_perimeter_and_seed(self) -> None:
        profile = AdaptiveRegionProfile(
            analysis_step_m=128,
            corpus_edge_stride=4,
            middle_residual_m=0.1,
            coarse_residual_m=0.1,
            curvature_residual_m=0.1,
        )
        plan = build_adaptive_region_plan(
            origin_m=(0, 0),
            columns=9,
            rows=9,
            heights_m=[3.0] * 81,
            categories=[24] * 81,
            logical_seed_points_m=((512, 512),),
            profile=profile,
        )
        flags = dict(zip(plan.points, plan.point_source_flags, strict=True))
        perimeter = {point for point, flag in flags.items() if flag & SOURCE_CORPUS_EDGE}
        self.assertEqual(
            perimeter,
            {
                (0, 0),
                (512, 0),
                (1024, 0),
                (0, 512),
                (1024, 512),
                (0, 1024),
                (512, 1024),
                (1024, 1024),
            },
        )

    def test_mixed_curvature_saddle_is_not_lost(self) -> None:
        columns = rows = 9
        heights = [float(i * j) for j in range(rows) for i in range(columns)]
        plan = build_adaptive_region_plan(
            origin_m=(0, 0),
            columns=columns,
            rows=rows,
            heights_m=heights,
            categories=[24] * (columns * rows),
            logical_seed_points_m=(),
            profile=AdaptiveRegionProfile(
                analysis_step_m=128,
                middle_residual_m=100.0,
                coarse_residual_m=100.0,
                curvature_residual_m=0.1,
            ),
        )
        flags = dict(zip(plan.points, plan.point_source_flags, strict=True))
        self.assertTrue(
            any(
                flag & SOURCE_DEM_CURVATURE
                and 0 < point[0] < 1024
                and 0 < point[1] < 1024
                for point, flag in flags.items()
            )
        )

    def test_partial_stride_boundary_uses_one_dimensional_interpolation(self) -> None:
        columns = rows = 6
        heights = [0.0] * (columns * rows)
        heights[3 * columns + 5] = 10.0
        plan = build_adaptive_region_plan(
            origin_m=(0, 0),
            columns=columns,
            rows=rows,
            heights_m=heights,
            categories=[24] * (columns * rows),
            logical_seed_points_m=(),
            profile=AdaptiveRegionProfile(
                analysis_step_m=128,
                middle_residual_m=1.0,
                coarse_residual_m=100.0,
                curvature_residual_m=100.0,
                corpus_edge_stride=4,
            ),
        )
        flags = dict(zip(plan.points, plan.point_source_flags, strict=True))
        self.assertTrue(flags[(640, 384)] & SOURCE_DEM_RESIDUAL)
        self.assertFalse(flags[(640, 384)] & SOURCE_CORPUS_EDGE)

    def test_seed_points_must_be_unique_integral_and_in_bounds(self) -> None:
        arguments = dict(
            origin_m=(0, 0),
            columns=3,
            rows=3,
            heights_m=[0.0] * 9,
            categories=[24] * 9,
            profile=AdaptiveRegionProfile(analysis_step_m=128),
        )
        for seeds in (((64.5, 64),), ((384, 128),), ((128, 128), (128, 128))):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                build_adaptive_region_plan(
                    logical_seed_points_m=seeds,
                    **arguments,
                )


if __name__ == "__main__":
    unittest.main()
