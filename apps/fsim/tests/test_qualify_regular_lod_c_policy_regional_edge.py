from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import qualify_regular_lod_c_policy_regional_edge as edge  # noqa: E402


def activity(object_id: int, active: int) -> str:
    return f"PINGO_STREAM object_active=ok oid={object_id} active={active}\n"


def replacement(object_id: int) -> str:
    return (
        "PINGO_STREAM mesh_replace=ok stage=29696 "
        f"mid={object_id} bytes=580 v=22 i=96 u=16 t=96 us=12\n"
    )


def synthetic_cold() -> str:
    contract = edge.edge_host_contract()
    active_ids = list(contract["cold_active_ids"])
    lines = [
        activity(object_id, 0)
        for object_id in range(1, edge.staged.SLOT_COUNT + 1)
    ]
    for sequence, object_id in enumerate(active_ids):
        lines.append(replacement(object_id))
        lines.append(activity(object_id, 1))
        lines.append(f"PINGO_RENDER seq={sequence} bmid=257\n")
    return "".join(lines)


class RegionalEdgeQualificationTests(unittest.TestCase):
    def test_source_transform_changes_only_four_exact_constants(self) -> None:
        for mode, value in edge.SUPPORTED_MODES.items():
            with self.subTest(mode=mode):
                base, transformed = edge.edge_profile_source(mode)
                differences = [
                    (first, second)
                    for first, second in zip(
                        base.splitlines(), transformed.splitlines(), strict=True
                    )
                    if first != second
                ]
                self.assertEqual(differences, list(edge.SOURCE_TRANSFORMS))
                self.assertIn(
                    f"terrain_manager_regular_policy_mode: equ {value}",
                    transformed,
                )

    def test_host_contract_pins_clipped_source_ordinals_and_schedule(self) -> None:
        contract = edge.edge_host_contract()
        self.assertEqual(contract["origin"], [0, 117])
        self.assertEqual(contract["final_origin"], [1, 117])
        self.assertEqual(contract["step"], [1, 0])
        self.assertEqual(
            contract["old_endpoint"],
            {
                "clipped_owner_count": 118,
                "unbounded_source_owner_count": 227,
                "clipped_source_ordinals": 109,
                "near_count": 51,
                "coarse_count": 67,
            },
        )
        self.assertEqual(
            contract["new_endpoint"],
            {
                "clipped_owner_count": 129,
                "unbounded_source_owner_count": 217,
                "clipped_source_ordinals": 88,
                "near_count": 61,
                "coarse_count": 68,
            },
        )
        recipe = contract["recipe"]
        self.assertEqual(recipe["index"], 8)
        self.assertEqual(recipe["raw_group_count"], 26)
        self.assertEqual(recipe["filtered_nonempty_group_count"], 15)
        self.assertEqual(recipe["filtered_empty_group_count"], 11)
        self.assertEqual(recipe["clipped_retiring_ordinal_references"], 28)
        self.assertEqual(recipe["clipped_entering_ordinal_references"], 7)
        self.assertTrue(recipe["source_ordinal_clipping_exact"])
        self.assertTrue(recipe["resolved_schedule_equals_direct_host_schedule"])
        self.assertEqual(
            contract["transition"],
            {
                "preserved_owner_count": 106,
                "retiring_count": 12,
                "entering_count": 23,
                "final_owner_count": 129,
                "final_scan_desired_count": 159,
            },
        )

    def test_cold_slot_map_is_exact_and_noncontiguous(self) -> None:
        contract = edge.edge_host_contract()
        active = list(contract["cold_active_ids"])
        self.assertEqual(len(active), 118)
        self.assertNotEqual(active, list(range(1, 119)))
        evidence = edge.validate_cold_endpoint(synthetic_cold(), contract)
        self.assertEqual(evidence["sequence"], 117)
        self.assertEqual(evidence["active_ids"], active)
        self.assertTrue(evidence["active_slot_map_exact"])

    def test_cold_validator_rejects_wrong_active_slot(self) -> None:
        contents = synthetic_cold()
        expected = edge.edge_host_contract()["cold_active_ids"]
        object_id = expected[0]
        broken = contents.replace(activity(object_id, 1), activity(159, 1), 1)
        with self.assertRaisesRegex(
            edge.EdgeQualificationError, "active slots changed"
        ):
            edge.validate_cold_endpoint(broken, edge.edge_host_contract())

    def test_centered_forward_right_chord_resolves_q_zero_to_q_one(self) -> None:
        ideal_x, ideal_z = edge.six._camera_rebase_delta(edge.EDGE_STEP)
        contents = (
            "PINGO_POSE camera_translation raw_x=32 raw_y=8000 raw_z=32\n"
            "PINGO_POSE camera_translation "
            f"raw_x={32 + ideal_x + 32} raw_y=8000 "
            f"raw_z={32 + ideal_z + 32}\n"
        )
        rebases = edge.six.camera_rebases(
            contents, 0, edge.EDGE_CAMERA
        )
        self.assertEqual(len(rebases), 1)
        self.assertEqual(
            rebases[0]["direction_index"], edge.EDGE_DIRECTION_INDEX
        )
        self.assertEqual(rebases[0]["step"], [1, 0])


if __name__ == "__main__":
    unittest.main()
