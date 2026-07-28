#!/usr/bin/env python3
"""Validate and summarize PINGO_RENDER records using a benchmark profile."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path


RECORD_RE = re.compile(
    r"PINGO_RENDER\s+seq=(\d+)(?:\s+bmid=(\d+))?\s+render_us=(\d+)"
)


def percentile_nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def latest_run(
    records: list[tuple[int, int | None, int]],
    warmup_count: int,
    measured_count: int,
    warmup_bmid: int,
    measured_bmid: int,
) -> list[tuple[int, int | None, int]]:
    expected = warmup_count + measured_count
    has_bitmap_ids = any(bmid is not None for _, bmid, _ in records)
    if not has_bitmap_ids and len(records) != expected:
        raise ValueError(
            "legacy records have no bitmap IDs and the log does not contain "
            f"exactly one {expected}-frame run; mixed captures are ambiguous"
        )
    for start in range(len(records) - expected, -1, -1):
        candidate = records[start : start + expected]
        sequences = [sequence for sequence, _, _ in candidate]
        first = sequences[0]
        wanted = [
            (first + offset) & 0xFFFFFFFF
            for offset in range(expected)
        ]
        if sequences != wanted:
            continue
        if has_bitmap_ids:
            bitmap_ids = [bmid for _, bmid, _ in candidate]
            wanted_ids = (
                [warmup_bmid] * warmup_count
                + [measured_bmid] * measured_count
            )
            if bitmap_ids != wanted_ids:
                continue
        elif first % expected != 0:
            # Compatibility for captures made before bitmap IDs were logged.
            continue
        if sequences == wanted:
            return candidate
    raise ValueError(f"no complete contiguous run of {expected} records found")


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
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    text = args.log.read_text(encoding="utf-8", errors="replace") if args.log else sys.stdin.read()
    records = [
        (int(seq), int(bmid) if bmid else None, int(duration))
        for seq, bmid, duration in RECORD_RE.findall(text)
    ]
    warmup_count = int(profile["warmup_frames"])
    measured_count = int(profile["measured_frames"])
    expected = warmup_count + measured_count
    measured_bmid = int(profile.get("target_bitmap_id", 257))
    warmup_bmid = int(profile.get("warmup_target_bitmap_id", measured_bmid))
    run = latest_run(
        records,
        warmup_count,
        measured_count,
        warmup_bmid,
        measured_bmid,
    )
    warmups = run[:warmup_count]
    measured = run[warmup_count:]
    durations = [duration for _, _, duration in measured]
    step = int(profile["rotation_step_degrees"])
    frames = [
        {
            "frame": index,
            "angle_deg": index * step,
            "render_us": duration,
        }
        for index, (_, _, duration) in enumerate(measured)
    ]
    mean = statistics.fmean(durations)
    summary = {
        "profile": profile["name"],
        "texture_format": profile.get("texture_format", "unknown"),
        "target_format": profile.get("target_format", "unknown"),
        "platform": args.platform,
        "firmware": args.firmware,
        "timing_scope": "rendererRender only",
        "warmup_target_bitmap_id": warmup_bmid,
        "target_bitmap_id": measured_bmid,
        "render_sequence_start": run[0][0],
        "render_sequence_end": run[-1][0],
        "warmup_frames": warmup_count,
        "measured_frames": measured_count,
        "total_render_us": sum(durations),
        "minimum_render_us": min(durations),
        "maximum_render_us": max(durations),
        "mean_render_us": mean,
        "median_render_us": statistics.median(durations),
        "population_stdev_us": statistics.pstdev(durations),
        "p95_render_us": percentile_nearest_rank(durations, 0.95),
        "equivalent_mean_fps": 1_000_000 / mean,
        "frames": frames,
    }

    print(
        f"Profile: {summary['profile']} ({args.platform}, "
        f"{summary['texture_format']} texture -> {summary['target_format']} target)"
    )
    print(f"Frames: {measured_count} measured after {warmup_count} warmups")
    print(f"Mean: {mean:.1f} us ({summary['equivalent_mean_fps']:.2f} equivalent FPS)")
    print(
        f"Min/median/p95/max: {summary['minimum_render_us']} / "
        f"{summary['median_render_us']:.1f} / {summary['p95_render_us']} / "
        f"{summary['maximum_render_us']} us"
    )
    print(f"Total renderer time: {summary['total_render_us']} us")
    if args.json_output:
        args.json_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
