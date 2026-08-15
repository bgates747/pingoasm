from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import qualify_regular_lod_c_policy_six_directions as qualify  # noqa: E402


def activity(object_id: int, active: int) -> str:
    return f"PINGO_STREAM object_active=ok oid={object_id} active={active}\n"


def replacement(object_id: int) -> str:
    return (
        "PINGO_STREAM mesh_replace=ok stage=29696 "
        f"mid={object_id} bytes=580 v=22 i=96 u=16 t=96 us=12\n"
    )


def pose(object_id: int, xyz: tuple[int, int, int] = (0, 9728, 0)) -> str:
    return (
        "PINGO_WIDE object_translation=ok "
        f"oid={object_id} raw_x={xyz[0]} raw_y={xyz[1]} raw_z={xyz[2]}\n"
    )


def synthetic_transition(
    shapes: list[tuple[int, int]],
) -> tuple[str, int]:
    lines: list[str] = []
    for object_id in range(1, qualify.staged.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in range(1, qualify.staged.COLD_ACTIVE_COUNT + 1):
        lines.append(activity(object_id, 1))
    start = sum(len(line) for line in lines)
    active = set(range(1, qualify.staged.COLD_ACTIVE_COUNT + 1))
    inactive = set(
        range(
            qualify.staged.COLD_ACTIVE_COUNT + 1,
            qualify.staged.SLOT_COUNT + 1,
        )
    )
    sequence = qualify.staged.COLD_SEQUENCE + 1
    for retire_count, enter_count in shapes:
        entering = sorted(inactive)[:enter_count]
        retiring = sorted(active)[:retire_count]
        if len(entering) != enter_count or len(retiring) != retire_count:
            raise AssertionError("synthetic schedule exceeded slot capacity")
        for object_id in entering:
            lines.append(replacement(object_id))
            lines.append(pose(object_id))
        for object_id in retiring:
            lines.append(activity(object_id, 0))
            active.remove(object_id)
            inactive.add(object_id)
        for object_id in entering:
            lines.append(activity(object_id, 1))
            inactive.remove(object_id)
            active.add(object_id)
        lines.append(f"PINGO_RENDER seq={sequence} bmid=257\n")
        sequence += 1
    return "".join(lines), start


class SixDirectionQualificationTests(unittest.TestCase):
    def test_deterministic_summary_omits_host_timing_offsets_and_log_hash(self) -> None:
        report = {
            "input": {
                "chord": "w",
                "keys": ["W"],
                "precenter_with_s": False,
                "scancodes": ["0x001d"],
                "events": [{"host_vblank": 123}],
            },
            "observed_neighbor": {
                "direction_index": 0,
                "direction_name": "north",
                "step": [0, 1],
                "origin": [80, 126],
                "host_neighbor_valid": True,
                "offset": 999,
                "raw_before": [1, 2, 3],
            },
            "host_schedule": {"group_count": 29},
            "transition_stream": {
                "command50_count": 33,
                "command50_all_inactive": True,
                "retiring_count": 31,
                "entering_count": 33,
                "group_count": 29,
                "group_shapes": [[1, 0]],
                "retire_before_enter": True,
                "render_inside_group_commit": False,
                "final_active_ids": [1],
            },
            "final_state": {
                "manager": {
                    "state": 2,
                    "ring": 5,
                    "desired_count": 229,
                    "active_count": 229,
                    "converged": 1,
                    "last_operation": 0,
                    "last_error": 0,
                    "origin": [80, 126],
                    "proposed_origin": [80, 126],
                    "origin_dirty": 0,
                    "staged_count": 0,
                },
                "provider": {"transition_state": 0},
                "policy": {
                    "mode": 1,
                    "module_status": 1,
                    "qualification_failure": 0,
                    "selector_calls": 29,
                    "selector_matches": 29,
                    "selector_counter_contract": True,
                },
                "camera": {"position": [123, 8000, -466]},
            },
            "final_owner_slot_transforms": {
                "active_owner_slot_transform_count": 229,
                "active_owner_slot_map_exact": True,
                "active_transforms_exact": True,
                "records_sha256": "abc",
                "records": [{"object_id": 1}],
            },
            "fault_markers": [],
            "emulator_exit_status": 0,
            "log_sha256": "volatile",
            "qualified": True,
        }
        first = qualify.deterministic_direction_summary(report)
        report["input"]["events"][0]["host_vblank"] = 999
        report["observed_neighbor"]["offset"] = 1234
        report["log_sha256"] = "different"
        report["final_state"]["camera"]["position"][0] = 456
        second = qualify.deterministic_direction_summary(report)
        self.assertEqual(first, second)
        self.assertNotIn("events", first["input"])
        self.assertNotIn("offset", first["neighbor"])

    def test_input_matrix_is_the_six_requested_physical_chords(self) -> None:
        self.assertEqual(
            [
                (item.name, item.keys, item.precenter_with_s)
                for item in qualify.INPUT_CHORDS
            ],
            [
                ("w", ("W",), False),
                ("s", ("S",), False),
                ("w-d", ("W", "D"), True),
                ("s-d", ("S", "D"), False),
                ("w-a", ("W", "A"), True),
                ("s-a", ("S", "A"), False),
            ],
        )

    def test_classifies_all_six_exact_rebase_vectors(self) -> None:
        observed: list[tuple[int, int]] = []
        for direction, step in enumerate(qualify.TRANSITION_DIRECTION_STEPS):
            ideal_x, ideal_z = qualify._camera_rebase_delta(step)
            self.assertEqual(
                qualify.classify_rebase_delta(ideal_x + 32, ideal_z - 32),
                direction,
            )
            before_x = qualify.staged.CAMERA_INITIAL_X + 32
            before_z = qualify.staged.CAMERA_INITIAL_Z
            contents = (
                "PINGO_POSE camera_translation "
                f"raw_x={before_x} raw_y=8000 raw_z={before_z}\n"
                "PINGO_POSE camera_translation "
                f"raw_x={before_x + ideal_x + 32} raw_y=8000 "
                f"raw_z={before_z + ideal_z - 32}\n"
            )
            evidence = qualify.camera_rebases(contents, 0)
            self.assertEqual(len(evidence), 1)
            observed.append(tuple(evidence[0]["step"]))
        self.assertEqual(set(observed), set(qualify.TRANSITION_DIRECTION_STEPS))

    def test_rejects_large_jump_that_is_not_a_hex_neighbor(self) -> None:
        with self.assertRaisesRegex(
            qualify.QualificationError, "not one unique axial neighbor"
        ):
            qualify.classify_rebase_delta(8_800, 7_680)

    def test_host_schedules_pin_all_six_group_and_activity_counts(self) -> None:
        observed = []
        for direction in range(6):
            schedule, shapes = qualify.transition_schedule(
                qualify.staged.START_ORIGIN, direction
            )
            observed.append(
                (
                    len(shapes),
                    sum(item[0] for item in shapes),
                    sum(item[1] for item in shapes),
                    len(schedule.preserved),
                )
            )
        self.assertEqual(
            observed,
            [
                (29, 31, 33, 196),
                (17, 29, 41, 198),
                (26, 40, 30, 187),
                (15, 36, 33, 191),
                (20, 23, 25, 204),
                (22, 31, 34, 196),
            ],
        )

    def test_accepts_each_exact_host_atomic_schedule(self) -> None:
        for direction in range(6):
            with self.subTest(direction=direction):
                schedule, shapes = qualify.transition_schedule(
                    qualify.staged.START_ORIGIN, direction
                )
                contents, start = synthetic_transition(shapes)
                evidence = qualify.validate_transition_stream(
                    contents, start, shapes, len(schedule.new_plan.owners)
                )
                self.assertEqual(evidence["group_count"], len(shapes))
                self.assertTrue(evidence["command50_all_inactive"])
                self.assertFalse(evidence["render_inside_group_commit"])
                self.assertEqual(
                    evidence["command50_count"],
                    sum(item[1] for item in shapes),
                )

    def test_rejects_render_that_splits_an_atomic_commit(self) -> None:
        schedule, shapes = qualify.transition_schedule(
            qualify.staged.START_ORIGIN, 0
        )
        contents, start = synthetic_transition(shapes)
        # Direction 0 eventually has a (2,1) group.  Split its retirement pair.
        activity_records = list(
            qualify.capture.OBJECT_ACTIVE_RE.finditer(contents, start)
        )
        for first, second in zip(activity_records, activity_records[1:]):
            between = contents[first.end() : second.start()]
            if (
                first.group(2) == second.group(2) == "0"
                and "PINGO_RENDER" not in between
            ):
                broken = (
                    contents[: second.start()]
                    + "PINGO_RENDER seq=999 bmid=257\n"
                    + contents[second.start() :]
                )
                break
        else:
            self.fail("synthetic transition omitted a splittable group")
        with self.assertRaisesRegex(
            qualify.QualificationError, "atomic group shapes changed"
        ):
            qualify.validate_transition_stream(
                broken, start, shapes, len(schedule.new_plan.owners)
            )

    def test_expected_transform_matches_cold_receipt_for_near_and_coarse(self) -> None:
        manifest = json.loads(
            (qualify.FIXTURE / "MANAGER.json").read_text(encoding="utf-8")
        )
        records = manifest["initial_view"]["records"]
        for record in (records[0], records[91]):
            identity = (
                int(record["lod"]),
                int(record["identity_q"]),
                int(record["identity_r"]),
            )
            self.assertEqual(
                qualify.expected_owner_transform(
                    identity, qualify.staged.START_ORIGIN
                ),
                tuple(record["translation_counts"]),
            )

    def test_validates_exact_fifo_chord_order(self) -> None:
        chord = qualify.INPUT_CHORDS[2]
        lines = []
        frame = 10
        for action, code in [
            ("down", qualify.input_trace.SET2_CODES["S"]),
            ("up", qualify.input_trace.SET2_CODES["S"]),
            *(("down", code) for code in chord.scancodes),
            *(("up", code) for code in reversed(chord.scancodes)),
        ]:
            lines.append(
                f"FAB_INPUT frame={frame} action={action} "
                f"scancode=0x{code:04x} source=fifo\n"
            )
            frame += 1
        evidence = qualify.validate_input("".join(lines), chord)
        self.assertEqual(evidence["keys"], ["W", "D"])


if __name__ == "__main__":
    unittest.main()
