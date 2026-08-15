#!/usr/bin/env python3
"""Preserve the exact MANAGER manifest used by the frozen CRC timing reports.

The snapshot is small ignored evidence, not a tracked application artifact.
It lets historical analyzers bind the old report identity after the live
manager is regenerated for another application/CRC policy.  The selected
initial-view record corpus is independently revalidated; top-level application
binary and loader-policy context are historical metadata, not current inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import build_regular_lod_mos_uart_thre_sibling as mos_builder


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = mos_builder.MANAGER_MANIFEST
DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-historical-manager-witness-v1"
)
SNAPSHOT_NAME = "MANAGER.historical-crc1.json"
REPORT_NAME = "WITNESS.json"
SCHEMA = "pingo-terrain-regular-lod-historical-manager-witness-v1"
HISTORICAL_MANAGER_BYTES = 146_178
HISTORICAL_MANAGER_SHA256 = (
    "b566b7c13f45b93d7abe4b5252cee62a6e150d8e979f435185b74cc8b434c8ea"
)
HISTORICAL_REPORT_IDENTITY = {
    "key": "build/p3dm/bay-area-regular-n1-hierarchy/MANAGER.json",
    "bytes": HISTORICAL_MANAGER_BYTES,
    "sha256": HISTORICAL_MANAGER_SHA256,
}


class HistoricalManagerWitnessError(RuntimeError):
    """The historical snapshot or its semantic cold-corpus binding changed."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, key: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise HistoricalManagerWitnessError(f"missing or unsafe artifact: {path}")
    return {"key": key, "bytes": path.stat().st_size, "sha256": sha256(path)}


def load_canonical_json(path: Path, description: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise HistoricalManagerWitnessError(f"missing {description}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HistoricalManagerWitnessError(f"unreadable {description}: {path}") from error
    if not isinstance(value, dict):
        raise HistoricalManagerWitnessError(f"{description} root is not an object")
    canonical = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if path.read_bytes() != canonical:
        raise HistoricalManagerWitnessError(f"{description} is not canonical JSON")
    return value


def require_historical_manager(path: Path) -> bytes:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise HistoricalManagerWitnessError("historical MANAGER is absent or unsafe")
    path = path.resolve()
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != HISTORICAL_MANAGER_BYTES or digest != HISTORICAL_MANAGER_SHA256:
        raise HistoricalManagerWitnessError(
            "historical MANAGER identity changed: "
            f"bytes={len(payload)} sha256={digest}"
        )
    return payload


def validate_witness(
    directory: Path,
    *,
    runtime_root: Path = mos_builder.RUNTIME_FIXTURE,
) -> tuple[Path, Path, dict[str, object]]:
    directory = directory.expanduser().resolve()
    snapshot = directory / SNAPSHOT_NAME
    receipt_path = directory / REPORT_NAME
    require_historical_manager(snapshot)
    receipt = load_canonical_json(receipt_path, "historical MANAGER receipt")
    if receipt.get("schema") != SCHEMA or receipt.get("qualified") is not True:
        raise HistoricalManagerWitnessError("historical MANAGER receipt is not qualified")
    if receipt.get("historical_report_identity") != HISTORICAL_REPORT_IDENTITY:
        raise HistoricalManagerWitnessError("historical report identity binding changed")
    expected_artifact = {
        "key": f"artifacts/{SNAPSHOT_NAME}",
        "bytes": HISTORICAL_MANAGER_BYTES,
        "sha256": HISTORICAL_MANAGER_SHA256,
    }
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping) or artifacts.get("manager_manifest") != expected_artifact:
        raise HistoricalManagerWitnessError("historical snapshot artifact binding changed")
    semantic = mos_builder.validate_runtime_corpus(
        manifest_path=snapshot,
        root=runtime_root,
    )
    if receipt.get("manager_semantic_witness") != semantic:
        raise HistoricalManagerWitnessError("historical manager semantic witness changed")
    return snapshot, receipt_path, receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    source_root = source.parent
    if output == source_root or source_root in output.parents or output in source_root.parents:
        raise HistoricalManagerWitnessError(
            "output must not equal, contain, or descend from the source tree"
        )
    if output.exists():
        raise HistoricalManagerWitnessError(f"refusing to replace existing output: {output}")
    payload = require_historical_manager(source)
    semantic = mos_builder.validate_runtime_corpus(
        manifest_path=source,
        root=mos_builder.RUNTIME_FIXTURE,
    )
    output.mkdir(parents=True)
    snapshot = output / SNAPSHOT_NAME
    snapshot.write_bytes(payload)
    receipt = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "ignored_evidence_only": True,
            "live_manager_modified": False,
            "application_binary_copied": False,
            "emulator_run": False,
        },
        "historical_report_identity": HISTORICAL_REPORT_IDENTITY,
        "artifacts": {
            "manager_manifest": artifact(
                snapshot, key=f"artifacts/{SNAPSHOT_NAME}"
            )
        },
        "manager_semantic_witness": semantic,
        "purpose": (
            "evidence-local binding for the exact MANAGER used by the frozen "
            "accepted+TEMT and CRC-nibble+THRE reports"
        ),
    }
    receipt_path = output / REPORT_NAME
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_witness(output)
    print(f"Historical regular-LOD MANAGER witness passed: {receipt_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HistoricalManagerWitnessError, mos_builder.MosUartThreBuildError) as error:
        raise SystemExit(f"historical MANAGER witness failed: {error}") from error
