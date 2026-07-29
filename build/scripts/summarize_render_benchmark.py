#!/usr/bin/env python3
"""Validate and summarize PINGO_RENDER records using a benchmark profile."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_render_benchmark import motion_translation


RECORD_RE = re.compile(
    r"PINGO_RENDER\s+seq=(\d+)(?:\s+bmid=(\d+))?\s+render_us=(\d+)"
)
EXTENDED_RECORD_RE = re.compile(
    RECORD_RE.pattern + r"([^\r\n]*)"
)

TIMING_RESIDUAL_TOLERANCE_US = 8

DIAGNOSTIC_V1_KEYS = (
    "d",
    "w",
    "h",
    "fmt",
    "cmd",
    "pre",
    "clr",
    "xf",
    "ts",
    "ras",
    "out",
    "ob",
    "ti",
    "tz",
    "tf",
    "td",
    "to",
    "tr",
    "tv",
    "pt",
    "pc",
    "pz",
    "pd",
    "pu",
    "ps",
)
DIAGNOSTIC_V2_KEYS = (
    *DIAGNOSTIC_V1_KEYS[:14],
    "tfr",
    *DIAGNOSTIC_V1_KEYS[14:],
)
DIAGNOSTIC_KEYS_BY_VERSION = {
    1: DIAGNOSTIC_V1_KEYS,
    2: DIAGNOSTIC_V2_KEYS,
}

DIAGNOSTIC_NAMES = {
    "w": "width",
    "h": "height",
    "fmt": "pixel_format_bits_per_channel",
    "cmd": "command_us",
    "pre": "prepare_us",
    "clr": "clear_us",
    "xf": "transform_us",
    "ts": "triangle_setup_us",
    "ras": "raster_us",
    "out": "output_finalize_us",
    "ob": "objects",
    "ti": "triangles_submitted",
    "tz": "triangles_z_rejected",
    "tfr": "triangles_frustum_rejected",
    "tf": "triangles_backface_rejected",
    "td": "triangles_degenerate",
    "to": "triangles_bbox_rejected",
    "tr": "triangles_rasterized",
    "tv": "triangles_bbox_clamped",
    "pt": "fragments_bbox",
    "pc": "fragments_covered",
    "pz": "fragments_depth_range_rejected",
    "pd": "fragments_depth_test_rejected",
    "pu": "fragments_reciprocal_w_rejected",
    "ps": "fragments_shaded",
}


@dataclass(frozen=True)
class MalformedDiagnostics:
    message: str


DiagnosticData = dict[str, int] | MalformedDiagnostics | None
RenderRecord = tuple[int, int | None, int, DiagnosticData]


def parse_diagnostics(tail: str) -> dict[str, int] | None:
    tokens = tail.split()
    if not tokens:
        return None
    if not any(token == "d" or token.startswith("d=") for token in tokens):
        return None

    fields: dict[str, int] = {}
    for token in tokens:
        if token.count("=") != 1:
            raise ValueError(f"malformed diagnostic token: {token!r}")
        key, value = token.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9]*", key):
            raise ValueError(f"invalid diagnostic key: {key!r}")
        if key in fields:
            raise ValueError(f"duplicate diagnostic key: {key}")
        if not value.isdecimal():
            raise ValueError(
                f"diagnostic value for {key} is not an unsigned integer"
            )
        fields[key] = int(value)

    version = fields.get("d")
    if version not in DIAGNOSTIC_KEYS_BY_VERSION:
        raise ValueError(f"unsupported diagnostic schema version {version}")
    expected_keys = set(DIAGNOSTIC_KEYS_BY_VERSION[version])
    missing = expected_keys - fields.keys()
    unknown = fields.keys() - expected_keys
    if missing:
        raise ValueError(
            "diagnostic record is missing fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ValueError(
            "diagnostic record has unknown fields: " + ", ".join(sorted(unknown))
        )
    if fields["w"] <= 0 or fields["h"] <= 0:
        raise ValueError("diagnostic dimensions must be positive")
    if fields["fmt"] not in (2, 8):
        raise ValueError("diagnostic fmt must be 2 (RGBA2222) or 8 (RGBA8888)")
    if fields["ti"] != (
        fields["tz"]
        + fields.get("tfr", 0)
        + fields["tf"]
        + fields["td"]
        + fields["to"]
        + fields["tr"]
    ):
        raise ValueError("diagnostic triangle counters violate their partition")
    if fields["pc"] != fields["pz"] + fields["pd"] + fields["pu"] + fields["ps"]:
        raise ValueError("diagnostic covered-fragment counters violate their partition")
    if fields["pc"] > fields["pt"]:
        raise ValueError("diagnostic covered fragments exceed bounding-box fragments")
    return fields


def parse_records(text: str) -> list[RenderRecord]:
    records: list[RenderRecord] = []
    for match in EXTENDED_RECORD_RE.finditer(text):
        sequence, bmid, duration, tail = match.groups()
        try:
            diagnostics: DiagnosticData = parse_diagnostics(tail)
        except ValueError as exc:
            # Run selection is based on the stable legacy fields. Preserve a
            # malformed diagnostic tail so an interrupted earlier run can be
            # ignored while a malformed record in the selected run still
            # fails loudly.
            diagnostics = MalformedDiagnostics(str(exc))
        records.append(
            (
                int(sequence),
                int(bmid) if bmid else None,
                int(duration),
                diagnostics,
            )
        )
    return records


def percentile_nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def latest_run(
    records: list[RenderRecord],
    warmup_count: int,
    measured_count: int,
    warmup_bmid: int,
    measured_bmid: int,
    series_runs: int = 1,
) -> list[RenderRecord]:
    frames_per_series = warmup_count + measured_count
    expected = frames_per_series * series_runs
    has_bitmap_ids = any(bmid is not None for _, bmid, _, _ in records)
    if not has_bitmap_ids and len(records) != expected:
        raise ValueError(
            "legacy records have no bitmap IDs and the log does not contain "
            f"exactly one {expected}-frame run; mixed captures are ambiguous"
        )
    for start in range(len(records) - expected, -1, -1):
        candidate = records[start : start + expected]
        sequences = [sequence for sequence, _, _, _ in candidate]
        first = sequences[0]
        wanted = [
            (first + offset) & 0xFFFFFFFF
            for offset in range(expected)
        ]
        if sequences != wanted:
            continue
        if has_bitmap_ids:
            bitmap_ids = [bmid for _, bmid, _, _ in candidate]
            series_ids = (
                [warmup_bmid] * warmup_count
                + [measured_bmid] * measured_count
            )
            wanted_ids = series_ids * series_runs
            if bitmap_ids != wanted_ids:
                continue
        elif first % expected != 0:
            # Compatibility for captures made before bitmap IDs were logged.
            continue
        if sequences == wanted:
            return candidate
    raise ValueError(f"no complete contiguous run of {expected} records found")


def selected_diagnostics(
    run: list[RenderRecord],
    require_diagnostics: bool,
) -> list[dict[str, int]] | None:
    for sequence, _, _, diagnostics in run:
        if isinstance(diagnostics, MalformedDiagnostics):
            raise ValueError(
                f"selected run has malformed diagnostics at seq={sequence}: "
                f"{diagnostics.message}"
            )

    diagnostics = [item for _, _, _, item in run]
    has_diagnostics = any(isinstance(item, dict) for item in diagnostics)
    if has_diagnostics and not all(isinstance(item, dict) for item in diagnostics):
        raise ValueError("selected run mixes diagnostic and ordinary records")
    if require_diagnostics and not has_diagnostics:
        raise ValueError("selected run has no renderer diagnostics")
    if not has_diagnostics:
        return None
    return [item for item in diagnostics if isinstance(item, dict)]


def expected_diagnostic_identity(
    profile: dict[str, Any],
) -> tuple[int, int, int]:
    resolution = profile.get("resolution")
    if not isinstance(resolution, list) or len(resolution) != 2:
        raise ValueError(
            "diagnostic profile must declare a two-element resolution"
        )
    width, height = (int(value) for value in resolution)
    if width <= 0 or height <= 0:
        raise ValueError("diagnostic profile resolution must be positive")

    target_formats = {
        "rgba2222": 2,
        "rgba8888": 8,
    }
    target_format = profile.get("target_format")
    if target_format not in target_formats:
        raise ValueError(
            "diagnostic profile target_format must be rgba2222 or rgba8888"
        )
    return width, height, target_formats[target_format]


def timing_residuals(
    sequence: int,
    render_us: int,
    diagnostics: dict[str, int],
) -> tuple[int, int]:
    renderer_residual_us = render_us - sum(
        diagnostics[key] for key in ("clr", "xf", "ts", "ras")
    )
    command_residual_us = diagnostics["cmd"] - (
        diagnostics["pre"] + render_us + diagnostics["out"]
    )
    if renderer_residual_us < -TIMING_RESIDUAL_TOLERANCE_US:
        raise ValueError(
            f"diagnostic renderer phases exceed render_us by "
            f"{-renderer_residual_us} us at seq={sequence}"
        )
    if command_residual_us < -TIMING_RESIDUAL_TOLERANCE_US:
        raise ValueError(
            f"diagnostic command phases exceed command_us by "
            f"{-command_residual_us} us at seq={sequence}"
        )
    return renderer_residual_us, command_residual_us


def build_summary(
    profile: dict[str, Any],
    records: list[RenderRecord],
    *,
    platform: str = "unknown",
    firmware: str = "unknown",
    require_diagnostics: bool = False,
) -> dict[str, Any]:
    warmup_count = int(profile["warmup_frames"])
    measured_count = int(profile["measured_frames"])
    series_runs = int(profile.get("series_runs", 1))
    if measured_count <= 0 or warmup_count < 0:
        raise ValueError(
            "benchmark frame counts must be non-negative and "
            "measured_frames positive"
        )
    if not 1 <= series_runs <= 255:
        raise ValueError("series_runs must be between 1 and 255")
    measured_bmid = int(profile.get("target_bitmap_id", 257))
    warmup_bmid = int(profile.get("warmup_target_bitmap_id", measured_bmid))
    run = latest_run(
        records,
        warmup_count,
        measured_count,
        warmup_bmid,
        measured_bmid,
        series_runs,
    )
    frames_per_series = warmup_count + measured_count
    measured_indexes = [
        series * frames_per_series + offset
        for series in range(series_runs)
        for offset in range(warmup_count, frames_per_series)
    ]
    measured = [run[index] for index in measured_indexes]
    run_diagnostics = selected_diagnostics(run, require_diagnostics)

    run_residuals: list[tuple[int, int]] | None = None
    if run_diagnostics is not None:
        schema_versions = {item["d"] for item in run_diagnostics}
        if len(schema_versions) != 1:
            raise ValueError("selected diagnostic run changes schema version")
        identities = {
            (item["w"], item["h"], item["fmt"])
            for item in run_diagnostics
        }
        if len(identities) != 1:
            raise ValueError(
                "selected diagnostic run changes dimensions or pixel format"
            )
        observed_identity = next(iter(identities))
        expected_identity = expected_diagnostic_identity(profile)
        if observed_identity != expected_identity:
            raise ValueError(
                "selected diagnostic run identity "
                f"{observed_identity[0]}x{observed_identity[1]} "
                f"RGBA{observed_identity[2]} does not match profile "
                f"{expected_identity[0]}x{expected_identity[1]} "
                f"RGBA{expected_identity[2]}"
            )
        run_residuals = [
            timing_residuals(sequence, duration, diagnostics)
            for (sequence, _, duration, _), diagnostics
            in zip(run, run_diagnostics, strict=True)
        ]

    durations = [duration for _, _, duration, _ in measured]
    frames = []
    for index, (_, _, duration, _) in enumerate(measured):
        frame_in_series = index % measured_count
        frame = {
            "series": index // measured_count,
            "frame": frame_in_series,
            "render_us": duration,
        }
        if "frames_per_orbit" in profile:
            orbit_degrees = (
                frame_in_series * 360.0 / int(profile["frames_per_orbit"])
            )
            frame["orbit_angle_deg"] = orbit_degrees
            frame["orbit_revolution"] = orbit_degrees / 360.0
        else:
            step = int(profile["rotation_step_degrees"])
            angle_degrees = frame_in_series * step
            frame["angle_deg"] = angle_degrees
            translation = motion_translation(profile, angle_degrees)
            if translation is not None:
                frame["translation_words"] = list(translation)
        frames.append(frame)

    if run_diagnostics is not None and run_residuals is not None:
        measured_diagnostics = [
            run_diagnostics[index] for index in measured_indexes
        ]
        measured_residuals = [
            run_residuals[index] for index in measured_indexes
        ]
        for frame, diagnostics, residuals in zip(
            frames,
            measured_diagnostics,
            measured_residuals,
            strict=True,
        ):
            frame["diagnostics"] = {
                DIAGNOSTIC_NAMES[key]: value
                for key, value in diagnostics.items()
                if key != "d"
            }
            renderer_residual_us, command_residual_us = residuals
            frame["diagnostics"].update(
                {
                    "renderer_residual_us": renderer_residual_us,
                    "command_residual_us": command_residual_us,
                }
            )

    mean = statistics.fmean(durations)
    series_summaries = []
    for series in range(series_runs):
        start = series * measured_count
        series_durations = durations[start : start + measured_count]
        series_mean = statistics.fmean(series_durations)
        series_summaries.append(
            {
                "series": series,
                "minimum_render_us": min(series_durations),
                "maximum_render_us": max(series_durations),
                "mean_render_us": series_mean,
                "median_render_us": statistics.median(series_durations),
                "population_stdev_us": statistics.pstdev(series_durations),
                "p95_render_us": percentile_nearest_rank(
                    series_durations, 0.95
                ),
                "equivalent_mean_fps": 1_000_000 / series_mean,
            }
        )
    summary = {
        "profile": profile["name"],
        "texture_format": profile.get("texture_format", "unknown"),
        "target_format": profile.get("target_format", "unknown"),
        "platform": platform,
        "firmware": firmware,
        "timing_scope": "rendererRender only",
        "warmup_target_bitmap_id": warmup_bmid,
        "target_bitmap_id": measured_bmid,
        "render_sequence_start": run[0][0],
        "render_sequence_end": run[-1][0],
        "series_runs": series_runs,
        "warmup_frames_per_series": warmup_count,
        "measured_frames_per_series": measured_count,
        "warmup_frames": warmup_count * series_runs,
        "measured_frames": measured_count * series_runs,
        "total_render_us": sum(durations),
        "minimum_render_us": min(durations),
        "maximum_render_us": max(durations),
        "mean_render_us": mean,
        "median_render_us": statistics.median(durations),
        "population_stdev_us": statistics.pstdev(durations),
        "p95_render_us": percentile_nearest_rank(durations, 0.95),
        "equivalent_mean_fps": 1_000_000 / mean,
        "series": series_summaries,
        "frames": frames,
    }

    if run_diagnostics is not None and run_residuals is not None:
        measured_diagnostics = [
            run_diagnostics[index] for index in measured_indexes
        ]
        measured_residuals = [
            run_residuals[index] for index in measured_indexes
        ]
        timing_keys = ("cmd", "pre", "clr", "xf", "ts", "ras", "out")
        timing_totals = {
            key: sum(item[key] for item in measured_diagnostics)
            for key in timing_keys
        }
        schema_version = measured_diagnostics[0]["d"]
        counter_keys = [
            "ob",
            "ti",
            "tz",
            "tf",
            "td",
            "to",
            "tr",
            "tv",
            "pt",
            "pc",
            "pz",
            "pd",
            "pu",
            "ps",
        ]
        if schema_version >= 2:
            counter_keys.insert(3, "tfr")
        counter_totals = {
            key: sum(item[key] for item in measured_diagnostics)
            for key in counter_keys
        }
        total_renderer_us = sum(durations)
        attributed_renderer_us = sum(
            timing_totals[key] for key in ("clr", "xf", "ts", "ras")
        )
        renderer_residual_values = [
            renderer for renderer, _ in measured_residuals
        ]
        command_residual_values = [
            command for _, command in measured_residuals
        ]
        renderer_residual_us = total_renderer_us - attributed_renderer_us
        command_residual_us = (
            timing_totals["cmd"]
            - timing_totals["pre"]
            - total_renderer_us
            - timing_totals["out"]
        )
        renderer_unattributed_us = sum(
            max(value, 0) for value in renderer_residual_values
        )
        renderer_rounding_overage_us = sum(
            max(-value, 0) for value in renderer_residual_values
        )
        command_unattributed_us = sum(
            max(value, 0) for value in command_residual_values
        )
        command_rounding_overage_us = sum(
            max(-value, 0) for value in command_residual_values
        )
        width, height, pixel_format = expected_diagnostic_identity(profile)

        def share(value: int, denominator: int) -> float:
            return value / denominator if denominator else 0.0

        summary["renderer_diagnostics"] = {
            "schema_version": schema_version,
            "measurement_warning": (
                "Instrumented timings and counters are attribution data; "
                "compare ordinary firmware for release performance."
            ),
            "command_scope": (
                "valid Pingo command 38 entry through target bitmap ready; "
                "later display/flip commands are excluded"
            ),
            "width": width,
            "height": height,
            "pixel_format_bits_per_channel": pixel_format,
            "timing_residual_tolerance_us_per_frame": (
                TIMING_RESIDUAL_TOLERANCE_US
            ),
            "timing_totals_us": {
                DIAGNOSTIC_NAMES[key]: value
                for key, value in timing_totals.items()
            },
            "timing_means_us": {
                DIAGNOSTIC_NAMES[key]: value / len(measured)
                for key, value in timing_totals.items()
            },
            "renderer_residual_us": renderer_residual_us,
            "renderer_unattributed_us": renderer_unattributed_us,
            "renderer_rounding_overage_us": renderer_rounding_overage_us,
            "command_residual_us": command_residual_us,
            "command_unattributed_us": command_unattributed_us,
            "command_rounding_overage_us": command_rounding_overage_us,
            "renderer_phase_shares": {
                "clear": share(timing_totals["clr"], total_renderer_us),
                "transform": share(timing_totals["xf"], total_renderer_us),
                "triangle_setup": share(timing_totals["ts"], total_renderer_us),
                "raster": share(timing_totals["ras"], total_renderer_us),
                "unattributed": share(
                    renderer_unattributed_us, total_renderer_us
                ),
                "rounding_overage": share(
                    renderer_rounding_overage_us, total_renderer_us
                ),
            },
            "command_phase_shares": {
                "prepare": share(
                    timing_totals["pre"], timing_totals["cmd"]
                ),
                "renderer": share(
                    total_renderer_us, timing_totals["cmd"]
                ),
                "output_finalize": share(
                    timing_totals["out"], timing_totals["cmd"]
                ),
                "unattributed": share(
                    command_unattributed_us, timing_totals["cmd"]
                ),
                "rounding_overage": share(
                    command_rounding_overage_us, timing_totals["cmd"]
                ),
            },
            "counter_totals": {
                DIAGNOSTIC_NAMES[key]: value
                for key, value in counter_totals.items()
            },
            "triangle_outcome_ratios": {
                "z_rejected": share(
                    counter_totals["tz"], counter_totals["ti"]
                ),
                "backface_rejected": share(
                    counter_totals["tf"], counter_totals["ti"]
                ),
                "degenerate": share(
                    counter_totals["td"], counter_totals["ti"]
                ),
                "bbox_rejected": share(
                    counter_totals["to"], counter_totals["ti"]
                ),
                "rasterized": share(
                    counter_totals["tr"], counter_totals["ti"]
                ),
            },
            "bbox_clamped_triangle_ratio": share(
                counter_totals["tv"], counter_totals["ti"]
            ),
            "coverage_ratio": share(
                counter_totals["pc"], counter_totals["pt"]
            ),
            "depth_range_reject_ratio": share(
                counter_totals["pz"], counter_totals["pc"]
            ),
            "depth_test_reject_ratio": share(
                counter_totals["pd"], counter_totals["pc"]
            ),
            "reciprocal_w_reject_ratio": share(
                counter_totals["pu"], counter_totals["pc"]
            ),
            "shade_ratio": share(
                counter_totals["ps"], counter_totals["pc"]
            ),
        }
        if schema_version >= 2:
            summary["renderer_diagnostics"]["triangle_outcome_ratios"][
                "frustum_rejected"
            ] = share(counter_totals["tfr"], counter_totals["ti"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "log",
        nargs="?",
        type=Path,
        help="captured console log; stdin when omitted",
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--platform", choices=("hardware", "emulator", "unknown"), default="unknown")
    parser.add_argument("--firmware", default="unknown")
    parser.add_argument(
        "--series-runs",
        type=int,
        help=(
            "override profile series_runs; use 1 when re-parsing a "
            "historical single-series capture"
        ),
    )
    parser.add_argument(
        "--require-diagnostics",
        action="store_true",
        help="reject a selected run without a complete supported diagnostic schema",
    )
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    if args.series_runs is not None:
        profile["series_runs"] = args.series_runs
    text = args.log.read_text(encoding="utf-8", errors="replace") if args.log else sys.stdin.read()
    records = parse_records(text)
    summary = build_summary(
        profile,
        records,
        platform=args.platform,
        firmware=args.firmware,
        require_diagnostics=args.require_diagnostics,
    )

    print(
        f"Profile: {summary['profile']} ({summary['platform']}, "
        f"{summary['texture_format']} texture -> {summary['target_format']} target)"
    )
    print(
        f"Series: {summary['series_runs']}; "
        f"{summary['measured_frames_per_series']} measured after "
        f"{summary['warmup_frames_per_series']} warmups per series "
        f"({summary['measured_frames']} measured total)"
    )
    mean = summary["mean_render_us"]
    print(f"Mean: {mean:.1f} us ({summary['equivalent_mean_fps']:.2f} equivalent FPS)")
    if summary["series_runs"] > 1:
        series_means = ", ".join(
            f"{item['series'] + 1}: {item['mean_render_us']:.1f}"
            for item in summary["series"]
        )
        print(f"Series means (us): {series_means}")
    print(
        f"Min/median/p95/max: {summary['minimum_render_us']} / "
        f"{summary['median_render_us']:.1f} / {summary['p95_render_us']} / "
        f"{summary['maximum_render_us']} us"
    )
    print(f"Total renderer time: {summary['total_render_us']} us")
    if "renderer_diagnostics" in summary:
        diagnostics = summary["renderer_diagnostics"]
        phase_shares = diagnostics["renderer_phase_shares"]
        print(
            "Renderer attribution: "
            f"clear {phase_shares['clear']:.1%}, "
            f"transform {phase_shares['transform']:.1%}, "
            f"triangle setup {phase_shares['triangle_setup']:.1%}, "
            f"raster {phase_shares['raster']:.1%}, "
            f"unattributed {phase_shares['unattributed']:.1%}"
        )
        print(
            "Fragment ratios: "
            f"coverage {diagnostics['coverage_ratio']:.1%}, "
            f"depth-range reject "
            f"{diagnostics['depth_range_reject_ratio']:.1%}, "
            f"depth-test reject "
            f"{diagnostics['depth_test_reject_ratio']:.1%}, "
            f"reciprocal-W reject "
            f"{diagnostics['reciprocal_w_reject_ratio']:.1%}, "
            f"shaded {diagnostics['shade_ratio']:.1%}"
        )
        triangle_ratios = diagnostics["triangle_outcome_ratios"]
        outcomes = [
            f"near/camera {triangle_ratios['z_rejected']:.1%}",
        ]
        if "frustum_rejected" in triangle_ratios:
            outcomes.append(
                f"frustum {triangle_ratios['frustum_rejected']:.1%}"
            )
        outcomes.extend(
            (
                f"backface {triangle_ratios['backface_rejected']:.1%}",
                f"degenerate {triangle_ratios['degenerate']:.1%}",
                f"bbox {triangle_ratios['bbox_rejected']:.1%}",
                f"rasterized {triangle_ratios['rasterized']:.1%}",
            )
        )
        print(
            f"Triangle outcomes (schema {diagnostics['schema_version']}): "
            + ", ".join(outcomes)
        )
    if args.json_output:
        args.json_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
