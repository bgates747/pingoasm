from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_regular_lod_mos_uart_thre_sibling as builder  # noqa: E402
import build_regular_lod_crc_register_sibling as crc_builder  # noqa: E402
import profile_regular_lod_mos_uart_thre_sibling as profile  # noqa: E402
from pingo_terrain.regular_lod_profile import MeshReplaceRecord  # noqa: E402


class MosUartThreLiveProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.crc_build = Path(cls.temporary.name) / "crc-register"
        cls.build = Path(cls.temporary.name) / "build"
        crc_builder.main(("--output", str(cls.crc_build)))
        builder.main(
            (
                "--crc-build",
                str(cls.crc_build),
                "--output",
                str(cls.build),
            )
        )
        cls.control, cls.candidate, _receipt = profile.validate_build(cls.build)
        cls.control_program, cls.control_listing, cls.control_symbols = (
            profile.validate_crc1_control(cls.build)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def layout(self) -> profile.NormativeLayout:
        return profile.resolve_normative_layout(
            self.control_program, self.control_symbols
        )

    def test_layout_has_exact_submit_sites_and_no_post_upload_breakpoint(self) -> None:
        layout = self.layout()

        self.assertEqual(layout.read_call, 0x043067)
        self.assertEqual(layout.upload_call, 0x04307B)
        self.assertEqual(layout.startup_submit_call, 0x0629C1)
        self.assertEqual(layout.loop_submit_call, 0x062A09)
        self.assertEqual(
            layout.events_for_record(0),
            (
                ("read_call", 0x043067),
                ("upload_call", 0x04307B),
                ("publication_complete_submit", 0x0629C1),
            ),
        )
        self.assertEqual(layout.events_for_record(1)[-1][1], 0x062A09)
        self.assertEqual(len(layout.breakpoints), 4)

    def test_normative_driver_requires_publication_before_matching_submit(self) -> None:
        layout = self.layout()

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        live = profile.NormativeProfiler(process, layout, 1)
        contents = ""
        for name, address in layout.events_for_record(0):
            if name == "publication_complete_submit":
                contents += profile.PUBLICATION_MARKER + "mid=1\n"
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"state\n"))
            contents += "Cycles since last break: 17\n"
            live.service(contents)
            self.assertTrue(process.stdin.getvalue().endswith(b"continue\n"))
        self.assertEqual(live.require_complete()["publication_before_submit_count"], 1)

        rejected = profile.NormativeProfiler(Process(), layout, 1)
        contents = ""
        for _name, address in layout.events_for_record(0)[:2]:
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            rejected.service(contents)
            contents += "Cycles since last break: 1\n"
            rejected.service(contents)
        submit = layout.startup_submit_call
        with self.assertRaisesRegex(profile.MosUartThreProfileError, "publications"):
            rejected.service(
                contents + f"CPU paused (breakpoint)\n* {submit:06x}: op\n"
            )

        late = profile.NormativeProfiler(Process(), layout, 1)
        contents = ""
        for _name, address in layout.events_for_record(0)[:2]:
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            late.service(contents)
            contents += "Cycles since last break: 1\n"
            late.service(contents)
        with self.assertRaisesRegex(profile.MosUartThreProfileError, "publications"):
            late.service(
                contents
                + f"CPU paused (breakpoint)\n* {submit:06x}: op\n"
                + profile.PUBLICATION_MARKER
                + "mid=1\n"
            )

    def test_parser_and_reconstruction_measure_read_and_upload_to_submit(self) -> None:
        layout = self.layout()
        events = layout.events_for_record(0)
        lines = [
            f"* {events[0][1]:06x}: op",
            "Cycles since last break: 999",
            f"* {events[1][1]:06x}: op",
            "Cycles since last break: 120",
            profile.PUBLICATION_MARKER + "mid=1",
            f"* {events[2][1]:06x}: op",
            "Cycles since last break: 80",
        ]
        contents = "\n".join(lines)
        states = profile.parse_normative_states(contents, layout, 1)
        publication = MeshReplaceRecord(
            line_number=5,
            log_offset=contents.index(profile.PUBLICATION_MARKER),
            stage_buffer_id=0x7400,
            mesh_id=1,
            data_bytes=16,
            vertices=1,
            position_indices=0,
            texture_coordinates=2,
            texture_indices=0,
            publication_us=0,
        )
        bound = [
            {
                "path": "record.agn",
                "file_sha256": "0" * 64,
                "data_bytes": 16,
                "mesh_id": 1,
            }
        ]

        records = profile.reconstruct_normative_records(
            states,
            [publication],
            profile.publication_marker_offsets(contents),
            bound,
        )

        self.assertEqual(
            records[0]["upload_to_publication_complete_submit_guest_cycles"], 80
        )
        self.assertEqual(
            records[0]["read_to_publication_complete_submit_guest_cycles"], 200
        )
        self.assertLess(records[0]["upload_call_line"], records[0]["publication_line"])
        self.assertLess(records[0]["publication_line"], records[0]["submit_line"])

    def test_exact_publication_marker_offset_rejects_same_line_late_marker(self) -> None:
        layout = self.layout()
        events = layout.events_for_record(0)
        lines = [
            f"* {events[0][1]:06x}: op",
            "Cycles since last break: 999",
            f"* {events[1][1]:06x}: op",
            "Cycles since last break: 120",
            (
                "noisy-prefix "
                f"* {events[2][1]:06x}: op "
                + profile.PUBLICATION_MARKER
                + "mid=1"
            ),
            "Cycles since last break: 80",
        ]
        contents = "\n".join(lines)
        states = profile.parse_normative_states(contents, layout, 1)
        publication_line_start = contents.index("noisy-prefix")
        publication_offset = profile.publication_marker_offsets(contents)[0]
        submit_offset = int(states[2]["breakpoint_log_offset"])
        self.assertLess(publication_line_start, submit_offset)
        self.assertLess(submit_offset, publication_offset)

        publication = MeshReplaceRecord(
            line_number=5,
            log_offset=publication_line_start,
            stage_buffer_id=0x7400,
            mesh_id=1,
            data_bytes=16,
            vertices=1,
            position_indices=0,
            texture_coordinates=2,
            texture_indices=0,
            publication_us=0,
        )
        bound = [
            {
                "path": "record.agn",
                "file_sha256": "0" * 64,
                "data_bytes": 16,
                "mesh_id": 1,
            }
        ]
        with self.assertRaisesRegex(
            profile.MosUartThreProfileError, "between upload and submit"
        ):
            profile.reconstruct_normative_records(
                states, [publication], [publication_offset], bound
            )

    def test_comparisons_distinguish_normative_and_diagnostic_metrics(self) -> None:
        def normative(variant: str, upload: list[int], read: list[int]) -> dict[str, object]:
            return {
                "variant": variant,
                "metrics": {
                    "upload_to_publication_complete_submit": {
                        "summary_loop_226": {"total": sum(upload)},
                    },
                    "read_to_publication_complete_submit": {
                        "summary_loop_226": {"total": sum(read)},
                    },
                },
            }

        metric = profile.paired_metric(
            normative("pinned-temt", [100], [200]),
            normative("patched-thre", [75], [175]),
            "upload_to_publication_complete_submit",
            "summary_loop_226",
        )
        self.assertTrue(metric["completion_equivalent"])
        self.assertEqual(metric["delta_cycles"], -25)

        def diagnostic(total: int) -> dict[str, object]:
            return {
                "phases": {
                    name: {"summary": {"total": total}}
                    for name in profile.cold.PHASE_NAMES
                }
            }

        phases = profile.diagnostic_comparison(diagnostic(100), diagnostic(80))
        self.assertTrue(all(not value["completion_equivalent"] for value in phases.values()))

    def test_render_prefix_and_shutdown_tail_are_strictly_bounded(self) -> None:
        def render(
            sequence: int, *, objects: int = 227, out: int = 0
        ) -> str:
            return (
                f"PINGO_RENDER seq={sequence} bmid=257 render_us=1 d=4 w=320 "
                "h=240 fmt=2 far=65535 cmd=1 pre=1 clr=1 xf=1 ts=1 ras=1 "
                f"out={out} ob={objects} obt=227 ofr=193 ta=40736 ti=7628 "
                "tz=0 tfr=2845 tc=399 tu=4384 tg=4987 tp=0 tf=1422 td=606 "
                "to=0 tr=2959 tv=0 pt=130498 pc=58910 pz=0 pd=17164 "
                "pu=0 ps=41746"
            )

        valid = "\n".join(render(sequence) for sequence in range(229))
        evidence = profile.validate_render_sequence_evidence(valid)
        self.assertEqual(evidence["qualified_prefix"], list(range(227)))
        self.assertEqual(evidence["post_endpoint_shutdown_tail"], [227, 228])
        self.assertTrue(evidence["tail_stable_counters_identical"])
        self.assertIn("out", evidence["required_render_fields"])
        self.assertNotIn("out", evidence["structural_stable_fields"])

        timing_tail = (
            "\n".join(render(sequence) for sequence in range(227))
            + "\n"
            + render(227, out=1)
        )
        timing_evidence = profile.validate_render_sequence_evidence(timing_tail)
        self.assertEqual(timing_evidence["endpoint_out"], 0)
        self.assertEqual(timing_evidence["post_endpoint_tail_out"], [1])
        self.assertTrue(timing_evidence["tail_stable_counters_identical"])

        invalid_sequences = {
            "nonzero": list(range(1, 228)),
            "gap": list(range(227)) + [228],
            "duplicate": list(range(227)) + [226],
        }
        for name, sequences in invalid_sequences.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                profile.MosUartThreProfileError, "contiguous prefix"
            ):
                profile.validate_render_sequence_evidence(
                    "\n".join(render(sequence) for sequence in sequences)
                )

        with self.assertRaisesRegex(
            profile.MosUartThreProfileError, "scene mutation"
        ):
            profile.validate_render_sequence_evidence(
                valid + "\n" + profile.PUBLICATION_MARKER + "late=1"
            )
        with self.assertRaisesRegex(
            profile.MosUartThreProfileError, "stable counters"
        ):
            profile.validate_render_sequence_evidence(
                "\n".join(render(sequence) for sequence in range(227))
                + "\n"
                + render(227, objects=228)
            )
        with self.assertRaisesRegex(
            profile.MosUartThreProfileError, "omits required fields.*out"
        ):
            profile.validate_render_sequence_evidence(
                "\n".join(render(sequence) for sequence in range(227)).replace(
                    "out=0 ", ""
                )
            )
        with self.assertRaisesRegex(
            profile.MosUartThreProfileError, "tail is too long"
        ):
            profile.validate_render_sequence_evidence(
                "\n".join(
                    render(sequence)
                    for sequence in range(
                        227 + profile.MAX_POST_ENDPOINT_RENDER_TAIL + 1
                    )
                )
            )

    def test_emulator_commands_differ_only_by_exact_mos_argument(self) -> None:
        layout = self.layout()
        vdp = profile.staged.require_file(profile.survey.DEFAULT_VDP, "VDP")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sd_root = output / "sd"
            sd_root.mkdir()
            _run, _program, _symbols, control_mos, _map = (
                profile.prepare_run_output(output, "control", self.control)
            )
            _run, _program, _symbols, candidate_mos, _map = (
                profile.prepare_run_output(output, "candidate", self.candidate)
            )
            control = profile.emulator_command(
                sd_root,
                vdp,
                control_mos,
                builder.PINNED_MOS_SHA256,
                layout.breakpoints,
            )
            candidate = profile.emulator_command(
                sd_root,
                vdp,
                candidate_mos,
                builder.PATCHED_MOS_SHA256,
                layout.breakpoints,
            )
        self.assertEqual(len(control), len(candidate))
        differences = [
            index for index, (left, right) in enumerate(zip(control, candidate))
            if left != right
        ]
        self.assertEqual(differences, [control.index("--mos") + 1])
        self.assertNotIn("p3dm_uart0_write_block_thre", " ".join(control))

    def test_run_staging_copies_exact_same_stem_map_for_hostfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            run, program, symbols, mos_copy, mos_map_copy = (
                profile.prepare_run_output(output, "control", self.control)
            )
            self.assertEqual(mos_map_copy, mos_copy.with_suffix(".map"))
            self.assertEqual(
                profile.sha256(mos_map_copy), builder.PINNED_MAP_SHA256
            )
            self.assertEqual(
                mos_map_copy.read_bytes(), builder.PINNED_MAP.read_bytes()
            )
            self.assertEqual(
                profile.sha256(program), crc_builder.ACCEPTED_PROGRAM_SHA256
            )
            self.assertEqual(
                profile.sha256(symbols),
                builder.CRC1_CONTROL_ARTIFACTS["legacy_control_symbols"][2],
            )
            self.assertEqual((run / "autoexec.txt").read_bytes(), profile.AUTOEXEC)

            sd_root = output / "sd"
            sd_root.mkdir()
            profile.staged.stage_fixture(sd_root, program)
            corpus = builder.validate_runtime_corpus(sd_root / "survey")
            self.assertEqual(
                corpus["coverage_digest_sha256"],
                builder.EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256,
            )

            program.write_bytes(b"not-the-accepted-program")
            with self.assertRaisesRegex(
                profile.MosUartThreProfileError,
                "private CRC1 legacy_control_program identity changed",
            ):
                profile.require_exact_run_copy(program, "legacy_control_program")

    def test_private_control_ignores_simulated_promoted_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            promoted_program = root / "canonical.bin"
            promoted_symbols = root / "canonical.symbols"
            promoted_program.write_bytes(b"simulated-nibble-program")
            promoted_symbols.write_bytes(b"simulated-nibble-symbols")
            with (
                mock.patch.object(crc_builder, "ACCEPTED_PROGRAM", promoted_program),
                mock.patch.object(crc_builder, "ACCEPTED_SYMBOLS", promoted_symbols),
            ):
                program, _listing, symbols = profile.validate_crc1_control(
                    self.build
                )
                layout = profile.resolve_normative_layout(program, symbols)

        self.assertEqual(profile.sha256(program), crc_builder.ACCEPTED_PROGRAM_SHA256)
        self.assertEqual(layout.startup_submit_call, profile.STARTUP_SUBMIT_CALL)


if __name__ == "__main__":
    unittest.main()
