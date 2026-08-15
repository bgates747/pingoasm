#!/usr/bin/env python3
"""Reparse and compare the accepted+TEMT and CRC-nibble+THRE profiles.

This is a read-only cross-report analyzer.  It launches no emulator and edits
no source evidence.  The two input reports, their selected normative run
artifacts, and their raw logs are hash-pinned and reparsed before the
cumulative read-to-publication-complete-submit delta is emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import profile_regular_lod_crc_mos_uart_thre_combined as combined
import profile_regular_lod_crc_nibble_thre_sibling as nibble
import profile_regular_lod_mos_uart_thre_sibling as mos_profile
import build_regular_lod_historical_manager_witness as manager_witness


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_REPORT = (
    ROOT
    / "build/evidence/regular-lod-crc-mos-uart-thre-combined-profile-v1"
    / "regular-lod-crc-mos-uart-thre-combined-profile.json"
)
DEFAULT_CANDIDATE_REPORT = (
    ROOT
    / "build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v3"
    / "regular-lod-crc-nibble-thre-sibling-profile.json"
)
DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-crc-nibble-cumulative-analysis-v3"
)
DEFAULT_MANAGER_WITNESS = manager_witness.DEFAULT_OUTPUT
RECEIPT_NAME = "regular-lod-crc-nibble-cumulative-analysis.json"
SCHEMA = "pingo-terrain-regular-lod-crc-nibble-cumulative-analysis-v3"
EXPECTED_RECORDS = 227
METRIC = "read_to_publication_complete_submit"

BASELINE_REPORT_BYTES = 1_003_942
BASELINE_REPORT_SHA256 = (
    "e1cebf288d4fea4ebaf1674ad080715d75bda04a217f3c75daa89ccf4fa15c08"
)
CANDIDATE_REPORT_BYTES = 811_487
CANDIDATE_REPORT_SHA256 = (
    "fab87d454970f4ee8dccd9124af261c0c92cd927e896770ef3e2471dff706829"
)
BASELINE_LOG_SHA256 = (
    "d4247494f37504e91b2e6c92788bb7b10b192de0f3d7253bd9c73d549c30cc78"
)
CANDIDATE_LOG_SHA256 = (
    "ad500e3baba93656b126649eccb6321abce6ffe560c11aa7dadf1697db86dfd7"
)
RECORD_IDENTITY_DIGEST_SHA256 = (
    "7cc0a6465b0efdc83afff8498c51f06a7c84cb3e9fdbde71a233475e40f2156a"
)
EXPECTED_TOTALS = {
    "summary_all_227": {
        "baseline": 577_773_621,
        "candidate": 277_614_315,
        "delta": -300_159_306,
        "percent_rounded_4dp": "-51.9510%",
    },
    "summary_loop_226": {
        "baseline": 575_316_551,
        "candidate": 276_165_167,
        "delta": -299_151_384,
        "percent_rounded_4dp": "-51.9977%",
    },
}
EVIDENCE_PARSER_IDENTITIES = {
    "baseline_profile": {
        "key": "scripts/profile_regular_lod_crc_mos_uart_thre_combined.py",
        "bytes": 42_348,
        "sha256": "cf8bcb53dd7f9268f76d717936b14dd7942337807a03bf2f4d08b922d3bf8dac",
    },
    "candidate_profile": {
        "key": "scripts/profile_regular_lod_crc_nibble_thre_sibling.py",
        "bytes": 91_483,
        "sha256": "48a52c938174f6addaae45ad21d4f0f335706e2b828a08544cf8908ee6d7a1cc",
    },
    "semantic_validator": {
        "key": "scripts/profile_regular_lod_mos_uart_thre_sibling.py",
        "bytes": 53_644,
        "sha256": "8407f10c347c29fac46079b3982497c6183f7ab22662b87ee7bfaaf0a0cd13b2",
    },
}
CURRENT_PARSER_IDENTITIES = {
    "baseline_profile": {
        "key": "scripts/profile_regular_lod_crc_mos_uart_thre_combined.py",
        "bytes": 45_683,
        "sha256": "ffc68ea62068d13d425d6bba7157e86cb80c25b3c27731b6dc933b461a3d79ff",
    },
    "candidate_profile": {
        "key": "scripts/profile_regular_lod_crc_nibble_thre_sibling.py",
        "bytes": 91_963,
        "sha256": "f98d2295fbb5284711f41d7ee9e35c54435de196eab246622fbdd5dc33458692",
    },
    "semantic_validator": {
        "key": "scripts/profile_regular_lod_mos_uart_thre_sibling.py",
        "bytes": 55_549,
        "sha256": "756ff521e43d3902a88de77b3b8796b59538a23dfe6139efbdc305cc63bbbd5d",
    },
}


class CumulativeAnalysisError(RuntimeError):
    """A report identity, raw reparse, comparability, or metric gate failed."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT
    )
    parser.add_argument(
        "--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT
    )
    parser.add_argument(
        "--manager-witness", type=Path, default=DEFAULT_MANAGER_WITNESS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, key: str | None = None) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise CumulativeAnalysisError(f"missing artifact: {path}")
    if key is None:
        try:
            key = str(path.relative_to(ROOT))
        except ValueError:
            key = path.name
    return {"key": key, "bytes": path.stat().st_size, "sha256": sha256(path)}


def require_file(
    path: Path, expected_bytes: int, expected_sha256: str, description: str
) -> Path:
    path = path.expanduser().resolve()
    if (
        not path.is_file()
        or path.stat().st_size != expected_bytes
        or sha256(path) != expected_sha256
    ):
        actual_bytes = path.stat().st_size if path.is_file() else None
        actual_sha256 = sha256(path) if path.is_file() else None
        raise CumulativeAnalysisError(
            f"{description} identity changed: bytes={actual_bytes} "
            f"sha256={actual_sha256}"
        )
    return path


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CumulativeAnalysisError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CumulativeAnalysisError(f"JSON root is not an object: {path}")
    return value


def artifact_path(value: object, description: str) -> Path:
    if not isinstance(value, Mapping):
        raise CumulativeAnalysisError(f"{description} artifact is missing")
    key = value.get("key")
    size = value.get("bytes")
    digest = value.get("sha256")
    if (
        not isinstance(key, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not isinstance(digest, str)
    ):
        raise CumulativeAnalysisError(f"{description} artifact shape changed")
    path = ROOT / key
    require_file(path, size, digest, description)
    if artifact(path) != dict(value):
        raise CumulativeAnalysisError(f"{description} artifact binding changed")
    return path.resolve()


def require_identity_path(
    report: Mapping[str, object], name: str, path: Path
) -> dict[str, object]:
    identity = report.get("identity")
    if not isinstance(identity, Mapping):
        raise CumulativeAnalysisError("profile identity is missing")
    expected = identity.get(name)
    if not isinstance(expected, Mapping):
        raise CumulativeAnalysisError(f"profile identity omits {name}")
    actual = artifact(path, key=str(expected.get("key")))
    if actual != dict(expected):
        raise CumulativeAnalysisError(f"profile {name} identity changed")
    return actual


def validate_historical_manager_join(
    baseline_report: Mapping[str, object],
    candidate_report: Mapping[str, object],
    witness_directory: Path,
) -> dict[str, object]:
    """Remap both frozen report identities to an exact evidence-local snapshot."""

    snapshot, receipt_path, receipt = manager_witness.validate_witness(
        witness_directory
    )
    for name, report in (
        ("baseline", baseline_report),
        ("candidate", candidate_report),
    ):
        identity = report.get("identity")
        if not isinstance(identity, Mapping) or (
            identity.get("manager_manifest")
            != manager_witness.HISTORICAL_REPORT_IDENTITY
        ):
            raise CumulativeAnalysisError(
                f"{name} historical MANAGER report identity changed"
            )
        expected_corpus = mos_profile.corpus_witness(
            receipt["manager_semantic_witness"]
        )
        if identity.get("runtime_corpus") != expected_corpus:
            raise CumulativeAnalysisError(
                f"{name} historical MANAGER corpus witness changed"
            )
    return {
        "historical_report_identity": dict(
            manager_witness.HISTORICAL_REPORT_IDENTITY
        ),
        "evidence_local_snapshot": artifact(snapshot),
        "evidence_local_receipt": artifact(receipt_path),
        "selected_runtime_corpus": mos_profile.corpus_witness(
            receipt["manager_semantic_witness"]
        ),
        "live_manager_path_consulted": False,
    }


def select_run(
    report: Mapping[str, object], variant: str
) -> dict[str, object]:
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise CumulativeAnalysisError("profile runs are missing")
    matches = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("mode") == "normative-publication-complete"
        and run.get("variant") == variant
    ]
    if len(matches) != 1:
        raise CumulativeAnalysisError(
            f"expected one normative {variant} run, found {len(matches)}"
        )
    return matches[0]


def metric_evidence(cycles: Sequence[int]) -> dict[str, object]:
    return {
        "cycles": list(cycles),
        "summary_all_227": mos_profile.summarize_distribution(cycles).as_dict(),
        "summary_loop_226": mos_profile.summarize_distribution(cycles[1:]).as_dict(),
        "startup_record_0": cycles[0],
        "completion_equivalent": True,
    }


def record_identities(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    keys = ("order", "path", "file_sha256", "data_bytes")
    return [{name: record[name] for name in keys} for record in records]


def identity_digest(records: Sequence[Mapping[str, object]]) -> str:
    payload = (
        json.dumps(
            record_identities(records), sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def reparse_normative(
    report: Mapping[str, object],
    variant: str,
    resolver: Callable[[Path, Path], mos_profile.NormativeLayout],
    layout_evidence: Callable[
        [Path, mos_profile.NormativeLayout], dict[str, object]
    ],
) -> dict[str, object]:
    run = select_run(report, variant)
    paths = {
        name: artifact_path(run.get(name), f"{variant} {name}")
        for name in (
            "program",
            "symbols",
            "mos",
            "mos_map",
            "command",
            "autoexec",
            "log",
        )
    }
    layout = resolver(paths["program"], paths["symbols"])
    expected_layout = layout_evidence(paths["program"], layout)
    if run.get("layout") != expected_layout:
        raise CumulativeAnalysisError(f"{variant} serialized layout changed")
    command = load_json(paths["command"])
    if (
        command.get("mode") != "normative-publication-complete"
        or command.get("variant") != variant
        or command.get("program") != run.get("program")
        or command.get("symbols") != run.get("symbols")
        or command.get("mos") != run.get("mos")
        or command.get("mos_map") != run.get("mos_map")
        or command.get("layout") != expected_layout
    ):
        raise CumulativeAnalysisError(f"{variant} command binding changed")
    contents = paths["log"].read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render = mos_profile.validate_run_semantics(contents)
    states = mos_profile.parse_normative_states(contents, layout, EXPECTED_RECORDS)
    marker_offsets = mos_profile.publication_marker_offsets(contents)
    bound = mos_profile.bind_publications(publications)
    records = mos_profile.reconstruct_normative_records(
        states, publications, marker_offsets, bound
    )
    publication_semantics = [
        list(row) for row in mos_profile.publication_semantics(publications)
    ]
    read_cycles = [
        int(record["read_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    upload_cycles = [
        int(record["upload_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    metrics = {
        METRIC: metric_evidence(read_cycles),
        "upload_to_publication_complete_submit": metric_evidence(upload_cycles),
    }
    reparse_checks = {
        "state_count": len(states) == EXPECTED_RECORDS * 3,
        "record_count": len(records) == EXPECTED_RECORDS,
        "records": run.get("records") == records,
        "metrics": run.get("metrics") == metrics,
        "cold_endpoint": run.get("cold_endpoint") == endpoint,
        "publication_semantics": run.get("publication_semantics")
        == publication_semantics,
        "render_sequences": run.get("render_sequences")
        == render["qualified_prefix"],
    }
    failed = [name for name, passed in reparse_checks.items() if not passed]
    if failed:
        raise CumulativeAnalysisError(
            f"{variant} raw-log reparse differs from serialized evidence: {failed}"
        )
    live = run.get("live")
    if not isinstance(live, Mapping) or (
        live.get("record_count") != EXPECTED_RECORDS
        or live.get("events_per_record") != 3
        or live.get("cycle_state_count") != EXPECTED_RECORDS * 3
        or live.get("publication_before_submit_count") != EXPECTED_RECORDS
    ):
        raise CumulativeAnalysisError(f"{variant} live cardinality changed")
    return {
        "variant": variant,
        "mode": run["mode"],
        "artifacts": {name: artifact(path) for name, path in paths.items()},
        "layout": expected_layout,
        "logical_boundaries": [
            "read_call",
            "upload_call",
            "successful_publication_marker",
            "matching_own_image_submit_call",
        ],
        "metric": METRIC,
        "completion_equivalent": True,
        "records": records,
        "record_identities": record_identities(records),
        "record_identity_digest_sha256": identity_digest(records),
        "cold_endpoint": endpoint,
        "publication_semantics": publication_semantics,
        "render_sequences": render["qualified_prefix"],
        "metrics": metrics,
        "strict_upload_publication_submit_order_reparsed_all_227": True,
        "raw_log_reparsed": True,
    }


def assert_comparable(
    baseline_report: Mapping[str, object],
    candidate_report: Mapping[str, object],
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    for name in ("emulator", "vdp", "manager_manifest", "world_manifest"):
        left = baseline_report.get("identity", {}).get(name)
        right = candidate_report.get("identity", {}).get(name)
        if left != right:
            raise CumulativeAnalysisError(f"cross-report {name} differs")
    left_corpus = baseline_report.get("identity", {}).get("runtime_corpus")
    right_corpus = candidate_report.get("identity", {}).get("runtime_corpus")
    if left_corpus != right_corpus:
        raise CumulativeAnalysisError("cross-report runtime corpus differs")
    equal_fields = (
        "mode",
        "logical_boundaries",
        "metric",
        "completion_equivalent",
        "record_identities",
        "record_identity_digest_sha256",
        "cold_endpoint",
        "publication_semantics",
        "render_sequences",
    )
    for name in equal_fields:
        if baseline.get(name) != candidate.get(name):
            raise CumulativeAnalysisError(f"cross-report {name} differs")
    left_layout = baseline.get("layout")
    right_layout = candidate.get("layout")
    if not isinstance(left_layout, Mapping) or not isinstance(right_layout, Mapping):
        raise CumulativeAnalysisError("cross-report layouts are missing")
    stable_layout = ("read_call", "upload_call", "submit_target")
    if any(left_layout.get(name) != right_layout.get(name) for name in stable_layout):
        raise CumulativeAnalysisError("cross-report logical boundary targets differ")
    if (
        left_layout.get("events_per_record") != 3
        or right_layout.get("events_per_record") != 3
        or left_layout.get("no_breakpoint_after_upload_before_submit") is not True
        or right_layout.get("no_breakpoint_after_upload_before_submit") is not True
    ):
        raise CumulativeAnalysisError("cross-report boundary method changed")
    return {
        "same_emulator": True,
        "same_vdp": True,
        "same_manager_and_world_manifests": True,
        "same_exact_227_record_runtime_corpus": True,
        "same_record_order_path_sha256_and_data_bytes": True,
        "record_identity_digest_sha256": RECORD_IDENTITY_DIGEST_SHA256,
        "same_cold_endpoint_publication_semantics_and_render_prefix": True,
        "same_normative_three_event_method": True,
        "same_read_upload_and_submit_target_boundaries": True,
        "own_image_submit_call_sites_resolved_independently": True,
        "publication_marker_strictly_between_upload_and_own_submit_all_227": True,
        "physical_submit_call_addresses_may_shift_with_application_layout": True,
    }


def cumulative_metric(
    baseline: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    result = {}
    for summary, expected in EXPECTED_TOTALS.items():
        before = baseline["metrics"][METRIC][summary]["total"]
        after = candidate["metrics"][METRIC][summary]["total"]
        if not isinstance(before, int) or not isinstance(after, int) or before <= 0:
            raise CumulativeAnalysisError(f"invalid cumulative total: {summary}")
        value = {
            "baseline_cycles": before,
            "candidate_cycles": after,
            "delta_cycles": after - before,
            "candidate_vs_baseline_percent": (after - before) * 100.0 / before,
            "candidate_vs_baseline_percent_rounded_4dp": (
                f"{(after - before) * 100.0 / before:.4f}%"
            ),
            "boundary": summary,
            "completion_equivalent": True,
        }
        if (
            value["baseline_cycles"] != expected["baseline"]
            or value["candidate_cycles"] != expected["candidate"]
            or value["delta_cycles"] != expected["delta"]
            or value["candidate_vs_baseline_percent_rounded_4dp"]
            != expected["percent_rounded_4dp"]
        ):
            raise CumulativeAnalysisError(
                f"cumulative metric changed at {summary}: {value}"
            )
        result[summary] = value
    return result


def analyze(
    baseline_path: Path,
    candidate_path: Path,
    manager_witness_directory: Path = DEFAULT_MANAGER_WITNESS,
) -> dict[str, object]:
    baseline_path = require_file(
        baseline_path,
        BASELINE_REPORT_BYTES,
        BASELINE_REPORT_SHA256,
        "accepted+TEMT baseline report",
    )
    candidate_path = require_file(
        candidate_path,
        CANDIDATE_REPORT_BYTES,
        CANDIDATE_REPORT_SHA256,
        "CRC-nibble+THRE candidate report",
    )
    baseline_report = load_json(baseline_path)
    candidate_report = load_json(candidate_path)
    if (
        baseline_report.get("schema") != combined.SCHEMA
        or candidate_report.get("schema") != nibble.SCHEMA
        or baseline_report.get("qualified") is not True
        or candidate_report.get("qualified") is not True
    ):
        raise CumulativeAnalysisError("input report qualification changed")
    historical_manager = validate_historical_manager_join(
        baseline_report,
        candidate_report,
        manager_witness_directory,
    )
    shared_paths = {
        "emulator": mos_profile.input_trace.FAB_BINARY,
        "vdp": mos_profile.survey.DEFAULT_VDP,
        "world_manifest": mos_profile.builder.WORLD_MANIFEST,
    }
    shared_identity = {}
    for name, path in shared_paths.items():
        left = require_identity_path(baseline_report, name, path)
        right = require_identity_path(candidate_report, name, path)
        if left != right:
            raise CumulativeAnalysisError(f"live cross-report {name} differs")
        shared_identity[name] = left
    shared_identity["historical_manager"] = historical_manager
    parser_sources = {
        "baseline_profile": Path(combined.__file__).resolve(),
        "candidate_profile": Path(nibble.__file__).resolve(),
        "semantic_validator": Path(mos_profile.__file__).resolve(),
    }
    evidence_parser_sources = {
        "baseline_profile": baseline_report["identity"]["profile_script"],
        "candidate_profile": candidate_report["identity"]["profile_script"],
        "semantic_validator": candidate_report["identity"][
            "semantic_validator_script"
        ],
    }
    if evidence_parser_sources != EVIDENCE_PARSER_IDENTITIES:
        raise CumulativeAnalysisError("evidence parser source identity changed")
    current_parser_sources = {
        name: artifact(path) for name, path in parser_sources.items()
    }
    if current_parser_sources != CURRENT_PARSER_IDENTITIES:
        raise CumulativeAnalysisError("current raw-log parser source identity changed")
    baseline = reparse_normative(
        baseline_report,
        "accepted-temt-control",
        combined.resolve_normative_layout,
        combined.layout_evidence,
    )
    candidate = reparse_normative(
        candidate_report,
        "crc-nibble-thre-candidate",
        nibble.resolve_normative_layout,
        nibble.layout_evidence,
    )
    if (
        baseline["artifacts"]["log"]["sha256"] != BASELINE_LOG_SHA256
        or candidate["artifacts"]["log"]["sha256"] != CANDIDATE_LOG_SHA256
        or baseline["record_identity_digest_sha256"]
        != RECORD_IDENTITY_DIGEST_SHA256
        or candidate["record_identity_digest_sha256"]
        != RECORD_IDENTITY_DIGEST_SHA256
    ):
        raise CumulativeAnalysisError("selected raw-log or record identity changed")
    comparability = assert_comparable(
        baseline_report, candidate_report, baseline, candidate
    )
    metric = cumulative_metric(baseline, candidate)
    return {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "read_only_cross_report_analysis": True,
            "emulator_run": False,
            "accepted_source_or_artifact_modified": False,
            "input_report_or_log_modified": False,
            "fresh_runtime_pair_claimed": False,
            "selected_normative_run_count": 2,
            "records_reparsed_per_run": EXPECTED_RECORDS,
            "historical_to_current_parser_compatibility_pinned": True,
            "historical_manager_rebound_to_evidence_local_snapshot": True,
            "live_manager_path_consulted": False,
        },
        "identity": {
            "baseline_report": artifact(baseline_path),
            "candidate_report": artifact(candidate_path),
            "analyzer_script": artifact(Path(__file__)),
            "evidence_parser_sources": evidence_parser_sources,
            "current_parser_sources": current_parser_sources,
            "shared_runtime": shared_identity,
            "runtime_corpus": baseline_report["identity"]["runtime_corpus"],
        },
        "endpoints": {
            "baseline": {
                "application": "accepted",
                "mos": "TEMT control",
                "variant": baseline["variant"],
                "program": baseline["artifacts"]["program"],
                "mos_artifact": baseline["artifacts"]["mos"],
                "raw_log": baseline["artifacts"]["log"],
                "layout": baseline["layout"],
            },
            "candidate": {
                "application": "16-entry RRD nibble CRC",
                "mos": "THRE candidate",
                "variant": candidate["variant"],
                "program": candidate["artifacts"]["program"],
                "mos_artifact": candidate["artifacts"]["mos"],
                "raw_log": candidate["artifacts"]["log"],
                "layout": candidate["layout"],
            },
        },
        "comparability": comparability,
        "metric": {
            "name": METRIC,
            "interpretation": (
                "guest cycles from the record read call through the matching "
                "own-image submit call after successful VDP publication"
            ),
            "all_records_including_startup_0": metric["summary_all_227"],
            "loop_records_1_through_226": metric["summary_loop_226"],
        },
        "raw_reparse": {
            "baseline_records": EXPECTED_RECORDS,
            "candidate_records": EXPECTED_RECORDS,
            "baseline_log": baseline["artifacts"]["log"],
            "candidate_log": candidate["artifacts"]["log"],
            "serialized_records_and_metrics_exact": True,
            "strict_publication_order_exact": True,
        },
        "limitations": {
            "cross_report_not_one_fresh_runtime_pair": True,
            "single_capture_per_endpoint_does_not_establish_repeatability": True,
            "cumulative_comparison_changes_both_crc_and_mos_components": True,
            "exact_image_emulator_evidence_only": True,
            "hardware_crc_timing_qualification_open": True,
            "hardware_uart_cts_fifo_timing_qualification_open": True,
            "thre_return_does_not_imply_transmitter_idle": True,
            "normal_mos_source_rebuild_required_for_promotion": True,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    evidence_roots = (
        args.baseline_report.expanduser().resolve().parent,
        args.candidate_report.expanduser().resolve().parent,
        args.manager_witness.expanduser().resolve(),
    )
    if any(
        output == root or root in output.parents or output in root.parents
        for root in evidence_roots
    ):
        raise CumulativeAnalysisError(
            "output must not equal, contain, or descend from an input evidence root"
        )
    if output.exists():
        raise CumulativeAnalysisError(
            f"refusing to replace existing output: {output}"
        )
    receipt = analyze(
        args.baseline_report,
        args.candidate_report,
        args.manager_witness,
    )
    output.mkdir(parents=True)
    receipt_path = output / RECEIPT_NAME
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Regular-LOD CRC-nibble cumulative analysis passed: {receipt_path}")
    all_records = receipt["metric"]["all_records_including_startup_0"]
    loop = receipt["metric"]["loop_records_1_through_226"]
    print(
        "read_to_publication_complete_submit "
        f"all227={all_records['candidate_vs_baseline_percent_rounded_4dp']} "
        f"loop226={loop['candidate_vs_baseline_percent_rounded_4dp']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        CumulativeAnalysisError,
        combined.CombinedProfileError,
        nibble.CrcNibbleThreProfileError,
        mos_profile.MosUartThreProfileError,
    ) as error:
        raise SystemExit(f"CRC-nibble cumulative analysis failed: {error}") from error
