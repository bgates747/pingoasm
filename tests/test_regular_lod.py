from __future__ import annotations

import unittest
from collections import Counter

from pingo_terrain.hex_terrain import (
    HEX_CELL_COUNT,
    HexCell,
    build_hex_terrain_cell,
    cell_from_id,
    hex_topology,
)
from pingo_terrain.p3dm import make_container, parse_container
from pingo_terrain.regular_lod import (
    ACTIVE_CELL_COUNT,
    FAR_RING,
    FINE_TRIANGLES_PER_SECTOR,
    HIERARCHY_LEVELS,
    HierarchyNode,
    NEAR_RING_MAX,
    SLOT_COUNT,
    SURFACE_TRIANGLES,
    TOTAL_TRIANGLES,
    TOTAL_VERTICES,
    axial_distance,
    decimate_l0_tile,
    lod_for_offset,
    ordered_disk_offsets,
    iter_hierarchy_nodes,
    node_planar_half_extents_m,
    sector_fine_faces,
    select_hierarchy_nodes,
    stable_slot,
    validate_full_partition,
    validate_bounded_hierarchy_plan,
    validate_hierarchy_plan,
    validate_slot_hash,
)


def source_tile(cell: HexCell):
    topology = hex_topology(cell.q, cell.r)
    elevations = tuple(
        (east + north) / 160_000.0 for east, north in topology.keys
    )
    materials = tuple(index % 15 for index in range(len(topology.faces)))
    return build_hex_terrain_cell(
        cell.q,
        cell.r,
        elevations_m=elevations,
        surface_materials=materials,
    ).tile


class RegularLodTests(unittest.TestCase):
    def test_fine_faces_partition_into_equal_regular_sectors(self) -> None:
        sectors = sector_fine_faces(HexCell(80, 125))
        self.assertEqual(tuple(map(len, sectors)), (FINE_TRIANGLES_PER_SECTOR,) * 6)
        self.assertEqual(
            sorted(face for sector in sectors for face in sector),
            list(range(6 * FINE_TRIANGLES_PER_SECTOR)),
        )

    def test_n1_is_a_strict_encoded_n5_decimation(self) -> None:
        cell = HexCell(80, 125)
        source = source_tile(cell)
        decimated = decimate_l0_tile(cell, source)
        self.assertEqual(decimated.tile.meta.lod, 1)
        self.assertEqual(decimated.tile.meta.tile_x, cell.q)
        self.assertEqual(decimated.tile.meta.tile_y, cell.r)
        self.assertEqual(decimated.tile.meta.model_half_extent_m, 1024)
        self.assertEqual(len(decimated.tile.positions), TOTAL_VERTICES)
        self.assertEqual(
            len(decimated.tile.position_indices) // 3,
            TOTAL_TRIANGLES,
        )
        self.assertEqual(len(decimated.sector_material_ids), SURFACE_TRIANGLES)
        self.assertTrue(
            set(decimated.tile.positions[:7]).issubset(set(source.positions[:91]))
        )
        self.assertEqual(
            parse_container(make_container(decimated.tile)),
            decimated.tile,
        )

    def test_material_reduction_preserves_sector_area(self) -> None:
        cell = HexCell(80, 125)
        decimated = decimate_l0_tile(cell, source_tile(cell))
        for histogram in decimated.sector_class_histograms:
            self.assertEqual(sum(histogram), FINE_TRIANGLES_PER_SECTOR)
        self.assertTrue(set(decimated.sector_material_ids).issubset({0, 1, 5}))

    def test_runtime_disk_order_and_lod_policy(self) -> None:
        offsets = ordered_disk_offsets()
        self.assertEqual(len(offsets), ACTIVE_CELL_COUNT)
        self.assertEqual(len(set(offsets)), ACTIVE_CELL_COUNT)
        self.assertEqual(offsets[0], (0, 0))
        self.assertTrue(
            all(axial_distance(*offset) <= NEAR_RING_MAX for offset in offsets[:91])
        )
        self.assertTrue(
            all(axial_distance(*offset) > NEAR_RING_MAX for offset in offsets[91:])
        )
        self.assertEqual(axial_distance(*offsets[91]), FAR_RING)
        self.assertEqual(lod_for_offset(5, 0, 5), 0)
        self.assertEqual(lod_for_offset(6, 0, 5), 1)
        self.assertEqual(lod_for_offset(1, 0, 0), 1)

    def test_radius_thirty_hash_is_exact_and_collision_free(self) -> None:
        offsets = ordered_disk_offsets()
        slots = {stable_slot(q, r) for q, r in offsets}
        self.assertEqual(slots, set(range(SLOT_COUNT)))
        validate_slot_hash(offsets)

    def test_complete_region_remains_one_dense_partition(self) -> None:
        validate_full_partition()

    def test_hierarchy_extents_fit_guarded_p3dm_models(self) -> None:
        expected = {
            "L8": ((2000.0, 1237.5), 2001, 64032),
            "L4": ((1040.0, 687.5), 1041, 33312),
            "L2": ((560.0, 412.5), 1024, 32768),
            "L1": ((320.0, 275.0), 1024, 32768),
        }
        for level in HIERARCHY_LEVELS:
            with self.subTest(level=level.name):
                self.assertEqual(
                    (
                        node_planar_half_extents_m(HierarchyNode(level, 0, 0)),
                        level.model_half_extent_m,
                        level.object_scale_q8_8,
                    ),
                    expected[level.name],
                )

    def test_complete_hierarchy_has_all_algorithmic_records(self) -> None:
        counts = Counter(node.level.name for node in iter_hierarchy_nodes())
        self.assertEqual(
            counts,
            {"L8": 1593, "L4": 6372, "L2": 25145, "L1": 50183},
        )

    def test_all_rings_and_alignment_phases_have_exact_ownership(self) -> None:
        total_ranges = {}
        for near_ring in range(NEAR_RING_MAX + 1):
            totals = []
            near_count = 1 + 3 * near_ring * (near_ring + 1)
            for phase_q in range(8):
                for phase_row in range(4):
                    q = 80 + phase_q
                    row = 120 + phase_row
                    r = row - q // 2
                    validate_hierarchy_plan(q, r, near_ring)
                    totals.append(
                        near_count + len(select_hierarchy_nodes(q, r, near_ring))
                    )
            total_ranges[near_ring] = min(totals), max(totals)
        self.assertEqual(
            total_ranges,
            {
                0: (107, 119),
                1: (114, 133),
                2: (136, 148),
                3: (159, 179),
                4: (189, 204),
                5: (217, 250),
            },
        )

    def test_bounded_corpus_edges_preserve_exact_ownership(self) -> None:
        for cell in (
            cell_from_id(0),
            cell_from_id(HEX_CELL_COUNT // 2),
            cell_from_id(HEX_CELL_COUNT - 1),
            HexCell(80, 125),
        ):
            with self.subTest(cell=(cell.q, cell.r)):
                validate_bounded_hierarchy_plan(cell.q, cell.r, NEAR_RING_MAX)


if __name__ == "__main__":
    unittest.main()
