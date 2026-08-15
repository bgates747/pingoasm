from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_uart_thre_sibling as builder  # noqa: E402
import build_regular_lod_crc_register_sibling as crc_builder  # noqa: E402
import capture_regular_lod_manager_survey as capture  # noqa: E402
import profile_regular_lod_uart_thre_sibling as profile  # noqa: E402
import profile_regular_lod_crc_register_sibling as crc_profile  # noqa: E402
from pingo_terrain.regular_lod_profile import MeshReplaceRecord  # noqa: E402


class UartThreLiveProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.candidate_root = Path(cls.temporary.name) / "candidate"
        cls.crc_root = Path(cls.temporary.name) / "crc"
        crc_builder.main(("--output", str(cls.crc_root)))
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
        return crc_profile.validate_legacy_control(self.crc_root)

    def test_layout_binds_same_outer_phases_and_exact_data_sender_sites(self) -> None:
        candidate_program, candidate_symbols = self.candidate_paths()
        control_program, _control_listing, control_symbols = self.control_paths()
        accepted = profile.resolve_layout(
            control_program,
            control_symbols,
            candidate=False,
        )
        candidate = profile.resolve_layout(
            candidate_program,
            candidate_symbols,
            candidate=True,
        )

        accepted_outer = [item for item in accepted.events if not item[0].startswith("sender_")]
        candidate_outer = [item for item in candidate.events if not item[0].startswith("sender_")]
        self.assertEqual(accepted_outer, candidate_outer)
        self.assertEqual(accepted.sender_call, candidate.sender_call)
        self.assertEqual(accepted.sender_post, accepted.sender_call + 2)
        self.assertEqual(candidate.sender_post, candidate.sender_call + 4)
        self.assertEqual(
            [name for name, _address in candidate.forbidden],
            ["zero_count", "rst18_fallback"],
        )
        self.assertEqual(len(candidate.breakpoints), 11)

    def test_live_driver_services_all_boundaries_and_rejects_fallback(self) -> None:
        candidate_program, candidate_symbols = self.candidate_paths()
        layout = profile.resolve_layout(
            candidate_program, candidate_symbols, candidate=True
        )

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        live = profile.LiveBoundaryProfiler(process, layout, 1)
        contents = ""
        for _name, address in layout.events:
            contents += f"CPU paused (breakpoint)\n* {address:06x}: instruction\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"state\n"))
            contents += "Cycles since last break: 17\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"continue\n"))
        self.assertEqual(live.require_complete()["cycle_state_count"], 11)

        rejected = profile.LiveBoundaryProfiler(Process(), layout, 1)
        name, address = layout.forbidden[1]
        with self.assertRaisesRegex(profile.UartThreProfileError, name):
            rejected.service(
                f"CPU paused (breakpoint)\n* {address:06x}: instruction\n"
            )

    def test_state_parser_requires_full_main_uart_contract_state(self) -> None:
        candidate_program, candidate_symbols = self.candidate_paths()
        layout = profile.resolve_layout(
            candidate_program, candidate_symbols, candidate=True
        )
        lines = []
        for index, (_name, address) in enumerate(layout.events):
            lines.append(f"* {address:06x}: op")
            lines.append(
                f"* {address:06x}: op AF:0044 BC:000000 DE:001234 "
                f"HL:005678 SPS:0000 SPL:0bffff IX:043af3 IY:000000 "
                f"IR:01{index:02x} MB:00 ADL:1 MADL:1 IFF1:1"
            )
            lines.append(f"Cycles since last break: {100 + index}")

        states = profile.parse_boundary_states("\n".join(lines), layout, 1)

        self.assertEqual([state["event"] for state in states], [name for name, _ in layout.events])
        self.assertEqual(states[6]["event"], "sender_call")
        self.assertEqual(states[6]["ir"], 0x0106)
        self.assertEqual(states[6]["mb"], 0)
        self.assertEqual(states[6]["iff1"], 1)
        self.assertEqual(states[6]["cycles_since_previous_boundary"], 106)

    def test_reconstruction_proves_positive_count_and_return_registers(self) -> None:
        candidate_program, candidate_symbols = self.candidate_paths()
        layout = profile.resolve_layout(
            candidate_program, candidate_symbols, candidate=True
        )
        expected = capture.initial_records()[:1]
        record = expected[0]
        data_bytes = int(record["data_bytes"])
        states = []
        for index, (name, address) in enumerate(layout.events):
            item = {
                "record": 0,
                "event": name,
                "address": address,
                "line_number": index + 1,
                "cycles_since_previous_boundary": 10 + index,
                "af": (data_bytes >> 8) << 8,
                "bc": data_bytes,
                "de": 0x123456,
                "hl": layout.file_buffer + builder.P3DM_DATA_OFFSET,
                "sps": 0,
                "spl": 0x0BFFFF,
                "ix": layout.file_buffer + 88,
                "iy": 0x04006C,
                "ir": 0x0101,
                "mb": 0,
                "adl": 1,
                "madl": 1,
                "iff1": 1,
            }
            if name == "sender_post":
                item.update(
                    af=0x0044,
                    bc=0,
                    de=(0x123456 & ~0xFF) | (data_bytes >> 8),
                    hl=layout.file_buffer + builder.P3DM_DATA_OFFSET + data_bytes,
                    ir=0x017F,
                )
            states.append(item)
        publication = MeshReplaceRecord(
            line_number=1,
            log_offset=0,
            stage_buffer_id=builder.P3DM_STAGE_BUFFER_ID,
            mesh_id=int(record["mesh_id"]),
            data_bytes=data_bytes,
            vertices=int(record["vertices"]),
            position_indices=int(record["position_indices"]),
            texture_coordinates=int(record["texture_coordinates"]),
            texture_indices=int(record["texture_indices"]),
            publication_us=0,
        )

        reconstructed, phases = profile.reconstruct_records(
            states, layout, expected, [publication]
        )

        self.assertEqual(reconstructed[0]["sender_return"]["AF"], 0x0044)
        self.assertEqual(reconstructed[0]["sender_return"]["BC"], 0)
        self.assertEqual(
            reconstructed[0]["sender_return"]["HL_from_file_buffer"],
            builder.P3DM_DATA_OFFSET + data_bytes,
        )
        self.assertEqual(phases["upload_vdu_staging"], [16 + 17 + 18])

    def test_build_binding_and_completion_equivalence_labels_are_explicit(self) -> None:
        program, symbols, receipt = profile.validate_build(self.candidate_root)
        self.assertEqual(program.name, f"{builder.PROGRAM_STEM}.bin")
        self.assertEqual(symbols.name, f"{builder.PROGRAM_STEM}.symbols")
        self.assertTrue(receipt["limitations"]["must_not_run_or_deploy_with_another_mos"])

        def run(variant: str, sender: int, upload: int, total: int) -> dict[str, object]:
            return {
                "variant": variant,
                "upload_segments": {"data_sender": {"summary": {"total": sender}}},
                "phases": {"upload_vdu_staging": {"summary": {"total": upload}}},
                "measured_phase_guest_cycles_total": {"aggregate": total},
            }

        result = profile.comparison(
            [run("accepted-rst18", 100, 200, 500), run("uart-thre", 60, 150, 450)]
        )
        self.assertFalse(result["data_sender"]["transmitter_completion_equivalent"])
        self.assertTrue(result["upload_vdu_staging"]["transmitter_completion_equivalent"])
        self.assertTrue(
            result["complete_measured_cold_phases"]["transmitter_completion_equivalent"]
        )

    def test_control_is_independent_of_simulated_promoted_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted_program = root / "canonical.bin"
            promoted_symbols = root / "canonical.symbols"
            promoted_program.write_bytes(b"simulated-nibble-program")
            promoted_symbols.write_bytes(b"simulated-nibble-symbols")
            with (
                mock.patch.object(builder, "ACCEPTED_PROGRAM", promoted_program),
                mock.patch.object(builder, "ACCEPTED_SYMBOLS", promoted_symbols),
            ):
                control_program, _listing, control_symbols = self.control_paths()
                layout = profile.resolve_layout(
                    control_program, control_symbols, candidate=False
                )

        self.assertEqual(
            profile.sha256(control_program), crc_builder.ACCEPTED_PROGRAM_SHA256
        )
        self.assertEqual(layout.sender_kind, "Console8 RST18 counted DATA write")


if __name__ == "__main__":
    unittest.main()
