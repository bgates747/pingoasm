from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import profile_regular_lod_crc_mos_uart_thre_combined as combined  # noqa: E402
import build_regular_lod_crc_register_sibling as crc_builder  # noqa: E402
import build_regular_lod_mos_uart_thre_sibling as mos_builder  # noqa: E402
from pingo_terrain.regular_lod_profile import MeshReplaceRecord  # noqa: E402


class CombinedCrcMosProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.crc_build = Path(cls.temporary.name) / "crc"
        cls.mos_build = Path(cls.temporary.name) / "mos"
        crc_builder.main(("--output", str(cls.crc_build)))
        mos_builder.main(
            (
                "--crc-build",
                str(cls.crc_build),
                "--output",
                str(cls.mos_build),
            )
        )
        cls.inputs = combined.validate_inputs(
            cls.crc_build, cls.mos_build
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_exact_qualified_receipts_and_component_matrix(self) -> None:
        inputs = self.inputs

        self.assertEqual(
            combined.sha256(inputs.crc_receipt), combined.CRC_BUILD_RECEIPT_SHA256
        )
        self.assertEqual(
            combined.sha256(inputs.mos_receipt), combined.MOS_BUILD_RECEIPT_SHA256
        )
        self.assertEqual(inputs.control.program_sha256, combined.ACCEPTED_PROGRAM_SHA256)
        self.assertEqual(inputs.control.symbols_sha256, combined.ACCEPTED_SYMBOLS_SHA256)
        self.assertEqual(inputs.control.mos_sha256, combined.PINNED_MOS_SHA256)
        self.assertEqual(inputs.candidate.program_sha256, combined.CRC_PROGRAM_SHA256)
        self.assertEqual(inputs.candidate.symbols_sha256, combined.CRC_SYMBOLS_SHA256)
        self.assertEqual(inputs.candidate.mos_sha256, combined.PATCHED_MOS_SHA256)
        self.assertFalse(inputs.composition["third_patch"])
        self.assertEqual(inputs.composition["candidate_sender_shift"], -13)
        self.assertEqual(inputs.composition["candidate_application_local_uart_symbols"], [])

    def test_inputs_ignore_simulated_promoted_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted_program = root / "canonical.bin"
            promoted_listing = root / "canonical.lst"
            promoted_symbols = root / "canonical.symbols"
            promoted_program.write_bytes(b"simulated-promoted-nibble-program")
            promoted_listing.write_bytes(b"simulated-promoted-nibble-listing")
            promoted_symbols.write_bytes(b"simulated-promoted-nibble-symbols")
            with (
                mock.patch.object(crc_builder, "ACCEPTED_PROGRAM", promoted_program),
                mock.patch.object(crc_builder, "ACCEPTED_LISTING", promoted_listing),
                mock.patch.object(crc_builder, "ACCEPTED_SYMBOLS", promoted_symbols),
            ):
                inputs = combined.validate_inputs(self.crc_build, self.mos_build)

        self.assertEqual(inputs.control.program_sha256, combined.ACCEPTED_PROGRAM_SHA256)
        self.assertEqual(inputs.control.symbols_sha256, combined.ACCEPTED_SYMBOLS_SHA256)

    def test_mutated_build_receipts_are_rejected_before_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crc_copy = root / "crc"
            mos_copy = root / "mos"
            shutil.copytree(self.crc_build, crc_copy)
            shutil.copytree(self.mos_build, mos_copy)
            crc_receipt = crc_copy / "BUILD.json"
            crc_receipt.write_bytes(crc_receipt.read_bytes() + b" ")
            with self.assertRaisesRegex(
                combined.CombinedProfileError, "CRC BUILD receipt"
            ):
                combined.validate_crc_build(crc_copy)
            mos_receipt = mos_copy / "BUILD.json"
            mos_receipt.write_bytes(mos_receipt.read_bytes() + b" ")
            with self.assertRaisesRegex(
                combined.CombinedProfileError, "MOS BUILD receipt"
            ):
                combined.validate_mos_build(mos_copy)

    def test_layouts_resolve_each_images_exact_shifted_submit_sites(self) -> None:
        control = combined.resolve_normative_layout(
            self.inputs.control.program, self.inputs.control.symbols
        )
        candidate = combined.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )

        self.assertEqual(control.read_call, 0x043067)
        self.assertEqual(control.upload_call, 0x04307B)
        self.assertEqual(control.startup_submit_call, 0x0629C1)
        self.assertEqual(control.loop_submit_call, 0x062A09)
        self.assertEqual(candidate.read_call, 0x043067)
        self.assertEqual(candidate.upload_call, 0x04307B)
        self.assertEqual(candidate.startup_submit_call, 0x0629B4)
        self.assertEqual(candidate.loop_submit_call, 0x0629FC)
        self.assertEqual(candidate.startup_submit_call - control.startup_submit_call, -13)
        self.assertEqual(candidate.loop_submit_call - control.loop_submit_call, -13)
        self.assertEqual(len(control.breakpoints), 4)
        self.assertEqual(len(candidate.breakpoints), 4)

    def test_diagnostic_phases_preserve_outer_sites_and_shift_targets(self) -> None:
        control_symbols = combined.mos_profile.staged.parse_symbols(
            self.inputs.control.symbols
        )
        candidate_symbols = combined.mos_profile.staged.parse_symbols(
            self.inputs.candidate.symbols
        )
        control = combined.mos_profile.cold.resolve_phase_spans(
            self.inputs.control.program, control_symbols
        )
        candidate = combined.mos_profile.cold.resolve_phase_spans(
            self.inputs.candidate.program, candidate_symbols
        )

        self.assertEqual(
            [(phase.call, phase.post_call) for phase in control],
            [(phase.call, phase.post_call) for phase in candidate],
        )
        self.assertEqual(
            [(phase.name, phase.target) for phase in control],
            [
                ("read_container_fatfs", 0x043096),
                ("validate_container", 0x0431C1),
                ("mirror_validated_z", 0x04385F),
                ("upload_vdu_staging", 0x043925),
                ("command50_enqueue", 0x043985),
            ],
        )
        self.assertEqual(
            [(phase.name, phase.target) for phase in candidate],
            [
                ("read_container_fatfs", 0x043096),
                ("validate_container", 0x0431C1),
                ("mirror_validated_z", 0x043852),
                ("upload_vdu_staging", 0x043918),
                ("command50_enqueue", 0x043978),
            ],
        )

    def test_normative_driver_uses_distinct_submit_layout_and_prefix_gate(self) -> None:
        candidate = combined.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        profiler = combined.mos_profile.NormativeProfiler(process, candidate, 1)
        contents = ""
        for name, address in candidate.events_for_record(0):
            if name == "publication_complete_submit":
                contents += combined.mos_profile.PUBLICATION_MARKER + "mid=1\n"
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            profiler.service(contents)
            contents += "Cycles since last break: 3\n"
            profiler.service(contents)
        self.assertEqual(profiler.require_complete()["record_count"], 1)

        late = combined.mos_profile.NormativeProfiler(Process(), candidate, 1)
        contents = ""
        for _name, address in candidate.events_for_record(0)[:2]:
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            late.service(contents)
            contents += "Cycles since last break: 1\n"
            late.service(contents)
        submit = candidate.startup_submit_call
        with self.assertRaisesRegex(
            combined.mos_profile.MosUartThreProfileError, "publications"
        ):
            late.service(
                contents
                + f"CPU paused (breakpoint)\n* {submit:06x}: op\n"
                + combined.mos_profile.PUBLICATION_MARKER
            )

    def test_shifted_submit_reconstruction_preserves_normative_metrics(self) -> None:
        layout = combined.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )
        events = layout.events_for_record(0)
        lines = [
            f"* {events[0][1]:06x}: op",
            "Cycles since last break: 999",
            f"* {events[1][1]:06x}: op",
            "Cycles since last break: 120",
            combined.mos_profile.PUBLICATION_MARKER + "mid=1",
            f"* {events[2][1]:06x}: op",
            "Cycles since last break: 80",
        ]
        contents = "\n".join(lines)
        states = combined.mos_profile.parse_normative_states(contents, layout, 1)
        publication_offset = contents.index(combined.mos_profile.PUBLICATION_MARKER)
        publication = MeshReplaceRecord(
            line_number=5,
            log_offset=publication_offset,
            stage_buffer_id=0x7400,
            mesh_id=1,
            data_bytes=16,
            vertices=1,
            position_indices=0,
            texture_coordinates=2,
            texture_indices=0,
            publication_us=0,
        )
        records = combined.mos_profile.reconstruct_normative_records(
            states,
            [publication],
            [publication_offset],
            [{"path": "r.agn", "file_sha256": "0" * 64, "data_bytes": 16, "mesh_id": 1}],
        )
        self.assertEqual(records[0]["submit_call"], 0x0629B4)
        self.assertEqual(
            records[0]["upload_to_publication_complete_submit_guest_cycles"], 80
        )
        self.assertEqual(
            records[0]["read_to_publication_complete_submit_guest_cycles"], 200
        )

    def test_generalized_staging_pins_both_component_pairs_and_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for mode, variant in (
                ("control", self.inputs.control),
                ("candidate", self.inputs.candidate),
            ):
                staged = combined.prepare_run_output(output, mode, variant)
                self.assertEqual(combined.sha256(staged.program), variant.program_sha256)
                self.assertEqual(combined.sha256(staged.symbols), variant.symbols_sha256)
                self.assertEqual(combined.sha256(staged.mos), variant.mos_sha256)
                self.assertEqual(combined.sha256(staged.mos_map), combined.PINNED_MAP_SHA256)
                self.assertEqual(
                    (staged.directory / "autoexec.txt").read_bytes(),
                    combined.mos_profile.AUTOEXEC,
                )
                sd_root = output / f"sd-{mode}"
                sd_root.mkdir()
                combined.mos_profile.staged.stage_fixture(sd_root, staged.program)
                corpus = combined.mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                self.assertEqual(
                    corpus["coverage_digest_sha256"],
                    combined.mos_profile.builder.EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256,
                )

    def test_commands_and_comparisons_keep_normative_diagnostic_distinction(self) -> None:
        control_layout = combined.resolve_normative_layout(
            self.inputs.control.program, self.inputs.control.symbols
        )
        candidate_layout = combined.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )
        vdp = combined.mos_profile.staged.require_file(
            combined.mos_profile.survey.DEFAULT_VDP, "VDP"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sd_root = output / "sd"
            sd_root.mkdir()
            control_staged = combined.prepare_run_output(
                output, "control", self.inputs.control
            )
            candidate_staged = combined.prepare_run_output(
                output, "candidate", self.inputs.candidate
            )
            control = combined.mos_profile.emulator_command(
                sd_root,
                vdp,
                control_staged.mos,
                self.inputs.control.mos_sha256,
                control_layout.breakpoints,
            )
            candidate = combined.mos_profile.emulator_command(
                sd_root,
                vdp,
                candidate_staged.mos,
                self.inputs.candidate.mos_sha256,
                candidate_layout.breakpoints,
            )
        self.assertIn("0x629c1", control)
        self.assertIn("0x629b4", candidate)
        self.assertNotIn("p3dm_uart0_write_block_thre", " ".join(candidate))

        def normative(total: int) -> dict[str, object]:
            return {
                "metrics": {
                    "read_to_publication_complete_submit": {
                        "summary_loop_226": {"total": total}
                    }
                }
            }

        result = combined.paired_metric(
            normative(100),
            normative(75),
            "read_to_publication_complete_submit",
            "summary_loop_226",
        )
        self.assertTrue(result["completion_equivalent"])

        def diagnostic(total: int) -> dict[str, object]:
            return {
                "phases": {
                    name: {"summary": {"total": total}}
                    for name in combined.mos_profile.cold.PHASE_NAMES
                },
                "measured_five_phase_guest_cycles_total": {
                    "summary": {"total": total * 5}
                },
            }

        phases = combined.diagnostic_comparison(diagnostic(100), diagnostic(80))
        self.assertTrue(all(not phase["completion_equivalent"] for phase in phases.values()))
        self.assertIn("measured_five_phase_guest_cycles_total", phases)

    def test_semantic_comparison_ignores_addresses_but_rejects_stream_change(self) -> None:
        def run(path: str) -> dict[str, object]:
            return {
                "cold_endpoint": {"sequence": 226},
                "publication_semantics": [(0x7400, 1, 16, 1, 0, 2, 0)],
                "render_sequences": list(range(227)),
                "records": [
                    {
                        "order": order,
                        "path": path,
                        "file_sha256": "0" * 64,
                        "data_bytes": 16,
                        "submit_call": 0x100 + order,
                    }
                    for order in range(227)
                ],
            }

        control = run("record.agn")
        candidate = run("record.agn")
        for record in candidate["records"]:
            record["submit_call"] += 13
        combined.assert_semantic_equivalence(control, candidate)
        candidate["records"][7]["path"] = "changed.agn"
        with self.assertRaisesRegex(
            combined.mos_profile.MosUartThreProfileError, "differs at 7"
        ):
            combined.assert_semantic_equivalence(control, candidate)


if __name__ == "__main__":
    unittest.main()
