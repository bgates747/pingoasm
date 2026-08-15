#!/usr/bin/env python3
"""Generate regular-LOD phase profiles and optional handoff recipes."""

from __future__ import annotations

import argparse
from pathlib import Path

from pingo_terrain.regular_lod_runtime import (
    emit_phase_include,
    emit_transition_include,
)


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
        help="phase-profile symbol prefix (default: regular_lod_phase)",
    )
    parser.add_argument(
        "--transition-prefix",
        default="regular_lod_transition",
        help=(
            "transition-recipe symbol prefix "
            "(default: regular_lod_transition)"
        ),
    )
    parser.add_argument(
        "--transition-output",
        type=Path,
        help=(
            "optional separate .inc file for full-owner transition recipes; "
            "the positional output remains phase-only for rollback stability"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    text = emit_phase_include(args.prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="ascii")
    print(f"wrote {args.output} ({len(text.encode('ascii'))} source bytes)")
    if args.transition_output is not None:
        if args.transition_output.resolve() == args.output.resolve():
            raise SystemExit("transition output must differ from phase output")
        transition_text = emit_transition_include(args.transition_prefix)
        args.transition_output.parent.mkdir(parents=True, exist_ok=True)
        args.transition_output.write_text(transition_text, encoding="ascii")
        print(
            f"wrote {args.transition_output} "
            f"({len(transition_text.encode('ascii'))} source bytes)"
        )


if __name__ == "__main__":
    main()
