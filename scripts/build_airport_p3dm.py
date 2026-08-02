#!/usr/bin/env python3
"""Build deterministic regional P3DM airport hard-surface components."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.airport_p3dm import build_airport_p3dm_corpus  # noqa: E402
from pingo_terrain.airports import (  # noqa: E402
    NASR_ARCHIVE_NAME,
    NASR_EFFECTIVE_DATE,
    load_airports,
)


DEFAULT_SOURCE = (
    ROOT
    / "data"
    / "downloads"
    / "airports"
    / f"faa-nasr-{NASR_EFFECTIVE_DATE}"
    / NASR_ARCHIVE_NAME
)
DEFAULT_OUTPUT = ROOT / "build" / "p3dm" / "bay-area-koak-proof"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        airports = load_airports(arguments.source.expanduser().resolve())
        output = arguments.output.expanduser().resolve()
        index = build_airport_p3dm_corpus(airports, output)
    except (FileNotFoundError, KeyError, StopIteration, ValueError) as error:
        print(f"AIRPORT_P3DM_ERROR {error}", file=sys.stderr)
        return 1
    index_path = output / "AIRPORTS.json"
    statistics = index["statistics"]
    print(
        "AIRPORT_P3DM",
        *(f"{key}={value}" for key, value in statistics.items()),
        f"index_sha256={sha256(index_path.read_bytes()).hexdigest()}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
