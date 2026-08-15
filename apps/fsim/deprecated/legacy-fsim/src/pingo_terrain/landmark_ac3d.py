"""Read-only inspection of flattened AC3D landmark donor meshes.

The FlightGear scenery donors considered by this project are small, textual
AC3D files with vertex coordinates already flattened into object space.  This
module deliberately stops at reporting: importing, recentering, triangulation,
and material quantisation remain explicit later build stages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
from typing import Any


_MATERIAL_RE = re.compile(
    r'^MATERIAL\s+"(?P<name>[^"]*)"\s+rgb\s+'
    r'(?P<red>\S+)\s+(?P<green>\S+)\s+(?P<blue>\S+)'
)
_QUOTED_RE = re.compile(r'^\S+\s+"(?P<value>[^"]*)"')


@dataclass(frozen=True)
class AC3DMaterial:
    name: str
    rgb: tuple[float, float, float]


@dataclass(frozen=True)
class AC3DInspection:
    path: str
    byte_size: int
    sha256: str
    header: str
    object_count: int
    material_count: int
    materials: tuple[AC3DMaterial, ...]
    vertex_count: int
    surface_count: int
    polygon_surface_count: int
    line_surface_count: int
    point_surface_count: int
    fan_triangle_count: int
    textures: tuple[str, ...]
    material_surface_counts: tuple[tuple[int, int], ...]
    minimum_xyz: tuple[float, float, float]
    maximum_xyz: tuple[float, float, float]
    has_object_transforms: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable report with stable field ordering."""

        return asdict(self)


def _quoted_value(line: str, keyword: str) -> str:
    match = _QUOTED_RE.match(line)
    if match is None:
        raise ValueError(f"malformed {keyword} directive: {line!r}")
    return match.group("value")


def inspect_ac3d(path: str | Path) -> AC3DInspection:
    """Inspect one textual AC3D file without acquiring or modifying it.

    Vertex extents are raw file coordinates.  If ``has_object_transforms`` is
    true they are not world-space bounds; a future importer must apply the
    hierarchy before using them for P3DM quantisation.
    """

    source_path = Path(path)
    payload = source_path.read_bytes()
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"AC3D file is not UTF-8 text: {source_path}") from error
    if not lines or not lines[0].startswith("AC3D"):
        raise ValueError(f"missing AC3D header: {source_path}")

    materials: list[AC3DMaterial] = []
    textures: set[str] = set()
    material_surface_counts: dict[int, int] = {}
    vertices: list[tuple[float, float, float]] = []
    object_count = 0
    surface_count = 0
    polygon_surface_count = 0
    line_surface_count = 0
    point_surface_count = 0
    fan_triangle_count = 0
    has_object_transforms = False

    index = 1
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line.startswith("MATERIAL "):
            match = _MATERIAL_RE.match(line)
            if match is None:
                raise ValueError(f"malformed MATERIAL directive: {line!r}")
            materials.append(
                AC3DMaterial(
                    name=match.group("name"),
                    rgb=(
                        float(match.group("red")),
                        float(match.group("green")),
                        float(match.group("blue")),
                    ),
                )
            )
            continue
        if line.startswith("OBJECT "):
            object_count += 1
            continue
        if line.startswith("texture "):
            textures.add(_quoted_value(line, "texture"))
            continue
        if line.startswith(("loc ", "rot ")):
            has_object_transforms = True
            continue
        if line.startswith("data "):
            raise ValueError("AC3D data blocks are unsupported by this inspector")
        if line.startswith("numvert "):
            count = int(line.split()[1])
            if index + count > len(lines):
                raise ValueError("truncated AC3D vertex block")
            for vertex_line in lines[index : index + count]:
                parts = vertex_line.split()
                if len(parts) < 3:
                    raise ValueError(f"malformed AC3D vertex: {vertex_line!r}")
                vertices.append(tuple(float(value) for value in parts[:3]))
            index += count
            continue
        if line.startswith("numsurf "):
            count = int(line.split()[1])
            for _ in range(count):
                if index >= len(lines) or not lines[index].strip().startswith(
                    "SURF "
                ):
                    raise ValueError("missing SURF directive in AC3D surface block")
                index += 1
                material_index: int | None = None
                while index < len(lines):
                    surface_line = lines[index].strip()
                    index += 1
                    if surface_line.startswith("mat "):
                        material_index = int(surface_line.split()[1])
                    if surface_line.startswith("refs "):
                        reference_count = int(surface_line.split()[1])
                        break
                else:
                    raise ValueError("missing refs directive in AC3D surface")
                if index + reference_count > len(lines):
                    raise ValueError("truncated AC3D surface reference block")
                index += reference_count
                surface_count += 1
                if material_index is not None:
                    material_surface_counts[material_index] = (
                        material_surface_counts.get(material_index, 0) + 1
                    )
                if reference_count >= 3:
                    polygon_surface_count += 1
                    fan_triangle_count += reference_count - 2
                elif reference_count == 2:
                    line_surface_count += 1
                else:
                    point_surface_count += 1

    if not vertices:
        raise ValueError(f"AC3D file has no vertices: {source_path}")
    minimum_xyz = tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
    maximum_xyz = tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))
    return AC3DInspection(
        path=str(source_path),
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        header=lines[0],
        object_count=object_count,
        material_count=len(materials),
        materials=tuple(materials),
        vertex_count=len(vertices),
        surface_count=surface_count,
        polygon_surface_count=polygon_surface_count,
        line_surface_count=line_surface_count,
        point_surface_count=point_surface_count,
        fan_triangle_count=fan_triangle_count,
        textures=tuple(sorted(textures)),
        material_surface_counts=tuple(sorted(material_surface_counts.items())),
        minimum_xyz=minimum_xyz,
        maximum_xyz=maximum_xyz,
        has_object_transforms=has_object_transforms,
    )
