from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pingo_terrain.regular_lod_runtime import (
    ProtectedSlotAllocator,
    build_runtime_plan,
    emit_phase_include,
    emit_transition_include,
)


ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "scripts/build_regular_lod_manager_survey.py"
ASSEMBLY = (
    ROOT
    / "fixtures/terrain-manager-survey/src/terrain-manager-regular-lod-survey.asm"
)
TRANSITION_INCLUDE = (
    ROOT
    / "fixtures/terrain-manager-regular-lod-survey/tgt/regular-lod-transitions.inc"
)
GROUP_SCRATCH_BUILDER = ROOT / "scripts/build_regular_lod_group_scratch.py"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_regular_lod_manager_survey", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()


class RegularLodManagerContractTests(unittest.TestCase):
    def test_marina_phase_counts_and_cold_slots_are_exact(self) -> None:
        near = []
        coarse = []
        totals = []
        for radius in range(6):
            runtime = build_runtime_plan(
                ProtectedSlotAllocator(), *builder.START_CELL, radius
            )
            near.append(len(runtime.near_entries))
            coarse.append(len(runtime.coarse.entries))
            totals.append(runtime.active_count)
        self.assertEqual(tuple(near), builder.NEAR_COUNTS)
        self.assertEqual(tuple(coarse), builder.MARINA_COARSE_COUNTS)
        self.assertEqual(tuple(totals), builder.MARINA_DESIRED_COUNTS)

        cold = build_runtime_plan(
            ProtectedSlotAllocator(),
            *builder.START_CELL,
            builder.DEFAULT_RADIUS,
        )
        self.assertEqual(
            tuple(entry.slot for entry in cold.coarse.entries),
            tuple(range(91, 227)),
        )
        self.assertEqual(cold.active_count, 227)
        centre = cold.near_entries[0]
        self.assertEqual((centre.q, centre.r, centre.slot), (80, 125, 46))

    def test_fixture_source_uses_the_full_manager_profile(self) -> None:
        source = ASSEMBLY.read_text(encoding="utf-8")
        for literal in (
            "terrain_manager_slot_count: equ 255",
            "terrain_manager_initial_ring: equ 5",
            "terrain_manager_defer_stale_rebase: equ 1",
            "manager_survey_projection_far_units: equ 65535",
            'include "../../../build/p3dm/bay-area-regular-n1-hierarchy/REGCORP.INC"',
            'include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-runtime.inc"',
            'include "terrain-manager-regular-lod-provider.inc"',
            'include "../../../runtime/ez80/terrain-manager.inc"',
            "call terrain_provider_prepare_plan",
            'include "terrain-manager-solid-sky.inc"',
            "camera_initial_pitch: equ 0",
            "camera_initial_yaw: equ -8192",
            "camera_initial_z: equ -466",
            "p3dm_mirror_z_on_load: equ 1",
            "call manager_survey_disable_scene_illumination",
        ):
            self.assertIn(literal, source)
        self.assertNotIn(
            'include "../../koak-flight-streamed/src/flight-backdrop.inc"',
            source,
        )
        self.assertLess(
            source.index("CCS sid"), source.index("pingo_set_projection_far_units")
        )

    def test_full_owner_profile_is_conditional_and_edge_safe(self) -> None:
        source = ASSEMBLY.read_text(encoding="utf-8")
        provider = ASSEMBLY.with_name(
            "terrain-manager-regular-lod-provider.inc"
        ).read_text(encoding="utf-8")
        self.assertIn("terrain_manager_group_staging: equ 1", source)
        self.assertIn(
            'include "../../terrain-manager-regular-lod-survey/tgt/regular-lod-transitions.inc"',
            source,
        )
        for symbol in (
            "regular_provider_near_slots",
            "regular_provider_plan_source_ordinals",
            "regular_transition_old_slot_by_ordinal",
            "regular_transition_target_template_to_dense",
            "regular_transition_select_feasible_group",
            "regular_transition_find_staging_slot",
            "terrain_provider_service_transition",
        ):
            self.assertIn(f"{symbol}:", provider)
        self.assertIn(
            "cp regular_lod_transition_near_radius\n    jr nz,@transition_deferred",
            provider,
        )
        self.assertIn("ld a,(terrain_manager_converged)", provider)
        self.assertIn("ld a,(regular_provider_endpoint_near_limit)", provider)
        self.assertIn("jr @normalized\n.else\n    jp @again", provider)

    def test_group_radius_change_is_a_render_idle_cold_restart(self) -> None:
        source = ASSEMBLY.read_text(encoding="utf-8")
        provider = ASSEMBLY.with_name(
            "terrain-manager-regular-lod-provider.inc"
        ).read_text(encoding="utf-8")
        idle = source.split("@service:", 1)[1].split("@exit:", 1)[0]
        completion = idle.index("call nz,consume_render_completion")
        released = idle.index("ld a,(render_in_flight)", completion)
        restart = idle.index("call manager_survey_apply_radius_request", released)
        service = idle.index("call terrain_manager_service_idle", restart)
        self.assertLess(completion, released)
        self.assertLess(released, restart)
        self.assertLess(restart, service)

        cold = source.split("manager_survey_cold_restart_radius:", 1)[1].split(
            "load_scene_resources:", 1
        )[0]
        ordered = (
            "call terrain_manager_shutdown_idle",
            "call terrain_provider_reset_for_cold_restart",
            "call terrain_manager_initialize",
            "call terrain_manager_submit_origin",
            "call terrain_manager_set_ring",
            "call terrain_provider_prepare_plan",
        )
        positions = [cold.index(call) for call in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("ld (manager_survey_restart_origin_q+0),a", cold)
        self.assertIn("ld (manager_survey_restart_origin_r+1),a", cold)

        reset = provider.split(
            "terrain_provider_reset_for_cold_restart:", 1
        )[1].split("regular_transition_target_owner_present:", 1)[0]
        for state in (
            "regular_provider_plan_valid",
            "regular_provider_plan_count",
            "regular_provider_endpoint_count",
            "regular_provider_unified_slots",
            "regular_transition_build_target",
            "regular_transition_state",
        ):
            self.assertIn(f"ld ({state}),a", reset)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_legacy_rollback_build_is_deterministic_and_non_mutating(self) -> None:
        accepted = (
            ROOT
            / "fixtures/terrain-manager-regular-lod-survey/tgt"
            / "terrain-manager-regular-lod-survey.bin"
        )
        before = (
            hashlib.sha256(ASSEMBLY.read_bytes()).hexdigest(),
            hashlib.sha256(accepted.read_bytes()).hexdigest(),
        )
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            for output in (first, second):
                subprocess.run(
                    [
                        sys.executable,
                        str(GROUP_SCRATCH_BUILDER),
                        "--group-staging",
                        "0",
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            one = json.loads(first.joinpath("BUILD.json").read_text())
            two = json.loads(second.joinpath("BUILD.json").read_text())
            self.assertEqual(one["artifacts"], two["artifacts"])
            self.assertEqual(
                one["policy"], {"terrain_manager_group_staging": 0}
            )
            self.assertEqual(
                one["transition_include_sha256"],
                "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
            )
        after = (
            hashlib.sha256(ASSEMBLY.read_bytes()).hexdigest(),
            hashlib.sha256(accepted.read_bytes()).hexdigest(),
        )
        self.assertEqual(before, after)

    def test_provider_prefers_inactive_slots_before_visible_fallback(self) -> None:
        provider = ASSEMBLY.with_name(
            "terrain-manager-regular-lod-provider.inc"
        ).read_text(encoding="utf-8")
        inactive = provider.index("@find_inactive:")
        fallback = provider.index("@find_any_begin:")
        self.assertLess(inactive, fallback)
        self.assertIn(
            "call terrain_manager_slot_flags_pointer",
            provider[inactive:fallback],
        )
        self.assertIn("and terrain_manager_flag_active", provider[inactive:fallback])

    def test_solid_sky_has_no_horizon_or_attitude_dependency(self) -> None:
        sky = ASSEMBLY.with_name("terrain-manager-solid-sky.inc").read_text(
            encoding="utf-8"
        )
        self.assertIn("terrain_sky_colour: equ 47", sky)
        self.assertIn("terrain_sky_compatibility_reserve_bytes: equ 704", sky)
        self.assertEqual(sky.count("terrain_sky_plot_triangle_absolute"), 3)
        for forbidden in (
            "camera_state",
            "backdrop_ground_colour",
            "backdrop_extract_attitude",
            "p3d_sincos16",
        ):
            self.assertNotIn(forbidden, sky)

    def test_runtime_presentation_is_level_north_and_unlit(self) -> None:
        self.assertEqual(builder.START_ROTATION, (0, -8_192, 0))
        source = ASSEMBLY.read_text(encoding="utf-8")
        illumination = source.split(
            "manager_survey_disable_scene_illumination:", 1
        )[1]
        self.assertIn("db 49h,46,0", illumination.split("@end:", 1)[0])

    def test_generated_phase_include_is_exact(self) -> None:
        expected = emit_phase_include().encode("ascii")
        actual = builder.RUNTIME_INCLUDE.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "22607a410cb2c3ef3506d30d542a7eb7a14160bec8c73bd68a6abb33f204aff4",
        )

    def test_generated_transition_include_is_exact(self) -> None:
        expected = emit_transition_include().encode("ascii")
        actual = builder.TRANSITION_INCLUDE.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
        )
        self.assertEqual(
            builder.MANAGER_SCHEMA,
            "pingo-terrain-regular-lod-manager-survey-v2",
        )

    def test_generated_transition_include_is_exact_and_separate(self) -> None:
        expected = emit_transition_include().encode("ascii")
        actual = TRANSITION_INCLUDE.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 109_831)
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
        )

    def test_checked_trh_link_is_idempotent_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            output = root / "hierarchy"
            fine = root / "fine"
            output.mkdir()
            (fine / "TRH/L0").mkdir(parents=True)
            builder.expose_fine_corpus(output, fine)
            link = output / "TRH"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), (fine / "TRH").resolve())
            builder.expose_fine_corpus(output, fine)

            link.unlink()
            link.mkdir()
            with self.assertRaises(SystemExit):
                builder.expose_fine_corpus(output, fine)


@unittest.skipUnless(
    builder.DEFAULT_OUTPUT.joinpath("WORLD.json").is_file(),
    "regular hierarchy has not been built",
)
class RegularLodManagerArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hierarchy, cls.selected = builder.require_hierarchy(
            builder.DEFAULT_OUTPUT
        )

    def test_hierarchy_and_fine_receipts_are_pinned(self) -> None:
        self.assertEqual(self.hierarchy["schema"], builder.HIERARCHY_SCHEMA)
        fine = builder.require_fine_corpus(builder.DEFAULT_FINE_CORPUS)
        self.assertEqual(fine["world_sha256"], builder.FINE_WORLD_SHA256)

    def test_installed_presentation_receipt_is_unlit_and_solid(self) -> None:
        manager = json.loads(
            builder.DEFAULT_OUTPUT.joinpath("MANAGER.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manager["camera"]["rotation"], [0, -8_192, 0])
        self.assertEqual(
            manager["camera"]["local_position_counts"], [4_275, 8_000, -466]
        )
        self.assertEqual(
            manager["manager"]["runtime_axis_adapter"]["published"],
            "X=north,Y=up,Z=+east (right-handed)",
        )
        self.assertEqual(
            manager["presentation"]["background"],
            {
                "agon_palette_index": 47,
                "attitude_dependent": False,
                "false_ground_enabled": False,
                "policy": "full-frame solid sky behind transparent target",
            },
        )
        terrain = manager["presentation"]["terrain"]
        self.assertFalse(terrain["scene_illumination_enabled"])
        self.assertFalse(terrain["illumination_bands_may_dither"])
        self.assertEqual(terrain["agon_palette_indices"], [20, 7, 21])

    def test_exact_marina_record_set_round_trips(self) -> None:
        records, aggregates = builder.initial_runtime_records(
            builder.DEFAULT_OUTPUT,
            builder.DEFAULT_FINE_CORPUS,
            self.selected,
        )
        self.assertEqual(len(records), 227)
        self.assertEqual([record["order"] for record in records], list(range(227)))
        self.assertEqual([record["slot"] for record in records[91:]], list(range(91, 227)))
        self.assertEqual(
            aggregates,
            {
                "records": 227,
                "container_bytes": 787_192,
                "data_bytes": 764_288,
                "vertices": 28_232,
                "triangles": 48_364,
                "maximum_record_bytes": 4_568,
                "level_counts": {
                    "fine": 91,
                    "L1": 11,
                    "L2": 21,
                    "L4": 6,
                    "L8": 98,
                },
            },
        )
        self.assertEqual(records[0]["object_id"], 47)
        self.assertEqual(records[0]["path"], "TRH/L0/49/ED.AGN")
        self.assertEqual(records[0]["translation_counts"], [0, 9728, 0])
        self.assertTrue(
            all(len(record["translation_counts"]) == 3 for record in records)
        )


if __name__ == "__main__":
    unittest.main()
