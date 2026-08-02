#!/usr/bin/env python3
"""Build the proven flat Jet and chase-view integration payload."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.aircraft_asset import DEFAULT_OUTPUT_DIR, build  # noqa: E402


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    manifest = build(arguments.output.expanduser())
    output = arguments.output.expanduser().resolve()
    print(
        "AIRCRAFT_ASSET",
        f"vertices={manifest['vertices']}",
        f"triangles={manifest['triangles']}",
        f"scale={manifest['object_scale_q8_8']}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
