from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import trace_regular_lod_north_transition as trace  # noqa: E402


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


def valid_log(
    *,
    active_coarse_before_replace: int | None = None,
    early_stale: bool = False,
    omit_pose: int | None = None,
) -> str:
    lines = []
    for object_id in range(1, trace.SLOT_COUNT + 1):
        lines.append(activity(object_id, 0))
    for object_id in range(1, trace.COLD_ACTIVE_COUNT + 1):
        lines.append(activity(object_id, 1))
    lines.append(f"PINGO_RENDER seq={trace.COLD_SEQUENCE} bmid=257\n")
    if active_coarse_before_replace is not None:
        lines.append(activity(active_coarse_before_replace, 1))

    # One 32-count movement step combined with the -8800 floating-origin
    # shift.  The parser deliberately checks that there is exactly one wrap.
    lines.append(
        "PINGO_POSE camera_translation raw_x=4627 raw_y=8000 raw_z=-466\n"
    )
    lines.append(
        "PINGO_POSE camera_translation raw_x=-4141 raw_y=8000 raw_z=-466\n"
    )
    for index, object_id in enumerate(trace.PUBLICATION_IDS):
        if early_stale and index == len(trace.PUBLICATION_IDS) - 1:
            lines.append(activity(trace.STALE_OBJECT_IDS[0], 0))
        lines.append(replacement(object_id))
        if object_id != omit_pose:
            lines.append(pose(object_id))
        lines.append(activity(object_id, 1))
    for object_id in trace.STALE_OBJECT_IDS[int(early_stale) :]:
        lines.append(activity(object_id, 0))
    lines.append("PINGO_RENDER seq=300 bmid=257\n")
    lines.append("PINGO_RENDER seq=301 bmid=257\n")
    return "".join(lines)


class RegularLodNorthTransitionParserTests(unittest.TestCase):
    def test_capacity_scope_is_explicitly_local_not_universal(self) -> None:
        self.assertLessEqual(
            trace.FIRST_TRANSITION_COARSE_UNION,
            trace.COARSE_SLOT_CAPACITY,
        )
        self.assertGreater(
            trace.KNOWN_MAXIMUM_ADJACENT_COARSE_UNION,
            trace.COARSE_SLOT_CAPACITY,
        )

    def test_accepts_exact_inactive_first_transaction(self) -> None:
        evidence = trace.analyze_transition_log(valid_log())
        self.assertEqual(evidence["publication_count"], 33)
        self.assertEqual(
            evidence["coarse_inactive_before_replace"],
            list(range(228, 250)),
        )
        self.assertTrue(evidence["stale_deactivation_after_all_publications"])
        self.assertEqual(evidence["final_stream_active_count"], 229)
        self.assertEqual(evidence["camera_wrap_deltas"], [-8768])

    def test_rejects_active_coarse_slot_replacement(self) -> None:
        with self.assertRaisesRegex(
            trace.EvidenceError,
            "coarse OID 228 was active immediately before replacement",
        ):
            trace.analyze_transition_log(
                valid_log(active_coarse_before_replace=228)
            )

    def test_rejects_stale_retirement_before_last_publication(self) -> None:
        with self.assertRaisesRegex(
            trace.EvidenceError,
            "before all 33 publications completed",
        ):
            trace.analyze_transition_log(valid_log(early_stale=True))

    def test_rejects_publication_without_pose(self) -> None:
        with self.assertRaisesRegex(
            trace.EvidenceError,
            "publication was not replace -> pose -> activate",
        ):
            trace.analyze_transition_log(valid_log(omit_pose=228))


if __name__ == "__main__":
    unittest.main()
