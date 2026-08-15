#!/usr/bin/env python3
"""Qualify and compare four regular-LOD selector profile reports.

The inputs are independent crossings-only traces for the accepted assembly
fixture and the DUAL_STRICT, C_GUARDED, and ASM_CACHED policy siblings.  The
native cached mode is the fair architectural control: it consumes the same
cached pending descriptors as C without calling CPOLICY.  This analyzer does
no capture.  It binds each report to its log and executable artifacts, proves
semantic equivalence, and summarizes the already captured selector call-site
guest-cycle samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

from pingo_terrain.regular_lod_profile import (
    ProfileEvidenceError,
    parse_selector_cycle_pairs,
    summarize_distribution,
)


TRACE_SCHEMA = "pingo-terrain-regular-lod-staged-north-transitions-v2"
SCHEMA = "pingo-terrain-regular-lod-policy-ab-v2"
REPORT_NAME = "regular-lod-policy-ab.json"
PROGRAM_LOAD_ADDRESS = 0x040000
EXPECTED_CROSSING_GROUPS = (29, 21, 17, 17)
EXPECTED_SELECTOR_SAMPLES = sum(EXPECTED_CROSSING_GROUPS)
POLICY_STATUS_READY = 1
POLICY_MODE_DUAL_STRICT = 1
POLICY_MODE_C_GUARDED = 2
POLICY_MODE_ASM_CACHED = 3
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")


class PolicyABError(ValueError):
    """One input is incomplete, stale, or outside the comparison contract."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accepted",
        type=Path,
        required=True,
        help="accepted-assembly crossings-only selector profile JSON",
    )
    parser.add_argument(
        "--dual-strict",
        type=Path,
        required=True,
        help="DUAL_STRICT crossings-only selector profile JSON",
    )
    parser.add_argument(
        "--c-guarded",
        type=Path,
        required=True,
        help="C_GUARDED crossings-only selector profile JSON",
    )
    parser.add_argument(
        "--asm-cached",
        type=Path,
        required=True,
        help="module-free ASM_CACHED crossings-only selector profile JSON",
    )
    parser.add_argument(
        "--c-guarded-repeat",
        type=Path,
        action="append",
        default=[],
        help="additional independent current C_GUARDED profile (repeatable)",
    )
    parser.add_argument(
        "--asm-cached-repeat",
        type=Path,
        action="append",
        default=[],
        help="additional independent ASM_CACHED profile (repeatable)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help=f"new output JSON (normally {REPORT_NAME})",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_value(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PolicyABError(f"{description} is not a lowercase SHA-256")
    return value


def _mapping(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PolicyABError(f"{description} is not an object")
    return value


def _uint(value: object, description: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyABError(f"{description} is not a non-negative integer")
    if positive and value == 0:
        raise PolicyABError(f"{description} must be positive")
    return value


def _artifact(path: Path, description: str) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PolicyABError(f"missing {description}: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def _reported_artifact(
    report: Mapping[str, object], name: str, variant: str
) -> dict[str, object]:
    record = _mapping(report.get(name), f"{variant} {name} identity")
    encoded_path = record.get("path")
    if not isinstance(encoded_path, str) or not encoded_path:
        raise PolicyABError(f"{variant} {name} identity lacks a path")
    expected = _sha256_value(
        record.get("sha256"), f"{variant} {name} identity hash"
    )
    actual = _artifact(Path(encoded_path), f"{variant} {name} artifact")
    if actual["sha256"] != expected:
        raise PolicyABError(f"{variant} {name} artifact changed after capture")
    return actual


def _symbol_value(path: Path, name: str) -> int:
    values: set[int] = set()
    for line in path.read_text(encoding="ascii").splitlines():
        match = _SYMBOL_RE.fullmatch(line)
        if match is not None and match.group(1) == name:
            values.add(int(match.group(2), 16))
    if len(values) != 1:
        raise PolicyABError(
            f"symbol artifact does not define exactly one consistent {name}"
        )
    return next(iter(values))


def _validate_call_site(
    program: Path,
    symbols: Path,
    *,
    target: int,
    call: int,
    returned: int,
    variant: str,
) -> None:
    symbol_target = _symbol_value(
        symbols, "regular_transition_select_feasible_group"
    )
    if symbol_target != target:
        raise PolicyABError(
            f"{variant} selector target differs from its symbol artifact"
        )
    if returned != call + 4:
        raise PolicyABError(f"{variant} selector return is not after one ADL CALL")
    if call < PROGRAM_LOAD_ADDRESS:
        raise PolicyABError(f"{variant} selector call lies below program load")
    instruction = bytes((0xCD,)) + target.to_bytes(3, "little")
    image = program.read_bytes()
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = image.find(instruction, cursor)
        if offset < 0:
            break
        offsets.append(offset)
        cursor = offset + 1
    if offsets != [call - PROGRAM_LOAD_ADDRESS]:
        raise PolicyABError(
            f"{variant} selector profile is not bound to one exact program call"
        )


def _validate_selector(
    report: Mapping[str, object],
    contents: str,
    identities: Mapping[str, Mapping[str, object]],
    variant: str,
) -> dict[str, object]:
    profile = _mapping(report.get("selector_profile"), f"{variant} selector profile")
    expected_metadata = {
        "method": "automated-pausing-debugger-breakpoints",
        "measurement": "paused-debugger-call-to-post-call",
        "sample_count": EXPECTED_SELECTOR_SAMPLES,
    }
    for name, expected in expected_metadata.items():
        if profile.get(name) != expected:
            raise PolicyABError(
                f"{variant} selector {name}={profile.get(name)!r}, "
                f"expected {expected!r}"
            )
    addresses = {
        name: _uint(profile.get(name), f"{variant} selector {name}")
        for name in ("target", "call", "return")
    }
    if any(value > 0xFFFFFF for value in addresses.values()):
        raise PolicyABError(f"{variant} selector address lies outside 24-bit space")
    cycles_value = profile.get("cycles")
    if not isinstance(cycles_value, list):
        raise PolicyABError(f"{variant} selector cycles are not an array")
    cycles = [
        _uint(value, f"{variant} selector cycle sample", positive=True)
        for value in cycles_value
    ]
    if len(cycles) != EXPECTED_SELECTOR_SAMPLES:
        raise PolicyABError(
            f"{variant} selector has {len(cycles)} samples, "
            f"expected {EXPECTED_SELECTOR_SAMPLES}"
        )
    pairs = parse_selector_cycle_pairs(
        contents,
        entry_address=addresses["call"],
        post_call_address=addresses["return"],
    )
    parsed_cycles = [pair.selector_cycles for pair in pairs]
    if parsed_cycles != cycles:
        raise PolicyABError(
            f"{variant} embedded selector cycles differ from its hashed log"
        )
    _validate_call_site(
        Path(str(identities["program"]["path"])),
        Path(str(identities["symbols"]["path"])),
        target=addresses["target"],
        call=addresses["call"],
        returned=addresses["return"],
        variant=variant,
    )

    crossings = []
    cursor = 0
    for index, count in enumerate(EXPECTED_CROSSING_GROUPS):
        selected = cycles[cursor : cursor + count]
        cursor += count
        crossings.append(
            {
                "index": index,
                "group_count": count,
                "cycles": selected,
                "summary": summarize_distribution(selected).as_dict(),
            }
        )
    return {
        "target": addresses["target"],
        "call": addresses["call"],
        "return": addresses["return"],
        "measurement": profile["measurement"],
        "sample_count": len(cycles),
        "cycles": cycles,
        "summary": summarize_distribution(cycles).as_dict(),
        "crossings": crossings,
    }


def _validate_stream(report: Mapping[str, object], variant: str) -> dict[str, object]:
    stream = _mapping(
        report.get("transition_stream"), f"{variant} transition stream"
    )
    expected = {
        "command50_count": 130,
        "command50_all_inactive": True,
        "entering_count": 130,
        "retiring_count": 130,
        "group_count": EXPECTED_SELECTOR_SAMPLES,
        "retire_before_enter": True,
        "render_inside_group_commit": False,
    }
    for name, value in expected.items():
        if stream.get(name) != value:
            raise PolicyABError(
                f"{variant} transition {name}={stream.get(name)!r}, "
                f"expected {value!r}"
            )
    partitions = stream.get("group_shapes_by_transition")
    if not isinstance(partitions, list) or len(partitions) != 4:
        raise PolicyABError(f"{variant} transition lacks four group partitions")
    counts = tuple(
        len(partition) if isinstance(partition, list) else -1
        for partition in partitions
    )
    if counts != EXPECTED_CROSSING_GROUPS:
        raise PolicyABError(
            f"{variant} crossing group counts {counts!r} differ from "
            f"{EXPECTED_CROSSING_GROUPS!r}"
        )
    shapes: list[tuple[int, int]] = []
    for partition in partitions:
        assert isinstance(partition, list)
        for shape in partition:
            if not isinstance(shape, list) or len(shape) != 2:
                raise PolicyABError(f"{variant} transition has malformed group shape")
            retiring = _uint(shape[0], f"{variant} group retiring count")
            entering = _uint(shape[1], f"{variant} group entering count")
            if retiring > 14 or entering > 14 or retiring + entering == 0:
                raise PolicyABError(f"{variant} transition group exceeds policy ABI")
            shapes.append((retiring, entering))
    if sum(item[0] for item in shapes) != 130 or sum(
        item[1] for item in shapes
    ) != 130:
        raise PolicyABError(f"{variant} group shapes do not conserve 130/130 owners")

    active = stream.get("final_active_ids")
    if not isinstance(active, list):
        raise PolicyABError(f"{variant} final active IDs are not an array")
    active_ids = [
        _uint(value, f"{variant} final active object ID", positive=True)
        for value in active
    ]
    if (
        len(active_ids) != 227
        or active_ids != sorted(active_ids)
        or len(set(active_ids)) != len(active_ids)
        or active_ids[-1] > 255
    ):
        raise PolicyABError(f"{variant} final active slot set is malformed")
    return stream


_EXPECTED_MANAGER = {
    "active_count": 227,
    "converged": 1,
    "desired_count": 227,
    "last_error": 0,
    "last_operation": 0,
    "origin": [80, 129],
    "origin_dirty": 0,
    "proposed_origin": [80, 129],
    "resident_count": 240,
    "ring": 5,
    "staged_count": 0,
    "state": 1,
}
_EXPECTED_PROVIDER = {
    "desired_count": 227,
    "endpoint_count": 227,
    "endpoint_near_limit": 91,
    "plan_count": 136,
    "plan_valid": 1,
    "transition_state": 0,
    "unified_slots": 1,
}


def _validate_final_owner(
    report: Mapping[str, object], stream: Mapping[str, object], variant: str
) -> tuple[dict[str, object], dict[str, object]]:
    final_state = _mapping(report.get("final_state"), f"{variant} final state")
    manager = _mapping(final_state.get("manager"), f"{variant} manager state")
    provider = _mapping(final_state.get("provider"), f"{variant} provider state")
    slots = _mapping(final_state.get("slots"), f"{variant} slot state")
    if manager != _EXPECTED_MANAGER:
        raise PolicyABError(f"{variant} manager final endpoint changed")
    if provider != _EXPECTED_PROVIDER:
        raise PolicyABError(f"{variant} provider final endpoint changed")
    slot_contract = {
        "resident_count_from_flags": 240,
        "active_count_from_flags": 227,
        "owner_set_exact": True,
        "near_map_exact": True,
        "coarse_map_exact": True,
    }
    for name, expected in slot_contract.items():
        if slots.get(name) != expected:
            raise PolicyABError(
                f"{variant} final slots {name}={slots.get(name)!r}, "
                f"expected {expected!r}"
            )
    _sha256_value(slots.get("flags_sha256"), f"{variant} slot flags hash")
    if slots.get("active_ids") != stream.get("final_active_ids"):
        raise PolicyABError(
            f"{variant} stream and final snapshot active IDs differ"
        )
    semantic = {"manager": manager, "provider": provider, "slots": slots}
    return final_state, semantic


def _validate_policy(
    report: Mapping[str, object],
    final_state: Mapping[str, object],
    module: Mapping[str, object] | None,
    variant: str,
) -> dict[str, object]:
    policy = final_state.get("policy")
    if variant == "accepted_asm":
        if module is not None or policy is not None:
            raise PolicyABError(
                "accepted assembly report unexpectedly has C policy state"
            )
        optional_contract = {
            "policy_module_required": False,
            "policy_expected_available": False,
            "policy_expected_status": None,
            "policy_body_corrupted": False,
        }
        for name, expected in optional_contract.items():
            if name in report and report[name] != expected:
                raise PolicyABError(
                    f"accepted assembly {name}={report[name]!r}, "
                    f"expected {expected!r}"
                )
        return {
            "policy_abi_present": False,
            "module_status": None,
            "qualification_failure": 0,
            "c_selector_calls": 0,
            "c_selector_matches": 0,
        }

    if variant == "asm_cached":
        if module is not None:
            raise PolicyABError("ASM_CACHED unexpectedly staged CPOLICY")
        report_contract = {
            "policy_module_required": False,
            "policy_expected_available": False,
            "policy_expected_status": None,
            "policy_body_corrupted": False,
        }
        for name, expected in report_contract.items():
            if report.get(name) != expected:
                raise PolicyABError(
                    f"ASM_CACHED {name}={report.get(name)!r}, "
                    f"expected {expected!r}"
                )
        observed = _mapping(policy, "asm_cached policy snapshot")
        expected = {
            "mode": POLICY_MODE_ASM_CACHED,
            "module_status": 0,
            "qualification_failure": 0,
            "selector_calls": EXPECTED_SELECTOR_SAMPLES,
            "selector_matches": 0,
            "module_expected_available": False,
            "module_required": False,
            "selector_counter_contract": True,
            "asm_cached_has_no_module_dependency": True,
        }
        for name, value in expected.items():
            if observed.get(name) != value:
                raise PolicyABError(
                    f"asm_cached policy {name}={observed.get(name)!r}, "
                    f"expected {value!r}"
                )
        return {
            "policy_abi_present": True,
            "mode": POLICY_MODE_ASM_CACHED,
            "module_required": False,
            "module_status": 0,
            "qualification_failure": 0,
            "selector_calls": EXPECTED_SELECTOR_SAMPLES,
            "selector_matches": 0,
            "healthy_path_uses_asm_oracle": False,
        }

    if module is None:
        raise PolicyABError(f"{variant} report lacks the fixed policy module")
    if report.get("policy_expected_available") is not True:
        raise PolicyABError(f"{variant} did not require the policy capability")
    if (
        "policy_module_required" in report
        and report["policy_module_required"] is not True
    ):
        raise PolicyABError(f"{variant} did not require the policy module")
    if (
        "policy_expected_status" in report
        and report["policy_expected_status"] != POLICY_STATUS_READY
    ):
        raise PolicyABError(f"{variant} did not require READY policy status")
    if (
        "policy_body_corrupted" in report
        and report["policy_body_corrupted"] is not False
    ):
        raise PolicyABError(f"{variant} used a corrupt policy module")
    observed = _mapping(policy, f"{variant} policy snapshot")
    mode = (
        POLICY_MODE_DUAL_STRICT
        if variant == "dual_strict"
        else POLICY_MODE_C_GUARDED
    )
    expected_matches = EXPECTED_SELECTOR_SAMPLES if variant == "dual_strict" else 0
    expected = {
        "mode": mode,
        "module_status": POLICY_STATUS_READY,
        "qualification_failure": 0,
        "selector_calls": EXPECTED_SELECTOR_SAMPLES,
        "selector_matches": expected_matches,
        "module_expected_available": True,
        "selector_counter_contract": True,
        "c_guarded_healthy_path_has_no_asm_oracle": variant == "c_guarded",
    }
    for name, value in expected.items():
        if observed.get(name) != value:
            raise PolicyABError(
                f"{variant} policy {name}={observed.get(name)!r}, "
                f"expected {value!r}"
            )
    if (
        "module_expected_status" in observed
        and observed["module_expected_status"] != POLICY_STATUS_READY
    ):
        raise PolicyABError(f"{variant} snapshot did not require READY status")
    return {
        "policy_abi_present": True,
        "mode": mode,
        "module_status": POLICY_STATUS_READY,
        "qualification_failure": 0,
        "c_selector_calls": EXPECTED_SELECTOR_SAMPLES,
        "c_selector_matches": expected_matches,
        "healthy_path_uses_asm_oracle": variant == "dual_strict",
    }


def _load_variant(path: Path, variant: str) -> dict[str, object]:
    report_artifact = _artifact(path, f"{variant} report")
    report_path = Path(str(report_artifact["path"]))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PolicyABError(f"{variant} report is not valid UTF-8 JSON") from error
    report = _mapping(report, f"{variant} report")
    if report.get("schema") != TRACE_SCHEMA:
        raise PolicyABError(f"{variant} report has an unexpected schema")
    if report.get("qualified") is not True:
        raise PolicyABError(f"{variant} trace is not qualified")
    if report.get("mode") != "four-crossing":
        raise PolicyABError(f"{variant} trace is not crossings-only")
    if report.get("radius_input") is not None or report.get(
        "radius_restart_stream"
    ) is not None:
        raise PolicyABError(f"{variant} trace includes a radius restart")
    if report.get("emulator_exit_status") != 0:
        raise PolicyABError(f"{variant} emulator did not exit successfully")
    if report.get("shutdown") != "debugger-memory-exit":
        raise PolicyABError(f"{variant} trace lacks its final debugger snapshot")

    log_artifact = _artifact(report_path.parent / "emulator.log", f"{variant} log")
    reported_log_hash = _sha256_value(
        report.get("log_sha256"), f"{variant} reported log hash"
    )
    if log_artifact["sha256"] != reported_log_hash:
        raise PolicyABError(f"{variant} emulator log changed after capture")
    log_contents = Path(str(log_artifact["path"])).read_text(
        encoding="utf-8", errors="replace"
    )

    identities = {
        name: _reported_artifact(report, name, variant)
        for name in ("program", "symbols", "vdp", "emulator", "mos")
    }
    proxy_record = _mapping(report.get("proxy"), f"{variant} proxy identity")
    proxy_hash = _sha256_value(
        proxy_record.get("sha256"), f"{variant} proxy hash"
    )
    exports = proxy_record.get("exports")
    if (
        not isinstance(exports, list)
        or not exports
        or any(not isinstance(item, str) or not item for item in exports)
        or exports != sorted(set(exports))
    ):
        raise PolicyABError(f"{variant} proxy exports are malformed")
    proxy_artifact = _artifact(
        report_path.parent / "vdp_input_trace_proxy.so", f"{variant} proxy"
    )
    if proxy_artifact["sha256"] != proxy_hash:
        raise PolicyABError(f"{variant} proxy artifact changed after capture")
    proxy_artifact["exports"] = exports
    identities["proxy"] = proxy_artifact

    module_record = report.get("policy_module")
    if module_record is None:
        module = None
    else:
        module = _reported_artifact(report, "policy_module", variant)
    selector = _validate_selector(report, log_contents, identities, variant)
    stream = _validate_stream(report, variant)
    final_state, final_owner = _validate_final_owner(
        report, stream, variant
    )
    policy = _validate_policy(report, final_state, module, variant)
    return {
        "source_root": str(report_path.parent),
        "report": report_artifact,
        "log": log_artifact,
        "identities": identities,
        "policy_module": module,
        "policy": policy,
        "selector": selector,
        "transition_stream": stream,
        "final_owner": final_owner,
    }


def _semantic_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _percentage_deltas(
    baseline: Mapping[str, int | float],
    candidate: Mapping[str, int | float],
) -> dict[str, float]:
    result = {}
    for name in ("total", "minimum", "maximum", "mean", "median", "p95"):
        base = baseline[name]
        value = candidate[name]
        if isinstance(base, bool) or not isinstance(base, (int, float)) or base == 0:
            raise PolicyABError(f"accepted {name} cannot be a percentage baseline")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyABError(f"guarded {name} is not numeric")
        result[name] = round((value - base) * 100.0 / base, 6)
    return result


def _validate_comparison(
    variants: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    selected = [
        variants[name]
        for name in (
            "accepted_asm",
            "dual_strict",
            "c_guarded",
            "asm_cached",
        )
    ]
    roots = {str(item["source_root"]) for item in selected}
    reports = {
        str(item["report"]["sha256"])  # type: ignore[index]
        for item in selected
    }
    logs = {str(item["log"]["sha256"]) for item in selected}  # type: ignore[index]
    if len(roots) != 4 or len(reports) != 4 or len(logs) != 4:
        raise PolicyABError(
            "all four policy variants must come from distinct processes"
        )

    common_identity: dict[str, str] = {}
    for name in ("vdp", "emulator", "mos", "proxy"):
        hashes = {
            str(item["identities"][name]["sha256"])  # type: ignore[index]
            for item in selected
        }
        if len(hashes) != 1:
            raise PolicyABError(f"variants used different {name} artifacts")
        common_identity[name] = next(iter(hashes))

    for name in ("program", "symbols"):
        paths = {
            str(item["identities"][name]["path"])  # type: ignore[index]
            for item in selected
        }
        hashes = {
            str(item["identities"][name]["sha256"])  # type: ignore[index]
            for item in selected
        }
        if len(paths) != 4 or len(hashes) != 4:
            raise PolicyABError(
                f"the four variant {name} artifacts are not distinct"
            )

    accepted_module = variants["accepted_asm"]["policy_module"]
    dual_module = variants["dual_strict"]["policy_module"]
    guarded_module = variants["c_guarded"]["policy_module"]
    cached_module = variants["asm_cached"]["policy_module"]
    if (
        accepted_module is not None
        or cached_module is not None
        or not isinstance(dual_module, dict)
        or not isinstance(guarded_module, dict)
    ):
        raise PolicyABError("policy module presence differs from the A/B contract")
    if dual_module["sha256"] != guarded_module["sha256"]:
        raise PolicyABError("dual and guarded runs used different policy modules")

    stream_hashes = {
        _semantic_sha256(item["transition_stream"]) for item in selected
    }
    owner_hashes = {_semantic_sha256(item["final_owner"]) for item in selected}
    if len(stream_hashes) != 1:
        raise PolicyABError("variant transition streams are not semantically exact")
    if len(owner_hashes) != 1:
        raise PolicyABError("variant final owner states are not semantically exact")
    return {
        "independent_processes": True,
        "common_identity": common_identity,
        "policy_module_sha256": dual_module["sha256"],
        "transition_stream_equivalent": True,
        "transition_stream_sha256": next(iter(stream_hashes)),
        "final_owner_state_equivalent": True,
        "final_owner_state_sha256": next(iter(owner_hashes)),
    }


def _selector_comparison(
    variants: Mapping[str, Mapping[str, object]],
    *,
    baseline_name: str,
    candidate_name: str,
) -> dict[str, object]:
    baseline = variants[baseline_name]["selector"]
    candidate = variants[candidate_name]["selector"]
    assert isinstance(baseline, dict)
    assert isinstance(candidate, dict)
    baseline_crossings = baseline["crossings"]
    candidate_crossings = candidate["crossings"]
    assert isinstance(baseline_crossings, list)
    assert isinstance(candidate_crossings, list)
    crossing_deltas = []
    for index, (base_crossing, candidate_crossing) in enumerate(
        zip(baseline_crossings, candidate_crossings, strict=True)
    ):
        crossing_deltas.append(
            {
                "index": index,
                "group_count": EXPECTED_CROSSING_GROUPS[index],
                "percent": _percentage_deltas(
                    base_crossing["summary"], candidate_crossing["summary"]
                ),
            }
        )
    return {
        "name": f"{candidate_name}_vs_{baseline_name}",
        "baseline": baseline_name,
        "candidate": candidate_name,
        "delta_definition": (
            f"({candidate_name} - {baseline_name}) / {baseline_name} * 100"
        ),
        "positive_percent_is_more_guest_cycles": True,
        "overall_percent": _percentage_deltas(
            baseline["summary"], candidate["summary"]
        ),
        "crossings": crossing_deltas,
    }


def _resident_image_sizes(
    variants: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    sizes: dict[str, dict[str, int]] = {}
    for name, variant in variants.items():
        identities = variant["identities"]
        assert isinstance(identities, dict)
        program = identities["program"]
        assert isinstance(program, dict)
        program_bytes = _uint(program["bytes"], f"{name} program bytes", positive=True)
        module = variant["policy_module"]
        module_bytes = 0
        if module is not None:
            assert isinstance(module, dict)
            module_bytes = _uint(
                module["bytes"], f"{name} module bytes", positive=True
            )
        sizes[name] = {
            "program_image_bytes": program_bytes,
            "policy_module_image_bytes": module_bytes,
            "resident_image_bytes": program_bytes + module_bytes,
        }

    comparisons = {}
    for baseline_name, candidate_name in (
        ("accepted_asm", "c_guarded"),
        ("accepted_asm", "asm_cached"),
        ("c_guarded", "asm_cached"),
    ):
        baseline = sizes[baseline_name]
        candidate = sizes[candidate_name]
        key = f"{candidate_name}_vs_{baseline_name}"
        comparisons[key] = {
            field: candidate[field] - baseline[field]
            for field in (
                "program_image_bytes",
                "policy_module_image_bytes",
                "resident_image_bytes",
            )
        }
    return {
        "definition": (
            "exact captured program-file bytes plus the separately loaded "
            "CPOLICY image when that mode requires it"
        ),
        "caveat": (
            "ASM_CACHED still links unreachable common module-loader, CRC, and "
            "C-call client routines; this is a profile-specific linked-image "
            "comparison, not an optimized native-only size claim."
        ),
        "variants": sizes,
        "comparisons_signed_bytes": comparisons,
    }


def _repeatability_evidence(
    variants: Mapping[str, Mapping[str, object]],
    *,
    c_guarded_repeats: Sequence[Path],
    asm_cached_repeats: Sequence[Path],
) -> dict[str, object] | None:
    if not c_guarded_repeats and not asm_cached_repeats:
        return None
    if len(c_guarded_repeats) != len(asm_cached_repeats):
        raise PolicyABError("guarded/cached repeat counts differ")
    if len(c_guarded_repeats) < 2:
        raise PolicyABError(
            "repeatability requires two additional reports per mode (three runs)"
        )

    loaded: dict[str, list[Mapping[str, object]]] = {
        "c_guarded": [variants["c_guarded"]],
        "asm_cached": [variants["asm_cached"]],
    }
    for name, paths in (
        ("c_guarded", c_guarded_repeats),
        ("asm_cached", asm_cached_repeats),
    ):
        reference = variants[name]
        for path in paths:
            candidate = _load_variant(path, name)
            for identity_name in (
                "program",
                "symbols",
                "vdp",
                "emulator",
                "mos",
                "proxy",
            ):
                reference_hash = reference["identities"][identity_name]["sha256"]  # type: ignore[index]
                candidate_hash = candidate["identities"][identity_name]["sha256"]  # type: ignore[index]
                if candidate_hash != reference_hash:
                    raise PolicyABError(
                        f"{name} repeat used different {identity_name} bytes"
                    )
            if _semantic_sha256(candidate["transition_stream"]) != _semantic_sha256(
                reference["transition_stream"]
            ):
                raise PolicyABError(f"{name} repeat transition stream changed")
            if _semantic_sha256(candidate["final_owner"]) != _semantic_sha256(
                reference["final_owner"]
            ):
                raise PolicyABError(f"{name} repeat final owner state changed")
            loaded[name].append(candidate)

    all_logs = {
        str(run["log"]["sha256"])  # type: ignore[index]
        for runs in loaded.values()
        for run in runs
    }
    expected_logs = sum(len(runs) for runs in loaded.values())
    if len(all_logs) != expected_logs:
        raise PolicyABError("repeatability reports are not independent process logs")

    result: dict[str, object] = {
        "measurement": "paused-debugger-call-to-post-call",
        "selector_samples_per_run": EXPECTED_SELECTOR_SAMPLES,
        "independent_processes": True,
        "variants": {},
    }
    totals_by_name: dict[str, list[int]] = {}
    for name, runs in loaded.items():
        totals = [int(run["selector"]["summary"]["total"]) for run in runs]  # type: ignore[index]
        totals_by_name[name] = totals
        mean_total = sum(totals) / len(totals)
        population_stddev = math.sqrt(
            sum((value - mean_total) ** 2 for value in totals) / len(totals)
        )
        result["variants"][name] = {  # type: ignore[index]
            "run_count": len(runs),
            "total_cycles": totals,
            "total_cycles_summary": summarize_distribution(totals).as_dict(),
            "total_range_cycles": max(totals) - min(totals),
            "total_range_percent_of_mean": round(
                (max(totals) - min(totals)) * 100.0 / mean_total, 9
            ),
            "total_population_stddev_cycles": round(population_stddev, 9),
            "evidence": [
                {
                    "report": run["report"],
                    "log": run["log"],
                }
                for run in runs
            ],
        }

    paired = [
        round((cached - guarded) * 100.0 / guarded, 9)
        for cached, guarded in zip(
            totals_by_name["asm_cached"],
            totals_by_name["c_guarded"],
            strict=True,
        )
    ]
    result["paired_asm_cached_vs_c_guarded_total_percent"] = paired
    result["paired_delta_range_percentage_points"] = round(
        max(paired) - min(paired), 9
    )
    return result


def analyze_reports(
    accepted: Path,
    dual_strict: Path,
    c_guarded: Path,
    asm_cached: Path,
    *,
    c_guarded_repeats: Sequence[Path] = (),
    asm_cached_repeats: Sequence[Path] = (),
) -> dict[str, object]:
    variants = {
        "accepted_asm": _load_variant(accepted, "accepted_asm"),
        "dual_strict": _load_variant(dual_strict, "dual_strict"),
        "c_guarded": _load_variant(c_guarded, "c_guarded"),
        "asm_cached": _load_variant(asm_cached, "asm_cached"),
    }
    qualification = _validate_comparison(variants)
    comparisons = {
        f"{candidate}_vs_{baseline}": _selector_comparison(
            variants, baseline_name=baseline, candidate_name=candidate
        )
        for baseline, candidate in (
            ("accepted_asm", "c_guarded"),
            ("accepted_asm", "asm_cached"),
            ("c_guarded", "asm_cached"),
        )
    }

    public_variants = {}
    for name, variant in variants.items():
        public_variants[name] = {
            key: variant[key]
            for key in (
                "report",
                "log",
                "identities",
                "policy_module",
                "policy",
                "selector",
            )
        }
    return {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "variants": [
                "accepted_asm",
                "dual_strict",
                "c_guarded",
                "asm_cached",
            ],
            "crossings": 4,
            "crossing_group_counts": list(EXPECTED_CROSSING_GROUPS),
            "selector_samples_per_variant": EXPECTED_SELECTOR_SAMPLES,
            "measurement": "paused-debugger-call-to-post-call",
        },
        "qualification": qualification,
        "variants": public_variants,
        "comparisons": comparisons,
        "resident_image_size": _resident_image_sizes(variants),
        "repeatability": _repeatability_evidence(
            variants,
            c_guarded_repeats=c_guarded_repeats,
            asm_cached_repeats=asm_cached_repeats,
        ),
        "limitations": [
            (
                "Cycle samples measure only selector call-site guest cycles from "
                "the CALL breakpoint through the post-CALL breakpoint; the "
                "once-per-transition descriptor-cache build is outside this span."
            ),
            (
                "Debugger pauses exclude these runs from host render timing and do "
                "not measure full handoff, SD/FatFS, validation, UART/VDP staging, "
                "rendering, host wall time, or physical-hardware latency."
            ),
            (
                "ASM_CACHED retains unreachable common C/module client code, so "
                "resident-image bytes do not estimate a pruned native-only build."
            ),
        ],
    }


def main() -> int:
    arguments = parse_arguments()
    output = arguments.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"Refusing to replace existing output: {output}")
    try:
        report = analyze_reports(
            arguments.accepted,
            arguments.dual_strict,
            arguments.c_guarded,
            arguments.asm_cached,
            c_guarded_repeats=arguments.c_guarded_repeat,
            asm_cached_repeats=arguments.asm_cached_repeat,
        )
    except (PolicyABError, ProfileEvidenceError, KeyError, TypeError) as error:
        raise SystemExit(f"regular-LOD policy A/B failed: {error}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summaries = report["variants"]
    assert isinstance(summaries, dict)
    accepted_median = summaries["accepted_asm"]["selector"]["summary"]["median"]
    guarded_median = summaries["c_guarded"]["selector"]["summary"]["median"]
    cached_median = summaries["asm_cached"]["selector"]["summary"]["median"]
    delta = report["comparisons"]["asm_cached_vs_c_guarded"]["overall_percent"][
        "median"
    ]
    print(f"Qualified regular-LOD policy A/B: {output}")
    print(
        f"accepted median={accepted_median:.1f} cycles; "
        f"guarded median={guarded_median:.1f} cycles; "
        f"cached median={cached_median:.1f} cycles; "
        f"cached-vs-guarded delta={delta:+.3f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
