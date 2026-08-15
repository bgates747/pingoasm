from __future__ import annotations

from collections.abc import Iterator, Mapping
import unittest

from pingo_terrain.collision import (
    MAX_DOWNWARD_ACCEL_Q8,
    MAX_HORIZONTAL_ACCEL_Q8,
    Q15_ONE,
    AircraftProxy,
    AircraftSweep,
    AirportContactBox,
    AirportEnvelope,
    ClosedAABB,
    CollisionDisposition,
    CollisionPose,
    ContactKind,
    RunwaySupportRegion,
    TerrainEnvelope,
    TerrainSurfaceBox,
    elevation_dm_ceil_q8,
    elevation_dm_floor_q8,
    evaluate_collision,
    runway_contains,
    runway_contains_proxy,
    runway_sweep_overlaps,
    terrain_surface_boxes_from_p3dm,
)
from pingo_terrain.flight_model import (
    GRAVITY_STEP_Q8,
    MAX_THRUST_Q8,
    VELOCITY_LIMIT_Q8,
    lift_q8,
)
from pingo_terrain.p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
)
from pingo_terrain.streaming import (
    POSITION_Q8_PER_METRE,
    FloatingOriginPosition,
    RegionalGrid,
)


M = POSITION_Q8_PER_METRE
GRID = RegionalGrid(0, 0, 4, 4)


class ForbiddenMapping(Mapping):
    """Fail if a broad-phase rejection accidentally reaches detail data."""

    def __getitem__(self, key):  # pragma: no cover - failure path
        raise AssertionError(f"narrow mapping was accessed for {key!r}")

    def __iter__(self) -> Iterator:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __contains__(self, key) -> bool:  # pragma: no cover - failure path
        raise AssertionError(f"narrow mapping was probed for {key!r}")


class TrackingMapping(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lookups = []

    def get(self, key, default=None):
        self.lookups.append(key)
        return super().get(key, default)


def pose(east_m: float, north_m: float, altitude_m: float) -> CollisionPose:
    return CollisionPose(round(east_m * M), round(north_m * M), round(altitude_m * M))


def proxy(horizontal_m: float = 1.0, vertical_m: float = 1.0) -> AircraftProxy:
    return AircraftProxy(
        round(horizontal_m * M),
        round(horizontal_m * M),
        round(vertical_m * M),
        round(vertical_m * M),
    )


def stationary(
    east_m: float,
    north_m: float,
    altitude_m: float,
    *,
    body: AircraftProxy | None = None,
    supported: bool = False,
) -> AircraftSweep:
    point = pose(east_m, north_m, altitude_m)
    return AircraftSweep(point, point, body or proxy(), was_runway_supported=supported)


def envelope(tile_x: int, tile_y: int, minimum_dm: int, maximum_dm: int):
    return TerrainEnvelope(tile_x, tile_y, minimum_dm, maximum_dm, 768)


def surface_box(
    identifier: int,
    west_m: float,
    south_m: float,
    east_m: float,
    north_m: float,
    minimum_m: float,
    maximum_m: float,
) -> TerrainSurfaceBox:
    return TerrainSurfaceBox(
        identifier,
        ClosedAABB(
            round(west_m * M),
            round(south_m * M),
            round(minimum_m * M),
            round(east_m * M),
            round(north_m * M),
            round(maximum_m * M),
        ),
    )


class FixedPointAndP3DMTests(unittest.TestCase):
    def test_descriptor_decimetres_round_outward_for_both_signs(self) -> None:
        self.assertEqual(elevation_dm_floor_q8(1), 409)
        self.assertEqual(elevation_dm_ceil_q8(1), 410)
        self.assertEqual(elevation_dm_floor_q8(-1), -410)
        self.assertEqual(elevation_dm_ceil_q8(-1), -409)

    def test_descriptor_broad_bounds_include_mesh_decode_error(self) -> None:
        bound = TerrainEnvelope(0, 0, 100, 100, 768)
        self.assertLess(bound.minimum_altitude_q8, 10 * M)
        self.assertGreater(bound.maximum_altitude_q8, 10 * M)
        self.assertEqual(bound.collision_slack_q8, 2 * bound.decode_error_q8 + 1)

    def test_floating_origin_conversion_preserves_regional_axes(self) -> None:
        source = FloatingOriginPosition(1, 2, 17, -33)
        converted = CollisionPose.from_floating_origin(GRID, source, 123)
        self.assertEqual(converted.east_q8, GRID.tile_position_q8 + 0x100000 + 17)
        self.assertEqual(converted.north_q8, 2 * GRID.tile_position_q8 + 0x100000 - 33)
        self.assertEqual(converted.altitude_q8, 123)

    def test_p3dm_surface_boxes_exclude_skirts_and_round_outward(self) -> None:
        tile = P3DMTile(
            stage_buffer_id=0x7400,
            meta=P3DMMeta(
                layer_kind=LayerKind.TERRAIN,
                lod=0,
                shading_mode=ShadingMode.FLAT_PATTERN,
                illumination=IlluminationPolicy.SCENE,
                material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
                tile_x=0,
                tile_y=0,
                center_east_m=256,
                center_north_m=256,
                minimum_elevation_dm=-10,
                maximum_elevation_dm=10,
                model_half_extent_m=10,
            ),
            positions=(
                (0, 0, 0),
                (0, 100, 1000),
                (1000, 200, 0),
                (0, -1000, 0),
                (0, -900, 1000),
            ),
            position_indices=(0, 1, 2, 0, 3, 4),
            uvs=((0, 0),),
            uv_indices=(0, 0, 0, 0, 0, 0),
        )
        boxes = terrain_surface_boxes_from_p3dm(tile, vertical_origin_q8=0)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0].identifier, 0)
        bounds = boxes[0].bounds
        expected_span = 1000 * 10 * M / Q15_ONE
        self.assertLessEqual(bounds.minimum_east_q8, round((256 * M) - expected_span))
        self.assertGreaterEqual(bounds.maximum_north_q8, round((256 * M) + expected_span))
        self.assertGreaterEqual(bounds.maximum_altitude_q8, 200 * 10 * M / Q15_ONE)
        self.assertGreaterEqual(bounds.minimum_east_q8, 0)
        self.assertLessEqual(bounds.maximum_east_q8, 512 * M)

    def test_descriptor_broad_maximum_dominates_expanded_surface_box(self) -> None:
        source_elevation_m = 100
        raw_y = round((source_elevation_m - 608) * Q15_ONE / 768)
        tile = P3DMTile(
            stage_buffer_id=0x7400,
            meta=P3DMMeta(
                layer_kind=LayerKind.TERRAIN,
                lod=0,
                shading_mode=ShadingMode.FLAT_PATTERN,
                illumination=IlluminationPolicy.SCENE,
                material_set=MaterialSet.TERRAIN_SELECTOR_4X4,
                tile_x=0,
                tile_y=0,
                center_east_m=256,
                center_north_m=256,
                minimum_elevation_dm=1000,
                maximum_elevation_dm=1000,
                model_half_extent_m=768,
            ),
            positions=((0, raw_y, 0), (0, raw_y, 1000), (1000, raw_y, 0)),
            position_indices=(0, 1, 2),
            uvs=((0, 0),),
            uv_indices=(0, 0, 0),
        )
        broad = TerrainEnvelope.from_p3dm(tile)
        narrow = terrain_surface_boxes_from_p3dm(tile)
        self.assertGreaterEqual(
            broad.maximum_altitude_q8,
            max(box.bounds.maximum_altitude_q8 for box in narrow),
        )

    def test_f2_acceleration_envelopes_cover_current_force_extrema(self) -> None:
        maximum_lift = lift_q8(VELOCITY_LIMIT_Q8, 0)
        maximum_drag = VELOCITY_LIMIT_Q8 >> 8
        loose_horizontal = maximum_lift + MAX_THRUST_Q8 + maximum_drag
        loose_downward = loose_horizontal + abs(GRAVITY_STEP_Q8)
        self.assertEqual((loose_horizontal, loose_downward), (140, 185))
        self.assertGreaterEqual(MAX_HORIZONTAL_ACCEL_Q8, loose_horizontal)
        self.assertGreaterEqual(MAX_DOWNWARD_ACCEL_Q8, loose_downward)


class TerrainPolicyTests(unittest.TestCase):
    def test_high_aircraft_uses_only_descriptor_maximum(self) -> None:
        decision = evaluate_collision(
            stationary(768, 768, 100),
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 100)},
            terrain_surface_boxes=ForbiddenMapping(),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CLEAR)
        self.assertEqual(decision.terrain_box_tests, 0)

    def test_far_mountain_is_rejected_by_reachable_horizontal_bounds(self) -> None:
        envelopes = TrackingMapping(
            {
                (1, 1): envelope(1, 1, -100, 0),
                (3, 3): envelope(3, 3, -100, 20_000),
            }
        )
        decision = evaluate_collision(
            stationary(768, 768, 100),
            grid=GRID,
            terrain_envelopes=envelopes,
            terrain_surface_boxes=ForbiddenMapping(),
            maximum_horizontal_accel_q8=0,
            maximum_downward_accel_q8=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CLEAR)
        self.assertNotIn((3, 3), envelopes.lookups)

    def test_missing_immediate_descriptor_holds_last_safe_pose(self) -> None:
        decision = evaluate_collision(
            stationary(768, 768, 20),
            grid=GRID,
            terrain_envelopes={},
            terrain_surface_boxes={},
        )
        self.assertEqual(decision.disposition, CollisionDisposition.HOLD_FOR_DATA)
        self.assertEqual(decision.contact_kind, ContactKind.TERRAIN)

    def test_probable_contact_without_detail_holds_instead_of_clearing(self) -> None:
        decision = evaluate_collision(
            stationary(768, 768, 4),
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 50)},
            terrain_surface_boxes={},
        )
        self.assertEqual(decision.disposition, CollisionDisposition.HOLD_FOR_DATA)
        self.assertIn("no retained surface boxes", decision.reason)

    def test_aircraft_below_descriptor_minimum_is_definite_contact(self) -> None:
        decision = evaluate_collision(
            stationary(768, 768, 5),
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, 100, 200)},
            terrain_surface_boxes=ForbiddenMapping(),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.contact_kind, ContactKind.TERRAIN)
        self.assertEqual(decision.terrain_box_tests, 0)

    def test_narrow_surface_box_treats_exact_equality_as_contact(self) -> None:
        contact = surface_box(7, 767, 767, 768, 768, 0, 3)
        decision = evaluate_collision(
            stationary(769, 769, 4),
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 50)},
            terrain_surface_boxes={(1, 1): (contact,)},
            lookahead_ticks=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.subject, "1,1:7")
        self.assertEqual(decision.terrain_box_tests, 1)

    def test_narrow_boxes_can_clear_an_immediate_descriptor_overlap(self) -> None:
        remote = surface_box(3, 512, 512, 600, 600, 0, 20)
        decision = evaluate_collision(
            stationary(768, 768, 4),
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 200)},
            terrain_surface_boxes={(1, 1): (remote,)},
            lookahead_ticks=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CLEAR)
        self.assertEqual(decision.terrain_box_tests, 1)

    def test_ahead_high_tile_warns_without_reading_its_surface_boxes(self) -> None:
        sweep = AircraftSweep(
            pose(1010, 768, 50),
            pose(1011, 768, 50),
            proxy(),
            velocity_east_q8=M,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes={
                (1, 1): envelope(1, 1, -100, 0),
                (2, 1): envelope(2, 1, -100, 1000),
            },
            terrain_surface_boxes=ForbiddenMapping(),
            maximum_horizontal_accel_q8=0,
            maximum_downward_accel_q8=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.AHEAD_WARNING)
        self.assertEqual(decision.subject, "2,1")
        self.assertEqual(decision.terrain_box_tests, 0)

    def test_missing_ahead_descriptor_warns_but_does_not_hold_current_step(self) -> None:
        sweep = AircraftSweep(
            pose(1010, 768, 100),
            pose(1011, 768, 100),
            proxy(),
            velocity_east_q8=M,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 0)},
            terrain_surface_boxes=ForbiddenMapping(),
            maximum_horizontal_accel_q8=0,
            maximum_downward_accel_q8=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.AHEAD_WARNING)
        self.assertEqual(decision.subject, "2,1")


class RunwayAndAirportPolicyTests(unittest.TestCase):
    def runway(self) -> RunwaySupportRegion:
        return RunwaySupportRegion(
            "KOAK-10R/28L",
            center_east_q8=768 * M,
            center_north_q8=768 * M,
            along_east_q15=Q15_ONE,
            along_north_q15=0,
            half_length_counts=100,
            half_width_counts=20,
            reference_altitude_q8=10 * M,
        )

    def low_terrain(self):
        return {(1, 1): envelope(1, 1, -100, 0)}

    def test_runway_rectangle_is_closed_at_its_exact_edge(self) -> None:
        region = self.runway()
        edge = CollisionPose(
            region.center_east_q8 + region.half_length_counts * 256,
            region.center_north_q8 + region.half_width_counts * 256,
            region.reference_altitude_q8,
        )
        self.assertTrue(runway_contains(region, edge))
        self.assertFalse(runway_contains_proxy(region, edge, proxy()))

    def test_fractional_count_cannot_false_prove_full_runway_containment(self) -> None:
        region = self.runway()
        almost_85_counts = 84 * 256 + 255
        point = CollisionPose(
            region.center_east_q8 + almost_85_counts,
            region.center_north_q8,
            region.reference_altitude_q8,
        )
        self.assertTrue(runway_contains(region, point))
        self.assertFalse(runway_contains_proxy(region, point, proxy()))

    def test_explicit_runway_support_masks_flat_terrain_beneath_it(self) -> None:
        decision = evaluate_collision(
            stationary(768, 768, 10, supported=True),
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes=ForbiddenMapping(),
            runway_regions=(self.runway(),),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.RUNWAY_SUPPORTED)
        self.assertEqual(decision.contact_kind, ContactKind.RUNWAY)

    def test_gentle_downward_crossing_acquires_support(self) -> None:
        sweep = AircraftSweep(
            pose(768, 768, 10.25),
            pose(768, 768, 10),
            proxy(),
            velocity_up_q8=-100,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes=ForbiddenMapping(),
            runway_regions=(self.runway(),),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.RUNWAY_SUPPORTED)
        self.assertIn("acquired", decision.reason)

    def test_positive_takeoff_velocity_releases_existing_support(self) -> None:
        sweep = AircraftSweep(
            pose(768, 768, 10),
            pose(768, 768, 10.1),
            proxy(),
            velocity_up_q8=100,
            was_runway_supported=True,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 200)},
            terrain_surface_boxes=ForbiddenMapping(),
            runway_regions=(self.runway(),),
            lookahead_ticks=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CLEAR)
        self.assertEqual(decision.contact_kind, ContactKind.NONE)
        self.assertIn("wholly above", decision.reason)

    def test_partial_runway_footprint_does_not_mask_terrain(self) -> None:
        region = self.runway()
        end = CollisionPose(
            region.center_east_q8 + region.half_length_counts * 256,
            region.center_north_q8,
            region.reference_altitude_q8 + M,
        )
        sweep = AircraftSweep(
            end,
            end,
            proxy(),
            velocity_up_q8=100,
            was_runway_supported=True,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes={(1, 1): envelope(1, 1, -100, 200)},
            terrain_surface_boxes={},
            runway_regions=(region,),
            lookahead_ticks=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.HOLD_FOR_DATA)

    def test_downward_sweep_off_runway_edge_is_contact_not_support(self) -> None:
        region = self.runway()
        sweep = AircraftSweep(
            pose(774.0, 768, 10.25),
            pose(774.5, 768, 9.9),
            proxy(),
            velocity_east_q8=M // 2,
            velocity_up_q8=-100,
        )
        self.assertTrue(runway_sweep_overlaps(region, sweep))
        self.assertFalse(runway_contains(region, sweep.end))
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes={},
            runway_regions=(region,),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.contact_kind, ContactKind.RUNWAY)

    def test_sweep_entering_runway_cannot_skip_uncovered_terrain(self) -> None:
        region = self.runway()
        sweep = AircraftSweep(
            pose(774.5, 768, 10.25),
            pose(768, 768, 10),
            proxy(),
            velocity_east_q8=-M,
            velocity_up_q8=-100,
        )
        self.assertTrue(runway_contains(region, sweep.end))
        self.assertFalse(runway_contains_proxy(region, sweep.start, sweep.proxy))
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes={},
            runway_regions=(region,),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.contact_kind, ContactKind.RUNWAY)

    def test_unsupported_below_plane_states_are_contact_not_touchdown(self) -> None:
        region = self.runway()
        sweeps = (
            AircraftSweep(pose(768, 768, 9.9), pose(768, 768, 9.9), proxy()),
            AircraftSweep(
                pose(768, 768, 9.9),
                pose(768, 768, 10.1),
                proxy(),
                velocity_up_q8=100,
            ),
        )
        for sweep in sweeps:
            with self.subTest(sweep=sweep):
                decision = evaluate_collision(
                    sweep,
                    grid=GRID,
                    terrain_envelopes=self.low_terrain(),
                    terrain_surface_boxes={},
                    runway_regions=(region,),
                )
                self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
                self.assertEqual(decision.contact_kind, ContactKind.RUNWAY)

    def test_fast_or_deep_runway_crossing_is_contact(self) -> None:
        sweep = AircraftSweep(
            pose(768, 768, 12),
            pose(768, 768, 9),
            proxy(),
            velocity_up_q8=-600,
        )
        decision = evaluate_collision(
            sweep,
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes={},
            runway_regions=(self.runway(),),
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.contact_kind, ContactKind.RUNWAY)

    def test_airport_detail_is_skipped_until_broad_box_is_probable(self) -> None:
        airport = AirportEnvelope(
            "KOAK-obstacles",
            ClosedAABB(700 * M, 700 * M, 0, 800 * M, 800 * M, 20 * M),
        )
        decision = evaluate_collision(
            stationary(768, 768, 100),
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes=ForbiddenMapping(),
            airport_envelopes=(airport,),
            airport_contact_boxes=ForbiddenMapping(),
            lookahead_ticks=0,
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CLEAR)
        self.assertEqual(decision.airport_box_tests, 0)

    def test_airport_obstacle_contact_overrides_runway_support(self) -> None:
        aircraft = stationary(768, 768, 10, supported=True)
        obstacle_bounds = ClosedAABB(
            767 * M,
            767 * M,
            9 * M,
            769 * M,
            769 * M,
            11 * M,
        )
        airport = AirportEnvelope("KOAK-obstacles", obstacle_bounds)
        decision = evaluate_collision(
            aircraft,
            grid=GRID,
            terrain_envelopes=self.low_terrain(),
            terrain_surface_boxes={},
            runway_regions=(self.runway(),),
            airport_envelopes=(airport,),
            airport_contact_boxes={
                "KOAK-obstacles": (AirportContactBox("hangar", obstacle_bounds),)
            },
        )
        self.assertEqual(decision.disposition, CollisionDisposition.CONTACT)
        self.assertEqual(decision.contact_kind, ContactKind.AIRPORT)
        self.assertEqual(decision.subject, "hangar")


if __name__ == "__main__":
    unittest.main()
