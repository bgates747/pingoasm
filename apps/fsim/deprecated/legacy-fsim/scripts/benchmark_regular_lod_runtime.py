#!/usr/bin/env python3
"""Benchmark the accepted regular-LOD runtime in three isolated processes.

The stationary capture measures cold publication and 300 mutation-free render
frames.  The ordinary staged trace measures four adjacent-cell handoffs.  A
separate debugger-paused trace measures only selector guest cycles; its host
render timings are deliberately excluded.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import capture_koak_flight as capture
import capture_terrain_manager_survey as survey
import trace_regular_lod_staged_north_transitions as staged
from pingo_terrain.regular_lod_profile import (
    MeshReplaceRecord,
    ProfileEvidenceError,
    RenderRecord,
    parse_regular_lod_profile,
    parse_selector_cycle_pairs,
    summarize_distribution,
    summarize_render_window,
)


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "pingo-terrain-regular-lod-runtime-benchmark-v1"
REPORT_NAME = "regular-lod-runtime-benchmark.json"
STATIONARY_REPORT = "regular-lod-manager-survey-capture.json"
TRACE_REPORT = staged.REPORT_NAME
COLD_SEQUENCE = staged.COLD_SEQUENCE
STEADY_FIRST = COLD_SEQUENCE + 1
STEADY_FRAMES = 300
STEADY_LAST = STEADY_FIRST + STEADY_FRAMES - 1
EXPECTED_CROSSING_GROUPS = (29, 21, 17, 17)
RENDER_METRICS = (
    "render_us",
    "cmd",
    "pre",
    "clr",
    "xf",
    "ts",
    "ras",
    "out",
)
STRUCTURAL_FIELDS = ("ob", "obt", "ofr", "ti", "tr")
RADIUS_INPUT_RE = re.compile(
    r"FAB_INPUT [^\r\n]*\baction=down\b[^\r\n]*"
    r"\bscancode=0x0025\b[^\r\n]*\bsource=fifo-tap\b"
)


class BenchmarkError(ValueError):
    """A captured benchmark does not satisfy the accepted runtime contract."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--stationary-source",
        type=Path,
        help="reuse a completed 0/226/526 stationary capture directory",
    )
    parser.add_argument(
        "--handoff-source",
        type=Path,
        help="reuse a completed unprofiled four-crossing trace directory",
    )
    parser.add_argument(
        "--selector-source",
        type=Path,
        help="reuse a completed selector-profile four-crossing trace directory",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise BenchmarkError(f"missing benchmark artifact: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def checked_identity(report: dict, names: tuple[str, ...]) -> dict[str, dict]:
    result = {}
    for name in names:
        record = report.get(name)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise BenchmarkError(f"source report lacks {name} artifact path")
        actual = artifact(Path(record["path"]))
        if actual["sha256"] != record.get("sha256"):
            raise BenchmarkError(f"source report {name} artifact changed")
        result[name] = record
    return result


def load_report(
    directory: Path, name: str, expected_schema: str
) -> tuple[Path, dict, Path, str]:
    root = directory.expanduser().resolve()
    report_path = root / name
    log_path = root / "emulator.log"
    if not report_path.is_file() or not log_path.is_file():
        raise BenchmarkError(f"incomplete benchmark source: {root}")
    document = json.loads(report_path.read_text(encoding="utf-8"))
    if document.get("schema") != expected_schema:
        raise BenchmarkError(f"unexpected source schema: {report_path}")
    if document.get("qualified") is not True:
        raise BenchmarkError(f"source is not qualified: {report_path}")
    if document.get("log_sha256") != sha256(log_path):
        raise BenchmarkError(f"source log hash changed: {log_path}")
    return report_path, document, log_path, log_path.read_text(
        encoding="utf-8", errors="replace"
    )


def run_source(
    output: Path,
    name: str,
    source: Path | None,
    command: list[str],
    timeout: float,
) -> tuple[Path, dict[str, object]]:
    if source is not None:
        root = source.expanduser().resolve()
        if not root.is_dir():
            raise BenchmarkError(f"benchmark source is not a directory: {root}")
        return root, {"mode": "reused", "whole_process_wall_seconds": None}
    root = output / name
    started = time.perf_counter()
    try:
        subprocess.run(
            [*command, "--output", str(root), "--timeout", str(timeout)],
            cwd=ROOT,
            check=True,
            timeout=timeout + 30.0,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise BenchmarkError(f"{name} benchmark process failed") from error
    return root, {
        "mode": "captured",
        "whole_process_wall_seconds": time.perf_counter() - started,
    }


def validate_render(record: RenderRecord) -> None:
    if any(
        isinstance(value, int) and value < 0
        for _name, value in record.fields
    ):
        raise BenchmarkError(f"render seq {record.sequence} has a negative counter")
    if record.integer("d") != 4:
        raise BenchmarkError(f"render seq {record.sequence} changed diagnostics ABI")
    expected_presentation = {
        "bmid": 257,
        "w": 320,
        "h": 240,
        "fmt": 2,
        "far": 65_535,
    }
    for name, expected in expected_presentation.items():
        if record.integer(name) != expected:
            raise BenchmarkError(
                f"render seq {record.sequence} changed {name}: "
                f"{record.integer(name)} != {expected}"
            )
    if record.integer("ti") != sum(
        record.integer(name) for name in ("tz", "tfr", "tc", "tu")
    ):
        raise BenchmarkError(f"render seq {record.sequence} triangle input mismatch")
    if record.integer("tg") != sum(
        record.integer(name) for name in ("tp", "tf", "td", "to", "tr")
    ):
        raise BenchmarkError(f"render seq {record.sequence} triangle output mismatch")
    if not (
        record.integer("ofr") <= record.integer("obt") <= record.integer("ob")
    ):
        raise BenchmarkError(f"render seq {record.sequence} object counters mismatch")
    if record.integer("pc") != sum(
        record.integer(name) for name in ("pz", "pd", "pu", "ps")
    ) or record.integer("pc") > record.integer("pt"):
        raise BenchmarkError(f"render seq {record.sequence} pixel counters mismatch")
    if record.integer("render_us") < sum(
        record.integer(name) for name in ("clr", "xf", "ts", "ras")
    ):
        raise BenchmarkError(f"render seq {record.sequence} has impossible phase time")
    if record.integer("cmd") < sum(
        record.integer(name) for name in ("pre", "render_us", "out")
    ):
        raise BenchmarkError(f"render seq {record.sequence} has impossible command time")


def render_samples(records: list[RenderRecord]) -> dict[str, list[int]]:
    return {
        name: [record.integer(name) for record in records]
        for name in RENDER_METRICS
    }


def summarize_derived(records: list[RenderRecord]) -> dict[str, object]:
    renderer_unattributed = [
        record.integer("render_us")
        - sum(record.integer(name) for name in ("clr", "xf", "ts", "ras"))
        for record in records
    ]
    command_unattributed = [
        record.integer("cmd")
        - record.integer("pre")
        - record.integer("render_us")
        - record.integer("out")
        for record in records
    ]
    return {
        "renderer_unattributed_us": {
            "samples": renderer_unattributed,
            "summary": summarize_distribution(renderer_unattributed).as_dict(),
        },
        "command_unattributed_us": {
            "samples": command_unattributed,
            "summary": summarize_distribution(command_unattributed).as_dict(),
        },
    }


def analyze_stationary(directory: Path) -> dict[str, object]:
    report_path, report, log_path, contents = load_report(
        directory,
        STATIONARY_REPORT,
        "pingo-terrain-regular-lod-manager-survey-capture-v1",
    )
    if report.get("requested_sequences") != [0, COLD_SEQUENCE, STEADY_LAST]:
        raise BenchmarkError("stationary capture does not contain 300 steady frames")
    profile = parse_regular_lod_profile(contents)
    renders = list(profile.renders)
    sequences = [record.sequence for record in renders]
    if (
        not sequences
        or sequences[-1] < STEADY_LAST
        or sequences != list(range(sequences[-1] + 1))
    ):
        raise BenchmarkError(
            "stationary render sequence is not a contiguous 0..526-or-later run"
        )
    for record in renders:
        validate_render(record)
    cold_render = [record for record in renders if record.sequence == COLD_SEQUENCE]
    if len(cold_render) != 1:
        raise BenchmarkError("stationary capture lacks unique cold endpoint")
    endpoint = cold_render[0]
    publications = list(profile.mesh_replacements)
    if len(publications) != staged.COLD_ACTIVE_COUNT:
        raise BenchmarkError("stationary cold publication count changed")
    if any(item.log_offset > endpoint.log_offset for item in publications):
        raise BenchmarkError("mesh publication occurred after cold convergence")
    if any(
        match.start() > endpoint.log_offset
        for regex in (
            capture.OBJECT_ACTIVE_RE,
            survey.OBJECT_TRANSLATION_RE,
            staged.CAMERA_TRANSLATION_RE,
        )
        for match in regex.finditer(contents)
    ):
        raise BenchmarkError("object mutation occurred in the stationary window")

    steady_records = [
        record for record in renders if STEADY_FIRST <= record.sequence <= STEADY_LAST
    ]
    window = summarize_render_window(
        renders,
        first_sequence=STEADY_FIRST,
        last_sequence=STEADY_LAST,
        metric_names=(*RENDER_METRICS, *STRUCTURAL_FIELDS),
    )
    timing_fields = {"seq", *RENDER_METRICS}
    structural_names = tuple(
        sorted(
            name
            for name, value in steady_records[0].fields
            if isinstance(value, int) and name not in timing_fields
        )
    )
    structural = summarize_render_window(
        steady_records,
        metric_names=structural_names,
    )
    for name in structural_names:
        summary = structural.metric(name)
        if summary.minimum != summary.maximum:
            raise BenchmarkError(f"steady structural counter {name} changed")
    frames = {int(frame["sequence"]): frame for frame in report["frames"]}
    for sequence in (COLD_SEQUENCE, STEADY_LAST):
        if sequence not in frames:
            raise BenchmarkError(f"stationary capture lacks frame {sequence}")
    if any(
        frames[COLD_SEQUENCE][name] != frames[STEADY_LAST][name]
        for name in ("rgba2_sha256", "depth_sha256")
    ):
        raise BenchmarkError("stationary pixels changed between seq226 and seq526")
    terrain_records = report["fixture_contract"]["terrain_records"]
    container_bytes = sum(int(item["bytes"]) for item in terrain_records.values())
    publication_us = [item.publication_us for item in publications]
    return {
        "identity": checked_identity(
            report, ("program", "vdp", "emulator", "mos")
        ),
        "report": artifact(report_path),
        "log": artifact(log_path),
        "cold": {
            "publication_count": len(publications),
            "container_bytes": container_bytes,
            "data_bytes": sum(item.data_bytes for item in publications),
            "vertices": sum(item.vertices for item in publications),
            "triangles": sum(item.position_indices for item in publications) // 3,
            "native_command50_us": {
                "samples": publication_us,
                "summary": summarize_distribution(publication_us).as_dict(),
            },
            "endpoint_render": endpoint.as_dict(),
        },
        "steady": {
            "window": window.as_dict(),
            "structural_counters": structural.as_dict(),
            "samples": render_samples(steady_records),
            "derived": summarize_derived(steady_records),
            "mutation_free": True,
            "frame_hashes_equal": True,
        },
    }


def _handoff_end(contents: str, report: dict) -> int:
    if report.get("radius_input") is None:
        return len(contents)
    match = RADIUS_INPUT_RE.search(contents)
    if match is None:
        raise BenchmarkError("radius restart report has no input boundary")
    return match.start()


def _group_publications(
    contents: str,
    start: int,
    end: int,
    publications: list[MeshReplaceRecord],
) -> list[dict[str, object]]:
    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start, end))
    render_matches = list(staged.RENDER_RE.finditer(contents, start, end))
    render_offsets = [match.start() for match in render_matches]
    by_interval: dict[int, list[re.Match[str]]] = {}
    for match in activity:
        by_interval.setdefault(bisect_right(render_offsets, match.start()), []).append(match)
    groups = []
    cursor = 0
    previous_end = start
    for interval in sorted(by_interval):
        records = by_interval[interval]
        values = [int(match.group(2)) for match in records]
        enter = sum(values)
        retire = len(values) - enter
        if values != [0] * retire + [1] * enter:
            raise BenchmarkError("handoff group does not retire before entering")
        selected = publications[cursor : cursor + enter]
        if len(selected) != enter:
            raise BenchmarkError("handoff group lacks staged publications")
        if any(
            item.log_offset <= previous_end or item.log_offset >= records[0].start()
            for item in selected
        ):
            raise BenchmarkError("handoff publication lies outside its stage window")
        groups.append(
            {
                "retiring": retire,
                "entering": enter,
                "publication_count": len(selected),
                "data_bytes": sum(item.data_bytes for item in selected),
                "native_command50_us": sum(item.publication_us for item in selected),
                "preceding_render_sequence": (
                    int(render_matches[interval - 1].group(1))
                    if interval
                    else None
                ),
                "following_render_sequence": (
                    int(render_matches[interval].group(1))
                    if interval < len(render_matches)
                    else None
                ),
            }
        )
        cursor += enter
        previous_end = records[-1].end()
    if cursor != len(publications):
        raise BenchmarkError("unassigned handoff publications remain")
    return groups


def analyze_handoff(directory: Path) -> dict[str, object]:
    report_path, report, log_path, contents = load_report(
        directory, TRACE_REPORT, staged.SCHEMA
    )
    if report.get("mode") != "four-crossing":
        raise BenchmarkError("handoff source must be a crossings-only trace")
    if report.get("selector_profile") is not None:
        raise BenchmarkError("handoff render timing came from a selector-profile run")
    identity = checked_identity(
        report, ("program", "symbols", "vdp", "emulator", "mos")
    )
    proxy_artifact = artifact(directory / "vdp_input_trace_proxy.so")
    if proxy_artifact["sha256"] != report.get("proxy", {}).get("sha256"):
        raise BenchmarkError("handoff proxy artifact changed")
    identity["proxy"] = report["proxy"]
    start = staged.cold_end_offset(contents)
    end = _handoff_end(contents, report)
    profile = parse_regular_lod_profile(contents)
    for record in profile.renders:
        validate_render(record)
    publications = [
        item for item in profile.mesh_replacements if start < item.log_offset < end
    ]
    if len(publications) != staged.EXPECTED_ENTERING_COUNT:
        raise BenchmarkError("handoff publication count changed")
    groups = _group_publications(contents, start, end, publications)
    reported_shapes = report.get("transition_stream", {}).get(
        "group_shapes_by_transition"
    )
    if not isinstance(reported_shapes, list):
        raise BenchmarkError("handoff report lacks transition group partitions")
    crossing_group_counts = tuple(len(item) for item in reported_shapes)
    if crossing_group_counts != EXPECTED_CROSSING_GROUPS:
        raise BenchmarkError("handoff report group partition changed")
    if len(groups) != sum(crossing_group_counts):
        raise BenchmarkError("handoff group count changed")
    reported_flat = []
    for transition in reported_shapes:
        for shape in transition:
            if (
                not isinstance(shape, list)
                or len(shape) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in shape
                )
            ):
                raise BenchmarkError("handoff report contains an invalid group shape")
            reported_flat.append((shape[0], shape[1]))
    observed_flat = [
        (int(item["retiring"]), int(item["entering"])) for item in groups
    ]
    if observed_flat != reported_flat:
        raise BenchmarkError("handoff log group shapes differ from the trace report")
    crossings = []
    cursor = 0
    for index, count in enumerate(crossing_group_counts):
        selected = groups[cursor : cursor + count]
        cursor += count
        crossing_publications = sum(item["publication_count"] for item in selected)
        crossing_us = [
            publication.publication_us
            for publication in publications[
                sum(item["publication_count"] for item in groups[: cursor - count]) :
                sum(item["publication_count"] for item in groups[:cursor])
            ]
        ]
        crossings.append(
            {
                "index": index,
                "group_count": count,
                "entering": crossing_publications,
                "retiring": sum(int(item["retiring"]) for item in selected),
                "data_bytes": sum(int(item["data_bytes"]) for item in selected),
                "native_command50_us": {
                    "samples": crossing_us,
                    "summary": summarize_distribution(crossing_us).as_dict(),
                },
                "maximum_atomic_commit_activity": max(
                    int(item["retiring"]) + int(item["entering"])
                    for item in selected
                ),
                "first_preceding_render_sequence": selected[0][
                    "preceding_render_sequence"
                ],
                "last_following_render_sequence": selected[-1][
                    "following_render_sequence"
                ],
                "transition_render_span": (
                    int(selected[-1]["following_render_sequence"])
                    - int(selected[0]["preceding_render_sequence"])
                    if selected[0]["preceding_render_sequence"] is not None
                    and selected[-1]["following_render_sequence"] is not None
                    else None
                ),
            }
        )

    activity = list(capture.OBJECT_ACTIVE_RE.finditer(contents, start, end))
    final_activity_offset = activity[-1].end()
    final_renders = [
        record
        for record in profile.renders
        if final_activity_offset < record.log_offset < end
    ][: staged.POST_CONVERGENCE_RENDERS]
    if len(final_renders) != staged.POST_CONVERGENCE_RENDERS:
        raise BenchmarkError("handoff trace lacks three converged renders")
    steady = summarize_render_window(
        final_renders,
        metric_names=(*RENDER_METRICS, *STRUCTURAL_FIELDS),
    )
    handoff_renders = [
        record for record in profile.renders if start < record.log_offset < end
    ]
    return {
        "identity": identity,
        "report": artifact(report_path),
        "log": artifact(log_path),
        "publication_count": len(publications),
        "data_bytes": sum(item.data_bytes for item in publications),
        "native_command50_us": {
            "samples": [item.publication_us for item in publications],
            "summary": summarize_distribution(
                item.publication_us for item in publications
            ).as_dict(),
        },
        "group_count": len(groups),
        "crossings": crossings,
        "flight_and_handoff_render_us": {
            "samples": [record.render_us for record in handoff_renders],
            "summary": summarize_distribution(
                record.render_us for record in handoff_renders
            ).as_dict(),
        },
        "first_three_converged_renders": steady.as_dict(),
    }


def analyze_selector(directory: Path) -> dict[str, object]:
    report_path, report, log_path, contents = load_report(
        directory, TRACE_REPORT, staged.SCHEMA
    )
    if report.get("mode") != "four-crossing":
        raise BenchmarkError("selector source must omit the radius restart")
    identity = checked_identity(
        report, ("program", "symbols", "vdp", "emulator", "mos")
    )
    proxy_artifact = artifact(directory / "vdp_input_trace_proxy.so")
    if proxy_artifact["sha256"] != report.get("proxy", {}).get("sha256"):
        raise BenchmarkError("selector proxy artifact changed")
    identity["proxy"] = report["proxy"]
    embedded = report.get("selector_profile")
    if not isinstance(embedded, dict):
        raise BenchmarkError("selector source lacks profiling metadata")
    expected_metadata = {
        "method": "automated-pausing-debugger-breakpoints",
        "measurement": "paused-debugger-call-to-post-call",
        "sample_count": sum(EXPECTED_CROSSING_GROUPS),
    }
    for name, expected in expected_metadata.items():
        if embedded.get(name) != expected:
            raise BenchmarkError(
                f"selector profile {name}={embedded.get(name)!r}, "
                f"expected {expected!r}"
            )
    for name in ("call", "return", "target"):
        if (
            isinstance(embedded.get(name), bool)
            or not isinstance(embedded.get(name), int)
            or not 0 <= embedded[name] <= 0xFFFFFF
        ):
            raise BenchmarkError(f"selector source has invalid {name} address")
    symbol_values = staged.parse_symbols(Path(report["symbols"]["path"]))
    if symbol_values.get("regular_transition_select_feasible_group") != embedded[
        "target"
    ]:
        raise BenchmarkError("selector implementation address differs from symbols")
    program_path = Path(report["program"]["path"])
    if artifact(program_path)["sha256"] != report["program"]["sha256"]:
        raise BenchmarkError("selector program path no longer matches its report")
    if staged.selector_call_span(program_path, embedded["target"]) != (
        embedded["call"],
        embedded["return"],
    ):
        raise BenchmarkError("selector profiling addresses do not match program bytes")
    pairs = parse_selector_cycle_pairs(
        contents,
        entry_address=embedded["call"],
        post_call_address=embedded["return"],
    )
    samples = [pair.selector_cycles for pair in pairs]
    if len(samples) != sum(EXPECTED_CROSSING_GROUPS):
        raise BenchmarkError("selector sample count changed")
    if embedded.get("cycles") != samples:
        raise BenchmarkError("selector report and debugger states disagree")
    crossings = []
    cursor = 0
    for index, count in enumerate(EXPECTED_CROSSING_GROUPS):
        selected = samples[cursor : cursor + count]
        cursor += count
        crossings.append(
            {
                "index": index,
                "sample_count": count,
                "cycles": selected,
                "summary": summarize_distribution(selected).as_dict(),
            }
        )
    return {
        "identity": identity,
        "report": artifact(report_path),
        "log": artifact(log_path),
        "call_address": embedded["call"],
        "post_call_address": embedded["return"],
        "implementation_address": embedded["target"],
        "cycles": samples,
        "summary": summarize_distribution(samples).as_dict(),
        "crossings": crossings,
        "host_render_timing_excluded": True,
    }


def validate_cross_run_identity(
    stationary: dict[str, object],
    handoff: dict[str, object],
    selector: dict[str, object],
) -> dict[str, str]:
    identities = [
        stationary["identity"],
        handoff["identity"],
        selector["identity"],
    ]

    def hashes(name: str, selected: list[dict]) -> set[str]:
        values = set()
        for identity in selected:
            record = identity.get(name)
            if not isinstance(record, dict) or not isinstance(
                record.get("sha256"), str
            ):
                raise BenchmarkError(f"run identity lacks {name} hash")
            values.add(record["sha256"])
        return values

    result = {}
    for name in ("program", "vdp", "emulator", "mos"):
        values = hashes(name, identities)
        if len(values) != 1:
            raise BenchmarkError(f"benchmark runs used different {name} artifacts")
        result[name] = next(iter(values))
    for name in ("symbols", "proxy"):
        values = hashes(name, identities[1:])
        if len(values) != 1:
            raise BenchmarkError(f"handoff/profile runs used different {name}")
        result[name] = next(iter(values))
    return result


def main() -> int:
    arguments = parse_arguments()
    if arguments.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    output.mkdir(parents=True)
    python = sys.executable
    stationary_root, stationary_run = run_source(
        output,
        "stationary",
        arguments.stationary_source,
        [
            python,
            "-B",
            str(ROOT / "scripts/capture_regular_lod_manager_survey.py"),
            "--steady-frames",
            str(STEADY_FRAMES),
        ],
        arguments.timeout,
    )
    handoff_root, handoff_run = run_source(
        output,
        "handoff",
        arguments.handoff_source,
        [
            python,
            "-B",
            str(ROOT / "scripts/trace_regular_lod_staged_north_transitions.py"),
            "--crossings-only",
        ],
        arguments.timeout,
    )
    selector_root, selector_run = run_source(
        output,
        "selector",
        arguments.selector_source,
        [
            python,
            "-B",
            str(ROOT / "scripts/trace_regular_lod_staged_north_transitions.py"),
            "--crossings-only",
            "--profile-selector",
        ],
        arguments.timeout,
    )
    roots = {stationary_root, handoff_root, selector_root}
    if len(roots) != 3:
        raise SystemExit("stationary, handoff, and selector runs must be distinct")
    try:
        stationary = analyze_stationary(stationary_root)
        handoff = analyze_handoff(handoff_root)
        selector = analyze_selector(selector_root)
        common_identity = validate_cross_run_identity(
            stationary, handoff, selector
        )
    except (ProfileEvidenceError, BenchmarkError, KeyError, TypeError) as error:
        raise SystemExit(f"regular-LOD benchmark failed: {error}") from error
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "qualification_scope": {
            "name": "partial accepted-assembly performance baseline",
            "phase_one_complete": False,
            "unmeasured": [
                "hardware SD latency",
                "guest FatFS seek/read cycles",
                "guest container validation and mirror cycles",
                "guest UART/VDU staging cycles",
                "per-crossing origin-to-convergence guest cycles and vblanks",
            ],
            "whole_process_wall_time_is_not_phase_latency": True,
        },
        "scope": {
            "stationary_sequences": [0, COLD_SEQUENCE, STEADY_LAST],
            "steady_frame_count": STEADY_FRAMES,
            "handoff_crossings": 4,
            "selector_calls": sum(EXPECTED_CROSSING_GROUPS),
            "selector_profile_is_separate_process": True,
        },
        "common_identity": common_identity,
        "runs": {
            "stationary": stationary_run,
            "handoff": handoff_run,
            "selector": selector_run,
        },
        "stationary": stationary,
        "handoff": handoff,
        "selector": selector,
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Qualified regular-LOD runtime benchmark: {report_path}")
    print(
        "steady median="
        f"{stationary['steady']['window']['metrics']['render_us']['median']:.1f}us; "
        "selector median="
        f"{selector['summary']['median']:.1f} cycles; "
        f"handoff DATA={handoff['data_bytes']} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
