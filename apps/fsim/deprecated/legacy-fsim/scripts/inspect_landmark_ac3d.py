#!/usr/bin/env python3
"""Print deterministic JSON reports for local AC3D landmark donors."""

from __future__ import annotations

import argparse
import json

from pingo_terrain.landmark_ac3d import inspect_ac3d


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="local .ac files to inspect")
    return parser.parse_args()


def main() -> None:
    reports = [inspect_ac3d(path).to_dict() for path in parse_args().paths]
    print(json.dumps(reports, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
