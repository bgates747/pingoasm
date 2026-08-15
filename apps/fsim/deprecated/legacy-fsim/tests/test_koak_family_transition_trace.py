from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


input_trace = load_script("trace_koak_input")
takeoff_trace = load_script("trace_koak_takeoff")
family_capture = load_script("capture_koak_family_lod")
trace = load_script("trace_koak_family_transition")


class KOAKFamilyTransitionTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(trace.PLAN.read_text())

    def test_generated_transaction_is_exact_thirteen_off_thirteen_on(self) -> None:
        pattern = trace.transition_pattern(self.plan)
        self.assertEqual(len(pattern), 26)
        self.assertEqual(
            pattern,
            tuple((slot, 0) for slot in (29, 19, 20, 21, 24, *range(1, 9)))
            + tuple((slot, 1) for slot in (*range(9, 17), 25, 26, 27, 28, 37)),
        )
        expected = trace.expected_final_slots(self.plan)
        self.assertEqual(len(expected), 24)
        self.assertEqual(
            expected,
            {
                *range(9, 17),
                17,
                18,
                22,
                23,
                *range(25, 29),
                *range(30, 38),
            },
        )

    def test_exact_transaction_rejects_missing_duplicate_and_interleaved_calls(self) -> None:
        pattern = trace.transition_pattern(self.plan)
        prefix = [(101, 1), (201, 1)]
        self.assertEqual(trace.find_exact_transaction(prefix + list(pattern), pattern), 0)
        with self.assertRaisesRegex(SystemExit, "found 0"):
            trace.find_exact_transaction(list(pattern[:-1]), pattern)
        with self.assertRaisesRegex(SystemExit, "found 2"):
            trace.find_exact_transaction(list(pattern) * 2, pattern)
        interleaved = list(pattern)
        interleaved.insert(5, (18, 1))
        with self.assertRaisesRegex(SystemExit, "found 0"):
            trace.find_exact_transaction(interleaved, pattern)

    def test_transaction_is_bracketed_by_adjacent_submitted_renders(self) -> None:
        pattern = trace.transition_pattern(self.plan)
        lines = ["PINGO_RENDER seq=1195 bmid=257 status=ok"]
        lines.extend(
            f"PINGO_STREAM object_active=ok oid={slot} active={active}"
            for slot, active in pattern
        )
        lines.append("PINGO_RENDER seq=1196 bmid=257 status=ok")
        self.assertEqual(
            trace.transaction_render_bracket("\n".join(lines), pattern),
            (1195, 1196),
        )
        with self.assertRaisesRegex(SystemExit, "Could not bracket"):
            trace.transaction_render_bracket("\n".join(lines[:-1]), pattern)
        interleaved = list(lines)
        interleaved.insert(8, "PINGO_RENDER seq=999 bmid=257 status=ok")
        with self.assertRaisesRegex(SystemExit, "interleaved"):
            trace.transaction_render_bracket("\n".join(interleaved), pattern)
        publication = list(lines)
        publication.insert(
            8,
            "PINGO_STREAM mesh_replace=ok stage=29696 mid=9 bytes=100 "
            "v=3 i=3 u=1 t=3 us=50",
        )
        with self.assertRaisesRegex(SystemExit, "interleaved"):
            trace.transaction_render_bracket("\n".join(publication), pattern)
        other_activity = list(lines)
        other_activity.insert(
            8, "PINGO_STREAM object_active=ok oid=201 active=1"
        )
        with self.assertRaisesRegex(SystemExit, "other_activity"):
            trace.transaction_render_bracket("\n".join(other_activity), pattern)

    def test_pose_rebase_preserves_chase_offset_and_common_wrap(self) -> None:
        contents = "\n".join(
            (
                "PINGO_STREAM object_active=ok oid=201 active=1",
                "PINGO_RENDER seq=1190 bmid=257 status=ok",
                "noise PINGO_POSE object_translation oid=101 "
                "raw_x=1 raw_y=2 raw_z=3",
                "PINGO_POSE object_translation oid=201 "
                "raw_x=1949 raw_y=5133 raw_z=4084",
                "PINGO_POSE camera_translation "
                "raw_x=1842 raw_y=5170 raw_z=3807",
                "PINGO_RENDER seq=1191 bmid=257 status=ok",
                "PINGO_POSE object_translation oid=201 "
                "raw_x=1956 raw_y=5144 raw_z=-4089",
                "PINGO_POSE camera_translation "
                "raw_x=1849 raw_y=5181 raw_z=-4366",
                "PINGO_RENDER seq=1192 bmid=257 status=ok",
            )
        )
        evidence = trace.validate_pose_rebase(contents, (1191, 1192))
        self.assertEqual(
            evidence["common_translation_delta_raw"], [7, 11, -8173]
        )
        self.assertEqual(
            evidence["before"]["camera_minus_aircraft_raw"],
            [-107, 37, -277],
        )
        self.assertTrue(evidence["chase_offset_preserved"])

    def test_pose_rebase_rejects_missing_mismatched_and_nonwrap_updates(self) -> None:
        def log(
            before_camera: tuple[int, int, int] = (90, 210, 270),
            after_camera: tuple[int, int, int] = (95, 216, -7930),
            include_after_aircraft: bool = True,
        ) -> str:
            lines = [
                "PINGO_STREAM object_active=ok oid=201 active=1",
                "PINGO_RENDER seq=10 bmid=257 status=ok",
                "PINGO_POSE object_translation oid=201 "
                "raw_x=100 raw_y=200 raw_z=300",
                "PINGO_POSE camera_translation "
                f"raw_x={before_camera[0]} raw_y={before_camera[1]} "
                f"raw_z={before_camera[2]}",
                "PINGO_RENDER seq=11 bmid=257 status=ok",
            ]
            if include_after_aircraft:
                lines.append(
                    "PINGO_POSE object_translation oid=201 "
                    "raw_x=105 raw_y=206 raw_z=-7900"
                )
            lines.extend(
                (
                    "PINGO_POSE camera_translation "
                    f"raw_x={after_camera[0]} raw_y={after_camera[1]} "
                    f"raw_z={after_camera[2]}",
                    "PINGO_RENDER seq=12 bmid=257 status=ok",
                )
            )
            return "\n".join(lines)

        with self.assertRaisesRegex(SystemExit, "exactly one"):
            trace.validate_pose_rebase(
                log(include_after_aircraft=False), (11, 12)
            )
        with self.assertRaisesRegex(SystemExit, "chase offset"):
            trace.validate_pose_rebase(
                log(after_camera=(96, 216, -7930)), (11, 12)
            )
        with self.assertRaisesRegex(SystemExit, "terrain-cell wrap"):
            trace.validate_pose_rebase(
                log(after_camera=(95, 216, 280)).replace(
                    "raw_x=105 raw_y=206 raw_z=-7900",
                    "raw_x=105 raw_y=206 raw_z=310",
                ),
                (11, 12),
            )
        reversed_pose = log().replace(
            "PINGO_POSE object_translation oid=201 "
            "raw_x=105 raw_y=206 raw_z=-7900\n"
            "PINGO_POSE camera_translation "
            "raw_x=95 raw_y=216 raw_z=-7930",
            "PINGO_POSE camera_translation "
            "raw_x=95 raw_y=216 raw_z=-7930\n"
            "PINGO_POSE object_translation oid=201 "
            "raw_x=105 raw_y=206 raw_z=-7900",
        )
        with self.assertRaisesRegex(SystemExit, "did not follow"):
            trace.validate_pose_rebase(reversed_pose, (11, 12))

    def test_terrain_reposition_reconstructs_one_generated_coarse_origin(self) -> None:
        pattern = trace.transition_pattern(self.plan)
        coarse = (91, 147)
        east_origin = coarse[0] * trace.COARSE_CELL_RAW + trace.COARSE_CENTER_BIAS_RAW
        north_origin = coarse[1] * trace.COARSE_CELL_RAW + trace.COARSE_CENTER_BIAS_RAW
        lines = ["PINGO_RENDER seq=10 bmid=257 status=ok"]
        for entry in self.plan["loads"]:
            east, north = entry["center_counts"]
            lines.append(
                "PINGO_WIDE object_translation=ok "
                f"oid={entry['slot']} raw_x={north - north_origin} "
                f"raw_y={trace.TERRAIN_Y_RAW} raw_z={east_origin - east}"
            )
        lines.extend(
            f"PINGO_STREAM object_active=ok oid={slot} active={active}"
            for slot, active in pattern
        )
        lines.append("PINGO_RENDER seq=11 bmid=257 status=ok")
        contents = "\n".join(lines)
        evidence = trace.validate_terrain_reposition(
            contents, (10, 11), pattern, self.plan
        )
        self.assertEqual(evidence["record_count"], 37)
        self.assertEqual(evidence["coarse_cell"], [91, 147])
        self.assertEqual(
            evidence["slot_order"],
            [int(entry["slot"]) for entry in self.plan["loads"]],
        )

        damaged = contents.replace(
            "oid=37 raw_x=-12288 raw_y=9728 raw_z=307200",
            "oid=37 raw_x=-12288 raw_y=9728 raw_z=307201",
        )
        with self.assertRaisesRegex(SystemExit, "one coarse-cell"):
            trace.validate_terrain_reposition(
                damaged, (10, 11), pattern, self.plan
            )

    def test_boundary_sequence_parser_is_sorted_unique_and_nonnegative(self) -> None:
        self.assertEqual(trace.parse_sequence_list("1196,1194,1195"), (1194, 1195, 1196))
        for invalid in ("", "x", "1,-1", "2,2"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(Exception):
                    trace.parse_sequence_list(invalid)

    def test_validation_correlates_position_runtime_and_vdp_activity(self) -> None:
        initial = [(slot, 0) for slot in range(1, 38)] + [
            (int(entry["slot"]), 1)
            for entry in self.plan["loads"]
            if entry["activate_after_load"]
        ]
        events = initial + list(trace.transition_pattern(self.plan))
        state = {
            "coarse_cell": [91, 146],
            "arithmetic_failure": False,
            "displacement_m": [100.0, 1_200.0],
        }
        family_state = {
            "plan_cursor": 37,
            "plan_total": 37,
            "error_hold": 0,
            "swap_complete": 1,
            "last_error": 0,
        }
        result = trace.validate_transition(
            state, family_state, events, self.plan
        )
        self.assertEqual(result["transaction_command_count"], 26)
        self.assertEqual(len(result["final_active_terrain_slots"]), 24)

        for field, value, message in (
            ("plan_cursor", 36, "did not arm"),
            ("error_hold", 1, "invalid state"),
            ("swap_complete", 0, "invalid state"),
            ("last_error", 7, "invalid state"),
        ):
            with self.subTest(field=field):
                bad_family = dict(family_state)
                bad_family[field] = value
                with self.assertRaisesRegex(SystemExit, message):
                    trace.validate_transition(state, bad_family, events, self.plan)

        bad_position = dict(state)
        bad_position["coarse_cell"] = [92, 146]
        with self.assertRaisesRegex(SystemExit, "did not cross"):
            trace.validate_transition(
                bad_position, family_state, events, self.plan
            )

    def test_publications_require_every_mesh_exactly_once(self) -> None:
        def line(mesh_id: int) -> str:
            return (
                "PINGO_STREAM mesh_replace=ok stage=29696 "
                f"mid={mesh_id} bytes=100 v=3 i=3 u=1 t=3 us={mesh_id}"
            )

        contents = "\n".join(
            line(mesh_id) for mesh_id in (*range(1, 38), 101, 102)
        )
        evidence = trace.publication_evidence(contents)
        self.assertEqual(evidence["count"], 39)
        self.assertEqual(evidence["maximum_publication_us"], 102)
        with self.assertRaisesRegex(SystemExit, "multiplicity"):
            trace.publication_evidence(contents + "\n" + line(37))
        with self.assertRaisesRegex(SystemExit, "multiplicity"):
            trace.publication_evidence(contents.replace(line(37), ""))

    def test_family_snapshot_decodes_independent_single_byte_symbols(self) -> None:
        symbols = {
            "family_plan_cursor": 0x102030,
            "family_error_hold": 0x203040,
            "family_swap_complete": 0x304050,
            "streaming_last_error": 0x405060,
            "family_plan_total_count": 37,
        }
        memory = {
            0x102030: 37,
            0x203040: 0,
            0x304050: 1,
            0x405060: 0,
        }
        self.assertEqual(
            trace.decode_family_state(memory, symbols),
            {
                "plan_cursor": 37,
                "plan_total": 37,
                "error_hold": 0,
                "swap_complete": 1,
                "last_error": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
