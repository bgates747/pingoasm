from __future__ import annotations

from fractions import Fraction
import unittest

from pingo_terrain.feature_terrain import (
    cyclic_corner_smooth,
    point_in_polygon,
    polygon_centroid,
    quantize_loop,
    reconcile_feature_crossings,
    signed_area,
)


class FeatureTerrainGeometryTests(unittest.TestCase):
    def test_cyclic_filter_rounds_without_changing_cardinality(self) -> None:
        square = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
        rounded = cyclic_corner_smooth(square)
        self.assertEqual(
            rounded,
            ((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)),
        )
        self.assertEqual(len(rounded), len(square))
        self.assertGreater(signed_area(rounded), 0.0)
        self.assertEqual(polygon_centroid(rounded), (2.0, 2.0))

    def test_quantization_retains_ccw_loop_and_removes_collisions(self) -> None:
        loop = ((0.0, 0.0), (0.01, 0.01), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
        quantized = quantize_loop(loop, counts_per_metre=16)
        self.assertEqual(len(quantized), 4)
        self.assertGreater(signed_area(quantized), 0.0)

    def test_feature_crossing_becomes_one_canonical_shared_key(self) -> None:
        feature = ((-5, -5), (5, -5), (5, 5), (-5, 5))
        terrain = (((0, -10), (0, 10)),)
        reconciled = reconcile_feature_crossings(feature, terrain)
        self.assertEqual(reconciled.crossing_points, ((0, -5), (0, 5)))
        self.assertIn((0, -5), reconciled.feature_loop)
        self.assertIn((0, 5), reconciled.feature_loop)
        self.assertEqual(
            reconciled.terrain_segments,
            (((0, -10), (0, -5)), ((0, -5), (0, 5)), ((0, 5), (0, 10))),
        )

    def test_point_in_polygon_includes_exact_edges_and_rational_centroids(self) -> None:
        square = ((0, 0), (8, 0), (8, 8), (0, 8))
        self.assertTrue(point_in_polygon((4, 4), square))
        self.assertTrue(point_in_polygon((0, 4), square))
        self.assertTrue(point_in_polygon((Fraction(7, 3), Fraction(5, 3)), square))
        self.assertFalse(point_in_polygon((9, 4), square))


if __name__ == "__main__":
    unittest.main()
