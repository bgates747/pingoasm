#!/usr/bin/env python3
"""Report independent X, Y, and Z bounds from OBJ vertex records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


AXES = ("x", "y", "z")


def read_bounds(path: Path) -> dict[str, object]:
    minimum = [float("inf")] * 3
    maximum = [float("-inf")] * 3
    vertex_count = 0

    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            fields = line.split()
            if not fields or fields[0] != "v":
                continue
            if len(fields) < 4:
                raise ValueError(f"{path}:{line_number}: incomplete vertex record")
            try:
                vertex = [float(value) for value in fields[1:4]]
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid vertex coordinate"
                ) from exc
            for index, value in enumerate(vertex):
                minimum[index] = min(minimum[index], value)
                maximum[index] = max(maximum[index], value)
            vertex_count += 1

    if vertex_count == 0:
        raise ValueError(f"{path}: no vertex records found")

    return {
        "path": str(path),
        "vertices": vertex_count,
        "minimum": dict(zip(AXES, minimum)),
        "maximum": dict(zip(AXES, maximum)),
        "span": {
            axis: maximum[index] - minimum[index]
            for index, axis in enumerate(AXES)
        },
        "center": {
            axis: (minimum[index] + maximum[index]) / 2
            for index, axis in enumerate(AXES)
        },
    }


def format_number(value: float) -> str:
    return f"{value:.6f}"


def print_table(results: list[dict[str, object]]) -> None:
    print(
        "mesh\tvertices"
        "\tmin_x\tmax_x\tmin_y\tmax_y\tmin_z\tmax_z"
        "\tspan_x\tspan_y\tspan_z"
    )
    for result in results:
        minimum = result["minimum"]
        maximum = result["maximum"]
        span = result["span"]
        assert isinstance(minimum, dict)
        assert isinstance(maximum, dict)
        assert isinstance(span, dict)
        values = [
            Path(str(result["path"])).name,
            str(result["vertices"]),
            format_number(minimum["x"]),
            format_number(maximum["x"]),
            format_number(minimum["y"]),
            format_number(maximum["y"]),
            format_number(minimum["z"]),
            format_number(maximum["z"]),
            format_number(span["x"]),
            format_number(span["y"]),
            format_number(span["z"]),
        ]
        print("\t".join(values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meshes", nargs="+", type=Path, help="OBJ files to inspect")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of a tab-separated table",
    )
    args = parser.parse_args()

    results = [read_bounds(path) for path in args.meshes]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
