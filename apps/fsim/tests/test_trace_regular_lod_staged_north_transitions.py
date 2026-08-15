from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import trace_regular_lod_staged_north_transitions as trace  # noqa: E402


def activity(object_id: int, active: int) -> str:
    return f"PINGO_STREAM object_active=ok oid={object_id} active={active}\n"


def replacement(object_id: int) -> str:
    return (
        "PINGO_STREAM mesh_replace=ok stage=29696 "
        f"mid={object_id} bytes=580 v=22 i=96 u=16 t=96 us=12\n"
    )


def pose(object_id: int) -> str:
    return (
        "PINGO_WIDE object_translation=ok "
        f"oid={object_id} raw_x=0 raw_y=9728 raw_z=0\n"
    )


def valid_transition_log() -> tuple[str, int]:
    lines: list[str] = []
    for object_id in range(1, trace.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in range(1, trace.COLD_ACTIVE_COUNT + 1):
        lines.append(activity(object_id, 1))
    start = sum(len(line) for line in lines)

    active = set(range(1, trace.COLD_ACTIVE_COUNT + 1))
    inactive = set(range(trace.COLD_ACTIVE_COUNT + 1, trace.SLOT_COUNT + 1))
    sequence = trace.COLD_SEQUENCE + 1
    for transition in trace.expected_group_shapes():
        for retire_count, enter_count in transition:
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


def valid_radius_restart_log() -> tuple[str, int, list[int]]:
    lines: list[str] = []
    pre_restart = list(range(1, trace.EXPECTED_FINAL_ACTIVE_COUNT + 1))
    for object_id in range(1, trace.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in pre_restart:
        lines.append(activity(object_id, 1))
    start = sum(len(line) for line in lines)
    for object_id in pre_restart:
        lines.append(activity(object_id, 0))
    for object_id in range(1, trace.RESTART_ACTIVE_COUNT + 1):
        lines.append(replacement(object_id))
        lines.append(pose(object_id))
        lines.append(activity(object_id, 1))
        lines.append(f"PINGO_RENDER seq={400 + object_id} bmid=257\n")
    return "".join(lines), start, pre_restart


class StagedNorthTransitionParserTests(unittest.TestCase):
    def test_host_schedule_has_exact_four_crossing_shape(self) -> None:
        shapes = trace.expected_group_shapes()
        self.assertEqual([len(item) for item in shapes], [29, 21, 17, 17])
        self.assertEqual(
            [sum(enter for _, enter in item) for item in shapes],
            [33, 36, 32, 29],
        )
        self.assertEqual(
            [sum(retire for retire, _ in item) for item in shapes],
            [31, 35, 23, 41],
        )

    def test_accepts_exact_inactive_staging_and_atomic_groups(self) -> None:
        contents, start = valid_transition_log()
        evidence = trace.validate_transition_stream(contents, start)
        self.assertEqual(evidence["command50_count"], 130)
        self.assertTrue(evidence["command50_all_inactive"])
        self.assertEqual(evidence["entering_count"], 130)
        self.assertEqual(evidence["retiring_count"], 130)
        self.assertEqual(evidence["group_count"], 84)
        self.assertTrue(evidence["retire_before_enter"])
        self.assertFalse(evidence["render_inside_group_commit"])
        self.assertEqual(len(evidence["final_active_ids"]), 227)

    def test_rejects_command50_against_active_object(self) -> None:
        contents, start = valid_transition_log()
        broken = contents[:start] + replacement(1) + contents[start:]
        with self.assertRaisesRegex(
            trace.EvidenceError, "command 50 replaced active OID 1"
        ):
            trace.validate_transition_stream(broken, start)

    def test_rejects_activation_without_staged_pose(self) -> None:
        contents, start = valid_transition_log()
        first_pose = contents.find("PINGO_WIDE object_translation=ok", start)
        end = contents.find("\n", first_pose) + 1
        broken = contents[:first_pose] + contents[end:]
        with self.assertRaisesRegex(trace.EvidenceError, "without staged command-52"):
            trace.validate_transition_stream(broken, start)

    def test_camera_unwrap_is_exact_and_monotone(self) -> None:
        positions = [4307, 4627, -4141, 4627, -4141, 4627, -4141, 4627, -4141]
        contents = "".join(
            "PINGO_POSE camera_translation "
            f"raw_x={x} raw_y=8000 raw_z=-466\n"
            for x in positions
        )
        evidence = trace.validate_camera(contents, 0)
        self.assertEqual(evidence["wrap_count"], 4)
        self.assertEqual(evidence["wrap_deltas"], [-8768] * 4)

    def test_accepts_complete_cold_shutdown_then_inactive_refill(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        evidence = trace.validate_radius_restart_stream(
            contents, start, pre_restart
        )
        self.assertEqual(evidence["shutdown_count"], 227)
        self.assertTrue(evidence["shutdown_complete_before_first_replace"])
        self.assertFalse(evidence["render_inside_shutdown"])
        self.assertEqual(evidence["command50_count"], 196)
        self.assertTrue(evidence["command50_all_inactive"])
        self.assertEqual(evidence["refill_activation_count"], 196)

    def test_rejects_radius_refill_before_complete_shutdown(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        last_shutdown = contents.rfind(activity(pre_restart[-1], 0), start)
        broken = (
            contents[:last_shutdown]
            + replacement(228)
            + pose(228)
            + contents[last_shutdown:]
        )
        with self.assertRaisesRegex(
            trace.EvidenceError, "did not deactivate every old active"
        ):
            trace.validate_radius_restart_stream(broken, start, pre_restart)

    def test_rejects_active_slot_replace_during_radius_refill(self) -> None:
        contents, start, pre_restart = valid_radius_restart_log()
        first_shutdown_end = contents.find("\n", start) + 1
        broken = (
            contents[:first_shutdown_end]
            + replacement(pre_restart[-1])
            + contents[first_shutdown_end:]
        )
        with self.assertRaisesRegex(
            trace.EvidenceError,
            "did not deactivate every old active|replaced active",
        ):
            trace.validate_radius_restart_stream(broken, start, pre_restart)

    def test_radius_four_endpoint_has_196_owners(self) -> None:
        plan = trace.build_terrain_owner_plan(*trace.FINAL_ORIGIN, 4)
        self.assertEqual(len(plan.near_entries), 61)
        self.assertEqual(len(plan.coarse_entries), 135)
        self.assertEqual(len(plan.owners), trace.RESTART_ACTIVE_COUNT)


if __name__ == "__main__":
    unittest.main()
