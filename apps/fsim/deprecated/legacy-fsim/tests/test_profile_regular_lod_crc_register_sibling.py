from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_crc_register_sibling as builder  # noqa: E402
import profile_regular_lod_crc_register_sibling as profile  # noqa: E402


class CrcRegisterLiveProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.candidate_root = Path(cls.temporary.name) / "candidate"
        builder.main(("--output", str(cls.candidate_root)))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def candidate_paths(self) -> tuple[Path, Path]:
        return (
            self.candidate_root / f"{builder.PROGRAM_STEM}.bin",
            self.candidate_root / f"{builder.PROGRAM_STEM}.symbols",
        )

    def control_paths(self) -> tuple[Path, Path, Path]:
        return profile.validate_legacy_control(self.candidate_root)

    def test_accepted_and_candidate_layouts_share_all_execution_boundaries(self) -> None:
        program, symbols = self.candidate_paths()
        control_program, _control_listing, control_symbols = self.control_paths()
        accepted = profile.resolve_layout(control_program, control_symbols)
        candidate = profile.resolve_layout(program, symbols)

        self.assertEqual(accepted.events, candidate.events)
        self.assertEqual(candidate.crc_entry, 0x0437C7)
        self.assertEqual(candidate.crc_post, 0x0435EA)
        self.assertEqual(candidate.return_error, 0x043A2D)
        self.assertEqual(candidate.crc_value, 0x043AC5)
        self.assertEqual(candidate.file_buffer, 0x043AF3)
        self.assertEqual(len(candidate.breakpoints), 11)

    def test_live_driver_services_each_boundary_and_crc_memory_once(self) -> None:
        program, symbols = self.candidate_paths()
        layout = profile.resolve_layout(program, symbols)

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        live = profile.LiveBoundaryProfiler(process, layout, 1)
        contents = ""
        for name, address in layout.events:
            contents += f"CPU paused (breakpoint)\n* {address:06x}: instruction\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"state\n"))
            contents += f"Cycles since last break: {address & 0xffff}\n"
            live.service(contents)
            if name == "crc_post":
                self.assertTrue(process.stdin.getvalue().endswith(b"memory 0x43ac5 4\n"))
                contents += "043ac5: 01 02 03 04\n"
                live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"continue\n"))

        self.assertEqual(
            live.require_complete(),
            {
                "record_count": 1,
                "event_count_per_record": 11,
                "cycle_state_count": 11,
                "crc_memory_snapshot_count": 1,
            },
        )
        self.assertEqual(live.crc_memory, [b"\x01\x02\x03\x04"])

    def test_nested_state_parser_preserves_execution_order_and_registers(self) -> None:
        program, symbols = self.candidate_paths()
        layout = profile.resolve_layout(program, symbols)
        lines = []
        for index, (_name, address) in enumerate(layout.events):
            lines.append(f"* {address:06x}: op")
            lines.append(
                f"* {address:06x}: op AF:0044 BC:000000 DE:001234 "
                f"HL:005678 SPS:0000 SPL:0bffff IX:043af3 IY:000000 ADL:1"
            )
            lines.append(f"Cycles since last break: {100 + index}")
        contents = "\n".join(lines)

        states = profile.parse_boundary_states(contents, layout, 1)

        self.assertEqual([state["event"] for state in states], [name for name, _ in layout.events])
        self.assertEqual(states[4]["event"], "crc_post")
        self.assertEqual(states[4]["de"], 0x001234)
        self.assertEqual(states[4]["hl"], 0x005678)
        self.assertEqual(states[4]["cycles_since_previous_boundary"], 104)

    def test_negative_mutations_prove_crc9_and_index10_inputs(self) -> None:
        record, relative, payload = profile.first_record()
        self.assertEqual(relative.as_posix(), "TRH/L0/49/ED.AGN")

        crc_payload, crc = profile.mutate_negative("crc-data", record, payload)
        index_payload, index = profile.mutate_negative(
            "index-valid-crc", record, payload
        )

        self.assertEqual(crc["expected_error"], 9)
        self.assertNotEqual(crc["stored_crc32"], crc["actual_data_crc32"])
        self.assertEqual(crc["changed_file_offsets"], [100])
        self.assertEqual(index["expected_error"], 10)
        self.assertEqual(index["stored_crc32"], index["actual_data_crc32"])
        self.assertNotEqual(crc_payload, payload)
        self.assertNotEqual(index_payload, payload)
        self.assertIn(100 + 6 * int(record["vertices"]), index["changed_file_offsets"])

    def test_build_receipt_binding_accepts_only_stable_artifact_keys(self) -> None:
        program, symbols, receipt = profile.validate_build(self.candidate_root)

        self.assertEqual(program.name, f"{builder.PROGRAM_STEM}.bin")
        self.assertEqual(symbols.name, f"{builder.PROGRAM_STEM}.symbols")
        self.assertEqual(
            receipt["artifacts"]["program"]["key"],
            f"artifacts/{builder.PROGRAM_STEM}.bin",
        )

        control_program, control_listing, control_symbols = self.control_paths()
        self.assertEqual(profile.sha256(control_program), builder.ACCEPTED_PROGRAM_SHA256)
        self.assertEqual(
            profile.sha256(control_listing),
            profile.LEGACY_CONTROL_ARTIFACTS["legacy_control_listing"][2],
        )
        self.assertEqual(
            profile.sha256(control_symbols),
            profile.LEGACY_CONTROL_ARTIFACTS["legacy_control_symbols"][2],
        )

    def test_private_crc1_control_ignores_simulated_promoted_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            promoted = Path(directory)
            promoted_program = promoted / "terrain-manager-regular-lod-survey.bin"
            promoted_listing = promoted_program.with_suffix(".lst")
            promoted_symbols = promoted_program.with_suffix(".symbols")
            promoted_program.write_bytes(b"simulated-promoted-nibble-program")
            promoted_listing.write_bytes(b"simulated-promoted-nibble-listing")
            promoted_symbols.write_bytes(b"simulated-promoted-nibble-symbols")
            with (
                mock.patch.object(builder, "ACCEPTED_PROGRAM", promoted_program),
                mock.patch.object(builder, "ACCEPTED_LISTING", promoted_listing),
                mock.patch.object(builder, "ACCEPTED_SYMBOLS", promoted_symbols),
            ):
                program, _listing, symbols = self.control_paths()
                layout = profile.resolve_layout(program, symbols)

        self.assertEqual(profile.sha256(program), builder.ACCEPTED_PROGRAM_SHA256)
        self.assertEqual(layout.crc_entry, 0x0437C7)

    def test_semantic_equivalence_uses_ix_relative_to_each_shifted_buffer(self) -> None:
        base = {
            "cold_endpoint": {"active": 227},
            "publication_semantics": [(0x7400, 1, 16, 3, 3, 1, 3)],
            "records": [
                {
                    "order": order,
                    "path": f"record-{order}",
                    "file_sha256": f"{order:064x}",
                    "data_bytes": order + 1,
                    "stored_crc32": f"{order:08x}",
                    "p3dm_crc_value_hex": order.to_bytes(4, "little").hex(),
                    "final_ix": 0x043B00 + order,
                    "final_ix_from_file_buffer": 100 + order,
                }
                for order in range(profile.EXPECTED_RECORDS)
            ],
        }
        candidate = {
            **base,
            "records": [
                {**record, "final_ix": int(record["final_ix"]) - 13}
                for record in base["records"]
            ],
        }

        profile.assert_semantic_equivalence(base, candidate)
        candidate["records"][0]["final_ix_from_file_buffer"] += 1
        with self.assertRaisesRegex(profile.CrcSiblingProfileError, "record differs"):
            profile.assert_semantic_equivalence(base, candidate)


if __name__ == "__main__":
    unittest.main()
