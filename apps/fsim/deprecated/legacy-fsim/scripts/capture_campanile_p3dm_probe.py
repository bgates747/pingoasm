#!/usr/bin/env python3
"""Silently capture and validate the isolated live Campanile P3DM probe."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil
import sys
import tempfile

import capture_p3dm_loader_probe as capture


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/campanile-p3dm-probe/tgt"
MANIFEST = FIXTURE / "probe.json"
PROGRAM = FIXTURE / "CAMPTEST.BIN"
WIDTH = 320
HEIGHT = 240


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def expected_assets(manifest: dict) -> dict[str, dict[str, int | str]]:
    return {
        manifest["assembly"]["program_runtime_name"]: {
            "bytes": manifest["assembly"]["bytes"],
            "sha256": manifest["assembly"]["sha256"],
        },
        manifest["component"]["runtime_name"]: {
            "bytes": manifest["component"]["bytes"],
            "sha256": manifest["component"]["sha256"],
        },
        manifest["palette"]["runtime_name"]: {
            "bytes": manifest["palette"]["bytes"],
            "sha256": manifest["palette"]["sha256"],
        },
    }


def verify_assets(directory: Path, manifest: dict) -> dict[str, dict[str, int | str]]:
    witnessed: dict[str, dict[str, int | str]] = {}
    for name, expected in expected_assets(manifest).items():
        path = directory / name
        if not path.is_file():
            raise SystemExit(f"missing Campanile runtime asset: {path}")
        actual = {"bytes": path.stat().st_size, "sha256": file_sha256(path)}
        if actual != expected:
            raise SystemExit(
                f"Campanile runtime asset disagrees with probe.json: {name}"
            )
        witnessed[name] = actual
    return witnessed


def output_argument(arguments: list[str]) -> Path:
    for index, argument in enumerate(arguments):
        if argument == "--output" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).expanduser().resolve()
        if argument.startswith("--output="):
            return Path(argument.partition("=")[2]).expanduser().resolve()
    raise SystemExit("capture requires --output")


def validate_stream_log(log: str, manifest: dict) -> None:
    component = manifest["component"]
    expected = (
        "PINGO_STREAM mesh_replace=ok stage=29696 mid=1 "
        f"bytes={component['data_bytes']} "
        f"v={component['vertices']} "
        f"i={component['position_indices']} "
        f"u={component['uvs']} "
        f"t={component['uv_indices']}"
    )
    if expected not in log:
        raise SystemExit("capture lacks the exact Campanile command-50 witness")
    if "PINGO_STREAM object_active=ok oid=1 active=1" not in log:
        raise SystemExit("capture lacks Campanile object activation")
    if "CAMPANILE FAIL" in log or "replace_mesh_from_buffer:" in log:
        raise SystemExit("capture log contains a Campanile publication failure")


def analyze_silhouette(raw: bytes) -> dict[str, object]:
    if len(raw) != WIDTH * HEIGHT:
        raise SystemExit(f"unexpected Campanile target byte count: {len(raw)}")
    occupied = [index for index, value in enumerate(raw) if value]
    if not occupied:
        raise SystemExit("Campanile target has no visible silhouette")
    xs = [index % WIDTH for index in occupied]
    ys = [index // WIDTH for index in occupied]
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    box_width = bounds[2] - bounds[0] + 1
    box_height = bounds[3] - bounds[1] + 1
    colors = sorted(set(raw) - {0})
    center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]

    # These are intentionally semantic, not a module-specific frame hash:
    # enough material/color variation and a tall, centered, unclipped object
    # make the intended recognition view materially stronger than nonempty.
    if len(occupied) < 750:
        raise SystemExit("Campanile silhouette is too small to qualify")
    if box_width < 18 or box_height < 70 or box_height <= box_width:
        raise SystemExit("Campanile silhouette lacks the intended tall oblique view")
    if bounds[0] <= 2 or bounds[1] <= 2 or bounds[2] >= WIDTH - 3 or bounds[3] >= HEIGHT - 3:
        raise SystemExit("Campanile silhouette is clipped by the viewport")
    if abs(center[0] - WIDTH / 2) > 48 or abs(center[1] - HEIGHT / 2) > 40:
        raise SystemExit("Campanile silhouette is not locally centered")
    if len(colors) < 3:
        raise SystemExit("Campanile scene lacks flat-palette material diversity")
    return {
        "bounds_xyxy": bounds,
        "width": box_width,
        "height": box_height,
        "center_xy": center,
        "occupied_pixels": len(occupied),
        "nonzero_rgba2222_values": colors,
        "nonzero_rgba2222_value_count": len(colors),
        "qualification": "tall centered unclipped oblique landmark silhouette",
    }


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = output_argument(sys.argv[1:])
    verify_assets(FIXTURE, manifest)
    program_name = manifest["assembly"]["program_runtime_name"]
    if program_name != "CAMPTEST.BIN":
        raise SystemExit("probe manifest does not select the qualified 8.3 program")

    # Stage private byte-for-byte copies so the evidence binds the exact
    # immutable program, component and palette consumed by this emulator run.
    with tempfile.TemporaryDirectory(prefix="pingo-campanile-fixture-") as name:
        runtime = Path(name)
        for asset in expected_assets(manifest):
            shutil.copy2(FIXTURE / asset, runtime / asset)
        staged_assets = verify_assets(runtime, manifest)
        capture.FIXTURE = runtime
        capture.PROGRAM = runtime / program_name
        result = capture.main()
        log_path = output / "emulator.log"
        validate_stream_log(
            log_path.read_text(encoding="utf-8", errors="replace"), manifest
        )
        # Detect even a concurrent or accidental mutation after execution.
        if verify_assets(runtime, manifest) != staged_assets:
            raise SystemExit("Campanile staged assets changed during capture")

    report_path = output / "capture.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["fixture_sha256"] != manifest["assembly"]["sha256"]:
        raise SystemExit("captured program hash disagrees with probe.json")
    shutdown_method = report.get("shutdown_method")
    returncode = report.get("emulator_returncode")
    controlled_shutdown = shutdown_method == "sigint" or (
        shutdown_method == "already-exited" and returncode == 0
    )
    if not controlled_shutdown:
        raise SystemExit(
            f"emulator required non-clean shutdown method {shutdown_method!r}"
        )
    silhouette = analyze_silhouette(
        (output / f"pingo-{capture.BITMAP_ID}-{capture.SEQUENCE}.rgba2").read_bytes()
    )
    report.update(
        {
            "schema": "pingo-terrain-campanile-p3dm-capture-v1",
            "fixture": str(PROGRAM.resolve()),
            "executed_runtime_name": program_name,
            "executed_assets": staged_assets,
            "component_sha256": manifest["component"]["sha256"],
            "component_vertices": manifest["component"]["vertices"],
            "component_triangles": manifest["component"]["triangles"],
            "palette_sha256": manifest["palette"]["sha256"],
            "local_base_residual_m": manifest["local_placement"][
                "base_residual_m"
            ],
            "exact_stream_publication": True,
            "silhouette": silhouette,
            "clean_shutdown": controlled_shutdown,
        }
    )
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "CAMPANILE_CAPTURE",
        f"rgba2_sha256={report['rgba2_sha256']}",
        f"depth_sha256={report['depth_sha256']}",
        f"populated_pixels={report['populated_pixels']}",
        f"output={output}",
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
