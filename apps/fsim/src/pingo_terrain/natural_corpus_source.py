"""Compact portable source for the complete post-partition natural corpus.

The accepted Blender artifact contains nearly one million triangles.  Encoding
that mesh as the v1 list-of-dictionaries JSON used by the 91-cell proof would
produce hundreds of megabytes and require several times that much transient
Python memory.  This module defines the fixed-record v2 bridge used by the
complete regional build instead.

All records are little-endian and contain only source-semantic integers.  The
small JSON manifest pins their sizes and SHA-256 hashes.  Blender is therefore
needed only to extract the accepted master once; ordinary P3DM builds stream
the compact files with the project virtual environment.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import mmap
from pathlib import Path
import struct
from typing import Iterator

from .hex_terrain import COUNTS_PER_METRE, HEX_CELL_COUNT, cell_from_id
from .natural_runtime import NaturalRuntimeComponent


SOURCE_SCHEMA = "pingo-terrain-natural-runtime-source-v2"
VERTICES_PATH = Path("VERTICES.bin")
COMPONENTS_PATH = Path("COMPONENTS.bin")
FACES_PATH = Path("FACES.bin")

# Master vertex: UTM east count, UTM north count, rounded elevation count,
# original Blender float32 elevation bits.
VERTEX_RECORD = struct.Struct("<iiiI")

# Dense logical cell ID implies q/r.  Each component record selects one
# contiguous run in FACES.bin.
COMPONENT_RECORD = struct.Struct("<II")

# Master face index, three master vertex indices, terrain material ID.
FACE_RECORD = struct.Struct("<IIIIB")


def canonical_bytes(value: object) -> bytes:
    """Return the stable ASCII JSON representation used by semantic hashes."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def semantic_payload(document: dict) -> dict:
    """Select every field that defines source meaning rather than location."""

    return {
        "schema": document.get("schema"),
        "source": document.get("source"),
        "coordinate_contract": document.get("coordinate_contract"),
        "format_contract": document.get("format_contract"),
        "selection": document.get("selection"),
        "statistics": document.get("statistics"),
        "seam_evidence": document.get("seam_evidence"),
        "sections": document.get("sections"),
    }


def _require_exact_int(value: object, description: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{description} must be an exact integer: {value!r}")
    return value


def _require_sha256(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{description} is not a lowercase SHA-256: {value!r}")
    return value


class NaturalCorpusSource:
    """Validated, memory-mapped view of one complete v2 source bridge.

    Iterate exactly once with :meth:`components`.  The iterator validates dense
    cell order, face ownership, master indices, float32 elevation witnesses,
    and aggregate counts while yielding one component at a time.
    """

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.expanduser().resolve()
        try:
            self.document = json.loads(self.manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"natural source manifest is unreadable: {self.manifest_path}"
            ) from error
        if self.document.get("schema") != SOURCE_SCHEMA:
            raise ValueError(
                f"natural source schema changed: {self.document.get('schema')!r}"
            )
        expected_semantic = _require_sha256(
            self.document.get("semantic_sha256"), "natural semantic hash"
        )
        actual_semantic = sha256_bytes(canonical_bytes(semantic_payload(self.document)))
        if actual_semantic != expected_semantic:
            raise ValueError(
                f"natural source semantic hash changed: "
                f"{actual_semantic} != {expected_semantic}"
            )

        statistics = self.document.get("statistics")
        selection = self.document.get("selection")
        if not isinstance(statistics, dict) or not isinstance(selection, dict):
            raise ValueError("natural source selection/statistics are malformed")
        self.cell_count = _require_exact_int(
            selection.get("component_count"), "natural component count"
        )
        self.vertex_count = _require_exact_int(
            statistics.get("master_vertices"), "natural master vertex count"
        )
        self.face_count = _require_exact_int(
            statistics.get("master_faces"), "natural master face count"
        )
        if self.cell_count != HEX_CELL_COUNT:
            raise ValueError(
                f"complete natural source needs {HEX_CELL_COUNT} cells, "
                f"not {self.cell_count}"
            )
        self._section_specs = {
            "vertices": (VERTICES_PATH, self.vertex_count, VERTEX_RECORD),
            "components": (COMPONENTS_PATH, self.cell_count, COMPONENT_RECORD),
            "faces": (FACES_PATH, self.face_count, FACE_RECORD),
        }
        self.paths: dict[str, Path] = {}
        sections = self.document.get("sections")
        if not isinstance(sections, dict):
            raise ValueError("natural source section ledger is malformed")
        for name, (relative, records, record_struct) in self._section_specs.items():
            section = sections.get(name)
            if not isinstance(section, dict):
                raise ValueError(f"natural source omits section {name}")
            witness = (
                section.get("path"),
                section.get("records"),
                section.get("record_bytes"),
                section.get("bytes"),
            )
            expected = (
                relative.as_posix(),
                records,
                record_struct.size,
                records * record_struct.size,
            )
            if witness != expected:
                raise ValueError(
                    f"natural {name} section contract changed: "
                    f"{witness} != {expected}"
                )
            path = self.manifest_path.parent / relative
            if not path.is_file() or path.stat().st_size != expected[3]:
                raise ValueError(f"natural {name} section is missing or truncated: {path}")
            expected_hash = _require_sha256(
                section.get("sha256"), f"natural {name} section hash"
            )
            actual_hash = sha256_file(path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"natural {name} section hash changed: "
                    f"{actual_hash} != {expected_hash}"
                )
            self.paths[name] = path

        self.observed_statistics: dict[str, object] | None = None

    def components(self) -> Iterator[NaturalRuntimeComponent]:
        """Yield all dense cell owners while validating the complete ledger."""

        if self.observed_statistics is not None:
            raise RuntimeError("natural source components may be iterated only once")
        material_histogram: Counter[int] = Counter()
        component_vertex_instances = 0
        minimum_faces = self.face_count
        maximum_faces = 0
        expected_face_start = 0
        seen_faces = bytearray(self.face_count)
        validated_vertices = bytearray(self.vertex_count)

        with (
            self.paths["vertices"].open("rb") as vertex_file,
            self.paths["components"].open("rb") as component_file,
            self.paths["faces"].open("rb") as face_file,
            mmap.mmap(vertex_file.fileno(), 0, access=mmap.ACCESS_READ) as vertices,
            mmap.mmap(component_file.fileno(), 0, access=mmap.ACCESS_READ) as components,
            mmap.mmap(face_file.fileno(), 0, access=mmap.ACCESS_READ) as faces,
        ):
            for cell_id in range(self.cell_count):
                start, count = COMPONENT_RECORD.unpack_from(
                    components, cell_id * COMPONENT_RECORD.size
                )
                if start != expected_face_start or count == 0:
                    raise ValueError(
                        f"natural component {cell_id} has noncanonical face run "
                        f"{start}+{count}; expected start {expected_face_start}"
                    )
                expected_face_start += count
                minimum_faces = min(minimum_faces, count)
                maximum_faces = max(maximum_faces, count)

                source_faces: list[tuple[int, int, int]] = []
                source_materials: list[int] = []
                master_face_indices: list[int] = []
                master_vertices: set[int] = set()
                for ordinal in range(start, start + count):
                    record = FACE_RECORD.unpack_from(faces, ordinal * FACE_RECORD.size)
                    master_face, first, second, third, material = record
                    if not 0 <= master_face < self.face_count:
                        raise ValueError(
                            f"natural component {cell_id} has out-of-range master face "
                            f"{master_face}"
                        )
                    if seen_faces[master_face]:
                        raise ValueError(f"natural master face {master_face} has two owners")
                    seen_faces[master_face] = 1
                    if any(
                        vertex >= self.vertex_count
                        for vertex in (first, second, third)
                    ):
                        raise ValueError(
                            f"natural master face {master_face} references an invalid vertex"
                        )
                    if len({first, second, third}) != 3:
                        raise ValueError(f"natural master face {master_face} repeats a vertex")
                    if not 0 <= material < 15:
                        raise ValueError(
                            f"natural master face {master_face} has material {material}"
                        )
                    master_face_indices.append(master_face)
                    source_faces.append((first, second, third))
                    source_materials.append(material)
                    master_vertices.update((first, second, third))
                    material_histogram[material] += 1
                if master_face_indices != sorted(master_face_indices):
                    raise ValueError(
                        f"natural component {cell_id} faces are not in master order"
                    )

                ordered_vertices = sorted(master_vertices)
                local = {master: index for index, master in enumerate(ordered_vertices)}
                decoded_vertices: list[tuple[int, int, int]] = []
                for master in ordered_vertices:
                    east, north, elevation, elevation_bits = VERTEX_RECORD.unpack_from(
                        vertices, master * VERTEX_RECORD.size
                    )
                    if not validated_vertices[master]:
                        elevation_float32 = struct.unpack(
                            "<f", struct.pack("<I", elevation_bits)
                        )[0]
                        if round(elevation_float32 * COUNTS_PER_METRE) != elevation:
                            raise ValueError(
                                f"natural master vertex {master} elevation witness changed"
                            )
                        validated_vertices[master] = 1
                    decoded_vertices.append((east, north, elevation))
                component_vertex_instances += len(decoded_vertices)
                cell = cell_from_id(cell_id)
                yield NaturalRuntimeComponent(
                    cell=cell,
                    vertices=tuple(decoded_vertices),
                    faces=tuple(
                        (local[first], local[second], local[third])
                        for first, second, third in source_faces
                    ),
                    materials=tuple(source_materials),
                )

        if expected_face_start != self.face_count or not all(seen_faces):
            raise ValueError("natural source does not own every master face exactly once")
        if not all(validated_vertices):
            raise ValueError("natural source contains an unreferenced master vertex")
        self.observed_statistics = {
            "components": self.cell_count,
            "master_vertices": self.vertex_count,
            "master_faces": self.face_count,
            "component_vertex_instances": component_vertex_instances,
            "minimum_faces_per_component": minimum_faces,
            "maximum_faces_per_component": maximum_faces,
            "material_histogram": {
                str(material): count
                for material, count in sorted(material_histogram.items())
            },
        }
        expected = self.document["statistics"]
        for key, value in self.observed_statistics.items():
            if expected.get(key) != value:
                raise ValueError(
                    f"natural source statistic {key} changed: "
                    f"{value!r} != {expected.get(key)!r}"
                )
