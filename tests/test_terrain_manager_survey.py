from __future__ import annotations

from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.hex_terrain import (
    HexCell,
    build_hex_terrain_cell,
    disk_offsets,
    hex_distance,
    hex_topology,
)
from pingo_terrain.p3dm import make_container, make_data


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/terrain-manager-survey"
MAIN = FIXTURE / "src/terrain-manager-survey.asm"
CONTROLS = FIXTURE / "src/terrain-manager-controls.inc"
SCENE = FIXTURE / "src/terrain-manager-scene.inc"
PROVIDER = FIXTURE / "src/terrain-manager-hex-provider.inc"
BUILDER_PATH = ROOT / "scripts/build_terrain_manager_survey.py"
RUNTIME_MANAGER = ROOT / "runtime/ez80/terrain-manager.inc"

sys.path.insert(0, str(ROOT / "scripts"))

import build_terrain_manager_survey as builder  # noqa: E402


HEX_CLOSED_X_COUNT = 4_400
HEX_CLOSED_Z_TIP_COUNT = 5_120
HEX_CLOSED_HALFPLANE = 9_011_200
HEX_HYSTERESIS_COUNT = 256
HEX_SLOPED_NORMAL_SQUARED = 1024**2 + 1760**2
HEX_SLOPED_HYSTERESIS = round(
    HEX_HYSTERESIS_COUNT * math.sqrt(HEX_SLOPED_NORMAL_SQUARED)
)
HEX_RETAIN_X_COUNT = HEX_CLOSED_X_COUNT + HEX_HYSTERESIS_COUNT
HEX_RETAIN_Z_TIP_COUNT = HEX_CLOSED_Z_TIP_COUNT + HEX_HYSTERESIS_COUNT
HEX_RETAIN_HALFPLANE = HEX_CLOSED_HALFPLANE + HEX_SLOPED_HYSTERESIS

# dq, dr, and the exact local-camera displacement applied by the provider.
HEX_ORIGIN_STEPS = (
    (0, 1, 8_800, 0),
    (0, -1, -8_800, 0),
    (1, 0, 4_400, -7_680),
    (1, -1, -4_400, -7_680),
    (-1, 1, 4_400, 7_680),
    (-1, 0, -4_400, 7_680),
)


def provider_rebase_step(x_count: int, z_count: int) -> tuple[int, int, int, int] | None:
    """Host oracle for the provider's ordered integer retention test."""

    if abs(x_count) > HEX_RETAIN_X_COUNT:
        return HEX_ORIGIN_STEPS[0 if x_count >= 0 else 1]
    if (
        abs(z_count) > HEX_RETAIN_Z_TIP_COUNT
        or 1024 * abs(x_count) + 1760 * abs(z_count) > HEX_RETAIN_HALFPLANE
    ):
        if z_count < 0:
            return HEX_ORIGIN_STEPS[2 if x_count >= 0 else 3]
        return HEX_ORIGIN_STEPS[4 if x_count >= 0 else 5]
    return None


def normalize_provider_position(
    x_count: int, z_count: int
) -> tuple[int, int, int, int, int]:
    """Apply provider steps until its expanded retention hex owns the point."""

    q = r = steps = 0
    while (step := provider_rebase_step(x_count, z_count)) is not None:
        dq, dr, displacement_x, displacement_z = step
        q += dq
        r += dr
        x_count -= displacement_x
        z_count -= displacement_z
        steps += 1
        if steps > 16:
            raise AssertionError("provider normalization did not converge")
    return q, r, x_count, z_count, steps


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


def make_validation_corpus(
    corpus: Path, cells: tuple[HexCell, ...]
) -> tuple[dict, dict[int, dict]]:
    """Make a tiny real P3DM corpus for exhaustive validator regressions."""

    records: list[dict] = []
    maximum_elevations: list[int] = []
    for cell in cells:
        topology = hex_topology(cell.q, cell.r)
        built = build_hex_terrain_cell(
            cell.q,
            cell.r,
            elevations_m=(100.0 for _ in topology.points),
            surface_materials=(cell.cell_id % 15 for _ in topology.faces),
        )
        container = make_container(built.tile)
        data = make_data(built.tile)
        path = builder.record_path(corpus, cell)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(container)
        records.append(
            {
                "cell_id": cell.cell_id,
                "q": cell.q,
                "r": cell.r,
                "offset_row": cell.offset_row,
                "lod": 0,
                "path": path.relative_to(corpus).as_posix(),
                "bytes": len(container),
                "sha256": builder.sha256_bytes(container),
                "data_bytes": len(data),
                "data_sha256": builder.sha256_bytes(data),
                "vertices": len(built.tile.positions),
                "surface_vertices": built.surface_vertex_count,
                "triangles": len(built.tile.position_indices) // 3,
                "surface_triangles": built.surface_triangle_count,
                "skirt_triangles": built.skirt_triangle_count,
                "maximum_elevation_dm": built.tile.meta.maximum_elevation_dm,
                "material_histogram": {
                    str(material): count
                    for material, count in built.material_histogram
                },
            }
        )
        maximum_elevations.append(built.tile.meta.maximum_elevation_dm)

    statistics = {
        "records": len(records),
        "container_bytes": sum(record["bytes"] for record in records),
        "data_bytes": sum(record["data_bytes"] for record in records),
        "vertices": sum(record["vertices"] for record in records),
        "triangles": sum(record["triangles"] for record in records),
        "maximum_elevation_dm_min": min(maximum_elevations),
        "maximum_elevation_dm_max": max(maximum_elevations),
    }
    return (
        {"stage_buffer_id": builder.STAGING_BUFFER_ID, "statistics": statistics},
        {record["cell_id"]: record for record in records},
    )


class TerrainManagerSurveyHexContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder_source = normalized(BUILDER_PATH)
        self.controls = normalized(CONTROLS)
        self.scene = normalized(SCENE)
        self.provider = normalized(PROVIDER)
        self.manager = normalized(RUNTIME_MANAGER) if RUNTIME_MANAGER.is_file() else ""
        self.main = normalized(MAIN) if MAIN.is_file() else ""

    def test_radius_keys_select_complete_axial_disks_zero_through_five(self) -> None:
        expected_counts = (1, 7, 19, 37, 61, 91)
        self.assertEqual(builder.RADIUS_COUNTS, expected_counts)
        self.assertEqual(builder.DEFAULT_RADIUS, 2)
        self.assertEqual(builder.MAXIMUM_RADIUS, 5)
        self.assertEqual(builder.SLOT_COUNT, 91)
        for radius, expected_count in enumerate(expected_counts):
            with self.subTest(radius=radius):
                disk = disk_offsets(radius)
                self.assertEqual(len(disk), expected_count)
                self.assertEqual(disk[0], (0, 0))
                self.assertEqual(len(set(disk)), expected_count)
                self.assertTrue(
                    all(hex_distance((0, 0), offset) <= radius for offset in disk)
                )

    def test_campanile_axial_start_and_local_camera_are_exact(self) -> None:
        self.assertEqual(builder.START_CELL, (90, 121))
        self.assertEqual(builder.START_CANONICAL, (3711, 3496, -1482))
        cell = HexCell(*builder.START_CELL)
        self.assertEqual(cell.center_m, (565_184, 4_191_652))

        # Pingo X is north, and Pingo Z is negative east.  Reconstructing the
        # accepted projected witness proves that these are local-to-cell
        # counts, rather than the rectangular survey's biased render frame.
        local_x, _local_y, local_z = builder.START_CANONICAL
        east_m = cell.center_m[0] - local_z / 16
        north_m = cell.center_m[1] + local_x / 16
        self.assertEqual((east_m, north_m), (565_276.625, 4_191_883.9375))
        if self.main:
            self.assertRegex(
                self.main, r"terrain_manager_slot_count\s*:\s*equ\s+91"
            )
            for value in ("90", "121", "3711", "3496", "-1482"):
                self.assertIn(value, self.main)

    def test_dense_hex_record_path_uses_the_trh_namespace(self) -> None:
        corpus = Path("/corpus")
        path = builder.record_path(corpus, HexCell(90, 121))
        self.assertEqual(path, corpus / "TRH/L0/53/17.AGN")
        self.assertIn(
            '"trh/l0/{cell_id >> 8:02x}/{cell_id & 255:02x}.agn"',
            self.builder_source,
        )
        self.assertNotIn("trn/l0", self.builder_source)

    def test_corpus_validator_visits_and_rejects_a_corrupt_distant_cell(self) -> None:
        start = HexCell(*builder.START_CELL)
        distant = HexCell(0, 0)
        self.assertGreater(hex_distance((start.q, start.r), (distant.q, distant.r)), 5)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            corpus = Path(directory)
            cells = (start, distant)
            world, indexed = make_validation_corpus(corpus, cells)
            builder.validate_corpus_records(corpus, world, indexed, cells)

            distant_path = builder.record_path(corpus, distant)
            corrupted = bytearray(distant_path.read_bytes())
            corrupted[-1] ^= 0x01
            distant_path.write_bytes(corrupted)
            with self.assertRaisesRegex(
                SystemExit, r"SHA-256 changed.*TRH/L0/00/00\.AGN"
            ):
                builder.validate_corpus_records(corpus, world, indexed, cells)

    def test_corpus_validator_parses_payload_after_matching_file_hash(self) -> None:
        cell = HexCell(0, 0)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            corpus = Path(directory)
            cells = (cell,)
            world, indexed = make_validation_corpus(corpus, cells)
            path = builder.record_path(corpus, cell)
            malformed = b"NOPE" + path.read_bytes()[4:]
            path.write_bytes(malformed)
            indexed[cell.cell_id]["sha256"] = builder.sha256_bytes(malformed)
            with self.assertRaisesRegex(
                SystemExit, r"invalid indexed P3DM container.*TRH/L0/00/00\.AGN"
            ):
                builder.validate_corpus_records(corpus, world, indexed, cells)

    def test_full_corpus_gate_dispatches_the_complete_dense_id_range(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            corpus = Path(directory)
            world = {
                "schema": "pingo-terrain-regional-hex-corpus-v1",
                "selection": "full",
                "build_signature": "a" * 64,
                "statistics": {"records": 3, "container_bytes": 123},
                "path_equation": (
                    "TRH/L0/{cell_id >> 8:02X}/{cell_id & 255:02X}.AGN"
                ),
                "topology": {
                    "basis_q_m": [
                        builder.HEX_BASIS_Q_EAST_M,
                        builder.HEX_BASIS_Q_NORTH_M,
                    ],
                    "basis_r_m": [
                        builder.HEX_BASIS_R_EAST_M,
                        builder.HEX_BASIS_R_NORTH_M,
                    ],
                },
                "normalization": {
                    "object_scale_q8_8": builder.HEX_OBJECT_SCALE_Q8_8,
                    "object_translation_y_count": builder.HEX_TERRAIN_Y_COUNT,
                },
                "canonical_start": {
                    "q": builder.START_CELL[0],
                    "r": builder.START_CELL[1],
                    "pingo_x_count": builder.START_CANONICAL[0],
                    "pingo_y_count": builder.START_CANONICAL[1],
                    "pingo_z_count": builder.START_CANONICAL[2],
                },
                "records": [{"cell_id": cell_id} for cell_id in range(3)],
            }
            world_path = corpus / "WORLD.json"
            world_path.write_text(json.dumps(world), encoding="utf-8")
            with (
                patch.object(builder, "HEX_CELL_COUNT", 3),
                patch.object(builder, "FULL_WORLD_BYTES", world_path.stat().st_size),
                patch.object(builder, "FULL_WORLD_SHA256", builder.sha256(world_path)),
                patch.object(builder, "FULL_BUILD_SIGNATURE", "a" * 64),
                patch.object(builder, "FULL_CORPUS_BYTES", 123),
                patch.object(builder, "validate_corpus_records") as validate,
            ):
                self.assertEqual(builder.require_corpus(corpus), world)

            args = validate.call_args.args
            self.assertEqual(args[0], corpus)
            self.assertEqual(args[1], world)
            self.assertEqual(set(args[2]), {0, 1, 2})
            self.assertEqual(args[3], range(3))

    def test_scene_reserves_91_runtime_patched_full_u16_slots(self) -> None:
        self.assertEqual(builder.SLOT_COUNT, 91)
        self.assertEqual(builder.MESH_BASE, 1)
        self.assertEqual(builder.OBJECT_BASE, 1)
        self.assertRegex(
            self.scene,
            r"ld a\s*,\s*manager_survey_slot_count ld "
            r"\(terrain_scene_slots_remaining\)\s*,\s*a",
        )
        self.assertIn("manager_scene_store_u16_hl", self.scene)
        self.assertIn("manager_scene_load_u16_hl", self.scene)
        self.assertIn("manager_scene_load_u16_de", self.scene)
        self.assertRegex(
            self.scene,
            r"terrain_scene_packet_mesh_id\s*:\s*dw\s+0",
        )
        self.assertRegex(
            self.scene,
            r"terrain_scene_next_mesh_id\s*:\s*dw\s+0",
        )
        self.assertRegex(
            self.scene,
            r"terrain_scene_next_object_id\s*:\s*dw\s+0",
        )
        for advance, storage in (
            ("terrain_scene_advance_mesh_id", "terrain_scene_next_mesh_id"),
            ("terrain_scene_advance_object_id", "terrain_scene_next_object_id"),
        ):
            self.assertRegex(
                self.scene,
                rf"{advance}: ld hl\s*,\s*{storage} "
                r"inc \(hl\) ret nz inc hl inc \(hl\) ret",
            )
        self.assertIn("call pingo_create_object_runtime", self.scene)

    def test_perfect_hex_slot_map_is_injective_through_radius_five(self) -> None:
        self.assertIn("slot = (5*q + 11*r) mod 91", self.provider)
        self.assertIn("kernel basis (11,-5),(5,6)", self.provider)
        for origin in ((0, 0), (90, 121), (213, -106), (-32768, 32767)):
            for radius in range(6):
                with self.subTest(origin=origin, radius=radius):
                    slots = {
                        (5 * (origin[0] + dq) + 11 * (origin[1] + dr)) % 91
                        for dq, dr in disk_offsets(radius)
                    }
                    self.assertEqual(len(slots), len(disk_offsets(radius)))

    def test_provider_uses_expanded_closed_hex_and_wide_translation(self) -> None:
        corners = ((0, 5120), (4400, 2560))
        for x, z in corners:
            self.assertEqual(1024 * abs(x) + 1760 * abs(z), 9_011_200)
        self.assertEqual(HEX_SLOPED_NORMAL_SQUARED, 4_146_176)
        self.assertEqual(HEX_SLOPED_HYSTERESIS, 521_271)
        self.assertEqual(HEX_RETAIN_HALFPLANE, 9_532_471)
        self.assertLess(
            1024 * HEX_RETAIN_X_COUNT + 1760 * HEX_RETAIN_Z_TIP_COUNT,
            1 << 24,
        )
        for definition in (
            "hex_provider_hysteresis_count: equ 256",
            "hex_provider_vertical_exit_first: equ 4657",
            "hex_provider_tip_exit_first: equ 5377",
            "hex_provider_sloped_normal_squared: equ 4146176",
            "hex_provider_sloped_hysteresis: equ 521271",
            "hex_provider_sloped_exit_first: equ 9532472",
        ):
            self.assertIn(definition, self.provider)
        normalization = self.provider.split(
            "terrain_provider_normalize_position:", 1
        )[1].split("hex_provider_apply_origin_step:", 1)[0]
        vertical_at = normalization.index(
            "ld de,hex_provider_vertical_exit_first"
        )
        tip_at = normalization.index("ld de,hex_provider_tip_exit_first")
        sloped_at = normalization.index("ld de,hex_provider_sloped_exit_first")
        self.assertLess(vertical_at, tip_at)
        self.assertLess(tip_at, sloped_at)
        self.assertNotIn("ld de,9011201", normalization)
        self.assertIn("call pingo_set_object_xyz_translation_wide", self.provider)
        self.assertIn("db 1,7,19,37,61,91", self.provider)
        self.assertIn("terrain_provider_normalize_position", self.provider)

    def test_provider_hysteresis_retains_outer_ties_on_all_six_sides(self) -> None:
        retained = (
            (HEX_RETAIN_X_COUNT, 0),
            (-HEX_RETAIN_X_COUNT, 0),
            (2_329, 4_061),
            (-2_329, 4_061),
            (2_329, -4_061),
            (-2_329, -4_061),
            (0, HEX_RETAIN_Z_TIP_COUNT),
            (0, -HEX_RETAIN_Z_TIP_COUNT),
        )
        for point in retained:
            with self.subTest(point=point):
                self.assertIsNone(provider_rebase_step(*point))

        # These lattice points straddle one sloped expanded half-plane by one
        # Z count: the retained witness is below the exact rounded threshold,
        # and the next point is above it.
        self.assertEqual(1024 * 2_329 + 1760 * 4_061, 9_532_256)
        self.assertEqual(1024 * 2_329 + 1760 * 4_062, 9_534_016)

    def test_provider_hysteresis_crosses_each_side_once_without_chatter(self) -> None:
        crossings = (
            ((4_657, 0), (0, 1), (4_400, 0)),
            ((-4_657, 0), (0, -1), (-4_400, 0)),
            ((2_329, -4_062), (1, 0), (2_200, -3_840)),
            ((-2_329, -4_062), (1, -1), (-2_200, -3_840)),
            ((2_329, 4_062), (-1, 1), (2_200, 3_840)),
            ((-2_329, 4_062), (-1, 0), (-2_200, 3_840)),
        )
        for point, expected_origin, nominal_point in crossings:
            with self.subTest(point=point):
                q, r, local_x, local_z, steps = normalize_provider_position(*point)
                self.assertEqual((q, r), expected_origin)
                self.assertEqual(steps, 1)
                self.assertIsNone(provider_rebase_step(local_x, local_z))

                # Jitter on either side of the old ownership boundary remains
                # in the newly selected origin's symmetric 16 m deadband.
                nominal_x, nominal_z = nominal_point
                step = provider_rebase_step(*point)
                self.assertIsNotNone(step)
                assert step is not None
                displacement_x, displacement_z = step[2:]
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        self.assertIsNone(
                            provider_rebase_step(
                                nominal_x + dx - displacement_x,
                                nominal_z + dz - displacement_z,
                            )
                        )

    def test_provider_corner_ties_are_ordered_and_stable(self) -> None:
        # With both expanded constraints crossed, the assembly deliberately
        # chooses the vertical side first.  One X count back selects the
        # positive-Z sloped neighbor instead.  Both results settle in one step.
        vertical_corner = (4_657, 2_708)
        sloped_corner = (4_656, 2_708)
        self.assertEqual(provider_rebase_step(*vertical_corner)[:2], (0, 1))
        self.assertEqual(provider_rebase_step(*sloped_corner)[:2], (-1, 1))
        for point in (vertical_corner, sloped_corner, (0, 5_377), (-1, 5_377)):
            with self.subTest(point=point):
                _q, _r, local_x, local_z, steps = normalize_provider_position(*point)
                self.assertEqual(steps, 1)
                self.assertIsNone(provider_rebase_step(local_x, local_z))

    def test_rebase_retires_delta_six_cells_before_bounded_placement(self) -> None:
        if not self.manager:
            self.skipTest("universal terrain manager source is not present yet")
        rebase = self.manager.split("terrain_manager_reposition_active:", 1)[1]
        rebase = rebase.split("terrain_manager_query:", 1)[0]
        desired_at = rebase.index("call terrain_provider_candidate_is_desired")
        position_at = rebase.index("call terrain_provider_position_candidate")
        deactivate_at = rebase.index("call pingo_set_object_active")
        self.assertLess(desired_at, position_at)
        self.assertLess(desired_at, deactivate_at)

    def test_top_row_zero_through_five_have_exact_mos_matrix_bindings(self) -> None:
        expected = (
            (0, 7, 4, 40),
            (1, 0, 6, 49),
            (2, 1, 6, 50),
            (3, 1, 2, 18),
            (4, 2, 2, 19),
            (5, 3, 2, 20),
        )
        for digit, bit, byte, physical_key in expected:
            with self.subTest(digit=digit):
                self.assertRegex(
                    self.controls,
                    rf"bit {bit}\s*,\s*\(ix\+{byte}\)\s*; "
                    rf"top-row {digit}: physical key {physical_key}",
                )
                self.assertRegex(self.controls, rf"set {digit}\s*,\s*b")
        self.assertRegex(self.controls, r"cpl and b\s*; a = newly pressed radius keys")
        self.assertIn("manager_survey_radius_pending", self.controls)

    def test_new_fixture_has_no_rectangular_streamer_or_frame_bias_coupling(self) -> None:
        implementation = " ".join((self.builder_source, self.main))
        self.assertIn("pingo_terrain.hex_terrain", self.builder_source)
        for forbidden in (
            "build_regional_camera_survey",
            "regional-camera-streaming.inc",
            "regional_start_tile",
            "terrain_window_width",
            "terrain_window_height",
            "rectangular-chebyshev",
            "regional_frame_z_bias",
            "trn/l0",
            "bay-area-full-l0",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, implementation)

    def test_builder_emits_the_runtime_manifest_contract(self) -> None:
        self.assertEqual(builder.RUNTIME_PROGRAM_NAME, "P3DHXMG.BIN")
        self.assertEqual(builder.RUNTIME_MANIFEST_NAME, "MANAGER.json")
        self.assertEqual(builder.DEFAULT_CORPUS.name, "bay-area-hex-full-l0")

        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch_root = Path(directory)
            corpus = scratch_root / "build/p3dm/bay-area-hex-campanile-r5"
            corpus.mkdir(parents=True)
            (corpus / "WORLD.json").write_text("{}\n", encoding="utf-8")
            program = scratch_root / "fixture/terrain-manager-survey.bin"
            program.parent.mkdir(parents=True)
            world = {
                "selection": "campanile-r5",
                "statistics": {"records": 91, "container_bytes": 310_492},
            }
            resources = {
                "MATID.RG2": {"bytes": 16, "sha256": "material-witness"}
            }

            def fake_assemble() -> None:
                program.write_bytes(b"deterministic-manager-survey")

            with (
                patch.object(builder, "ROOT", scratch_root),
                patch.object(builder, "PROGRAM", program),
                patch.object(builder, "arguments", return_value=Namespace(corpus=corpus)),
                patch.object(builder, "require_corpus", return_value=world),
                patch.object(builder, "install_resources", return_value=resources),
                patch.object(builder, "assemble", side_effect=fake_assemble),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(builder.main(), 0)

            report = json.loads((corpus / "MANAGER.json").read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "pingo-terrain-manager-survey-v1")
            self.assertEqual(report["binary"]["runtime_path"], (
                "build/p3dm/bay-area-hex-campanile-r5/P3DHXMG.BIN"
            ))
            self.assertEqual(report["camera"]["axial_cell"], [90, 121])
            self.assertEqual(
                report["camera"]["local_position_counts"], [3711, 3496, -1482]
            )
            self.assertEqual(report["manager"], {
                "default_radius": 2,
                "maximum_radius": 5,
                "mesh_id_range": [1, 91],
                "object_id_range": [1, 91],
                "publication_budget_per_idle_pass": 1,
                "radius_cell_counts": [1, 7, 19, 37, 61, 91],
                "stable_slots": 91,
                "topology": "flat-top-axial-hex",
                "translation_command": 52,
            })
            self.assertEqual(report["resources"], resources)
            self.assertEqual(
                (corpus / "P3DHXMG.BIN").read_bytes(),
                b"deterministic-manager-survey",
            )

    def test_external_corpus_report_paths_remain_absolute(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            corpus = Path(directory).resolve()
            self.assertFalse(corpus.is_relative_to(ROOT.resolve()))
            self.assertEqual(builder.report_path(corpus), str(corpus))

    def test_source_include_closure_is_adl_width_clean_when_main_exists(self) -> None:
        if not MAIN.is_file() or not RUNTIME_MANAGER.is_file():
            self.skipTest("terrain-manager survey include closure is not complete yet")
        result = audit_paths(include_closure([MAIN]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_fixture_assembles_deterministically_when_main_exists(self) -> None:
        if not MAIN.is_file() or not RUNTIME_MANAGER.is_file():
            self.skipTest("terrain-manager survey include closure is not complete yet")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            scratch = Path(directory)
            shutil.copytree(ROOT / "fixtures", scratch / "fixtures")
            shutil.copytree(ROOT / "runtime", scratch / "runtime")
            copied_main = scratch / MAIN.relative_to(ROOT)
            outputs = (scratch / "first.bin", scratch / "second.bin")
            for output in outputs:
                completed = subprocess.run(
                    ["ez80asm", copied_main.name, str(output), "-c"],
                    cwd=copied_main.parent,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stdout + completed.stderr
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            payload = outputs[0].read_bytes()
            self.assertEqual(payload[:4], builder.FIXTURE_STUB)
            self.assertEqual(payload[0x40:0x45], builder.MOS_ADL_HEADER)


if __name__ == "__main__":
    unittest.main()
