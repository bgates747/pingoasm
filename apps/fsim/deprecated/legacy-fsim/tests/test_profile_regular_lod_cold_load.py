from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import profile_regular_lod_cold_load as profile  # noqa: E402
from pingo_terrain.regular_lod_profile import (  # noqa: E402
    MeshReplaceRecord,
    ProfileEvidenceError,
)


def accepted_like_symbols(base: int = profile.PROGRAM_LOAD_ADDRESS) -> dict[str, int]:
    return {
        "p3dm_load_component": base + 0x20,
        "p3dm_read_container": base + 0x80,
        "p3dm_validate_container": base + 0x120,
        "p3dm_mirror_validated_z": base + 0x160,
        "p3dm_upload_data": base + 0x1A0,
        "pingo_replace_mesh_from_buffer": base + 0x1E0,
    }


def synthetic_program(symbols: dict[str, int]) -> bytes:
    payload = bytearray(0x240)
    start = symbols["p3dm_load_component"] - profile.PROGRAM_LOAD_ADDRESS
    cursor = start + 3
    for spec in profile.PHASE_SPECS:
        target = symbols[spec.target_symbol]
        payload[cursor : cursor + 4] = bytes((0xCD,)) + target.to_bytes(
            3, "little"
        )
        cursor += 4
        if spec.name == "mirror_validated_z":
            # Its post-call is the immediately following upload call.
            continue
        cursor += 1
    return bytes(payload)


def debugger_state(pc: int, cycles: int) -> str:
    return (
        "CPU paused (breakpoint)\n"
        f"* {pc:06x}: instruction\n"
        f"* {pc:06x}: instruction\n"
        f"Cycles since last break: {cycles} Cycles per instruction: 4.0\n"
    )


def transcript(phases: tuple[profile.PhaseSpan, ...], records: int) -> str:
    lines = []
    boundaries = profile.execution_boundary_sequence(phases)
    for record in range(records):
        for event, address in enumerate(boundaries):
            lines.append(debugger_state(address, 1000 + record * 10 + event))
    return "".join(lines)


def manifest_record(order: int = 0) -> dict[str, object]:
    return {
        "bytes": 116,
        "data_bytes": 16,
        "identity_q": 80,
        "identity_r": 125,
        "level": "fine",
        "lod": 0,
        "mesh_id": order + 1,
        "object_id": order + 1,
        "order": order,
        "path": f"TRH/L0/00/{order:02X}.AGN",
        "position_indices": 3,
        "sha256": f"{order + 1:064x}",
        "slot": order,
        "texture_coordinates": 1,
        "texture_indices": 3,
        "triangles": 1,
        "vertices": 0,
    }


def publication(order: int = 0) -> MeshReplaceRecord:
    return MeshReplaceRecord(
        line_number=order + 1,
        log_offset=order,
        stage_buffer_id=profile.STAGE_BUFFER_ID,
        mesh_id=order + 1,
        data_bytes=16,
        vertices=0,
        position_indices=3,
        texture_coordinates=1,
        texture_indices=3,
        publication_us=7,
    )


class ColdLoadProfileTests(unittest.TestCase):
    def test_resolver_finds_exact_calls_and_coalesces_shared_boundary(self) -> None:
        symbols = accepted_like_symbols()
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "program.bin"
            program.write_bytes(synthetic_program(symbols))

            phases = profile.resolve_phase_spans(program, symbols)

        self.assertEqual(tuple(item.name for item in phases), profile.PHASE_NAMES)
        self.assertEqual(phases[2].post_call, phases[3].call)
        self.assertEqual(len(profile.execution_boundary_sequence(phases)), 9)
        self.assertEqual(
            profile.shared_boundary_roles(phases),
            {
                phases[2].post_call: (
                    "mirror_validated_z.post_call",
                    "upload_vdu_staging.call",
                )
            },
        )

    def test_resolver_rejects_missing_duplicate_and_reordered_calls(self) -> None:
        symbols = accepted_like_symbols()
        payload = bytearray(synthetic_program(symbols))
        body_start = symbols["p3dm_load_component"] - profile.PROGRAM_LOAD_ADDRESS
        read_call = bytes((0xCD,)) + symbols["p3dm_read_container"].to_bytes(
            3, "little"
        )
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "program.bin"
            missing = bytearray(payload)
            offset = missing.find(read_call, body_start)
            missing[offset] = 0
            program.write_bytes(missing)
            with self.assertRaisesRegex(profile.ColdLoadProfileError, "found 0"):
                profile.resolve_phase_spans(program, symbols)

            duplicate = bytearray(payload)
            duplicate[body_start + 45 : body_start + 49] = read_call
            program.write_bytes(duplicate)
            with self.assertRaisesRegex(profile.ColdLoadProfileError, "found 2"):
                profile.resolve_phase_spans(program, symbols)

            reordered = bytearray(payload)
            calls = []
            for spec in profile.PHASE_SPECS:
                encoded = bytes((0xCD,)) + symbols[spec.target_symbol].to_bytes(
                    3, "little"
                )
                calls.append((reordered.find(encoded, body_start), encoded))
            first_offset, first = calls[0]
            second_offset, second = calls[1]
            reordered[first_offset : first_offset + 4] = second
            reordered[second_offset : second_offset + 4] = first
            program.write_bytes(reordered)
            with self.assertRaisesRegex(profile.ColdLoadProfileError, "order"):
                profile.resolve_phase_spans(program, symbols)

    def test_accepted_program_pins_exact_phase_addresses(self) -> None:
        symbols = profile.staged.parse_symbols(profile.staged.DEFAULT_SYMBOLS)

        phases = profile.resolve_phase_spans(profile.staged.DEFAULT_PROGRAM, symbols)

        self.assertEqual(
            [(item.call, item.post_call) for item in phases],
            [
                (0x043067, 0x04306B),
                (0x04306C, 0x043070),
                (0x043077, 0x04307B),
                (0x04307B, 0x04307F),
                (0x043086, 0x04308A),
            ],
        )

    def test_live_profiler_drives_one_state_per_unique_boundary(self) -> None:
        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        symbols = accepted_like_symbols()
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "program.bin"
            program.write_bytes(synthetic_program(symbols))
            phases = profile.resolve_phase_spans(program, symbols)
        process = Process()
        live = profile.ColdLoadCycleProfiler(process, phases, 1)
        contents = ""
        for event, address in enumerate(profile.execution_boundary_sequence(phases)):
            contents += f"CPU paused (breakpoint)\n* {address:06x}: instruction\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"state\n"))
            contents += (
                f"* {address:06x}: instruction\n"
                f"Cycles since last break: {event + 1}\n"
            )
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"continue\n"))

        evidence = live.require_complete()
        self.assertEqual(evidence["record_count"], 1)
        self.assertEqual(evidence["unique_breakpoint_count"], 9)
        self.assertEqual(process.stdin.getvalue().count(b"delete 0x"), 9)

    def test_live_profiler_rejects_breakpoint_order_drift(self) -> None:
        symbols = accepted_like_symbols()
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "program.bin"
            program.write_bytes(synthetic_program(symbols))
            phases = profile.resolve_phase_spans(program, symbols)

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        live = profile.ColdLoadCycleProfiler(Process(), phases, 1)
        wrong = profile.execution_boundary_sequence(phases)[1]
        with self.assertRaisesRegex(profile.ColdLoadProfileError, "order changed"):
            live.service(
                f"CPU paused (breakpoint)\n* {wrong:06x}: instruction\n"
            )

    def test_phase_parser_preserves_shared_state_and_record_order(self) -> None:
        symbols = accepted_like_symbols()
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "program.bin"
            program.write_bytes(synthetic_program(symbols))
            phases = profile.resolve_phase_spans(program, symbols)
        contents = transcript(phases, 2)

        samples = profile.parse_phase_cycles(contents, phases, 2)

        self.assertEqual(set(samples), set(profile.PHASE_NAMES))
        self.assertTrue(all(len(values) == 2 for values in samples.values()))
        shared_pc = phases[2].post_call
        self.assertEqual(
            samples["mirror_validated_z"][0],
            1000
            + profile.execution_boundary_sequence(phases).index(shared_pc),
        )
        self.assertEqual(
            samples["upload_vdu_staging"][0],
            1000
            + profile.execution_boundary_sequence(phases).index(
                phases[3].post_call
            ),
        )

        dangling = contents.rsplit("Cycles since last break:", 1)[0]
        with self.assertRaises((ProfileEvidenceError, profile.ColdLoadProfileError)):
            profile.parse_phase_cycles(dangling, phases, 2)

    def test_record_binding_checks_bytes_counts_order_and_publication(self) -> None:
        records = [manifest_record(0), manifest_record(1)]
        publications = [publication(0), publication(1)]
        cycles = {
            name: [index + 1, index + 2]
            for index, name in enumerate(profile.PHASE_NAMES)
        }

        bound = profile.validate_record_bindings(records, publications, cycles)

        self.assertEqual(len(bound), 2)
        self.assertEqual(bound[0]["file_bytes"], 116)
        self.assertEqual(bound[0]["data_bytes"], 16)
        self.assertEqual(
            bound[0]["measured_phase_guest_cycles_total"],
            sum(values[0] for values in cycles.values()),
        )

        bad_publication = [publication(0), publication(1)]
        bad_publication[1] = MeshReplaceRecord(
            **{
                **{
                    field: getattr(bad_publication[1], field)
                    for field in bad_publication[1].__dataclass_fields__
                },
                "data_bytes": 18,
            }
        )
        with self.assertRaisesRegex(profile.ColdLoadProfileError, "data_bytes"):
            profile.validate_record_bindings(records, bad_publication, cycles)

        bad_records = [dict(records[0]), dict(records[1])]
        bad_records[1]["order"] = 0
        with self.assertRaisesRegex(profile.ColdLoadProfileError, "order"):
            profile.validate_record_bindings(bad_records, publications, cycles)

        short_cycles = dict(cycles)
        short_cycles[profile.PHASE_NAMES[0]] = [1]
        with self.assertRaisesRegex(profile.ColdLoadProfileError, "samples"):
            profile.validate_record_bindings(records, publications, short_cycles)


if __name__ == "__main__":
    unittest.main()
