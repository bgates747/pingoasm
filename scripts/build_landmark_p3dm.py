#!/usr/bin/env python3
"""Build the deterministic procedural Bay Area landmark P3DM corpus."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.landmark_p3dm import build_landmark_p3dm_corpus  # noqa: E402


DEFAULT_REGIONAL_MANIFEST = ROOT / "data/manifests/bay-area-2026-08-02.json"
DEFAULT_LANDMARK_MANIFEST = (
    ROOT / "data/manifests/bay-area-landmarks-2026-08-02.json"
)
DEFAULT_OUTPUT = ROOT / "build/p3dm/bay-area-koak-proof"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regional-manifest", type=Path, default=DEFAULT_REGIONAL_MANIFEST
    )
    parser.add_argument(
        "--landmark-manifest", type=Path, default=DEFAULT_LANDMARK_MANIFEST
    )
    parser.add_argument(
        "--source-root", type=Path, default=ROOT,
        help="root used to resolve manifest local_path records",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--skip-source-hash", action="store_true",
        help="skip sampled DEM file hashes (development only)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        output = arguments.output.expanduser().resolve()
        index = build_landmark_p3dm_corpus(
            output,
            source_root=arguments.source_root.expanduser().resolve(),
            regional_manifest_path=(
                arguments.regional_manifest.expanduser().resolve()
            ),
            landmark_manifest_path=(
                arguments.landmark_manifest.expanduser().resolve()
            ),
            verify_source_hashes=not arguments.skip_source_hash,
        )
    except (FileNotFoundError, KeyError, ValueError) as error:
        print(f"LANDMARK_P3DM_ERROR {error}", file=sys.stderr)
        return 1
    index_path = output / "LANDMARK.json"
    statistics = index["statistics"]
    print(
        "LANDMARK_P3DM",
        *(f"{key}={value}" for key, value in statistics.items()),
        f"index_sha256={sha256(index_path.read_bytes()).hexdigest()}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
