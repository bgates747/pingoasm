#!/usr/bin/env python3
"""Create the mandatory full-region Blender review for runtime colors.

This script does not regenerate or alter terrain topology.  It opens the pinned
accepted natural master, maps its preserved fifteen semantic IDs onto the
three exact Agon base colors used by the runtime, and saves a distinct derived
review artifact.  The derived file is presentation evidence, never extraction
authority.
"""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import export_natural_runtime_subset_blender as source_contract  # noqa: E402
from pingo_terrain.materials import (  # noqa: E402
    AGON_SOLID_TERRAIN_MATERIALS,
    BERKELEY_TERRAIN_MATERIALS,
)


DEFAULT_OUTPUT = (
    ROOT / "build/visualization/bay-area-natural-three-class-runtime-review.blend"
)
RECEIPT_SCHEMA = "pingo-terrain-natural-three-class-review-v1"
PALETTE_INDEX_BY_MATERIAL = (20, 7, 7, 7, 7) + (21,) * 10


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=source_contract.SOURCE_BLEND)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def runtime_class(material_id: int) -> int:
    if material_id == 0:
        return 0
    if 1 <= material_id <= 4:
        return 1
    if 5 <= material_id < 15:
        return 2
    raise ValueError(f"terrain material ID is outside 0..14: {material_id}")


def _blender_material(bpy, name: str, rgb8: tuple[int, int, int], palette: int):
    material = bpy.data.materials.new(name)
    color = tuple(channel / 255.0 for channel in rgb8) + (1.0,)
    material.diffuse_color = color
    material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
    material["agon_palette_index"] = palette
    material["runtime_rgb8"] = list(rgb8)
    material["runtime_base_is_exact_native_color"] = True
    return material


def build(bpy, source: Path, output: Path) -> dict:
    if output.exists():
        raise SystemExit(f"refusing to replace existing review artifact: {output}")
    terrain = bpy.data.objects.get(source_contract.TERRAIN_OBJECT_NAME)
    if terrain is None or terrain.type != "MESH":
        raise SystemExit("accepted natural master object is missing")
    if (
        bpy.context.scene.get("topology_and_ownership_sha256")
        != source_contract.SOURCE_TOPOLOGY_SHA256
        or not terrain.get("partition_checks_passed")
    ):
        raise SystemExit("accepted natural master topology is not qualified")
    mesh = terrain.data
    semantic = source_contract._require_attribute(
        mesh, "terrain_material_id", domain="FACE", data_type="INT"
    )
    semantic_ids = source_contract._foreach_int(semantic, len(mesh.polygons))

    rgb_by_class = (
        AGON_SOLID_TERRAIN_MATERIALS[0].rgb,
        AGON_SOLID_TERRAIN_MATERIALS[1].rgb,
        AGON_SOLID_TERRAIN_MATERIALS[5].rgb,
    )
    palette_by_class = (20, 7, 21)
    if rgb_by_class != ((0, 85, 255), (170, 170, 170), (0, 170, 85)):
        raise SystemExit(f"three-class runtime palette changed: {rgb_by_class}")
    expected_mapping = tuple(
        (palette, material.rgb)
        for palette, material in zip(
            PALETTE_INDEX_BY_MATERIAL,
            AGON_SOLID_TERRAIN_MATERIALS,
            strict=True,
        )
    )
    if expected_mapping != (
        ((20, (0, 85, 255)),)
        + ((7, (170, 170, 170)),) * 4
        + ((21, (0, 170, 85)),) * 10
    ):
        raise SystemExit("runtime material-to-palette mapping changed")

    runtime_materials = (
        _blender_material(bpy, "Runtime water — Agon 20", rgb_by_class[0], 20),
        _blender_material(bpy, "Runtime developed — Agon 7", rgb_by_class[1], 7),
        _blender_material(bpy, "Runtime other land — Agon 21", rgb_by_class[2], 21),
    )
    mesh.materials.clear()
    for material in runtime_materials:
        mesh.materials.append(material)
    presentation_indices = array(
        "i", (runtime_class(material_id) for material_id in semantic_ids)
    )
    mesh.polygons.foreach_set("material_index", presentation_indices)
    mesh.update()

    mapping = [
        {
            "material_id": material.material_id,
            "nlcd_category": material.nlcd_category,
            "name": material.name,
            "source_rgb8": list(material.rgb),
            "runtime_class": runtime_class(material.material_id),
            "runtime_palette_index": PALETTE_INDEX_BY_MATERIAL[material.material_id],
            "runtime_rgb8": list(AGON_SOLID_TERRAIN_MATERIALS[material.material_id].rgb),
        }
        for material in BERKELEY_TERRAIN_MATERIALS
    ]
    scene = bpy.context.scene
    scene["presentation_schema"] = RECEIPT_SCHEMA
    scene["presentation_source_blend_sha256"] = source_contract.SOURCE_BLEND_SHA256
    scene["presentation_source_topology_sha256"] = (
        source_contract.SOURCE_TOPOLOGY_SHA256
    )
    scene["presentation_exact_source_geometry"] = True
    scene["presentation_runtime_material_mapping_json"] = json.dumps(
        mapping, sort_keys=True, separators=(",", ":")
    )
    terrain["presentation_semantic_attribute"] = "terrain_material_id"
    terrain["presentation_material_classes"] = 3
    terrain["presentation_runtime_illumination"] = "scene"

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "source": {
            "blend_path": str(source.relative_to(ROOT)),
            "blend_sha256": source_contract.SOURCE_BLEND_SHA256,
            "topology_and_ownership_sha256": source_contract.SOURCE_TOPOLOGY_SHA256,
        },
        "output": {
            "blend_path": str(output.relative_to(ROOT)),
            "blend_bytes": output.stat().st_size,
            "blend_sha256": sha256_file(output),
        },
        "geometry": {
            "objects": 1,
            "vertices": len(mesh.vertices),
            "faces": len(mesh.polygons),
            "exact_source_geometry": True,
            "semantic_attribute_preserved": mesh.attributes.get(
                "terrain_material_id"
            )
            is not None,
        },
        "presentation": {
            "material_classes": 3,
            "scene_illumination": True,
            "mapping": mapping,
        },
        "inputs": {
            "materials_py_sha256": sha256_file(
                ROOT / "src/pingo_terrain/materials.py"
            ),
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "blender_version": bpy.app.version_string,
        },
    }
    receipt_path = output.with_suffix(".json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"accepted natural Blender artifact is missing: {source}")
    actual_sha = sha256_file(source)
    if actual_sha != source_contract.SOURCE_BLEND_SHA256:
        raise SystemExit(
            f"accepted natural Blender artifact changed: "
            f"{actual_sha} != {source_contract.SOURCE_BLEND_SHA256}"
        )
    try:
        import bpy
    except ImportError as error:  # pragma: no cover - Blender integration
        raise SystemExit("run this review builder through Blender") from error
    loaded = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if loaded != source:
        bpy.ops.wm.open_mainfile(filepath=str(source))
    receipt = build(bpy, source, output)
    print(
        "NATURAL_RUNTIME_REVIEW",
        f"vertices={receipt['geometry']['vertices']}",
        f"faces={receipt['geometry']['faces']}",
        f"materials={receipt['presentation']['material_classes']}",
        f"sha256={receipt['output']['blend_sha256']}",
        f"output={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

