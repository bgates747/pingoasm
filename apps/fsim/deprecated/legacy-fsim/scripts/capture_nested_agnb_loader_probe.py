#!/usr/bin/env python3
"""Silently exercise the nested-family eZ80 loader in the bespoke emulator."""

from __future__ import annotations

from pathlib import Path
import tempfile

import capture_p3dm_loader_probe as capture


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/nested-agnb-loader-probe/tgt"
PROGRAM = FIXTURE / "nested-agnb-loader-probe.bin"


def main() -> int:
    # Reuse the fail-closed dump/capture implementation without changing the
    # qualified loose probe. Its runtime command currently has one fixed binary
    # name, so expose a temporary read-only alias around the nested fixture.
    with tempfile.TemporaryDirectory(prefix="pingo-nested-agnb-fixture-") as name:
        runtime = Path(name)
        (runtime / "p3dm-loader-probe.bin").symlink_to(PROGRAM)
        (runtime / "RGN").symlink_to(FIXTURE / "RGN", target_is_directory=True)
        for asset in (
            "terrain-material-ids.rgba2",
            "terrain-pattern-lookup.bin",
            "terrain-patterns.rgba2",
        ):
            (runtime / asset).symlink_to(FIXTURE / asset)
        capture.FIXTURE = runtime
        capture.PROGRAM = runtime / "p3dm-loader-probe.bin"
        return capture.main()


if __name__ == "__main__":
    raise SystemExit(main())
