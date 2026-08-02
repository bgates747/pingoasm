#!/usr/bin/env python3
"""Build the bounded multi-record AGNB selected-loader probe."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
LOOSE_PROBE = ROOT / "fixtures/p3dm-loader-probe"
FIXTURE = ROOT / "fixtures/nested-agnb-loader-probe"
SOURCE = FIXTURE / "src"
TARGET = FIXTURE / "tgt"
RUNTIME_PATH = Path("RGN/00/00.AGN")
SELECTED_INDEX = 6

sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.nested_agnb import RecordIdentity, select_record  # noqa: E402
from pingo_terrain.p3dm import parse_container  # noqa: E402
from pingo_terrain.regional_lod import make_bundle, parse_bundle  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def make_probe_records():
    base = parse_container(
        (LOOSE_PROBE / "tgt/TRN/L0/00/0C.AGN").read_bytes()
    )
    records = []
    for index in range(10):
        if index == SELECTED_INDEX:
            records.append(base)
            continue
        if index == 0:
            lod, tile_x, tile_y = 2, 0, 0
        elif index == 1:
            lod, tile_x, tile_y = 1, 0, 0
        else:
            lod, tile_x, tile_y = 0, index - 2, 0
        meta = replace(
            base.meta,
            lod=lod,
            tile_x=tile_x,
            tile_y=tile_y,
            center_east_m=tile_x * 512 + 256,
            center_north_m=tile_y * 512 + 256,
        )
        records.append(replace(base, meta=meta))
    return tuple(records)


def main() -> int:
    records = make_probe_records()
    bundle = make_bundle(records)
    parsed, spans = parse_bundle(bundle)
    if parsed != records:
        raise SystemExit("nested AGNB probe bundle did not round-trip")
    if len(bundle) <= 16_384:
        raise SystemExit("probe family must exceed the one-file staging window")

    selected = select_record(
        BytesIO(bundle), RecordIdentity.from_tile(records[SELECTED_INDEX])
    )
    if selected.tile != records[SELECTED_INDEX]:
        raise SystemExit("bounded reader selected the wrong family record")
    if selected.bytes_read >= len(bundle):
        raise SystemExit("bounded reader unexpectedly read the whole family")

    destination = TARGET / RUNTIME_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bundle)
    for name in (
        "terrain-material-ids.rgba2",
        "terrain-pattern-lookup.bin",
        "terrain-patterns.rgba2",
    ):
        shutil.copy2(LOOSE_PROBE / "tgt" / name, TARGET / name)

    output = TARGET / "nested-agnb-loader-probe.bin"
    subprocess.run(
        ["ez80asm", "nested-agnb-loader-probe.asm", "../tgt/nested-agnb-loader-probe.bin"],
        cwd=SOURCE,
        check=True,
    )
    report = {
        "schema": "pingo-terrain-nested-agnb-loader-probe-v1",
        "runtime_path": RUNTIME_PATH.as_posix(),
        "family_bytes": len(bundle),
        "family_sha256": sha256(destination),
        "records": len(records),
        "selected_index": selected.record_index,
        "selected_list_offset": selected.list_offset,
        "selected_data_offset": selected.data_offset,
        "selected_data_bytes": selected.data_bytes,
        "bounded_bytes_read": selected.bytes_read,
        "binary_bytes": output.stat().st_size,
        "binary_sha256": sha256(output),
        "record_spans": [
            {
                "index": span.record_index,
                "list_offset": span.list_offset,
                "list_bytes": span.list_bytes,
                "data_offset": span.data_offset,
                "data_bytes": span.data_bytes,
            }
            for span in spans
        ],
    }
    (TARGET / "probe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "NESTED_AGNB_LOADER_PROBE",
        f"family={len(bundle)}",
        f"records={len(records)}",
        f"selected={selected.record_index}",
        f"read={selected.bytes_read}",
        f"binary_sha256={report['binary_sha256']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
