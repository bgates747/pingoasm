#!/usr/bin/env python3
"""Write the fixed KOAK west-transition JSON and eZ80 include witnesses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pingo_terrain.family_transition import (  # noqa: E402
    assembly_include,
    build_fixed_west_transition,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = build_fixed_west_transition()
    (output / "family-plan.inc").write_text(
        assembly_include(plan), encoding="utf-8"
    )
    (output / "family-plan.json").write_text(
        json.dumps(plan.to_json_record(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "FAMILY_TRANSITION_PLAN",
        f"loads={len(plan.load_entries)}",
        f"families={len(plan.required_families)}",
        f"output={output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
