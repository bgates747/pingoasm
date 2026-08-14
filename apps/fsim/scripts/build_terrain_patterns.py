#!/usr/bin/env python3
"""Build deterministic Berkeley terrain flat-pattern resources offline."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.flat_patterns import (  # noqa: E402
    compile_patterns,
    write_compiled_patterns,
)
from pingo_terrain.materials import BERKELEY_TERRAIN_MATERIALS  # noqa: E402


DEFAULT_OUTPUT = ROOT / "build/patterns"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile 4x4 RGBA2222 patterns for Berkeley terrain colors."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = arguments()
    compiled = compile_patterns(BERKELEY_TERRAIN_MATERIALS)
    patterns, lookup, metadata = write_compiled_patterns(compiled, args.output)
    three_color_entries = sum(
        bool(entry["used_three_colors"])
        for entry in compiled.metadata["entries"]
    )
    print(
        "TERRAIN_PATTERNS",
        f"materials={len(BERKELEY_TERRAIN_MATERIALS)}",
        f"bands={compiled.metadata['illumination_band_count']}",
        f"lookup_bytes={len(compiled.lookup)}",
        f"patterns={compiled.pattern_count}",
        f"pattern_bytes={len(compiled.patterns)}",
        f"three_color_entries={three_color_entries}",
        f"patterns_path={patterns}",
        f"lookup_path={lookup}",
        f"metadata_path={metadata}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

