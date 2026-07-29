#!/usr/bin/env python3
"""Compare two Pingo firmware versions using the chained hardware fixture."""

from __future__ import annotations

import argparse
import html
import re
import statistics
from dataclasses import dataclass
from pathlib import Path


RECORD_RE = re.compile(
    rb"PINGO_RENDER\s+seq=(\d+)\s+bmid=(\d+)\s+render_us=(\d+)"
)


@dataclass(frozen=True)
class Fixture:
    name: str
    bitmap_id: int
    first_sequence: int
    last_sequence: int

    @property
    def frame_count(self) -> int:
        return self.last_sequence - self.first_sequence + 1


FIXTURES = (
    Fixture("Cube", 1257, 0, 35),
    Fixture("HeavyTank", 1257, 36, 71),
    Fixture("EarthUV", 1257, 72, 107),
    Fixture("Earth party ellipse", 1410, 0, 288),
    Fixture("Cube near-plane", 1257, 108, 180),
    Fixture("EarthUV near-plane", 1257, 181, 253),
    Fixture("Jet near-plane", 1257, 254, 326),
    Fixture("Airliner near-plane", 1257, 327, 399),
    Fixture("EarthIco", 1257, 400, 435),
    Fixture("Lara", 1257, 436, 471),
    Fixture("Crash", 1257, 472, 507),
    Fixture("Jet", 1257, 508, 543),
    Fixture("Airliner", 1257, 544, 579),
    Fixture("Earth party", 1410, 289, 577),
    Fixture("Earth party dolly", 1410, 578, 866),
)

EXPECTED_LAST_SEQUENCE = {1257: 579, 1410: 866}


@dataclass(frozen=True)
class Result:
    name: str
    baseline_us: float
    candidate_us: float
    baseline_fps: float
    candidate_fps: float
    fps_gain_percent: float
    render_change_percent: float
    baseline_spread_us: float
    candidate_spread_us: float


def parse_complete_runs(path: Path) -> dict[int, list[list[int]]]:
    runs: dict[int, list[list[int]]] = {
        bitmap_id: [] for bitmap_id in EXPECTED_LAST_SEQUENCE
    }
    active: dict[int, list[tuple[int, int]] | None] = {
        bitmap_id: None for bitmap_id in EXPECTED_LAST_SEQUENCE
    }

    for match in RECORD_RE.finditer(path.read_bytes()):
        sequence, bitmap_id, render_us = map(int, match.groups())
        if bitmap_id not in active:
            continue
        if sequence == 0:
            active[bitmap_id] = []
        run = active[bitmap_id]
        if run is None:
            continue
        if run and sequence != run[-1][0] + 1:
            active[bitmap_id] = None
            continue
        run.append((sequence, render_us))
        if sequence == EXPECTED_LAST_SEQUENCE[bitmap_id]:
            runs[bitmap_id].append([value for _, value in run])
            active[bitmap_id] = None

    missing = [
        str(bitmap_id) for bitmap_id, complete in runs.items() if not complete
    ]
    if missing:
        raise ValueError(
            f"{path}: no complete run for bitmap stream(s) {', '.join(missing)}"
        )
    return runs


def fixture_run_means(
    runs: dict[int, list[list[int]]], fixture: Fixture
) -> list[float]:
    return [
        statistics.mean(
            run[fixture.first_sequence : fixture.last_sequence + 1]
        )
        for run in runs[fixture.bitmap_id]
    ]


def compare(
    baseline: dict[int, list[list[int]]],
    candidate: dict[int, list[list[int]]],
) -> list[Result]:
    results = []
    for fixture in FIXTURES:
        baseline_means = fixture_run_means(baseline, fixture)
        candidate_means = fixture_run_means(candidate, fixture)
        baseline_us = statistics.mean(baseline_means)
        candidate_us = statistics.mean(candidate_means)
        baseline_fps = 1_000_000.0 / baseline_us
        candidate_fps = 1_000_000.0 / candidate_us
        results.append(
            Result(
                name=fixture.name,
                baseline_us=baseline_us,
                candidate_us=candidate_us,
                baseline_fps=baseline_fps,
                candidate_fps=candidate_fps,
                fps_gain_percent=(candidate_fps / baseline_fps - 1.0) * 100.0,
                render_change_percent=(candidate_us / baseline_us - 1.0) * 100.0,
                baseline_spread_us=max(baseline_means) - min(baseline_means),
                candidate_spread_us=max(candidate_means) - min(candidate_means),
            )
        )

    def complete_suite_means(
        runs: dict[int, list[list[int]]],
    ) -> list[float]:
        run_count = min(len(stream_runs) for stream_runs in runs.values())
        means = []
        for run_index in range(run_count):
            values = []
            for fixture in FIXTURES:
                run = runs[fixture.bitmap_id][run_index]
                values.extend(
                    run[fixture.first_sequence : fixture.last_sequence + 1]
                )
            means.append(statistics.mean(values))
        return means

    baseline_means = complete_suite_means(baseline)
    candidate_means = complete_suite_means(candidate)
    baseline_us = statistics.mean(baseline_means)
    candidate_us = statistics.mean(candidate_means)
    baseline_fps = 1_000_000.0 / baseline_us
    candidate_fps = 1_000_000.0 / candidate_us
    results.append(
        Result(
            name="All frames (weighted)",
            baseline_us=baseline_us,
            candidate_us=candidate_us,
            baseline_fps=baseline_fps,
            candidate_fps=candidate_fps,
            fps_gain_percent=(candidate_fps / baseline_fps - 1.0) * 100.0,
            render_change_percent=(candidate_us / baseline_us - 1.0) * 100.0,
            baseline_spread_us=max(baseline_means) - min(baseline_means),
            candidate_spread_us=max(candidate_means) - min(candidate_means),
        )
    )
    return results


def print_table(
    results: list[Result], baseline_label: str, candidate_label: str
) -> None:
    headings = (
        "Fixture",
        f"{baseline_label} FPS",
        f"{candidate_label} FPS",
        "FPS gain",
        "Render-time change",
    )
    rows = [
        (
            result.name,
            f"{result.baseline_fps:.2f}",
            f"{result.candidate_fps:.2f}",
            f"{result.fps_gain_percent:+.2f}%",
            f"{result.render_change_percent:+.2f}%",
        )
        for result in results
    ]
    widths = [
        max(len(headings[index]), *(len(row[index]) for row in rows))
        for index in range(len(headings))
    ]
    print(
        "  ".join(
            heading.ljust(widths[index])
            for index, heading in enumerate(headings)
        )
    )
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(
            "  ".join(
                value.ljust(widths[index])
                for index, value in enumerate(row)
            )
        )


def html_report(
    results: list[Result], baseline_label: str, candidate_label: str
) -> str:
    maximum_fps = max(
        max(result.baseline_fps, result.candidate_fps) for result in results
    )
    chart_width = 1100
    label_width = 190
    plot_width = 830
    row_height = 42
    chart_height = 50 + len(results) * row_height
    bars = []
    for index, result in enumerate(results):
        y = 35 + index * row_height
        baseline_width = result.baseline_fps / maximum_fps * plot_width
        candidate_width = result.candidate_fps / maximum_fps * plot_width
        bars.extend(
            (
                f'<text x="0" y="{y + 13}" class="label">'
                f"{html.escape(result.name)}</text>",
                f'<rect x="{label_width}" y="{y}" width="{baseline_width:.2f}" '
                'height="14" class="baseline"/>',
                f'<text x="{label_width + baseline_width + 6:.2f}" '
                f'y="{y + 12}" class="value">{result.baseline_fps:.2f}</text>',
                f'<rect x="{label_width}" y="{y + 17}" '
                f'width="{candidate_width:.2f}" height="14" class="candidate"/>',
                f'<text x="{label_width + candidate_width + 6:.2f}" '
                f'y="{y + 29}" class="value">{result.candidate_fps:.2f}</text>',
            )
        )

    table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(result.name)}</td>"
        f"<td>{result.baseline_fps:.3f}</td>"
        f"<td>{result.candidate_fps:.3f}</td>"
        f"<td>{result.fps_gain_percent:+.2f}%</td>"
        f"<td>{result.baseline_us / 1000.0:.3f}</td>"
        f"<td>{result.candidate_us / 1000.0:.3f}</td>"
        f"<td>{result.render_change_percent:+.2f}%</td>"
        f"<td>{result.baseline_spread_us / 1000.0:.3f}</td>"
        f"<td>{result.candidate_spread_us / 1000.0:.3f}</td>"
        "</tr>"
        for result in results
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pingo firmware performance comparison</title>
<style>
body {{ background:#10141b; color:#e7edf5; font:16px system-ui,sans-serif;
       margin:2rem auto; max-width:1200px; padding:0 1rem; }}
h1,h2 {{ color:#fff; }}
.legend {{ display:flex; gap:1.5rem; margin:1rem 0; }}
.swatch {{ display:inline-block; width:1em; height:1em; margin-right:.4rem; }}
.baseline {{ fill:#718096; }} .candidate {{ fill:#38b2ac; }}
.label,.value {{ fill:#e7edf5; font:13px system-ui,sans-serif; }}
svg {{ width:100%; height:auto; background:#171d27; padding:1rem; }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
th,td {{ border-bottom:1px solid #344052; padding:.55rem; text-align:right; }}
th:first-child,td:first-child {{ text-align:left; }}
th {{ position:sticky; top:0; background:#171d27; }}
</style>
</head>
<body>
<h1>Pingo firmware performance comparison</h1>
<p>Equivalent FPS is 1,000,000 divided by mean renderer microseconds.
Higher FPS is better.</p>
<div class="legend">
<span><i class="swatch baseline"></i>{html.escape(baseline_label)}</span>
<span><i class="swatch candidate"></i>{html.escape(candidate_label)}</span>
</div>
<svg viewBox="0 0 {chart_width} {chart_height}" role="img"
 aria-label="Frames per second by fixture">
{''.join(bars)}
</svg>
<h2>Measurements</h2>
<table>
<thead><tr><th>Fixture</th>
<th>{html.escape(baseline_label)} FPS</th>
<th>{html.escape(candidate_label)} FPS</th>
<th>FPS gain</th>
<th>{html.escape(baseline_label)} ms</th>
<th>{html.escape(candidate_label)} ms</th>
<th>Render-time change</th>
<th>{html.escape(baseline_label)} run spread ms</th>
<th>{html.escape(candidate_label)} run spread ms</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two firmware versions using complete runs from the "
            "canonical 1,447-frame chained Pingo fixture."
        )
    )
    parser.add_argument("baseline_log", type=Path)
    parser.add_argument("candidate_log", type=Path)
    parser.add_argument("--baseline-label", default="Baseline")
    parser.add_argument("--candidate-label", default="Candidate")
    parser.add_argument("--html-output", type=Path)
    args = parser.parse_args()

    baseline = parse_complete_runs(args.baseline_log)
    candidate = parse_complete_runs(args.candidate_log)
    results = compare(baseline, candidate)
    print_table(results, args.baseline_label, args.candidate_label)

    if args.html_output:
        args.html_output.write_text(
            html_report(results, args.baseline_label, args.candidate_label),
            encoding="utf-8",
        )
        print(f"\nWrote {args.html_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
