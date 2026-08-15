#!/usr/bin/env python3
"""Render the backend-neutral cockpit panel scene to an RGBA PNG."""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pingo_terrain.cockpit_panel import validate_panel_dimensions  # noqa: E402
from pingo_terrain.cockpit_panel_pillow import render_panel  # noqa: E402


DEFAULT_SIZE = (1280, 368)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "build" / "visualization"


def parse_size(value: str) -> tuple[int, int]:
    """Parse WIDTHxHEIGHT and enforce the panel's exact 80:23 aspect."""

    fields = value.lower().split("x")
    if len(fields) != 2:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT")
    try:
        width, height = (int(field, 10) for field in fields)
        validate_panel_dimensions(width, height)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return width, height


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Draw the static 2D flight panel from its VDP-compatible scene. "
            "Output dimensions must preserve the exact 80:23 aspect ratio."
        )
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=DEFAULT_SIZE,
        metavar="WIDTHxHEIGHT",
        help="exact output dimensions (default: 1280x368)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="destination PNG (default: build/visualization/cockpit-panel-<size>.png)",
    )
    parser.add_argument(
        "--legacy-squash",
        action="store_true",
        help="preview the source artwork's measured 0.86 gauge-height artifact",
    )
    parser.add_argument(
        "--supersample",
        type=int,
        choices=range(1, 9),
        default=1,
        metavar="N",
        help="review-only antialias factor; 1 preserves native RGB222 edges",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing destination",
    )
    return parser.parse_args(argv)


def render_png_bytes(args: argparse.Namespace) -> tuple[bytes, int, int]:
    width, height = args.size
    image = render_panel(
        width,
        height,
        legacy_squash=args.legacy_squash,
        supersample=args.supersample,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue(), width, height


def default_output(width: int, height: int, legacy_squash: bool) -> Path:
    variant = "legacy-squash" if legacy_squash else "round"
    return DEFAULT_OUTPUT_DIR / f"cockpit-panel-{variant}-{width}x{height}.png"


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    payload, width, height = render_png_bytes(args)
    destination = args.output or default_output(width, height, args.legacy_squash)
    destination = destination.expanduser().resolve()
    if destination.exists() and not args.force:
        print(
            f"COCKPIT_PANEL_ERROR output exists (use --force): {destination}",
            file=sys.stderr,
        )
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    print(
        "COCKPIT_PANEL",
        f"width={width}",
        f"height={height}",
        f"legacy_squash={int(args.legacy_squash)}",
        f"supersample={args.supersample}",
        f"bytes={len(payload)}",
        f"sha256={sha256(payload).hexdigest()}",
        f"output={destination}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
