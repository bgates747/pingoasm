#!/usr/bin/env python3
"""Qualify the two production regular-LOD loader error paths in fresh guests.

This gate runs the installed canonical program with its tracked canonical
symbols and the stock Console8 MOS.  It deliberately does not collect timing
or compare historical siblings: one fresh process corrupts DATA and proves
error 9 with no mesh publication, and a second gives an invalid position index
an otherwise valid CRC and proves error 10 before CRC entry.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import build_regular_lod_manager_survey as builder
import capture_regular_lod_manager_survey as regular_capture
import capture_terrain_manager_survey as survey
import profile_regular_lod_crc_register_sibling as crc_profile
import trace_koak_input as input_trace


ROOT = Path(__file__).resolve().parent.parent
REPORT_NAME = "regular-lod-crc-production-errors.json"
SCHEMA = "pingo-terrain-regular-lod-crc-production-errors-v1"
NEGATIVE_KINDS = ("crc-data", "index-valid-crc")
EXPECTED_ERRORS = {"crc-data": 9, "index-valid-crc": 10}
RUNTIME_PROGRAM = regular_capture.PROGRAM
CANONICAL_PROGRAM = builder.PROGRAM
CANONICAL_LISTING = builder.LISTING
CANONICAL_SYMBOLS = builder.SYMBOLS
MANAGER_MANIFEST = regular_capture.MANIFEST
WORLD_MANIFEST = regular_capture.WORLD
EMULATOR_BYTES = 1_895_592
EMULATOR_SHA256 = (
    "832f6f8a18e4608f420381124ba33c4b550a034eb3973facdd9e8108fef8264b"
)
DIAGNOSTIC_VDP_BYTES = 11_404_816
DIAGNOSTIC_VDP_SHA256 = (
    "01a76a69fe9144707fef360a5551c183c2653d3020aa49d05bd93602cb37b6a9"
)
STOCK_MOS_BYTES = 81_072
STOCK_MOS_SHA256 = (
    "5fbacb749ee037f0428aeac39817b5a6d465adc020f92d4020bb7dcb046d39fe"
)


class ProductionCrcError(ValueError):
    """A canonical identity or guest error-path invariant changed."""


@dataclass(frozen=True, slots=True)
class ValidatedInputs:
    program: Path
    symbols: Path
    vdp: Path
    identity: dict[str, object]


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program",
        type=Path,
        required=True,
        help="installed production P3DRGL.BIN",
    )
    parser.add_argument(
        "--symbols",
        type=Path,
        required=True,
        help="tracked symbols from the same canonical CRC4 assembly",
    )
    parser.add_argument(
        "--vdp-module",
        type=Path,
        default=survey.DEFAULT_VDP,
        help="P3DM diagnostic PingoWolf VDP module",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, requested: Path | None = None) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ProductionCrcError(f"missing artifact: {resolved}")
    try:
        key = str(resolved.relative_to(ROOT))
    except ValueError:
        key = str(resolved)
    result: dict[str, object] = {
        "path": key,
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }
    if requested is not None:
        result["requested_path"] = str(requested.expanduser())
    return result


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProductionCrcError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ProductionCrcError(f"JSON root is not an object: {path}")
    return value


def require_exact(
    path: Path,
    *,
    expected_path: Path,
    expected_bytes: int,
    expected_sha256: str,
    description: str,
) -> Path:
    requested = path.expanduser()
    resolved = requested.resolve()
    canonical = expected_path.resolve()
    if resolved != canonical:
        raise ProductionCrcError(
            f"{description} is not the production artifact: "
            f"{resolved} != {canonical}"
        )
    if not resolved.is_file() or resolved.is_symlink():
        raise ProductionCrcError(f"{description} is not a regular file: {resolved}")
    actual = (resolved.stat().st_size, sha256(resolved))
    expected = (expected_bytes, expected_sha256)
    if actual != expected:
        raise ProductionCrcError(
            f"{description} identity changed: {actual!r} != {expected!r}"
        )
    return resolved


def require_content_identity(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    description: str,
) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ProductionCrcError(f"missing {description}: {resolved}")
    actual = (resolved.stat().st_size, sha256(resolved))
    expected = (expected_bytes, expected_sha256)
    if actual != expected:
        raise ProductionCrcError(
            f"{description} identity changed: {actual!r} != {expected!r}"
        )
    return resolved


def validate_inputs(
    program_argument: Path,
    symbols_argument: Path,
    vdp_argument: Path,
) -> ValidatedInputs:
    program = require_exact(
        program_argument,
        expected_path=RUNTIME_PROGRAM,
        expected_bytes=builder.CURRENT_PROGRAM_BYTES,
        expected_sha256=builder.CURRENT_PROGRAM_SHA256,
        description="installed production program",
    )
    symbols = require_exact(
        symbols_argument,
        expected_path=CANONICAL_SYMBOLS,
        expected_bytes=builder.CURRENT_SYMBOLS_BYTES,
        expected_sha256=builder.CURRENT_SYMBOLS_SHA256,
        description="canonical production symbols",
    )
    canonical_program = require_exact(
        CANONICAL_PROGRAM,
        expected_path=CANONICAL_PROGRAM,
        expected_bytes=builder.CURRENT_PROGRAM_BYTES,
        expected_sha256=builder.CURRENT_PROGRAM_SHA256,
        description="canonical production program",
    )
    canonical_listing = require_exact(
        CANONICAL_LISTING,
        expected_path=CANONICAL_LISTING,
        expected_bytes=builder.CURRENT_LISTING_BYTES,
        expected_sha256=builder.CURRENT_LISTING_SHA256,
        description="canonical production listing",
    )
    if program.read_bytes() != canonical_program.read_bytes():
        raise ProductionCrcError(
            "installed production program differs from the canonical program"
        )

    manager = load_json(MANAGER_MANIFEST)
    if manager.get("schema") != builder.MANAGER_SCHEMA:
        raise ProductionCrcError("production MANAGER schema changed")
    binary = manager.get("binary")
    expected_binary = {
        "path": str(RUNTIME_PROGRAM.resolve()),
        "bytes": builder.CURRENT_PROGRAM_BYTES,
        "sha256": builder.CURRENT_PROGRAM_SHA256,
    }
    if not isinstance(binary, Mapping) or dict(binary) != expected_binary:
        raise ProductionCrcError(
            f"production MANAGER binary witness changed: {binary!r}"
        )
    loader_policy = manager.get("manager", {})
    if not isinstance(loader_policy, Mapping) or (
        loader_policy.get("loader_crc32") != builder.LOADER_CRC32_POLICY
    ):
        raise ProductionCrcError("production MANAGER CRC4 witness changed")

    vdp = input_trace.require_file(vdp_argument, "diagnostic VDP module")
    survey.require_diagnostic_vdp(vdp)
    emulator = input_trace.require_file(input_trace.FAB_BINARY, "Fab executable")
    stock_mos = input_trace.require_file(input_trace.MOS_BINARY, "stock MOS image")
    require_content_identity(
        emulator,
        expected_bytes=EMULATOR_BYTES,
        expected_sha256=EMULATOR_SHA256,
        description="qualified Fab executable",
    )
    require_content_identity(
        vdp,
        expected_bytes=DIAGNOSTIC_VDP_BYTES,
        expected_sha256=DIAGNOSTIC_VDP_SHA256,
        description="qualified diagnostic VDP module",
    )
    require_content_identity(
        stock_mos,
        expected_bytes=STOCK_MOS_BYTES,
        expected_sha256=STOCK_MOS_SHA256,
        description="stock Console8 MOS image",
    )
    world = input_trace.require_file(WORLD_MANIFEST, "regular hierarchy WORLD")
    layout = crc_profile.resolve_layout(program, symbols)
    identity = {
        "program": artifact(program, requested=program_argument),
        "canonical_artifact_set": {
            "program": artifact(canonical_program),
            "listing": artifact(canonical_listing),
            "symbols": artifact(symbols, requested=symbols_argument),
        },
        "manager_manifest": artifact(MANAGER_MANIFEST),
        "world_manifest": artifact(world),
        "loader_crc32": dict(builder.LOADER_CRC32_POLICY),
        "layout": layout.as_dict(),
        "emulator": artifact(emulator),
        "stock_mos": artifact(stock_mos),
        "vdp": artifact(vdp, requested=vdp_argument),
    }
    return ValidatedInputs(program, symbols, vdp, identity)


def validate_negative_results(
    runs: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    if len(runs) != len(NEGATIVE_KINDS):
        raise ProductionCrcError(
            f"guest process count changed: {len(runs)} != {len(NEGATIVE_KINDS)}"
        )
    result: dict[str, dict[str, object]] = {}
    for expected_kind, run in zip(NEGATIVE_KINDS, runs, strict=True):
        kind = run.get("kind")
        if kind != expected_kind or kind in result:
            raise ProductionCrcError(
                f"guest negative order changed: {kind!r} != {expected_kind!r}"
            )
        expected_error = EXPECTED_ERRORS[expected_kind]
        if (
            run.get("fresh_process") is not True
            or run.get("guest_executed") is not True
            or run.get("guest_error") != expected_error
            or run.get("mesh_publications_before_rejection") != 0
            or run.get("cold_endpoint_reached") is not False
            or run.get("emulator_exit_status") != 0
            or run.get("first_breakpoint") != run.get("return_error_address")
        ):
            raise ProductionCrcError(
                f"guest {expected_kind} witness is incomplete: {run!r}"
            )
        if expected_kind == "index-valid-crc" and (
            run.get("first_breakpoint") == run.get("crc_entry_address")
        ):
            raise ProductionCrcError("error 10 no longer precedes CRC entry")
        result[expected_kind] = dict(run)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.timeout <= 0:
        raise ProductionCrcError("--timeout must be positive")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ProductionCrcError(f"refusing to replace existing output: {output}")

    inputs = validate_inputs(args.program, args.symbols, args.vdp_module)
    tool_identity = {
        "qualifier": artifact(Path(__file__)),
        "canonical_builder": artifact(Path(builder.__file__).resolve()),
        "negative_runner": artifact(Path(crc_profile.__file__).resolve()),
    }
    output.mkdir(parents=True)
    runs = [
        crc_profile.run_negative(
            kind=kind,
            program=inputs.program,
            symbols_path=inputs.symbols,
            vdp=inputs.vdp,
            output=output,
            timeout=args.timeout,
        )
        for kind in NEGATIVE_KINDS
    ]
    negatives = validate_negative_results(runs)

    final_inputs = validate_inputs(args.program, args.symbols, args.vdp_module)
    if final_inputs.identity != inputs.identity:
        raise ProductionCrcError("production input identity changed during the gate")
    if tool_identity != {
        "qualifier": artifact(Path(__file__)),
        "canonical_builder": artifact(Path(builder.__file__).resolve()),
        "negative_runner": artifact(Path(crc_profile.__file__).resolve()),
    }:
        raise ProductionCrcError("qualifier implementation changed during the gate")

    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "production_program": True,
            "canonical_symbols": True,
            "stock_mos": True,
            "qualified_emulator_vdp_mos_pinned": True,
            "fresh_process_per_negative": True,
            "process_count": 2,
            "timing_profile": False,
        },
        "identity": inputs.identity,
        "tools": tool_identity,
        "negative_qualification": {
            "crc_data_guest_error_9_no_publication": negatives["crc-data"],
            "invalid_index_valid_crc_guest_error_10_before_crc": negatives[
                "index-valid-crc"
            ],
        },
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Production CRC error-path qualification passed: {report_path}")
    print("fresh_processes=2 error9_no_publication=True error10_before_crc=True")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProductionCrcError, crc_profile.CrcSiblingProfileError) as error:
        raise SystemExit(
            f"Production CRC error-path qualification failed: {error}"
        ) from error
