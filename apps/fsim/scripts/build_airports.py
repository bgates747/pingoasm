#!/usr/bin/env python3
"""Build deterministic FAA-derived airport geometry without network access."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pingo_terrain.airports import (  # noqa: E402
    NASR_ARCHIVE_NAME,
    NASR_ARCHIVE_SHA256,
    NASR_EFFECTIVE_DATE,
    TARGET_ICAO_IDS,
    airport_manifest_record,
    build_airport_geometry,
    canonical_json_bytes,
    file_sha256,
    load_airports,
)
from pingo_terrain.paths import BUILD_ROOT, DOWNLOAD_ROOT, MANIFEST_ROOT  # noqa: E402


DEFAULT_SOURCE_DIR = DOWNLOAD_ROOT / "airports" / f"faa-nasr-{NASR_EFFECTIVE_DATE}"
DEFAULT_SOURCE = DEFAULT_SOURCE_DIR / NASR_ARCHIVE_NAME
DEFAULT_README = DEFAULT_SOURCE_DIR / "README.txt"
DEFAULT_OUTPUT = BUILD_ROOT / "airports" / f"faa-nasr-{NASR_EFFECTIVE_DATE}"
DEFAULT_MANIFEST = MANIFEST_ROOT / f"faa-nasr-airports-{NASR_EFFECTIVE_DATE}.json"
README_SHA256 = "28d45a131f10b040f8e2ee16a83d414b5109c3a096e12b01c8924378b2b63a12"
README_SIZE = 24_779


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Pingo airport runway intermediates from the pinned FAA archive."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--verify-manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Tracked manifest whose selected airport records must match the source.",
    )
    return parser.parse_args()


def _verify_readme(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"FAA NASR README is missing: {path}")
    if path.stat().st_size != README_SIZE or file_sha256(path) != README_SHA256:
        raise ValueError("FAA NASR README size or checksum mismatch")


def _verify_manifest(path: Path, records: list[dict[str, object]]) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    source = manifest["source_artifacts"]["apt_csv_archive"]
    if source["sha256"] != NASR_ARCHIVE_SHA256:
        raise ValueError("tracked manifest archive checksum does not match compiler pin")
    if manifest["selected_airports"] != records:
        raise ValueError("tracked FAA airport selection differs from pinned source archive")
    return manifest


def build(args: argparse.Namespace) -> dict[str, object]:
    _verify_readme(args.readme)
    airports = load_airports(args.source)
    records = [airport_manifest_record(airport) for airport in airports]
    manifest = _verify_manifest(args.verify_manifest, records)
    args.output.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, object]] = []
    total_vertices = 0
    total_triangles = 0
    canonical_start: dict[str, object] | None = None
    for airport in airports:
        geometry = build_airport_geometry(airport)
        payload = canonical_json_bytes(geometry)
        filename = f"{airport.icao_id.lower()}.airport.json"
        destination = args.output / filename
        destination.write_bytes(payload)
        statistics = geometry["statistics"]
        assert isinstance(statistics, dict)
        total_vertices += int(statistics["vertices"])
        total_triangles += int(statistics["triangles"])
        files.append(
            {
                "airport_icao": airport.icao_id,
                "file": filename,
                "bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
                "statistics": statistics,
            }
        )
        if "canonical_start" in geometry:
            canonical_start = geometry["canonical_start"]  # type: ignore[assignment]

    catalog: dict[str, object] = {
        "schema": "pingo-terrain-airport-build-catalog",
        "version": 1,
        "source_manifest": args.verify_manifest.relative_to(PROJECT_ROOT).as_posix(),
        "source_archive_sha256": NASR_ARCHIVE_SHA256,
        "effective_date": NASR_EFFECTIVE_DATE,
        "airports": list(TARGET_ICAO_IDS),
        "files": files,
        "statistics": {
            "airports": len(airports),
            "runways": sum(len(airport.runways) for airport in airports),
            "meshes": len(airports) * 2,
            "vertices": total_vertices,
            "triangles": total_triangles,
        },
        "canonical_start": canonical_start,
        "render_policy": manifest["render_policy"],
    }
    catalog_payload = canonical_json_bytes(catalog)
    (args.output / "catalog.json").write_bytes(catalog_payload)
    return {
        "output": args.output,
        "catalog_sha256": sha256(catalog_payload).hexdigest(),
        **catalog["statistics"],  # type: ignore[arg-type]
    }


def main() -> int:
    try:
        summary = build(parse_args())
    except (FileNotFoundError, KeyError, ValueError) as error:
        print(f"AIRPORT_BUILD_ERROR {error}", file=sys.stderr)
        return 1
    print(
        "AIRPORT_BUILD",
        *(f"{key}={value}" for key, value in summary.items()),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
