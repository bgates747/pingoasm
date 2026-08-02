#!/usr/bin/env python3
"""Audit eZ80 assembly for ADL fixed-width and stale-upper-byte hazards."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.adl_width import (  # noqa: E402
    assembly_paths,
    audit_paths,
    include_closure,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--default-adl", type=int, choices=(0, 1), default=1,
        help="mode inherited by includes without their own .assume (default: 1)",
    )
    parser.add_argument(
        "--show-review", action="store_true",
        help="also list register-indirect and unresolved-width accesses",
    )
    parser.add_argument(
        "--fail-review", action="store_true",
        help="treat unresolved/indirect accesses as failures",
    )
    parser.add_argument(
        "--follow-includes", action="store_true",
        help="treat each path as an entry file and recursively audit includes",
    )
    return parser.parse_args()


def describe(access) -> str:
    storage = ""
    if access.storage is not None:
        storage = (
            f"; target {access.storage.directive} at "
            f"{access.storage.path}:{access.storage.line}"
        )
    return (
        f"{access.path}:{access.line}: {access.classification}: "
        f"{access.direction} {access.data_bits}-bit {access.register.upper()} "
        f"via ({access.expression}){storage}\n"
        f"    {access.source.strip()}"
    )


def main() -> int:
    arguments = parse_arguments()
    paths = (
        include_closure(arguments.paths)
        if arguments.follow_includes
        else assembly_paths(arguments.paths)
    )
    result = audit_paths(paths, default_adl=arguments.default_adl)
    for access in result.hazards:
        print(describe(access))
    if arguments.show_review:
        for access in result.review_items:
            print(describe(access))

    counts = Counter(access.classification for access in result.accesses)
    print(
        "ADL width audit: "
        f"{len(paths)} files, {len(result.accesses)} wide memory accesses, "
        f"{len(result.hazards)} definite width hazards, "
        f"{len(result.review_items)} indirect/unresolved review items"
    )
    if counts:
        print("classifications: " + ", ".join(
            f"{name}={counts[name]}" for name in sorted(counts)
        ))
    return 1 if result.hazards or (
        arguments.fail_review and result.review_items
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
