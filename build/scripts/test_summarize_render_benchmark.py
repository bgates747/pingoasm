#!/usr/bin/env python3
"""Unit tests for versioned Pingo render diagnostic records."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from summarize_render_benchmark import (  # noqa: E402
    MalformedDiagnostics,
    RECORD_RE,
    build_summary,
    latest_run,
    parse_diagnostics,
    parse_records,
)


PROFILE = {
    "name": "diagnostic-test",
    "texture_format": "rgba2222",
    "target_format": "rgba2222",
    "resolution": [320, 240],
    "warmup_frames": 1,
    "measured_frames": 2,
    "rotation_step_degrees": 180,
    "warmup_target_bitmap_id": 1258,
    "target_bitmap_id": 1257,
}

DIAGNOSTIC_FIELDS = {
    "d": 1,
    "w": 320,
    "h": 240,
    "fmt": 2,
    "cmd": 210000,
    "pre": 100,
    "clr": 300,
    "xf": 400,
    "ts": 500,
    "ras": 198000,
    "out": 0,
    "ob": 1,
    "ti": 12,
    "tz": 1,
    "tf": 5,
    "td": 0,
    "to": 0,
    "tr": 6,
    "tv": 0,
    "pt": 100000,
    "pc": 50000,
    "pz": 1000,
    "pd": 4000,
    "pu": 0,
    "ps": 45000,
}
DIAGNOSTIC_FIELDS_V2 = {
    **DIAGNOSTIC_FIELDS,
    "d": 2,
    "tfr": 0,
}
DIAGNOSTIC_FIELDS_V3 = {
    **DIAGNOSTIC_FIELDS_V2,
    "d": 3,
    "obt": 1,
    "ofr": 0,
    "ta": 0,
}


def ordinary_line(
    *,
    sequence: int,
    bmid: int,
    render_us: int = 200000,
) -> str:
    return (
        f"PINGO_RENDER seq={sequence} bmid={bmid} "
        f"render_us={render_us}\n"
    )


def diagnostic_line(
    *,
    sequence: int = 7,
    bmid: int = 1257,
    render_us: int = 200000,
    fields: dict[str, int] | None = None,
) -> str:
    values = DIAGNOSTIC_FIELDS if fields is None else fields
    suffix = " ".join(f"{key}={value}" for key, value in values.items())
    return ordinary_line(
        sequence=sequence,
        bmid=bmid,
        render_us=render_us,
    ).rstrip() + f" {suffix}\n"


def diagnostic_run(
    *,
    sequences: tuple[int, int, int] = (100, 101, 102),
    fields: tuple[
        dict[str, int],
        dict[str, int],
        dict[str, int],
    ] | None = None,
) -> str:
    values = fields or (
        DIAGNOSTIC_FIELDS,
        DIAGNOSTIC_FIELDS,
        DIAGNOSTIC_FIELDS,
    )
    bitmap_ids = (1258, 1257, 1257)
    return "".join(
        diagnostic_line(sequence=sequence, bmid=bmid, fields=item)
        for sequence, bmid, item in zip(
            sequences,
            bitmap_ids,
            values,
            strict=True,
        )
    )


class ParseRenderDiagnosticsTests(unittest.TestCase):
    def test_ordinary_record_remains_compatible(self) -> None:
        line = ordinary_line(sequence=7, bmid=1257)
        self.assertEqual(
            parse_records("noise\n" + line),
            [(7, 1257, 200000, None)],
        )
        # Preserve the original public regex's three capture groups.
        self.assertEqual(RECORD_RE.findall(line), [("7", "1257", "200000")])

    def test_complete_version_one_record(self) -> None:
        records = parse_records(diagnostic_line())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][:3], (7, 1257, 200000))
        self.assertEqual(records[0][3], DIAGNOSTIC_FIELDS)

    def test_complete_version_two_record(self) -> None:
        records = parse_records(diagnostic_line(fields=DIAGNOSTIC_FIELDS_V2))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][3], DIAGNOSTIC_FIELDS_V2)

    def test_complete_version_three_record(self) -> None:
        records = parse_records(diagnostic_line(fields=DIAGNOSTIC_FIELDS_V3))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][3], DIAGNOSTIC_FIELDS_V3)

    def test_version_one_rejects_version_two_field(self) -> None:
        fields = dict(DIAGNOSTIC_FIELDS, tfr=0)
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(ValueError, "unknown fields: tfr"):
            parse_diagnostics(tail)

    def test_version_two_requires_frustum_field(self) -> None:
        fields = dict(DIAGNOSTIC_FIELDS, d=2)
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(ValueError, "missing fields: tfr"):
            parse_diagnostics(tail)

    def test_version_two_rejects_object_culling_fields(self) -> None:
        fields = dict(
            DIAGNOSTIC_FIELDS_V2,
            obt=1,
            ofr=0,
            ta=0,
        )
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(
            ValueError, "unknown fields: obt, ofr, ta"
        ):
            parse_diagnostics(tail)

    def test_version_three_requires_all_object_culling_fields(self) -> None:
        for missing in ("obt", "ofr", "ta"):
            fields = dict(DIAGNOSTIC_FIELDS_V3)
            del fields[missing]
            tail = " ".join(
                f"{key}={value}" for key, value in fields.items()
            )
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(
                    ValueError, f"missing fields: {missing}"
                ):
                    parse_diagnostics(tail)

    def test_version_three_enforces_object_counter_bounds(self) -> None:
        for fields in (
            dict(DIAGNOSTIC_FIELDS_V3, obt=2),
            dict(DIAGNOSTIC_FIELDS_V3, ofr=2),
            dict(DIAGNOSTIC_FIELDS_V3, obt=0, ofr=0, ta=1),
        ):
            tail = " ".join(
                f"{key}={value}" for key, value in fields.items()
            )
            with self.assertRaisesRegex(
                ValueError, "object counters|require a rejected object"
            ):
                parse_diagnostics(tail)

    def test_version_three_allows_fully_rejected_object(self) -> None:
        fields = dict(
            DIAGNOSTIC_FIELDS_V3,
            obt=1,
            ofr=1,
            ta=12,
            ti=0,
            tz=0,
            tfr=0,
            tf=0,
            td=0,
            to=0,
            tr=0,
            tv=0,
            pt=0,
            pc=0,
            pz=0,
            pd=0,
            pu=0,
            ps=0,
        )
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        self.assertEqual(parse_diagnostics(tail), fields)

    def test_malformed_record_is_preserved_for_run_selection(self) -> None:
        records = parse_records(
            ordinary_line(sequence=7, bmid=1257).rstrip()
            + " d=1 w=320\n"
        )
        self.assertIsInstance(records[0][3], MalformedDiagnostics)

    def test_truncated_schema_marker_is_malformed(self) -> None:
        records = parse_records(
            ordinary_line(sequence=7, bmid=1257).rstrip() + " d\n"
        )
        self.assertIsInstance(records[0][3], MalformedDiagnostics)

    def test_missing_field_is_rejected_by_diagnostic_parser(self) -> None:
        fields = dict(DIAGNOSTIC_FIELDS)
        del fields["ps"]
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(ValueError, "missing fields: ps"):
            parse_diagnostics(tail)

    def test_duplicate_field_is_rejected_by_diagnostic_parser(self) -> None:
        tail = " ".join(
            f"{key}={value}" for key, value in DIAGNOSTIC_FIELDS.items()
        )
        with self.assertRaisesRegex(ValueError, "duplicate diagnostic key: ps"):
            parse_diagnostics(tail + " ps=45000")

    def test_triangle_partition_is_enforced(self) -> None:
        fields = dict(DIAGNOSTIC_FIELDS, tr=5)
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(ValueError, "triangle counters"):
            parse_diagnostics(tail)

    def test_version_two_triangle_partition_includes_frustum(self) -> None:
        fields = dict(
            DIAGNOSTIC_FIELDS_V2,
            tz=0,
            tfr=1,
        )
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        self.assertEqual(parse_diagnostics(tail), fields)

    def test_fragment_partition_is_enforced(self) -> None:
        fields = dict(DIAGNOSTIC_FIELDS, ps=44999)
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        with self.assertRaisesRegex(ValueError, "covered-fragment counters"):
            parse_diagnostics(tail)


class SelectRenderRunTests(unittest.TestCase):
    def test_latest_complete_run_ignores_prior_noise(self) -> None:
        text = diagnostic_line(sequence=98, bmid=999) + diagnostic_run()
        selected = latest_run(
            parse_records(text),
            warmup_count=1,
            measured_count=2,
            warmup_bmid=1258,
            measured_bmid=1257,
        )
        self.assertEqual([record[0] for record in selected], [100, 101, 102])

    def test_prior_truncated_diagnostic_does_not_poison_latest_run(self) -> None:
        truncated = (
            ordinary_line(sequence=50, bmid=1258).rstrip()
            + " d=1 w=320\n"
        )
        summary = build_summary(
            PROFILE,
            parse_records(truncated + diagnostic_run()),
            require_diagnostics=True,
        )
        self.assertEqual(summary["render_sequence_start"], 100)
        self.assertIn("renderer_diagnostics", summary)

    def test_malformed_diagnostic_in_selected_run_fails(self) -> None:
        text = "".join(
            (
                diagnostic_line(sequence=100, bmid=1258),
                ordinary_line(sequence=101, bmid=1257).rstrip()
                + " d=1 w=320\n",
                diagnostic_line(sequence=102, bmid=1257),
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "selected run has malformed diagnostics at seq=101",
        ):
            build_summary(PROFILE, parse_records(text))

    def test_mixed_selected_run_fails(self) -> None:
        text = "".join(
            (
                ordinary_line(sequence=100, bmid=1258),
                diagnostic_line(sequence=101, bmid=1257),
                diagnostic_line(sequence=102, bmid=1257),
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "mixes diagnostic and ordinary records",
        ):
            build_summary(PROFILE, parse_records(text))

    def test_sequence_wrap_is_contiguous(self) -> None:
        sequences = (0xFFFFFFFE, 0xFFFFFFFF, 0)
        selected = latest_run(
            parse_records(diagnostic_run(sequences=sequences)),
            warmup_count=1,
            measured_count=2,
            warmup_bmid=1258,
            measured_bmid=1257,
        )
        self.assertEqual(
            [record[0] for record in selected],
            list(sequences),
        )

    def test_complete_multi_series_suite_is_selected(self) -> None:
        text = diagnostic_run() + diagnostic_run(
            sequences=(103, 104, 105)
        )
        selected = latest_run(
            parse_records(text),
            warmup_count=1,
            measured_count=2,
            warmup_bmid=1258,
            measured_bmid=1257,
            series_runs=2,
        )
        self.assertEqual(
            [record[0] for record in selected],
            [100, 101, 102, 103, 104, 105],
        )


class BuildRenderSummaryTests(unittest.TestCase):
    def test_orbit_profile_uses_orbit_metadata_without_rotation_label(self) -> None:
        profile = {
            **PROFILE,
            "warmup_frames": 0,
            "measured_frames": 3,
            "frames_per_orbit": 2,
        }
        records = parse_records(
            "".join(
                ordinary_line(sequence=index, bmid=1257)
                for index in range(3)
            )
        )
        summary = build_summary(profile, records)
        self.assertEqual(
            [frame["orbit_angle_deg"] for frame in summary["frames"]],
            [0.0, 180.0, 360.0],
        )
        self.assertEqual(
            [frame["orbit_revolution"] for frame in summary["frames"]],
            [0.0, 0.5, 1.0],
        )
        self.assertNotIn("angle_deg", summary["frames"][0])

    def test_multi_series_statistics_include_every_measured_frame(self) -> None:
        profile = dict(PROFILE, series_runs=2)
        text = diagnostic_run() + diagnostic_run(
            sequences=(103, 104, 105)
        )
        summary = build_summary(
            profile,
            parse_records(text),
            require_diagnostics=True,
        )
        self.assertEqual(summary["series_runs"], 2)
        self.assertEqual(summary["warmup_frames"], 2)
        self.assertEqual(summary["measured_frames"], 4)
        self.assertEqual(summary["warmup_frames_per_series"], 1)
        self.assertEqual(summary["measured_frames_per_series"], 2)
        self.assertEqual(len(summary["series"]), 2)
        self.assertEqual(
            [frame["series"] for frame in summary["frames"]],
            [0, 0, 1, 1],
        )
        self.assertEqual(
            [frame["angle_deg"] for frame in summary["frames"]],
            [0, 180, 0, 180],
        )
        self.assertEqual(
            summary["renderer_diagnostics"]["counter_totals"][
                "triangles_submitted"
            ],
            48,
        )

    def test_profile_identity_is_enforced(self) -> None:
        rgba8888 = tuple(
            dict(DIAGNOSTIC_FIELDS, fmt=8)
            for _ in range(3)
        )
        with self.assertRaisesRegex(ValueError, "does not match profile"):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=rgba8888)),
            )

        larger = tuple(
            dict(DIAGNOSTIC_FIELDS, w=640)
            for _ in range(3)
        )
        with self.assertRaisesRegex(ValueError, "does not match profile"):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=larger)),
            )

    def test_warmup_identity_is_part_of_run_identity(self) -> None:
        identities = (
            dict(DIAGNOSTIC_FIELDS, w=640),
            DIAGNOSTIC_FIELDS,
            DIAGNOSTIC_FIELDS,
        )
        with self.assertRaisesRegex(
            ValueError,
            "changes dimensions or pixel format",
        ):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=identities)),
            )

    def test_selected_run_cannot_mix_schema_versions(self) -> None:
        fields = (
            DIAGNOSTIC_FIELDS,
            DIAGNOSTIC_FIELDS_V3,
            DIAGNOSTIC_FIELDS,
        )
        with self.assertRaisesRegex(ValueError, "changes schema version"):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=fields)),
            )

    def test_require_diagnostics_and_ordinary_compatibility(self) -> None:
        text = "".join(
            (
                ordinary_line(sequence=100, bmid=1258),
                ordinary_line(sequence=101, bmid=1257),
                ordinary_line(sequence=102, bmid=1257),
            )
        )
        records = parse_records(text)
        summary = build_summary(PROFILE, records)
        self.assertNotIn("renderer_diagnostics", summary)
        self.assertEqual(summary["mean_render_us"], 200000)
        with self.assertRaisesRegex(ValueError, "has no renderer diagnostics"):
            build_summary(PROFILE, records, require_diagnostics=True)

    def test_diagnostic_aggregate_and_ratios(self) -> None:
        summary = build_summary(
            PROFILE,
            parse_records(diagnostic_run()),
            platform="hardware",
            firmware="test",
            require_diagnostics=True,
        )
        self.assertEqual(summary["total_render_us"], 400000)
        self.assertEqual(summary["mean_render_us"], 200000)
        diagnostics = summary["renderer_diagnostics"]
        self.assertEqual(diagnostics["schema_version"], 1)
        self.assertEqual(
            diagnostics["timing_totals_us"]["output_finalize_us"],
            0,
        )
        self.assertNotIn(
            "output_expand_us",
            diagnostics["timing_totals_us"],
        )
        self.assertEqual(diagnostics["renderer_residual_us"], 1600)
        self.assertEqual(diagnostics["renderer_unattributed_us"], 1600)
        self.assertEqual(diagnostics["renderer_rounding_overage_us"], 0)
        self.assertEqual(
            diagnostics["counter_totals"]["triangles_submitted"],
            24,
        )
        self.assertAlmostEqual(
            diagnostics["triangle_outcome_ratios"]["rasterized"],
            0.5,
        )
        self.assertAlmostEqual(diagnostics["coverage_ratio"], 0.5)
        self.assertAlmostEqual(
            diagnostics["reciprocal_w_reject_ratio"],
            0.0,
        )
        self.assertAlmostEqual(diagnostics["shade_ratio"], 0.9)
        self.assertEqual(
            summary["frames"][0]["diagnostics"]["renderer_residual_us"],
            800,
        )

    def test_version_two_aggregate_reports_frustum_rejection(self) -> None:
        fields = tuple(
            dict(
                DIAGNOSTIC_FIELDS_V2,
                tz=0,
                tfr=1,
            )
            for _ in range(3)
        )
        summary = build_summary(
            PROFILE,
            parse_records(diagnostic_run(fields=fields)),
            require_diagnostics=True,
        )
        diagnostics = summary["renderer_diagnostics"]
        self.assertEqual(diagnostics["schema_version"], 2)
        self.assertEqual(
            diagnostics["counter_totals"]["triangles_frustum_rejected"],
            2,
        )
        self.assertAlmostEqual(
            diagnostics["triangle_outcome_ratios"]["frustum_rejected"],
            1 / 12,
        )

    def test_version_three_aggregate_reports_object_culling(self) -> None:
        fields = tuple(
            dict(
                DIAGNOSTIC_FIELDS_V3,
                obt=1,
                ofr=1,
                ta=12,
                ti=0,
                tz=0,
                tfr=0,
                tf=0,
                td=0,
                to=0,
                tr=0,
                tv=0,
                pt=0,
                pc=0,
                pz=0,
                pd=0,
                pu=0,
                ps=0,
            )
            for _ in range(3)
        )
        summary = build_summary(
            PROFILE,
            parse_records(diagnostic_run(fields=fields)),
            require_diagnostics=True,
        )
        diagnostics = summary["renderer_diagnostics"]
        self.assertEqual(diagnostics["schema_version"], 3)
        self.assertEqual(
            diagnostics["counter_totals"]["objects_bounds_tested"],
            2,
        )
        self.assertEqual(
            diagnostics["counter_totals"]["objects_frustum_rejected"],
            2,
        )
        self.assertEqual(
            diagnostics["counter_totals"]["triangles_avoided"],
            24,
        )
        self.assertAlmostEqual(
            diagnostics["object_bounds_test_ratio"], 1.0
        )
        self.assertAlmostEqual(
            diagnostics["object_frustum_reject_ratio"], 1.0
        )
        self.assertAlmostEqual(
            diagnostics["triangle_avoidance_ratio"], 1.0
        )

    def test_motion_profile_adds_absolute_translation_to_frames(self) -> None:
        profile = {
            **PROFILE,
            "translation_motion": {
                "center": [0, 0, 0],
                "amplitude": [2400, 1800, 1600],
                "cycles": [1, 2, 1],
                "phase_degrees": [0, 0, 90],
            },
        }
        summary = build_summary(
            profile,
            parse_records(diagnostic_run()),
        )
        self.assertEqual(
            [frame["translation_words"] for frame in summary["frames"]],
            [[0, 0, 1600], [0, 0, -1600]],
        )

    def test_small_rounding_overage_is_explicitly_recorded(self) -> None:
        slight_overage = tuple(
            dict(DIAGNOSTIC_FIELDS, ras=198801)
            for _ in range(3)
        )
        summary = build_summary(
            PROFILE,
            parse_records(diagnostic_run(fields=slight_overage)),
        )
        diagnostics = summary["renderer_diagnostics"]
        self.assertEqual(diagnostics["renderer_residual_us"], -2)
        self.assertEqual(diagnostics["renderer_unattributed_us"], 0)
        self.assertEqual(diagnostics["renderer_rounding_overage_us"], 2)
        self.assertGreater(
            diagnostics["renderer_phase_shares"]["rounding_overage"],
            0,
        )

    def test_gross_renderer_timing_contradiction_is_rejected(self) -> None:
        impossible = tuple(
            dict(DIAGNOSTIC_FIELDS, ras=199000)
            for _ in range(3)
        )
        with self.assertRaisesRegex(
            ValueError,
            "renderer phases exceed render_us",
        ):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=impossible)),
            )

    def test_gross_command_timing_contradiction_is_rejected(self) -> None:
        impossible = tuple(
            dict(DIAGNOSTIC_FIELDS, cmd=190000)
            for _ in range(3)
        )
        with self.assertRaisesRegex(
            ValueError,
            "command phases exceed command_us",
        ):
            build_summary(
                PROFILE,
                parse_records(diagnostic_run(fields=impossible)),
            )


if __name__ == "__main__":
    unittest.main()
