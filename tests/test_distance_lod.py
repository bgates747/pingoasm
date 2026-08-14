from __future__ import annotations

import unittest

from pingo_terrain.distance_lod import (
    FAR_RING,
    MIDDLE_RING,
    NEAR_RING,
    DistanceFace,
    DistanceVertex,
    axial_distance,
    build_chunk,
    chunk_key,
    distance_tier,
)
from pingo_terrain.p3dm import make_container, parse_container


class DistanceLodTests(unittest.TestCase):
    def test_ring_classification(self) -> None:
        self.assertEqual(axial_distance(80, 125), 0)
        self.assertIsNone(distance_tier(80 + NEAR_RING, 125))
        self.assertEqual(distance_tier(80 + NEAR_RING + 1, 125), 1)
        self.assertEqual(distance_tier(80 + MIDDLE_RING, 125), 1)
        self.assertEqual(distance_tier(80 + MIDDLE_RING + 1, 125), 2)
        self.assertEqual(distance_tier(80 + FAR_RING, 125), 2)
        self.assertIsNone(distance_tier(80 + FAR_RING + 1, 125))

    def test_chunk_round_trip_and_skirt(self) -> None:
        vertices = {
            0: DistanceVertex(0, 0, 10.0),
            1: DistanceVertex(100, 0, 12.0),
            2: DistanceVertex(0, 100, 14.0),
            3: DistanceVertex(100, 100, 16.0),
        }
        faces = (
            DistanceFace((0, 1, 2), 86, 125, 0),
            DistanceFace((1, 3, 2), 86, 125, 1),
        )
        key = chunk_key(faces[0])
        self.assertIsNotNone(key)
        self.assertEqual(chunk_key(faces[1]), key)
        built = build_chunk(0, key, faces, vertices)  # type: ignore[arg-type]
        self.assertEqual(built.surface_triangles, 2)
        self.assertEqual(built.skirt_triangles, 8)
        self.assertEqual(len(built.tile.position_indices) // 3, 10)
        self.assertEqual(parse_container(make_container(built.tile)), built.tile)

    def test_mixed_bucket_is_rejected(self) -> None:
        vertices = {
            0: DistanceVertex(0, 0, 0.0),
            1: DistanceVertex(1, 0, 0.0),
            2: DistanceVertex(0, 1, 0.0),
        }
        first = DistanceFace((0, 1, 2), 86, 125, 0)
        second = DistanceFace((0, 1, 2), 93, 125, 0)
        with self.assertRaisesRegex(ValueError, "mixes bucket"):
            build_chunk(0, chunk_key(first), (first, second), vertices)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
