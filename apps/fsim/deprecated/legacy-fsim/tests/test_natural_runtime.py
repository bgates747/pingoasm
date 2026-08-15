from __future__ import annotations

import unittest

from pingo_terrain.hex_terrain import COUNTS_PER_METRE, HexCell
from pingo_terrain.natural_runtime import (
    NaturalRuntimeComponent,
    build_natural_runtime_component,
    maximum_absolute_position_word,
    reconstruct_renderer_float32,
    reconstruct_vertex_numerators,
    validate_same_lod_seams,
)
from pingo_terrain.p3dm import make_container, parse_container


def two_face_components() -> tuple[NaturalRuntimeComponent, ...]:
    west_cell = HexCell(90, 121)
    east_cell = HexCell(91, 121)
    west_center = west_cell.center_m
    east_center = east_cell.center_m
    middle_east = (west_center[0] + east_center[0]) * COUNTS_PER_METRE // 2
    middle_north = (west_center[1] + east_center[1]) * COUNTS_PER_METRE // 2
    lower = (middle_east, middle_north - 1000, 1600)
    upper = (middle_east, middle_north + 1000, 1616)
    west = (middle_east - 1000, middle_north, 1592)
    east = (middle_east + 1000, middle_north, 1624)
    return (
        NaturalRuntimeComponent(
            cell=west_cell,
            vertices=(west, lower, upper),
            faces=((0, 1, 2),),
            materials=(7,),
        ),
        NaturalRuntimeComponent(
            cell=east_cell,
            vertices=(east, upper, lower),
            faces=((0, 1, 2),),
            materials=(8,),
        ),
    )


class NaturalRuntimeTests(unittest.TestCase):
    def test_components_reverse_blender_winding_and_round_trip_p3dm(self) -> None:
        source = two_face_components()[0]
        built = build_natural_runtime_component(source)
        self.assertEqual(built.oriented_faces, ((0, 2, 1),))
        self.assertEqual(built.tile.position_indices, (0, 2, 1))
        self.assertEqual(built.tile.uv_indices, (7, 7, 7))
        self.assertEqual(parse_container(make_container(built.tile)), built.tile)
        for index, (east, north, elevation) in enumerate(source.vertices):
            self.assertEqual(
                reconstruct_vertex_numerators(built, index),
                (north * 256, elevation * 256, -east * 256),
            )

    def test_same_lod_seam_is_two_exact_opposite_copies(self) -> None:
        built = tuple(
            build_natural_runtime_component(component)
            for component in two_face_components()
        )
        report = validate_same_lod_seams(built)
        self.assertEqual(report["components"], 2)
        self.assertEqual(report["selected_selected_seam_edges"], 1)
        self.assertEqual(report["selected_subset_outer_edges"], 4)
        self.assertEqual(report["physical_component_pairs"], 1)
        self.assertEqual(report["boundary_reconstruction_instances"], 12)
        self.assertEqual(report["reconstruction_mismatches"], 0)
        self.assertEqual(report["renderer_float32_shared_vertices"], 2)
        self.assertGreaterEqual(
            report["renderer_float32_nonidentical_shared_vertices"], 0
        )
        self.assertLessEqual(
            report["renderer_float32_maximum_span_pingo_units"],
            3.0517578125e-05,
        )
        for component in built:
            for index in range(len(component.tile.positions)):
                self.assertEqual(
                    len(
                        reconstruct_renderer_float32(
                            component,
                            index,
                            built[0].source.cell,
                        )
                    ),
                    3,
                )
        self.assertLess(maximum_absolute_position_word(built), 32768)

    def test_disconnected_component_fails_before_p3dm_emission(self) -> None:
        cell = HexCell(90, 121)
        east, north = (value * COUNTS_PER_METRE for value in cell.center_m)
        component = NaturalRuntimeComponent(
            cell=cell,
            vertices=(
                (east, north, 1000),
                (east + 16, north, 1000),
                (east, north + 16, 1000),
                (east + 160, north, 1000),
                (east + 176, north, 1000),
                (east + 160, north + 16, 1000),
            ),
            faces=((0, 1, 2), (3, 4, 5)),
            materials=(1, 1),
        )
        with self.assertRaisesRegex(ValueError, "not connected"):
            build_natural_runtime_component(component)

    def test_extent_overflow_fails_closed(self) -> None:
        cell = HexCell(90, 121)
        east, north = (value * COUNTS_PER_METRE for value in cell.center_m)
        component = NaturalRuntimeComponent(
            cell=cell,
            vertices=(
                (east, north, 1000),
                (east + 16_384, north, 1000),
                (east, north + 16, 1000),
            ),
            faces=((0, 1, 2),),
            materials=(1,),
        )
        with self.assertRaisesRegex(ValueError, "exceeds the common"):
            build_natural_runtime_component(component)


if __name__ == "__main__":
    unittest.main()
