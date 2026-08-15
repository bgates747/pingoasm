from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from pingo_terrain.hex_terrain import disk_offsets


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/capture_terrain_manager_survey.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "capture_terrain_manager_survey", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def publication_line(mesh_id: int) -> str:
    shape = capture.EXPECTED_P3DM_SHAPE
    return (
        "PINGO_STREAM mesh_replace=ok "
        f"stage={capture.STAGE_BUFFER_ID} mid={mesh_id} "
        f"bytes={shape['data_bytes']} v={shape['vertices']} "
        f"i={shape['position_indices']} u={shape['texture_coordinates']} "
        f"t={shape['texture_indices']} us=37"
    )


def valid_log() -> str:
    lines = [
        f"noise PINGO_STREAM object_active=ok oid={object_id} active=0"
        for object_id in range(
            capture.OBJECT_ID_BASE,
            capture.OBJECT_ID_BASE + capture.SLOT_COUNT,
        )
    ]
    for ordinal, (object_id, translation) in enumerate(
        capture.expected_cells().items()
    ):
        x, y, z = translation
        lines.extend(
            (
                publication_line(object_id),
                "noise PINGO_WIDE object_translation=ok "
                f"oid={object_id} raw_x={x} raw_y={y} raw_z={z}",
                f"PINGO_STREAM object_active=ok oid={object_id} active=1",
            )
        )
        if ordinal == 0:
            lines.append("PINGO_DUMP seq=0 bmid=257 status=ok")
    lines.append("PINGO_DUMP seq=18 bmid=257 status=ok")
    lines.extend(
        f"PINGO_RENDER seq={sequence} bmid=257 render_us=400"
        for sequence in range(19)
    )
    return "\n".join(lines)


class TerrainManagerCaptureTests(unittest.TestCase):
    def test_expected_transforms_derive_from_disk_offsets_and_stable_slots(self) -> None:
        expected = capture.expected_cells()
        self.assertEqual(len(expected), 19)
        self.assertEqual(next(iter(expected.items())), (53, (0, 9728, 0)))

        independently_derived = {}
        q0, r0 = capture.START_CELL
        for dq, dr in disk_offsets(2):
            q, r = q0 + dq, r0 + dr
            object_id = 1 + (5 * q + 11 * r) % 91
            independently_derived[object_id] = (
                4400 * dq + 8800 * dr,
                9728,
                -7680 * dq,
            )
        self.assertEqual(expected, independently_derived)
        self.assertEqual(len(capture.expected_cells(radius=5)), 91)

    def test_parser_and_validator_accept_exact_uninterrupted_lifecycle(self) -> None:
        contents = valid_log()
        parsed = capture.parse_runtime_evidence(contents)
        self.assertEqual(len(parsed["replacements"]), 19)
        self.assertEqual(len(parsed["translations"]), 19)
        self.assertEqual(len(parsed["activity"]), 110)

        evidence = capture.validate_runtime_evidence(contents)
        self.assertEqual(evidence["initial_population_mesh_ids"], [53])
        self.assertEqual(evidence["complete_sequence"], 18)
        self.assertEqual(evidence["mesh_replace_count"], 19)
        self.assertEqual(evidence["unique_mesh_publications"], 19)
        self.assertEqual(evidence["unique_active_objects"], 19)
        self.assertEqual(len(evidence["final_active_object_ids"]), 19)
        self.assertEqual(evidence["validated_object_translations"], 19)
        self.assertEqual(evidence["render_sequences"], list(range(19)))

    def test_duplicate_publication_is_not_hidden_by_unique_id_set(self) -> None:
        contents = valid_log().replace(
            publication_line(53),
            publication_line(53) + "\n" + publication_line(53),
            1,
        )
        with self.assertRaisesRegex(ValueError, "multiplicity changed"):
            capture.validate_runtime_evidence(contents)

    def test_every_command_52_transform_must_match_exactly_once(self) -> None:
        contents = valid_log().replace(
            "oid=53 raw_x=0 raw_y=9728 raw_z=0",
            "oid=53 raw_x=1 raw_y=9728 raw_z=0",
            1,
        )
        with self.assertRaisesRegex(ValueError, "transform"):
            capture.validate_runtime_evidence(contents)

        duplicate = valid_log().replace(
            "noise PINGO_WIDE object_translation=ok "
            "oid=53 raw_x=0 raw_y=9728 raw_z=0",
            "noise PINGO_WIDE object_translation=ok "
            "oid=53 raw_x=0 raw_y=9728 raw_z=0\n"
            "PINGO_WIDE object_translation=ok "
            "oid=53 raw_x=0 raw_y=9728 raw_z=0",
            1,
        )
        with self.assertRaisesRegex(ValueError, "multiplicity changed"):
            capture.validate_runtime_evidence(duplicate)

    def test_restart_signatures_are_rejected(self) -> None:
        duplicate_bootstrap = valid_log().replace(
            "noise PINGO_STREAM object_active=ok oid=1 active=0",
            "noise PINGO_STREAM object_active=ok oid=1 active=0\n"
            "PINGO_STREAM object_active=ok oid=1 active=0",
            1,
        )
        with self.assertRaisesRegex(ValueError, "activation lifecycle"):
            capture.validate_runtime_evidence(duplicate_bootstrap)

        reset_render_counter = valid_log() + "\nPINGO_RENDER seq=0 bmid=257"
        with self.assertRaisesRegex(ValueError, "possible VDP/eZ80 reset"):
            capture.validate_runtime_evidence(reset_render_counter)

    def test_first_and_complete_dump_boundaries_are_semantic(self) -> None:
        contents = valid_log()
        marker = "PINGO_DUMP seq=18 bmid=257 status=ok"
        contents = contents.replace(marker, "", 1)
        contents = contents.replace(publication_line(54), marker + "\n" + publication_line(54))
        with self.assertRaisesRegex(ValueError, "complete radius-two disk"):
            capture.validate_runtime_evidence(contents)

    def test_known_vdp_failure_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "fatal diagnostics"):
            capture.validate_runtime_evidence(valid_log() + "\nVDP error: fault")

    def test_private_stage_copies_program_resources_and_exact_default_disk(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            fixture = root / "fixture"
            sd_root = root / "sd"
            fixture.mkdir()
            sd_root.mkdir()
            expected_payloads = {}
            for name in (capture.PROGRAM_NAME, *capture.RESOURCE_NAMES):
                payload = f"payload:{name}".encode("ascii")
                (fixture / name).write_bytes(payload)
                expected_payloads[name] = payload
            for relative in capture.terrain_record_paths():
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"record:{relative}".encode("ascii"))

            runtime = capture.stage_private_sd(sd_root, fixture)

            self.assertEqual(
                {path.name for path in runtime.iterdir()},
                {
                    capture.PROGRAM_NAME,
                    *capture.RESOURCE_NAMES,
                    capture.TERRAIN_RECORD_ROOT,
                },
            )
            for name, payload in expected_payloads.items():
                self.assertEqual((runtime / name).read_bytes(), payload)
                self.assertFalse((runtime / name).is_symlink())
            staged_records = tuple(
                path.relative_to(runtime)
                for path in (runtime / capture.TERRAIN_RECORD_ROOT).rglob("*.AGN")
            )
            self.assertEqual(set(staged_records), set(capture.terrain_record_paths()))
            self.assertEqual(len(staged_records), 19)
            self.assertFalse(
                any((runtime / relative).is_symlink() for relative in staged_records)
            )


if __name__ == "__main__":
    unittest.main()
