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

import profile_regular_lod_crc_nibble_thre_sibling as profile  # noqa: E402


class CrcNibbleThreProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = profile.validate_inputs(
            profile.DEFAULT_REGISTER_BUILD,
            profile.DEFAULT_NIBBLE_BUILD,
            profile.DEFAULT_MOS_BUILD,
        )

    def test_exact_current_receipts_artifacts_and_same_thre_mos(self) -> None:
        inputs = self.inputs

        self.assertEqual(
            profile.sha256(inputs.register_receipt),
            profile.REGISTER_RECEIPT_SHA256,
        )
        self.assertEqual(
            profile.sha256(inputs.nibble_receipt),
            profile.NIBBLE_RECEIPT_SHA256,
        )
        self.assertEqual(
            profile.sha256(inputs.mos_receipt), profile.MOS_RECEIPT_SHA256
        )
        self.assertEqual(
            inputs.control.program_sha256, profile.REGISTER_PROGRAM_SHA256
        )
        self.assertEqual(
            inputs.candidate.program_sha256, profile.NIBBLE_PROGRAM_SHA256
        )
        self.assertEqual(profile.sha256(inputs.thre_mos), profile.THRE_MOS_SHA256)
        self.assertEqual(
            inputs.composition["thre_mos_sha256_both_variants"],
            profile.THRE_MOS_SHA256,
        )
        self.assertFalse(inputs.composition["third_code_patch"])

    def test_stale_or_mutated_nibble_receipt_is_rejected_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "nibble"
            shutil.copytree(profile.DEFAULT_NIBBLE_BUILD, copied)
            receipt = copied / "BUILD.json"
            receipt.write_bytes(receipt.read_bytes() + b" ")
            with self.assertRaisesRegex(
                profile.CrcNibbleThreProfileError, "current CRC-nibble BUILD"
            ):
                profile.validate_nibble_build(copied)

    def test_each_image_resolves_own_shifted_submit_and_inner_sites(self) -> None:
        register_norm = profile.resolve_normative_layout(
            self.inputs.control.program, self.inputs.control.symbols
        )
        nibble_norm = profile.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )
        register_inner = profile.resolve_inner_layout(
            self.inputs.control.program, self.inputs.control.symbols
        )
        nibble_inner = profile.resolve_inner_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )

        self.assertEqual(register_norm.startup_submit_call, 0x0629B4)
        self.assertEqual(register_norm.loop_submit_call, 0x0629FC)
        self.assertEqual(nibble_norm.startup_submit_call, 0x062AA2)
        self.assertEqual(nibble_norm.loop_submit_call, 0x062AEA)
        self.assertEqual(
            nibble_norm.startup_submit_call - register_norm.startup_submit_call,
            238,
        )
        self.assertEqual(register_inner.breakpoints, (0x0437C7, 0x0435EA))
        self.assertEqual(nibble_inner.breakpoints, register_inner.breakpoints)
        self.assertEqual(register_inner.crc_value, 0x043AC5)
        self.assertEqual(nibble_inner.crc_value, 0x043BB3)
        self.assertEqual(nibble_inner.crc_value - register_inner.crc_value, 238)
        self.assertEqual(register_inner.file_buffer, 0x043AF3)
        self.assertEqual(nibble_inner.file_buffer, 0x043BE1)

    def test_outer_phase_calls_same_but_owned_targets_shift_238_bytes(self) -> None:
        register_symbols = profile.mos_profile.staged.parse_symbols(
            self.inputs.control.symbols
        )
        nibble_symbols = profile.mos_profile.staged.parse_symbols(
            self.inputs.candidate.symbols
        )
        register = profile.mos_profile.cold.resolve_phase_spans(
            self.inputs.control.program, register_symbols
        )
        nibble = profile.mos_profile.cold.resolve_phase_spans(
            self.inputs.candidate.program, nibble_symbols
        )

        self.assertEqual(
            [(phase.call, phase.post_call) for phase in register],
            [(phase.call, phase.post_call) for phase in nibble],
        )
        self.assertEqual(
            [phase.target for phase in nibble[2:]],
            [phase.target + 238 for phase in register[2:]],
        )

    def test_staging_pins_program_symbols_same_mos_map_autoexec_and_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for mode, variant in (
                ("register", self.inputs.control),
                ("nibble", self.inputs.candidate),
            ):
                staged = profile.prepare_run_output(
                    output, mode, variant, self.inputs.thre_mos
                )
                profile.validate_staged_run(staged, variant)
                self.assertEqual(
                    profile.sha256(staged.mos), profile.THRE_MOS_SHA256
                )
                self.assertEqual(
                    profile.sha256(staged.mos_map), profile.PINNED_MAP_SHA256
                )
                self.assertEqual(
                    (staged.directory / "autoexec.txt").read_bytes(),
                    profile.mos_profile.AUTOEXEC,
                )
                sd_root = output / f"sd-{mode}"
                sd_root.mkdir()
                profile.mos_profile.staged.stage_fixture(sd_root, staged.program)
                corpus = profile.mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                self.assertEqual(corpus["aggregates"]["records"], 227)
                self.assertEqual(corpus["aggregates"]["data_bytes"], 764_288)

    def test_minimal_inner_driver_is_exactly_two_boundaries_and_227_snapshots(
        self,
    ) -> None:
        layout = profile.resolve_inner_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        process = Process()
        driver = profile.InnerCrcProfiler(process, layout, 1)
        contents = ""
        contents += f"CPU paused (breakpoint)\n* {layout.crc_entry:06x}: op\n"
        driver.service(contents)
        contents += "Cycles since last break: 7\n"
        driver.service(contents)
        contents += f"CPU paused (breakpoint)\n* {layout.crc_post:06x}: op\n"
        driver.service(contents)
        contents += "Cycles since last break: 99\n"
        driver.service(contents)
        contents += f"{layout.crc_value:06x}: 01 02 03 04\n"
        driver.service(contents)

        evidence = driver.require_complete()
        self.assertEqual(evidence["events_per_record"], 2)
        self.assertEqual(evidence["cycle_state_count"], 2)
        self.assertEqual(evidence["crc_memory_snapshot_count"], 1)
        self.assertEqual(driver.crc_memory, [bytes((1, 2, 3, 4))])

    def test_inner_reconstruction_binds_all227_crc_ix_and_register_control(self) -> None:
        expected = profile.crc_profile.regular_capture.initial_records()

        def evidence(variant: profile.Variant):
            layout = profile.resolve_inner_layout(variant.program, variant.symbols)
            states = []
            memory = []
            bound = []
            for order, record in enumerate(expected):
                _payload, data, stored = profile.crc_profile.expected_record_payload(
                    record
                )
                crc = stored.to_bytes(4, "little")
                memory.append(crc)
                expected_ix = (
                    layout.file_buffer
                    + profile.register_builder.P3DM_DATA_OFFSET
                    + len(data)
                )
                hl = crc[0] | (crc[1] << 8)
                de = crc[2] | (crc[3] << 8)
                common = {
                    "record": order,
                    "af": 0,
                    "bc": 0,
                    "de": de if variant.register_resident else 0,
                    "hl": hl if variant.register_resident else 0,
                    "ix": expected_ix,
                }
                states.extend(
                    (
                        {
                            **common,
                            "event": "crc_entry",
                            "address": layout.crc_entry,
                            "line_number": order * 2 + 1,
                            "cycles_since_previous_boundary": 1,
                        },
                        {
                            **common,
                            "event": "crc_post",
                            "address": layout.crc_post,
                            "line_number": order * 2 + 2,
                            "cycles_since_previous_boundary": 100,
                        },
                    )
                )
                bound.append(
                    {
                        "order": order,
                        "path": record["path"],
                        "file_sha256": record["sha256"],
                        "data_bytes": len(data),
                    }
                )
            return profile.reconstruct_inner_records(
                states, memory, layout, variant, bound
            )

        control = evidence(self.inputs.control)
        candidate = evidence(self.inputs.candidate)
        self.assertEqual(len(control), 227)
        self.assertEqual(len(candidate), 227)
        self.assertIsNotNone(control[0]["register_crc_hex"])
        self.assertIsNone(candidate[0]["register_crc_hex"])
        profile.assert_inner_semantic_equivalence(
            {
                "cold_endpoint": {},
                "publication_semantics": [],
                "render_sequences": list(range(227)),
                "records": control,
            },
            {
                "cold_endpoint": {},
                "publication_semantics": [],
                "render_sequences": list(range(227)),
                "records": candidate,
            },
        )

    def test_normative_publication_gate_and_metric_pairs_remain_strict(self) -> None:
        layout = profile.resolve_normative_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )

        class Process:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()

        driver = profile.mos_profile.NormativeProfiler(Process(), layout, 1)
        contents = ""
        for name, address in layout.events_for_record(0):
            if name == "publication_complete_submit":
                contents += profile.mos_profile.PUBLICATION_MARKER + "mid=1\n"
            contents += f"CPU paused (breakpoint)\n* {address:06x}: op\n"
            driver.service(contents)
            contents += "Cycles since last break: 3\n"
            driver.service(contents)
        self.assertEqual(driver.require_complete()["publication_before_submit_count"], 1)

        def run(total: int):
            return {
                "metrics": {
                    "inner_crc_entry_to_post": {
                        "summary_all_227": {"total": total}
                    }
                }
            }

        paired = profile.paired_inner_metric(
            run(100), run(60), "summary_all_227"
        )
        self.assertEqual(paired["candidate_vs_control_percent"], -40.0)
        self.assertTrue(paired["direct_inner_measurement"])
        self.assertFalse(paired["completion_equivalent"])

    def test_negative_mutations_pin_error9_and_error10_precedence_inputs(self) -> None:
        record, _relative, original = profile.crc_profile.first_record()
        crc_data, crc_witness = profile.crc_profile.mutate_negative(
            "crc-data", record, original
        )
        index, index_witness = profile.crc_profile.mutate_negative(
            "index-valid-crc", record, original
        )

        self.assertEqual(crc_witness["expected_error"], 9)
        self.assertNotEqual(
            crc_witness["stored_crc32"], crc_witness["actual_data_crc32"]
        )
        self.assertEqual(index_witness["expected_error"], 10)
        self.assertEqual(
            index_witness["stored_crc32"], index_witness["actual_data_crc32"]
        )
        self.assertNotEqual(crc_data, original)
        self.assertNotEqual(index, original)
        layout = profile.resolve_inner_layout(
            self.inputs.candidate.program, self.inputs.candidate.symbols
        )
        self.assertEqual([layout.return_error], [0x043B1B])
        self.assertEqual(
            [layout.return_error, layout.crc_entry], [0x043B1B, 0x0437C7]
        )

    def test_recovery_revalidates_failed_v1_and_all_four_immutable_v2_runs(
        self,
    ) -> None:
        failed = profile.validate_failed_v1_race(
            profile.DEFAULT_FAILED_V1_EVIDENCE, self.inputs
        )
        self.assertEqual(failed["record_index"], 8)
        self.assertEqual(failed["successful_publications_at_submit"], 8)
        self.assertEqual(failed["successful_publications_required"], 9)
        self.assertTrue(failed["matching_publication_appeared_after_submit"])

        recovered = profile.recover_positive_evidence(
            profile.DEFAULT_RECOVERY_V2_EVIDENCE,
            self.inputs,
            profile.mos_profile.builder.validate_runtime_corpus(),
        )
        *runs, receipt = recovered
        self.assertEqual(receipt["file_count"], 28)
        self.assertEqual(len(runs), 4)
        self.assertTrue(
            all(len(run["records"]) == profile.EXPECTED_RECORDS for run in runs)
        )
        self.assertTrue(
            all(run["captured_in_current_invocation"] is False for run in runs)
        )
        candidate_inner = runs[-1]
        self.assertEqual(candidate_inner["render_evidence"]["endpoint_out"], 0)
        self.assertEqual(
            candidate_inner["render_evidence"]["post_endpoint_tail_out"], [1]
        )
        self.assertTrue(
            candidate_inner["render_evidence"]["tail_stable_counters_identical"]
        )
        self.assertEqual(
            profile.RECOVERY_NEGATIVE_KINDS,
            ("crc-data", "index-valid-crc"),
        )

    def test_recovery_manifest_rejects_any_pinned_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "v2"
            shutil.copytree(profile.DEFAULT_RECOVERY_V2_EVIDENCE, copied)
            command = (
                copied
                / "inner-crc-nibble-thre-candidate"
                / "command.json"
            )
            command.write_bytes(command.read_bytes() + b" ")
            with self.assertRaisesRegex(
                profile.CrcNibbleThreProfileError,
                "recovery-v2 positive evidence.*identity changed",
            ):
                profile.validate_immutable_evidence_tree(
                    copied,
                    profile.RECOVERY_V2_EVIDENCE_MANIFEST,
                    "recovery-v2 positive evidence",
                )

    def test_recovery_main_skips_positives_and_plans_only_two_negatives(self) -> None:
        calls = []

        def negative(kind, *_args, **_kwargs):
            calls.append(kind)
            return {"kind": kind, "fresh_process": True}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "v3"
            with (
                mock.patch.object(
                    profile,
                    "run_normative",
                    side_effect=AssertionError("recovery reran normative positive"),
                ),
                mock.patch.object(
                    profile,
                    "run_inner",
                    side_effect=AssertionError("recovery reran inner positive"),
                ),
                mock.patch.object(profile, "run_negative", side_effect=negative),
            ):
                result = profile.main(
                    (
                        "--recover-positive-evidence",
                        str(profile.DEFAULT_RECOVERY_V2_EVIDENCE),
                        "--failed-v1-evidence",
                        str(profile.DEFAULT_FAILED_V1_EVIDENCE),
                        "--output",
                        str(output),
                        "--timeout",
                        "1",
                    )
                )
            self.assertEqual(result, 0)
            self.assertEqual(calls, list(profile.RECOVERY_NEGATIVE_KINDS))
            report = json.loads((output / profile.REPORT_NAME).read_text())
            self.assertTrue(report["qualified"])
            self.assertEqual(report["scope"]["current_invocation_process_count"], 2)
            self.assertFalse(
                report["scope"]["all_six_runs_one_uninterrupted_invocation"]
            )
            self.assertEqual(
                report["recovery_finalization"]["v2_analyzer_stop"][
                    "positive_processes_completed"
                ],
                4,
            )


if __name__ == "__main__":
    unittest.main()
