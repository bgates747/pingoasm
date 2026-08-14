#!/usr/bin/env python3
"""Generate the assembly phase profiles for the regular hierarchy runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

from pingo_terrain.regular_lod_runtime import emit_phase_include


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        type=Path,
        help="new or existing .inc file to receive the generated profiles",
    )
    parser.add_argument(
        "--prefix",
        default="regular_lod_phase",
        help="assembly symbol prefix (default: regular_lod_phase)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    text = emit_phase_include(args.prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="ascii")
    print(f"wrote {args.output} ({len(text.encode('ascii'))} source bytes)")


if __name__ == "__main__":
    main()
