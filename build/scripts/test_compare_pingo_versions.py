#!/usr/bin/env python3
"""Tests for the two-version chained Pingo comparison tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from build.scripts.compare_pingo_versions import (
    FIXTURES,
    PROFILES,
    compare,
    html_report,
    json_report,
    parse_complete_runs,
    parse_complete_runs_many,
)


def record(sequence: int, bitmap_id: int, render_us: int) -> str:
    return (
        f"PINGO_RENDER seq={sequence} bmid={bitmap_id} "
        f"render_us={render_us}\n"
    )


def complete_log(render_us: int, partial_prefix: bool = False) -> str:
    lines = []
    if partial_prefix:
        lines.extend(record(i, 1410, render_us * 3) for i in range(20, 30))
    lines.extend(record(i, 1257, render_us) for i in range(580))
    lines.extend(record(i, 1410, render_us) for i in range(867))
    return "".join(lines)


def quick_log(render_us: int) -> str:
    lines = [record(i, 1257, render_us) for i in range(218)]
    lines.extend(record(i, 1410, render_us) for i in range(289))
    return "".join(lines)


def object_culling_log(render_us: int) -> str:
    return "".join(record(i, 1410, render_us) for i in range(867))


class ComparePingoVersionsTests(unittest.TestCase):
    def write_log(self, directory: Path, name: str, contents: str) -> Path:
        path = directory / name
        path.write_text(contents, encoding="ascii")
        return path

    def test_partial_prefix_is_ignored_and_complete_run_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_log(
                Path(temporary), "capture.log", complete_log(100_000, True)
            )
            runs = parse_complete_runs(path)
        self.assertEqual([len(run) for run in runs[1257]], [580])
        self.assertEqual([len(run) for run in runs[1410]], [867])

    def test_gap_rejects_incomplete_stream(self) -> None:
        lines = [record(i, 1257, 100_000) for i in range(580) if i != 200]
        lines.extend(record(i, 1410, 100_000) for i in range(867))
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_log(
                Path(temporary), "capture.log", "".join(lines)
            )
            with self.assertRaisesRegex(ValueError, "1257"):
                parse_complete_runs(path)

    def test_comparison_reports_equivalent_fps_and_both_graph_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline = parse_complete_runs(
                self.write_log(
                    directory, "baseline.log", complete_log(200_000)
                )
            )
            candidate = parse_complete_runs(
                self.write_log(
                    directory, "candidate.log", complete_log(100_000)
                )
            )
        results = compare(baseline, candidate)
        self.assertEqual(len(results), len(FIXTURES) + 1)
        self.assertAlmostEqual(results[0].baseline_fps, 5.0)
        self.assertAlmostEqual(results[0].candidate_fps, 10.0)
        self.assertAlmostEqual(results[0].fps_gain_percent, 100.0)
        report = html_report(results, "Version A", "Version B")
        self.assertIn(">5.00</text>", report)
        self.assertIn(">10.00</text>", report)
        self.assertIn("Version A", report)
        self.assertIn("Version B", report)

    def test_quick_profile_accepts_dedicated_quick_baseline(self) -> None:
        profile = PROFILES["quick"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline = parse_complete_runs(
                self.write_log(
                    directory, "baseline.log", quick_log(200_000)
                ),
                profile.expected_last_sequence,
            )
            candidate = parse_complete_runs(
                self.write_log(
                    directory, "candidate.log", quick_log(100_000)
                ),
                profile.expected_last_sequence,
            )
        results = compare(
            baseline,
            candidate,
            profile.fixtures,
            profile.weighted_label,
        )
        self.assertEqual(len(results), len(profile.fixtures) + 1)
        self.assertEqual(results[-1].frame_count, 507)
        self.assertEqual(results[-1].name, profile.weighted_label)
        self.assertAlmostEqual(results[-1].baseline_fps, 5.0)
        self.assertAlmostEqual(results[-1].candidate_fps, 10.0)

    def test_object_culling_profile_and_multiple_logs(self) -> None:
        profile = PROFILES["object-culling"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first_path = self.write_log(
                directory, "candidate-1.log", object_culling_log(100_000)
            )
            second_path = self.write_log(
                directory, "candidate-2.log", object_culling_log(120_000)
            )
            candidate = parse_complete_runs_many(
                (first_path, second_path),
                profile.expected_last_sequence,
            )
        self.assertEqual(len(candidate[1410]), 2)
        self.assertEqual(profile.frame_count, 867)
        self.assertEqual(
            [fixture.frame_count for fixture in profile.fixtures],
            [289, 289, 289],
        )
        self.assertEqual(candidate[1410][0][0], 100_000)
        self.assertEqual(candidate[1410][1][-1], 120_000)

    def test_object_culling_comparison_averages_repeated_candidate_runs(
        self,
    ) -> None:
        profile = PROFILES["object-culling"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline = parse_complete_runs_many(
                (
                    self.write_log(
                        directory,
                        "baseline.log",
                        object_culling_log(200_000),
                    ),
                ),
                profile.expected_last_sequence,
            )
            candidate = parse_complete_runs_many(
                (
                    self.write_log(
                        directory,
                        "candidate-1.log",
                        object_culling_log(100_000),
                    ),
                    self.write_log(
                        directory,
                        "candidate-2.log",
                        object_culling_log(200_000),
                    ),
                ),
                profile.expected_last_sequence,
            )
        results = compare(
            baseline,
            candidate,
            profile.fixtures,
            profile.weighted_label,
        )
        self.assertAlmostEqual(results[-1].baseline_fps, 5.0)
        self.assertAlmostEqual(results[-1].candidate_fps, 6.6666667)
        self.assertAlmostEqual(results[-1].fps_gain_percent, 33.3333333)
        self.assertEqual(results[-1].candidate_spread_us, 100_000)

    def test_json_report_records_sources_digests_and_profile(self) -> None:
        profile = PROFILES["quick"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline_path = self.write_log(
                directory, "baseline.log", quick_log(200_000)
            )
            candidate_path = self.write_log(
                directory, "candidate.log", quick_log(100_000)
            )
            candidate_repeat_path = self.write_log(
                directory, "candidate-repeat.log", quick_log(100_000)
            )
            baseline = parse_complete_runs(
                baseline_path, profile.expected_last_sequence
            )
            candidate = parse_complete_runs(
                candidate_path, profile.expected_last_sequence
            )
            results = compare(
                baseline,
                candidate,
                profile.fixtures,
                profile.weighted_label,
            )
            report = json_report(
                results,
                "A",
                "B",
                baseline_path,
                (candidate_path, candidate_repeat_path),
                baseline,
                candidate,
                profile,
                "2026-07-29T00:00:00Z",
            )
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["profile"]["key"], "quick")
        self.assertEqual(report["profile"]["frames_per_run"], 507)
        self.assertEqual(len(report["baseline"]["log_sha256"]), 64)
        self.assertNotIn("sources", report["baseline"])
        self.assertEqual(len(report["candidate"]["sources"]), 2)
        self.assertEqual(
            report["candidate"]["sources"][0]["complete_runs"],
            {"1257": 1, "1410": 1},
        )
        self.assertEqual(report["rows"][-1]["frames"], 507)

    def test_single_source_report_retains_schema_one(self) -> None:
        profile = PROFILES["object-culling"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            baseline_path = self.write_log(
                directory, "baseline.log", object_culling_log(200_000)
            )
            candidate_path = self.write_log(
                directory, "candidate.log", object_culling_log(100_000)
            )
            baseline = parse_complete_runs(
                baseline_path, profile.expected_last_sequence
            )
            candidate = parse_complete_runs(
                candidate_path, profile.expected_last_sequence
            )
            results = compare(
                baseline,
                candidate,
                profile.fixtures,
                profile.weighted_label,
            )
            report = json_report(
                results,
                "A",
                "B",
                baseline_path,
                candidate_path,
                baseline,
                candidate,
                profile,
                "2026-07-29T00:00:00Z",
            )
        self.assertEqual(report["schema_version"], 1)
        self.assertNotIn("sources", report["baseline"])
        self.assertNotIn("sources", report["candidate"])


if __name__ == "__main__":
    unittest.main()
