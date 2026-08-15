"""Deterministic procedural Bay Area landmark P3DM components.

The meshes in this module are original recognition silhouettes.  Publicly
pinned positions and controlling dimensions establish their scale; every
remaining proportion is deliberately labelled as an approximation in the
generated index.  No donor mesh, photograph, or bitmap texture is consumed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .airport_p3dm import project_wgs84_utm10
from .geotiff import sha256_file
from .p3dm import (
    IlluminationPolicy,
    LayerKind,
    MaterialSet,
    P3DMMeta,
    P3DMTile,
    ShadingMode,
    make_container,
    make_data,
    parse_container,
)
from .regional_raster import RasterMosaic
from .regional_lod import (
    ComponentSpec,
    SuperTileGrid,
    build_component,
    component_specs,
    rectangular_topology,
)


REGIONAL_CRS = "EPSG:32610"
REGIONAL_ORIGIN_EAST_M = 521_728
REGIONAL_ORIGIN_NORTH_M = 4_100_096
REGIONAL_VERTICAL_ORIGIN_M = 608.0
REGIONAL_TILE_SIZE_M = 512
REGIONAL_COLUMNS = 201
REGIONAL_ROWS = 252
METRES_PER_PINGO_UNIT = 8
P3D_NORM_MAX = 32_767
STAGING_BUFFER_ID = 0x7400
RETENTION_HYSTERESIS_M = REGIONAL_TILE_SIZE_M
FOUNDATION_BURY_MARGIN_M = 1.0
MINIMUM_FOUNDATION_DEPTH_M = 1

# Landmarks reuse the native raw six-bit color cube already specified for
# solid-flat airport layers.  The file is only 64 bytes and these procedural
# meshes address eight semantic cells; it is a selector table, not imagery.
SOLID_PALETTE = bytes(range(0xC0, 0x100))
LANDMARK_SELECTORS: dict[str, int] = {
    "warm_stone": 47,       # RGB levels 3,3,2
    "stone_shadow": 26,     # RGB levels 2,2,1
    "dark_opening": 5,      # RGB levels 1,1,0
    "clock_face": 63,       # RGB levels 3,3,3
    "metal_gray": 42,       # RGB levels 2,2,2
    "cool_glass": 58,       # RGB levels 2,2,3
    "glass_shadow": 37,     # RGB levels 1,1,2
    "crown_light": 62,      # RGB levels 2,3,3
}


@dataclass(frozen=True, slots=True)
class LandmarkSpec:
    landmark_id: str
    name: str
    filename: str
    latitude_deg: float
    longitude_deg: float
    anchor_semantics: str
    placement_source: str
    dimension_sources: tuple[str, ...]
    triangle_budget: int
    load_radius_m: int
    nominal_controls: tuple[str, ...]
    approximations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProceduralMesh:
    """Landmark-local metres: X north, Y AGL, Z west."""

    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int, int], ...]


@dataclass(frozen=True, slots=True)
class LandmarkFrame:
    center_east_abs_m: int
    center_north_abs_m: int
    model_half_extent_m: int

    @property
    def center_east_m(self) -> int:
        return self.center_east_abs_m - REGIONAL_ORIGIN_EAST_M

    @property
    def center_north_m(self) -> int:
        return self.center_north_abs_m - REGIONAL_ORIGIN_NORTH_M

    @property
    def tile_x(self) -> int:
        return self.center_east_m // REGIONAL_TILE_SIZE_M

    @property
    def tile_y(self) -> int:
        return self.center_north_m // REGIONAL_TILE_SIZE_M

    @property
    def scale_wire_q8_8(self) -> int:
        return self.model_half_extent_m * (
            256 // METRES_PER_PINGO_UNIT
        )


@dataclass(frozen=True, slots=True)
class _DecodedTerrainSurface:
    """One regional-LOD surface after the exact P3DM i16 quantization."""

    spec: ComponentSpec
    tile: P3DMTile
    vertices_east_north_elevation_m: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True, slots=True)
class _TerrainContact:
    model_base_elevation_m: float
    foundation_depth_m: int
    witness: dict[str, object]


class _MeshBuilder:
    def __init__(self) -> None:
        self.vertices: list[tuple[float, float, float]] = []
        self.triangles: list[tuple[int, int, int, int]] = []

    def _point(self, point: Sequence[float]) -> int:
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise ValueError(f"invalid procedural vertex: {point!r}")
        self.vertices.append((float(point[0]), float(point[1]), float(point[2])))
        return len(self.vertices) - 1

    def triangle(
        self,
        first: Sequence[float],
        second: Sequence[float],
        third: Sequence[float],
        selector: int,
    ) -> None:
        if selector not in LANDMARK_SELECTORS.values():
            raise ValueError(f"unregistered landmark selector: {selector}")
        indices = tuple(self._point(point) for point in (first, second, third))
        self.triangles.append((*indices, selector))

    def quad(
        self,
        first: Sequence[float],
        second: Sequence[float],
        third: Sequence[float],
        fourth: Sequence[float],
        selector: int,
    ) -> None:
        first_index = self._point(first)
        second_index = self._point(second)
        third_index = self._point(third)
        fourth_index = self._point(fourth)
        self.triangles.extend(
            (
                (first_index, second_index, third_index, selector),
                (first_index, third_index, fourth_index, selector),
            )
        )

    def box(
        self,
        *,
        center_x: float,
        center_z: float,
        width_x: float,
        width_z: float,
        bottom_y: float,
        top_y: float,
        side_selector: int,
        top_selector: int | None = None,
        bottom_selector: int | None = None,
    ) -> None:
        """Add four outward sides, an upward top, and an optional underside."""

        if width_x <= 0.0 or width_z <= 0.0 or top_y <= bottom_y:
            raise ValueError("box dimensions must be positive")
        top_selector = side_selector if top_selector is None else top_selector
        x0, x1 = center_x - width_x / 2.0, center_x + width_x / 2.0
        z0, z1 = center_z - width_z / 2.0, center_z + width_z / 2.0
        # +X, -X, +Z, -Z outward faces.
        self.quad((x1, bottom_y, z0), (x1, top_y, z0),
                  (x1, top_y, z1), (x1, bottom_y, z1), side_selector)
        self.quad((x0, bottom_y, z1), (x0, top_y, z1),
                  (x0, top_y, z0), (x0, bottom_y, z0), side_selector)
        self.quad((x0, bottom_y, z1), (x1, bottom_y, z1),
                  (x1, top_y, z1), (x0, top_y, z1), side_selector)
        self.quad((x1, bottom_y, z0), (x0, bottom_y, z0),
                  (x0, top_y, z0), (x1, top_y, z0), side_selector)
        # Clockwise when viewed from above gives +Y in Pingo axes.
        self.quad((x0, top_y, z0), (x0, top_y, z1),
                  (x1, top_y, z1), (x1, top_y, z0), top_selector)
        if bottom_selector is not None:
            # Reverse the top-cap order for a downward exterior normal.
            self.quad((x0, bottom_y, z0), (x1, bottom_y, z0),
                      (x1, bottom_y, z1), (x0, bottom_y, z1),
                      bottom_selector)

    def loft(
        self,
        bottom: Sequence[tuple[float, float]],
        top: Sequence[tuple[float, float]],
        *,
        bottom_y: float,
        top_y: float,
        side_selector: int,
        top_selector: int | None = None,
    ) -> None:
        """Join equal counter-clockwise X/Z rings and cap them upward."""

        if len(bottom) < 3 or len(bottom) != len(top) or top_y <= bottom_y:
            raise ValueError("loft rings must be equal polygons of at least 3 points")
        for index in range(len(bottom)):
            following = (index + 1) % len(bottom)
            self.quad(
                (*bottom[index][:1], bottom_y, *bottom[index][1:]),
                (*top[index][:1], top_y, *top[index][1:]),
                (*top[following][:1], top_y, *top[following][1:]),
                (*bottom[following][:1], bottom_y, *bottom[following][1:]),
                side_selector,
            )
        if top_selector is not None:
            center_x = sum(point[0] for point in top) / len(top)
            center_z = sum(point[1] for point in top) / len(top)
            for index in range(len(top)):
                following = (index + 1) % len(top)
                # Reverse the CCW ring for an upward Pingo normal.
                self.triangle(
                    (center_x, top_y, center_z),
                    (top[following][0], top_y, top[following][1]),
                    (top[index][0], top_y, top[index][1]),
                    top_selector,
                )

    def build(self) -> ProceduralMesh:
        mesh = ProceduralMesh(tuple(self.vertices), tuple(self.triangles))
        validate_procedural_mesh(mesh)
        return mesh


def _square_ring(half_x: float, half_z: float) -> tuple[tuple[float, float], ...]:
    return (
        (half_x, -half_z),
        (half_x, half_z),
        (-half_x, half_z),
        (-half_x, -half_z),
    )


def _regular_ring(count: int, radius: float) -> tuple[tuple[float, float], ...]:
    if count < 3 or radius <= 0.0:
        raise ValueError("regular ring needs at least three points and positive radius")
    return tuple(
        (
            radius * math.cos(2.0 * math.pi * index / count),
            radius * math.sin(2.0 * math.pi * index / count),
        )
        for index in range(count)
    )


def _rounded_square_ring(
    count: int, half_extent: float
) -> tuple[tuple[float, float], ...]:
    """Return a low-order superellipse with exact axis extrema."""

    if count % 4 or count < 8 or half_extent <= 0.0:
        raise ValueError("rounded square needs a positive multiple-of-four count")
    result = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        cosine, sine = math.cos(angle), math.sin(angle)
        result.append(
            (
                math.copysign(math.sqrt(abs(cosine)), cosine) * half_extent,
                math.copysign(math.sqrt(abs(sine)), sine) * half_extent,
            )
        )
    return tuple(result)


def _face_panel(
    builder: _MeshBuilder,
    *,
    axis: str,
    sign: int,
    plane: float,
    center_y: float,
    half_width: float,
    half_height: float,
    selector: int,
) -> None:
    """Add one outward offset facade panel on an axis-aligned face."""

    y0, y1 = center_y - half_height, center_y + half_height
    if axis == "x" and sign > 0:
        builder.quad((plane, y0, -half_width), (plane, y1, -half_width),
                     (plane, y1, half_width), (plane, y0, half_width), selector)
    elif axis == "x" and sign < 0:
        builder.quad((plane, y0, half_width), (plane, y1, half_width),
                     (plane, y1, -half_width), (plane, y0, -half_width), selector)
    elif axis == "z" and sign > 0:
        builder.quad((-half_width, y0, plane), (half_width, y0, plane),
                     (half_width, y1, plane), (-half_width, y1, plane), selector)
    elif axis == "z" and sign < 0:
        builder.quad((half_width, y0, plane), (-half_width, y0, plane),
                     (-half_width, y1, plane), (half_width, y1, plane), selector)
    else:
        raise ValueError(f"invalid facade axis/sign: {axis!r}, {sign}")


def build_campanile_mesh() -> ProceduralMesh:
    """Original recognition model using the pinned nominal 93.5736 m height."""

    warm = LANDMARK_SELECTORS["warm_stone"]
    shadow = LANDMARK_SELECTORS["stone_shadow"]
    dark = LANDMARK_SELECTORS["dark_opening"]
    clock = LANDMARK_SELECTORS["clock_face"]
    metal = LANDMARK_SELECTORS["metal_gray"]
    builder = _MeshBuilder()
    builder.box(center_x=0.0, center_z=0.0, width_x=14.0, width_z=14.0,
                bottom_y=0.0, top_y=2.2, side_selector=shadow, top_selector=warm)
    builder.box(center_x=0.0, center_z=0.0, width_x=10.8, width_z=10.8,
                bottom_y=2.2, top_y=66.0, side_selector=warm)
    builder.box(center_x=0.0, center_z=0.0, width_x=11.8, width_z=11.8,
                bottom_y=66.0, top_y=75.0, side_selector=warm)

    # A dark central prism behind four pale corner piers gives the belfry an
    # open silhouette without texture alpha or unsupported polygon holes.
    builder.box(center_x=0.0, center_z=0.0, width_x=8.6, width_z=8.6,
                bottom_y=75.0, top_y=86.0, side_selector=dark, top_selector=dark)
    for center_x in (-4.65, 4.65):
        for center_z in (-4.65, 4.65):
            builder.box(center_x=center_x, center_z=center_z,
                        width_x=1.5, width_z=1.5, bottom_y=75.0, top_y=86.0,
                        side_selector=warm)
    builder.box(center_x=0.0, center_z=0.0, width_x=12.5, width_z=12.5,
                bottom_y=86.0, top_y=89.0, side_selector=shadow, top_selector=warm)
    builder.loft(_square_ring(3.0, 3.0), _square_ring(2.4, 2.4),
                 bottom_y=89.0, top_y=91.0, side_selector=warm,
                 top_selector=metal)
    for index in range(4):
        following = (index + 1) % 4
        ring = _square_ring(2.4, 2.4)
        builder.triangle((ring[index][0], 91.0, ring[index][1]),
                         (0.0, 93.5736, 0.0),
                         (ring[following][0], 91.0, ring[following][1]), metal)

    # Four two-layer clock medallions are geometry, not bitmap decoration.
    for axis, sign in (("x", 1), ("x", -1), ("z", 1), ("z", -1)):
        _face_panel(builder, axis=axis, sign=sign, plane=sign * 5.98,
                    center_y=70.5, half_width=3.0, half_height=3.0,
                    selector=dark)
        _face_panel(builder, axis=axis, sign=sign, plane=sign * 6.06,
                    center_y=70.5, half_width=2.45, half_height=2.45,
                    selector=clock)
    return builder.build()


def build_mount_diablo_mesh() -> ProceduralMesh:
    """Original close-range summit-building and beacon approximation."""

    warm = LANDMARK_SELECTORS["warm_stone"]
    shadow = LANDMARK_SELECTORS["stone_shadow"]
    dark = LANDMARK_SELECTORS["dark_opening"]
    metal = LANDMARK_SELECTORS["metal_gray"]
    builder = _MeshBuilder()
    builder.box(center_x=0.0, center_z=0.0, width_x=20.0, width_z=14.0,
                bottom_y=0.0, top_y=0.8, side_selector=shadow, top_selector=warm)
    builder.box(center_x=0.0, center_z=0.0, width_x=16.0, width_z=10.0,
                bottom_y=0.8, top_y=4.8, side_selector=warm)
    builder.box(center_x=0.0, center_z=0.0, width_x=17.0, width_z=11.0,
                bottom_y=4.8, top_y=5.6, side_selector=shadow, top_selector=warm)
    octagon = _regular_ring(8, 4.2)
    builder.loft(octagon, octagon, bottom_y=5.6, top_y=9.2,
                 side_selector=warm, top_selector=shadow)
    mast = _regular_ring(8, 0.35)
    builder.loft(mast, mast, bottom_y=9.2, top_y=13.8,
                 side_selector=metal, top_selector=metal)
    beacon_ring = _regular_ring(8, 0.85)
    for index in range(8):
        following = (index + 1) % 8
        builder.triangle((beacon_ring[index][0], 13.8, beacon_ring[index][1]),
                         (0.0, 15.0, 0.0),
                         (beacon_ring[following][0], 13.8,
                          beacon_ring[following][1]), metal)
    for axis, sign, plane, width in (
        ("x", 1, 8.08, 1.5), ("x", -1, -8.08, 1.5),
        ("z", 1, 5.08, 1.5), ("z", -1, -5.08, 1.5),
    ):
        _face_panel(builder, axis=axis, sign=sign, plane=plane,
                    center_y=2.7, half_width=width, half_height=1.15,
                    selector=dark)
    return builder.build()


def build_salesforce_mesh() -> ProceduralMesh:
    """Original tower using pinned nominal public plan and height controls."""

    glass = LANDMARK_SELECTORS["cool_glass"]
    shadow = LANDMARK_SELECTORS["glass_shadow"]
    crown = LANDMARK_SELECTORS["crown_light"]
    builder = _MeshBuilder()
    half_plan = 50.9016 / 2.0
    rings = (
        (_rounded_square_ring(12, half_plan), 0.0, shadow),
        (_rounded_square_ring(12, half_plan), 140.0, glass),
        (_rounded_square_ring(12, 16.0), 277.9776, glass),
        (_rounded_square_ring(12, 8.0), 310.0, crown),
        (_rounded_square_ring(12, 1.5), 326.136, crown),
    )
    segment_selectors = (shadow, glass, glass, crown)
    for ((bottom, bottom_y, _), (top, top_y, _), selector) in zip(
        rings[:-1], rings[1:], segment_selectors, strict=True
    ):
        builder.loft(bottom, top, bottom_y=bottom_y, top_y=top_y,
                     side_selector=selector,
                     top_selector=crown if top_y == 326.136 else None)
    return builder.build()


def build_transamerica_mesh() -> ProceduralMesh:
    """Original pyramid using pinned nominal USGS plan and height controls."""

    warm = LANDMARK_SELECTORS["warm_stone"]
    shadow = LANDMARK_SELECTORS["stone_shadow"]
    dark = LANDMARK_SELECTORS["dark_opening"]
    metal = LANDMARK_SELECTORS["metal_gray"]
    builder = _MeshBuilder()
    half_plan = 53.0352 / 2.0
    builder.box(center_x=0.0, center_z=0.0, width_x=53.0352, width_z=53.0352,
                bottom_y=0.0, top_y=12.0, side_selector=shadow,
                top_selector=warm)
    builder.loft(_square_ring(half_plan, half_plan), _square_ring(2.0, 2.0),
                 bottom_y=12.0, top_y=250.0, side_selector=warm,
                 top_selector=metal)
    apex_ring = _square_ring(2.0, 2.0)
    for index in range(4):
        following = (index + 1) % 4
        builder.triangle((apex_ring[index][0], 250.0, apex_ring[index][1]),
                         (0.0, 260.0, 0.0),
                         (apex_ring[following][0], 250.0,
                          apex_ring[following][1]), metal)
    # The recognition-scale elevator/stair wings occupy their visible 70--120
    # m span.  Their inner edge remains inside the taper even at y=120, while
    # the nominal-plan outer edge gives the expected silhouette.  Part of the
    # y=70 underside lies outside the taper, so it is explicitly capped down.
    wing_inner = 14.0
    wing_outer = half_plan
    wing_width = wing_outer - wing_inner
    wing_center = (wing_outer + wing_inner) / 2.0
    for sign in (-1.0, 1.0):
        builder.box(
            center_x=sign * wing_center,
            center_z=0.0,
            width_x=wing_width,
            width_z=10.0,
            bottom_y=70.0,
            top_y=120.0,
            side_selector=dark,
            top_selector=shadow,
            bottom_selector=dark,
        )
    return builder.build()


LANDMARK_SPECS: tuple[LandmarkSpec, ...] = (
    LandmarkSpec(
        "campanile", "Sather Tower / the Campanile", "CAMPANIL.AGN",
        37.872332, -122.257964, "UC Berkeley campus-map attraction point",
        "https://www.berkeley.edu/map/campanile-sather-tower/",
        ("https://visit.berkeley.edu/campus-attractions/campanile-sather-tower/history-campanile/about",),
        320, 8_000,
        ("pinned nominal architectural height 93.5736 m (reported as 307 ft)",
         "reported clock-hand length 5.1816 m (17 ft), retained as a nominal source control only"),
        ("plan widths and vertical stage proportions are recognition estimates",
         "facade orientation is regional-grid aligned, not survey controlled",
         "clock medallions are simple layered quads; no hands or numerals are claimed"),
    ),
    LandmarkSpec(
        "mount_diablo", "Mount Diablo Summit Building and aviation beacon",
        "DIABLO.AGN", 37.881702, -121.914268, "USGS GNIS summit point",
        "USGS GNIS point as pinned in the landmark source manifest",
        ("https://www.parks.ca.gov/?page_id=517",
         "https://www.parks.ca.gov/?page_id=25059"),
        180, 3_000,
        ("reported summit elevation 1173.1752 m (3849 ft), nominal comparison control only",),
        ("all building footprint, stage, rotunda, and beacon dimensions are estimates",
         "the building is aligned to decoded L0 terrain rather than forced to the reported 3849 ft summit control",
         "the component is a visual accent and is not collision geometry"),
    ),
    LandmarkSpec(
        "salesforce", "Salesforce Tower", "SALESFRC.AGN",
        37.78993419, -122.397097479, "official DataSF address/parcel point",
        "https://data.sfgov.org/Geographic-Locations-and-Boundaries/Addresses-with-parcel-number/5mjj-njit",
        ("https://www.conservation.ca.gov/cgs/documents/program-smi/seminar/SMIP18-Proceedings.pdf",
         "https://commissions.sfplanning.org/cpcpackets/2012.0257.pdf"),
        160, 15_000,
        ("pinned nominal maximum floor plan 50.9016 m square (reported as up to 167 ft)",
         "pinned nominal roof height 277.9776 m (reported as approximately 912 ft)",
         "pinned nominal crown height 326.136 m (reported as approximately 1070 ft)"),
        ("taper start, intermediate ring widths, and rounded-square exponent are estimates",
         "address point is used as the model center; footprint survey geometry is not implied",
         "facade orientation is omitted because no authoritative alignment is pinned"),
    ),
    LandmarkSpec(
        "transamerica", "Transamerica Pyramid", "TRANSPYR.AGN",
        37.79521298, -122.4027781, "FlightGear placement anchor",
        "https://scenery.flightgear.org/api/objects?model=160&limit=100",
        ("https://pubs.usgs.gov/of/1989/0568/report.pdf",),
        80,
        15_000,
        ("pinned nominal USGS square plan 53.0352 m (reported as 174 ft)",
         "pinned nominal USGS architectural height 260.0 m (reported as 853 ft)"),
        ("podium, taper break, tip, and wing proportions are recognition estimates",
         "the procedural mesh consumes no FlightGear donor geometry",
         "the source heading is not baked because facade alignment is not survey controlled"),
    ),
)

_MESH_BUILDERS: dict[str, Callable[[], ProceduralMesh]] = {
    "campanile": build_campanile_mesh,
    "mount_diablo": build_mount_diablo_mesh,
    "salesforce": build_salesforce_mesh,
    "transamerica": build_transamerica_mesh,
}


def _cross(
    first: Sequence[float], second: Sequence[float], third: Sequence[float]
) -> tuple[float, float, float]:
    ab = tuple(second[axis] - first[axis] for axis in range(3))
    ac = tuple(third[axis] - first[axis] for axis in range(3))
    return (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )


def validate_procedural_mesh(mesh: ProceduralMesh) -> None:
    if not mesh.vertices or not mesh.triangles:
        raise ValueError("procedural landmark mesh is empty")
    for triangle_index, triangle in enumerate(mesh.triangles):
        if len(triangle) != 4:
            raise ValueError(f"landmark triangle {triangle_index} is malformed")
        indices = triangle[:3]
        if any(not 0 <= index < len(mesh.vertices) for index in indices):
            raise ValueError(f"landmark triangle {triangle_index} has a bad index")
        normal = _cross(*(mesh.vertices[index] for index in indices))
        if sum(value * value for value in normal) <= 1e-16:
            raise ValueError(f"landmark triangle {triangle_index} is degenerate")
        # Horizontal exterior surfaces may face either way: roofs face up,
        # while an exposed underside such as a Transamerica wing faces down.
        # The corpus-specific tests pin which procedural faces use each sense.
        if triangle[3] not in LANDMARK_SELECTORS.values():
            raise ValueError(f"landmark triangle {triangle_index} has an unknown material")


def add_buried_foundation_skirt(
    mesh: ProceduralMesh,
    *,
    depth_m: int,
    selector: int,
) -> ProceduralMesh:
    """Add four outward foundation walls below local y=0.

    The open bottom is guaranteed to remain below every witnessed rendered
    terrain surface.  Omitting horizontal caps avoids coplanar top faces and
    permits the surrounding terrain to hide the deliberately conservative
    axis-aligned foundation footprint.
    """

    validate_procedural_mesh(mesh)
    if not isinstance(depth_m, int) or depth_m < MINIMUM_FOUNDATION_DEPTH_M:
        raise ValueError("foundation depth must be a positive integer metre count")
    if selector not in LANDMARK_SELECTORS.values():
        raise ValueError("foundation selector is not a landmark material")
    x0 = min(vertex[0] for vertex in mesh.vertices)
    x1 = max(vertex[0] for vertex in mesh.vertices)
    z0 = min(vertex[2] for vertex in mesh.vertices)
    z1 = max(vertex[2] for vertex in mesh.vertices)
    if x0 >= x1 or z0 >= z1:
        raise ValueError("foundation footprint must have positive area")

    builder = _MeshBuilder()
    bottom = -float(depth_m)
    # Match the outward side order used by _MeshBuilder.box, but intentionally
    # omit both caps: the top lies inside the building and the bottom is buried.
    builder.quad((x1, bottom, z0), (x1, 0.0, z0),
                 (x1, 0.0, z1), (x1, bottom, z1), selector)
    builder.quad((x0, bottom, z1), (x0, 0.0, z1),
                 (x0, 0.0, z0), (x0, bottom, z0), selector)
    builder.quad((x0, bottom, z1), (x1, bottom, z1),
                 (x1, 0.0, z1), (x0, 0.0, z1), selector)
    builder.quad((x1, bottom, z0), (x0, bottom, z0),
                 (x0, 0.0, z0), (x1, 0.0, z0), selector)
    foundation = builder.build()
    offset = len(mesh.vertices)
    combined = ProceduralMesh(
        mesh.vertices + foundation.vertices,
        mesh.triangles + tuple(
            (first + offset, second + offset, third + offset, material)
            for first, second, third, material in foundation.triangles
        ),
    )
    validate_procedural_mesh(combined)
    return combined


def _nearest_integer(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


def _cell_center_word(cell: int, dimension: int = 8) -> int:
    if not 0 <= cell < dimension:
        raise ValueError(f"palette cell is outside 0..{dimension - 1}: {cell}")
    scale = dimension - 1
    lower = (cell * 65_535 + scale - 1) // scale
    upper = (
        65_535 if cell == scale
        else ((cell + 1) * 65_535 + scale - 1) // scale - 1
    )
    return (lower + upper) // 2


def solid_palette_uv(selector: int) -> tuple[int, int]:
    if not 0 <= selector < 64:
        raise ValueError(f"solid palette selector is outside 0..63: {selector}")
    column, row = selector % 8, selector // 8
    return _cell_center_word(column), 65_535 - _cell_center_word(row)


def resolve_solid_palette_uv(uv: tuple[int, int]) -> int:
    column = uv[0] * 7 // 65_535
    row = (65_535 - uv[1]) * 7 // 65_535
    return row * 8 + column


def _absolute_vertices(
    mesh: ProceduralMesh,
    *,
    anchor_east_m: float,
    anchor_north_m: float,
    ground_elevation_m: float,
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        (
            anchor_north_m + vertex[0],
            ground_elevation_m + vertex[1],
            -anchor_east_m + vertex[2],
        )
        for vertex in mesh.vertices
    )


def _terrain_contact_specs(
    hierarchy: SuperTileGrid,
    east_m: float,
    north_m: float,
) -> tuple[ComponentSpec, ComponentSpec, ComponentSpec]:
    tile_x = math.floor((east_m - REGIONAL_ORIGIN_EAST_M) / REGIONAL_TILE_SIZE_M)
    tile_y = math.floor((north_m - REGIONAL_ORIGIN_NORTH_M) / REGIONAL_TILE_SIZE_M)
    supertile = hierarchy.from_base_tile(tile_x, tile_y)
    specs = component_specs(supertile)

    def contains_anchor_tile(spec: ComponentSpec) -> bool:
        rectangle = spec.rectangle
        return (
            rectangle.tile_x <= tile_x < rectangle.tile_x + rectangle.width_cells
            and rectangle.tile_y
            <= tile_y
            < rectangle.tile_y + rectangle.height_cells
        )

    near = tuple(
        spec
        for spec in specs
        if spec.tier == "near" and contains_anchor_tile(spec)
    )
    if len(near) != 1:
        raise ValueError(
            f"terrain contact point selects {len(near)} L0 components: "
            f"{east_m},{north_m}"
        )
    transition = next(spec for spec in specs if spec.key == "D1")
    distant = next(spec for spec in specs if spec.key == "D2")
    return near[0], transition, distant


def _surface_cache_key(spec: ComponentSpec) -> tuple[int, ...]:
    rectangle = spec.rectangle
    return (
        spec.lod,
        rectangle.tile_x,
        rectangle.tile_y,
        rectangle.width_cells,
        rectangle.height_cells,
        spec.model_half_extent_m,
    )


def _decoded_terrain_surface(
    dem: RasterMosaic,
    hierarchy: SuperTileGrid,
    spec: ComponentSpec,
    cache: dict[tuple[int, ...], _DecodedTerrainSurface],
) -> _DecodedTerrainSurface:
    key = _surface_cache_key(spec)
    cached = cache.get(key)
    if cached is not None:
        return cached
    topology = rectangular_topology(hierarchy.base, spec.rectangle, spec.lod)
    elevations = []
    for east, north in topology.points:
        sample = dem.sample_bilinear(east, north)
        if sample.value is None:
            raise ValueError(
                f"DEM nodata at landmark contact vertex {east},{north}"
            )
        elevations.append(float(sample.value))
    # Materials do not participate in geometry.  Calling the regional builder
    # with a valid constant selector retains its exact i16 quantization,
    # component origin, and model-half-extent behavior without an NLCD pass.
    built = build_component(
        hierarchy.base,
        spec,
        elevations_m=elevations,
        surface_materials=(0,) * len(topology.faces),
    )
    tile = built.tile
    center_east = REGIONAL_ORIGIN_EAST_M + tile.meta.center_east_m
    center_north = REGIONAL_ORIGIN_NORTH_M + tile.meta.center_north_m
    half_extent = tile.meta.model_half_extent_m
    vertices = tuple(
        (
            center_east - encoded_z / P3D_NORM_MAX * half_extent,
            center_north + encoded_x / P3D_NORM_MAX * half_extent,
            REGIONAL_VERTICAL_ORIGIN_M
            + encoded_y / P3D_NORM_MAX * half_extent,
        )
        for encoded_x, encoded_y, encoded_z in tile.positions[
            : len(topology.points)
        ]
    )
    surface = _DecodedTerrainSurface(spec, tile, vertices, topology.faces)
    cache[key] = surface
    return surface


def _barycentric_weights(
    east_m: float,
    north_m: float,
    first: Sequence[float],
    second: Sequence[float],
    third: Sequence[float],
) -> tuple[float, float, float] | None:
    denominator = (
        (second[1] - third[1]) * (first[0] - third[0])
        + (third[0] - second[0]) * (first[1] - third[1])
    )
    if abs(denominator) < 1e-12:
        return None
    first_weight = (
        (second[1] - third[1]) * (east_m - third[0])
        + (third[0] - second[0]) * (north_m - third[1])
    ) / denominator
    second_weight = (
        (third[1] - first[1]) * (east_m - third[0])
        + (first[0] - third[0]) * (north_m - third[1])
    ) / denominator
    return first_weight, second_weight, 1.0 - first_weight - second_weight


def _decoded_surface_elevation(
    surface: _DecodedTerrainSurface,
    east_m: float,
    north_m: float,
) -> float:
    candidates = []
    for face in surface.faces:
        vertices = tuple(
            surface.vertices_east_north_elevation_m[index] for index in face
        )
        weights = _barycentric_weights(
            east_m, north_m, vertices[0], vertices[1], vertices[2]
        )
        if weights is None or min(weights) < -1e-7:
            continue
        candidates.append(
            sum(weight * vertex[2] for weight, vertex in zip(
                weights, vertices, strict=True
            ))
        )
    if not candidates:
        raise ValueError(
            f"decoded L{surface.spec.lod} terrain does not contain "
            f"{east_m},{north_m}"
        )
    if max(candidates) - min(candidates) > 1e-6:
        raise ValueError("decoded terrain faces disagree at a shared contact edge")
    return candidates[0]


def _clip_surface_polygon(
    polygon: tuple[tuple[float, float, float], ...],
    *,
    axis: int,
    boundary: float,
    keep_greater: bool,
) -> tuple[tuple[float, float, float], ...]:
    if not polygon:
        return ()

    def inside(vertex: Sequence[float]) -> bool:
        return vertex[axis] >= boundary if keep_greater else vertex[axis] <= boundary

    output = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside != previous_inside:
            delta = current[axis] - previous[axis]
            if abs(delta) < 1e-15:
                raise ValueError("parallel decoded terrain edge crossed a clip plane")
            fraction = (boundary - previous[axis]) / delta
            intersection = tuple(
                previous[index] + fraction * (current[index] - previous[index])
                for index in range(3)
            )
            output.append(intersection)
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return tuple(output)


def _decoded_surface_footprint_range(
    surface: _DecodedTerrainSurface,
    bounds: tuple[float, float, float, float],
) -> tuple[float, float]:
    west, south, east, north = bounds
    values = []
    for face in surface.faces:
        polygon = tuple(
            surface.vertices_east_north_elevation_m[index] for index in face
        )
        for axis, boundary, keep_greater in (
            (0, west, True),
            (0, east, False),
            (1, south, True),
            (1, north, False),
        ):
            polygon = _clip_surface_polygon(
                polygon,
                axis=axis,
                boundary=boundary,
                keep_greater=keep_greater,
            )
            if not polygon:
                break
        values.extend(vertex[2] for vertex in polygon)
    if not values:
        raise ValueError("landmark footprint does not overlap decoded terrain")
    return min(values), max(values)


def _terrain_contact(
    mesh: ProceduralMesh,
    *,
    raw_dem_anchor_elevation_m: float,
    anchor_east_m: float,
    anchor_north_m: float,
    dem: RasterMosaic,
    hierarchy: SuperTileGrid,
    cache: dict[tuple[int, ...], _DecodedTerrainSurface],
) -> _TerrainContact:
    local_x = tuple(vertex[0] for vertex in mesh.vertices)
    local_z = tuple(vertex[2] for vertex in mesh.vertices)
    footprint_bounds = (
        anchor_east_m - max(local_z),
        anchor_north_m + min(local_x),
        anchor_east_m - min(local_z),
        anchor_north_m + max(local_x),
    )
    specs = _terrain_contact_specs(hierarchy, anchor_east_m, anchor_north_m)
    decoded = []
    for label, spec in zip(("L0", "L1", "L2"), specs, strict=True):
        component_bounds = spec.rectangle.bounds(hierarchy.base)
        if not (
            component_bounds[0] <= footprint_bounds[0]
            and component_bounds[1] <= footprint_bounds[1]
            and footprint_bounds[2] <= component_bounds[2]
            and footprint_bounds[3] <= component_bounds[3]
        ):
            raise ValueError(
                f"landmark footprint crosses its {label} contact component"
            )
        surface = _decoded_terrain_surface(dem, hierarchy, spec, cache)
        anchor = _decoded_surface_elevation(
            surface, anchor_east_m, anchor_north_m
        )
        footprint_minimum, footprint_maximum = (
            _decoded_surface_footprint_range(surface, footprint_bounds)
        )
        decoded.append(
            (label, spec, anchor, footprint_minimum, footprint_maximum)
        )

    model_base = decoded[0][2]
    global_minimum = min(item[3] for item in decoded)
    foundation_depth = max(
        MINIMUM_FOUNDATION_DEPTH_M,
        math.ceil(
            max(0.0, model_base - global_minimum) + FOUNDATION_BURY_MARGIN_M
        ),
    )
    foundation_bottom = model_base - foundation_depth
    rendered_lods = {}
    for label, spec, anchor, footprint_minimum, footprint_maximum in decoded:
        rendered_lods[label] = {
            "component_key": spec.key,
            "lod": spec.lod,
            "component_rectangle_base_cells": [
                spec.rectangle.tile_x,
                spec.rectangle.tile_y,
                spec.rectangle.width_cells,
                spec.rectangle.height_cells,
            ],
            "model_half_extent_m": spec.model_half_extent_m,
            "anchor_elevation_m_navd88": round(anchor, 6),
            "anchor_minus_raw_dem_m": round(
                anchor - raw_dem_anchor_elevation_m, 6
            ),
            "anchor_minus_l0_model_base_m": round(anchor - model_base, 6),
            "footprint_elevation_range_m_navd88": [
                round(footprint_minimum, 6),
                round(footprint_maximum, 6),
            ],
            "footprint_range_minus_l0_model_base_m": [
                round(footprint_minimum - model_base, 6),
                round(footprint_maximum - model_base, 6),
            ],
        }
    witness = {
        "policy": (
            "model y=0 is the exact decoded regional L0 P3DM surface at the "
            "anchor; L1/L2 and footprint ranges are decoded after the same "
            "regional topology and i16 quantization"
        ),
        "raw_dem_anchor_elevation_m_navd88": round(
            raw_dem_anchor_elevation_m, 6
        ),
        "model_base_elevation_m_navd88": round(model_base, 6),
        "footprint_bounds_absolute_utm_m": [
            round(value, 6) for value in footprint_bounds
        ],
        "rendered_lods": rendered_lods,
        "minimum_rendered_footprint_elevation_m_navd88": round(
            global_minimum, 6
        ),
        "foundation_bottom_elevation_m_navd88": round(
            foundation_bottom, 6
        ),
        "minimum_foundation_burial_clearance_m": round(
            global_minimum - foundation_bottom, 6
        ),
    }
    return _TerrainContact(model_base, foundation_depth, witness)


def _frame_for_vertices(
    vertices: Iterable[tuple[float, float, float]],
    *,
    anchor_east_m: float,
    anchor_north_m: float,
) -> LandmarkFrame:
    vertices = tuple(vertices)
    center_east = _nearest_integer(anchor_east_m)
    center_north = _nearest_integer(anchor_north_m)
    maximum = max(
        max(
            abs(vertex[0] - center_north),
            abs(vertex[1] - REGIONAL_VERTICAL_ORIGIN_M),
            abs(vertex[2] + center_east),
        )
        for vertex in vertices
    )
    half_extent = math.floor(maximum) + 1
    if half_extent > 2_047:
        raise ValueError(f"landmark needs unsupported {half_extent} m half extent")
    return LandmarkFrame(center_east, center_north, half_extent)


def _encode_position(
    vertex: Sequence[float], frame: LandmarkFrame
) -> tuple[int, int, int]:
    local = (
        vertex[0] - frame.center_north_abs_m,
        vertex[1] - REGIONAL_VERTICAL_ORIGIN_M,
        vertex[2] + frame.center_east_abs_m,
    )
    encoded = tuple(
        _nearest_integer(value * P3D_NORM_MAX / frame.model_half_extent_m)
        for value in local
    )
    if any(abs(value) > P3D_NORM_MAX for value in encoded):
        raise ValueError(f"landmark normalization overflow: {local}")
    return encoded  # type: ignore[return-value]


def build_landmark_tile(
    spec: LandmarkSpec,
    mesh: ProceduralMesh,
    ground_elevation_m: float,
) -> tuple[P3DMTile, LandmarkFrame, dict[str, object]]:
    """Normalize one procedural mesh against the shared regional frame."""

    if not math.isfinite(ground_elevation_m):
        raise ValueError("landmark ground elevation must be finite")
    validate_procedural_mesh(mesh)
    east, north = project_wgs84_utm10(spec.latitude_deg, spec.longitude_deg)
    source_vertices = _absolute_vertices(
        mesh,
        anchor_east_m=east,
        anchor_north_m=north,
        ground_elevation_m=ground_elevation_m,
    )
    frame = _frame_for_vertices(
        source_vertices, anchor_east_m=east, anchor_north_m=north
    )
    if not 0 <= frame.tile_x < REGIONAL_COLUMNS or not 0 <= frame.tile_y < REGIONAL_ROWS:
        raise ValueError(f"{spec.landmark_id} anchor is outside regional grid")
    positions = tuple(_encode_position(vertex, frame) for vertex in source_vertices)
    position_indices = tuple(index for face in mesh.triangles for index in face[:3])
    used_selectors = tuple(
        selector for selector in LANDMARK_SELECTORS.values()
        if any(face[3] == selector for face in mesh.triangles)
    )
    selector_indices = {selector: index for index, selector in enumerate(used_selectors)}
    uv_indices = tuple(
        selector_indices[face[3]]
        for face in mesh.triangles
        for _ in range(3)
    )
    elevations = tuple(vertex[1] for vertex in source_vertices)
    tile = P3DMTile(
        stage_buffer_id=STAGING_BUFFER_ID,
        meta=P3DMMeta(
            layer_kind=LayerKind.LANDMARK,
            lod=0,
            shading_mode=ShadingMode.SOLID_FLAT,
            illumination=IlluminationPolicy.SCENE,
            material_set=MaterialSet.NATIVE_SOLID_PALETTE,
            tile_x=frame.tile_x,
            tile_y=frame.tile_y,
            center_east_m=frame.center_east_m,
            center_north_m=frame.center_north_m,
            minimum_elevation_dm=math.floor(min(elevations) * 10.0),
            maximum_elevation_dm=math.ceil(max(elevations) * 10.0),
            model_half_extent_m=frame.model_half_extent_m,
        ),
        positions=positions,
        position_indices=position_indices,
        uvs=tuple(solid_palette_uv(selector) for selector in used_selectors),
        uv_indices=uv_indices,
    )

    errors: list[float] = []
    decoded_vertices = []
    encoded_degenerate = 0
    winding_changes = 0
    upward_horizontal_triangles = 0
    downward_horizontal_triangles = 0
    for source, encoded in zip(source_vertices, positions, strict=True):
        decoded = (
            frame.center_north_abs_m
            + encoded[0] / P3D_NORM_MAX * frame.model_half_extent_m,
            REGIONAL_VERTICAL_ORIGIN_M
            + encoded[1] / P3D_NORM_MAX * frame.model_half_extent_m,
            -frame.center_east_abs_m
            + encoded[2] / P3D_NORM_MAX * frame.model_half_extent_m,
        )
        decoded_vertices.append(decoded)
        errors.extend(abs(decoded[axis] - source[axis]) for axis in range(3))
    for source_face, offset in zip(
        mesh.triangles, range(0, len(position_indices), 3), strict=True
    ):
        source_normal = _cross(*(source_vertices[index] for index in source_face[:3]))
        encoded_normal = _cross(
            *(positions[position_indices[offset + index]] for index in range(3))
        )
        if sum(value * value for value in encoded_normal) == 0:
            encoded_degenerate += 1
        if sum(
            source_normal[axis] * encoded_normal[axis] for axis in range(3)
        ) <= 0.0:
            winding_changes += 1
        if abs(source_normal[0]) < 1e-8 and abs(source_normal[2]) < 1e-8:
            if source_normal[1] > 0.0:
                upward_horizontal_triangles += 1
            else:
                downward_horizontal_triangles += 1
    if encoded_degenerate or winding_changes:
        raise ValueError(
            f"{spec.landmark_id} quantization produced {encoded_degenerate} "
            f"degenerates and {winding_changes} winding changes"
        )
    witness = {
        "source_axis_bounds_absolute_pingo_m": [
            [round(min(vertex[axis] for vertex in source_vertices), 6),
             round(max(vertex[axis] for vertex in source_vertices), 6)]
            for axis in range(3)
        ],
        "encoded_axis_bounds": [
            [min(vertex[axis] for vertex in positions),
             max(vertex[axis] for vertex in positions)]
            for axis in range(3)
        ],
        "maximum_decode_error_m": round(max(errors), 9),
        "theoretical_decode_error_bound_m": round(
            frame.model_half_extent_m / (2 * P3D_NORM_MAX), 9
        ),
        "source_degenerate_triangles": 0,
        "encoded_degenerate_triangles": encoded_degenerate,
        "winding_changes_after_quantization": winding_changes,
        "upward_horizontal_triangles": upward_horizontal_triangles,
        "downward_horizontal_triangles": downward_horizontal_triangles,
    }
    return tile, frame, witness


def _meta_record(meta: P3DMMeta) -> dict[str, int]:
    result = asdict(meta)
    result["layer_kind"] = int(meta.layer_kind)
    result["shading_mode"] = int(meta.shading_mode)
    result["illumination"] = int(meta.illumination)
    result["material_set"] = int(meta.material_set)
    return result


def _selector_record(selector: int) -> dict[str, object]:
    return {
        "index": selector,
        "rgba2222": 0xC0 | selector,
        "rgb_levels": [selector & 3, (selector >> 2) & 3, (selector >> 4) & 3],
    }


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _manifest_procedural(manifest: dict, name: str) -> dict:
    try:
        return next(item for item in manifest["procedural_landmarks"]
                    if item["landmark"] == name)
    except (KeyError, StopIteration) as error:
        raise ValueError(f"landmark manifest lacks procedural control {name!r}") from error


def _manifest_donor(manifest: dict, name: str) -> dict:
    try:
        return next(item for item in manifest["selected_donor_files"]
                    if item["landmark"] == name)
    except (KeyError, StopIteration) as error:
        raise ValueError(f"landmark manifest lacks control record {name!r}") from error


def validate_source_controls(manifest: dict) -> None:
    """Fail if the pinned manifest stops matching the procedural scale inputs."""

    campanile = _manifest_procedural(manifest, "Sather Tower / the Campanile")
    if (
        campanile.get("authoritative_height_m") != 93.5736
        or campanile.get("placement", {}).get("latitude_deg") != 37.872332
        or campanile.get("placement", {}).get("longitude_deg") != -122.257964
    ):
        raise ValueError("Campanile source controls changed")
    diablo = _manifest_procedural(
        manifest, "Mount Diablo Summit Building and aviation beacon"
    )
    if (
        diablo.get("summit_elevation_m") != 1173.1752
        or diablo.get("placement", {}).get("latitude_deg") != 37.881702
        or diablo.get("placement", {}).get("longitude_deg") != -121.914268
    ):
        raise ValueError("Mount Diablo source controls changed")
    salesforce = _manifest_procedural(manifest, "Salesforce Tower")
    if (
        salesforce.get("authoritative_dimensions_m") != {
            "crown_height": 326.136,
            "maximum_floor_plan": [50.9016, 50.9016],
            "roof_height": 277.9776,
        }
        or salesforce.get("placement", {}).get("latitude_deg") != 37.78993419
        or salesforce.get("placement", {}).get("longitude_deg")
        != -122.397097479
    ):
        raise ValueError("Salesforce Tower source controls changed")
    transamerica = _manifest_donor(manifest, "Transamerica Pyramid")
    if (
        transamerica.get("conversion_seed", {}).get(
            "authoritative_dimensions_m"
        ) != [53.0352, 260.0, 53.0352]
        or transamerica.get("placement", {}).get("latitude_deg")
        != 37.79521298
        or transamerica.get("placement", {}).get("longitude_deg")
        != -122.4027781
    ):
        raise ValueError("Transamerica source controls changed")


def _dem_source_tile(dataset: dict, east: float, north: float) -> dict:
    for tile in dataset.get("tiles", ()):
        west, south, east_limit, north_limit = tile["bbox"]
        if west <= east < east_limit and south < north <= north_limit:
            return tile
    raise ValueError(f"landmark point is outside DEM tiles: {east},{north}")


def _component_record(
    output: Path,
    relative: Path,
    tile: P3DMTile,
    frame: LandmarkFrame,
    witness: dict[str, object],
) -> dict[str, object]:
    container = make_container(tile)
    if parse_container(container) != tile:
        raise ValueError(f"P3DM round trip changed {relative.as_posix()}")
    destination = output / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(container)
    data = make_data(tile)
    return {
        "path": relative.as_posix(),
        "bytes": len(container),
        "sha256": sha256(container).hexdigest(),
        "data_bytes": len(data),
        "data_sha256": sha256(data).hexdigest(),
        "vertices": len(tile.positions),
        "triangles": len(tile.position_indices) // 3,
        "selectors": [resolve_solid_palette_uv(uv) for uv in tile.uvs],
        "meta": _meta_record(tile.meta),
        "object_transform": {
            "origin_absolute_m": {
                "east": frame.center_east_abs_m,
                "north": frame.center_north_abs_m,
                "elevation": REGIONAL_VERTICAL_ORIGIN_M,
            },
            "origin_relative_to_region_m": {
                "east": frame.center_east_m,
                "north": frame.center_north_m,
                "elevation": REGIONAL_VERTICAL_ORIGIN_M,
            },
            "pingo_axes_relative_to_region_m": [
                frame.center_north_m,
                REGIONAL_VERTICAL_ORIGIN_M,
                -frame.center_east_m,
            ],
            "euler_rotation_words": [0, 0, 0],
            "orientation_policy": (
                "procedural geometry is regional-grid aligned; no unpinned "
                "facade heading is asserted"
            ),
            "uniform_model_half_extent_m": frame.model_half_extent_m,
            "uniform_object_scale_internal": (
                frame.model_half_extent_m / METRES_PER_PINGO_UNIT
            ),
            "uniform_object_scale_q8_8": frame.scale_wire_q8_8,
        },
        "normalization_witness": witness,
    }


def build_landmark_p3dm_corpus(
    output: Path,
    *,
    source_root: Path,
    regional_manifest_path: Path,
    landmark_manifest_path: Path,
    verify_source_hashes: bool = True,
) -> dict[str, object]:
    """Build four procedural landmarks from pinned local control data."""

    regional_manifest_bytes = regional_manifest_path.read_bytes()
    landmark_manifest_bytes = landmark_manifest_path.read_bytes()
    regional_manifest = json.loads(regional_manifest_bytes)
    landmark_manifest = json.loads(landmark_manifest_bytes)
    validate_source_controls(landmark_manifest)
    try:
        dem_dataset = next(
            item for item in regional_manifest["datasets"]
            if item["id"] == "usgs-3dep-10m-utm10n"
        )
    except (KeyError, StopIteration) as error:
        raise ValueError("regional manifest lacks the 3DEP DEM") from error
    if dem_dataset.get("crs") != REGIONAL_CRS:
        raise ValueError("landmark DEM is not EPSG:32610")

    anchors = {
        spec.landmark_id: project_wgs84_utm10(
            spec.latitude_deg, spec.longitude_deg
        )
        for spec in LANDMARK_SPECS
    }
    hierarchy = SuperTileGrid()
    contact_specs_by_landmark = {
        landmark_id: _terrain_contact_specs(hierarchy, east, north)
        for landmark_id, (east, north) in anchors.items()
    }
    used_source_tiles = {}
    for landmark_id, (east, north) in anchors.items():
        source_points = [(east, north)]
        for contact_spec in contact_specs_by_landmark[landmark_id]:
            source_points.extend(
                rectangular_topology(
                    hierarchy.base,
                    contact_spec.rectangle,
                    contact_spec.lod,
                ).points
            )
        for point_east, point_north in source_points:
            source_tile = _dem_source_tile(
                dem_dataset, point_east, point_north
            )
            used_source_tiles[source_tile["id"]] = source_tile
    if verify_source_hashes:
        for tile in used_source_tiles.values():
            path = source_root / tile["local_path"]
            if path.stat().st_size != tile["byte_size"]:
                raise ValueError(f"DEM source size changed: {path}")
            if sha256_file(path) != tile["sha256"]:
                raise ValueError(f"DEM source hash changed: {path}")

    output.mkdir(parents=True, exist_ok=True)
    palette_relative = Path("LMK") / "SOLID64.RG2"
    palette_path = output / palette_relative
    palette_path.parent.mkdir(parents=True, exist_ok=True)
    palette_path.write_bytes(SOLID_PALETTE)
    mosaic = RasterMosaic(source_root, dem_dataset)
    surface_cache: dict[tuple[int, ...], _DecodedTerrainSurface] = {}

    landmark_records = []
    component_records = []
    for spec in LANDMARK_SPECS:
        east, north = anchors[spec.landmark_id]
        sample = mosaic.sample_bilinear(east, north)
        if sample.value is None or sample.edge_padded:
            raise ValueError(f"invalid DEM sample for {spec.landmark_id}: {sample}")
        raw_ground = float(sample.value)
        recognition_mesh = _MESH_BUILDERS[spec.landmark_id]()
        contact = _terrain_contact(
            recognition_mesh,
            raw_dem_anchor_elevation_m=raw_ground,
            anchor_east_m=east,
            anchor_north_m=north,
            dem=mosaic,
            hierarchy=hierarchy,
            cache=surface_cache,
        )
        foundation_selector_name = (
            "glass_shadow" if spec.landmark_id == "salesforce"
            else "stone_shadow"
        )
        foundation_selector = LANDMARK_SELECTORS[foundation_selector_name]
        mesh = add_buried_foundation_skirt(
            recognition_mesh,
            depth_m=contact.foundation_depth_m,
            selector=foundation_selector,
        )
        if len(mesh.triangles) > spec.triangle_budget:
            raise ValueError(
                f"{spec.landmark_id} exceeds triangle budget "
                f"{len(mesh.triangles)}>{spec.triangle_budget}"
            )
        tile, frame, witness = build_landmark_tile(
            spec, mesh, contact.model_base_elevation_m
        )
        relative = Path("LMK") / spec.filename
        component = _component_record(output, relative, tile, frame, witness)
        component_records.append(component)
        source_tile = _dem_source_tile(dem_dataset, east, north)
        recognition_x = [vertex[0] for vertex in recognition_mesh.vertices]
        recognition_y = [vertex[1] for vertex in recognition_mesh.vertices]
        recognition_z = [vertex[2] for vertex in recognition_mesh.vertices]
        local_x = [vertex[0] for vertex in mesh.vertices]
        local_y = [vertex[1] for vertex in mesh.vertices]
        local_z = [vertex[2] for vertex in mesh.vertices]
        geometry_radius = math.ceil(
            max(
                math.hypot(x, z)
                for x, z in zip(recognition_x, recognition_z, strict=True)
            )
        )
        record: dict[str, object] = {
            "id": spec.landmark_id,
            "name": spec.name,
            "approximation_status": (
                "original procedural recognition model; not survey, facade, "
                "navigation, or collision geometry"
            ),
            "anchor": {
                "semantics": spec.anchor_semantics,
                "source": spec.placement_source,
                "wgs84_degrees": [spec.longitude_deg, spec.latitude_deg],
                "absolute_utm_m": [round(east, 6), round(north, 6)],
                "relative_to_region_m": [
                    round(east - REGIONAL_ORIGIN_EAST_M, 6),
                    round(north - REGIONAL_ORIGIN_NORTH_M, 6),
                ],
            },
            "nominal_source_controls": list(spec.nominal_controls),
            "dimension_sources": list(spec.dimension_sources),
            "approximations": list(spec.approximations),
            "recognition_local_bounds_m": {
                "x_north": [
                    round(min(recognition_x), 6), round(max(recognition_x), 6)
                ],
                "y_agl": [
                    round(min(recognition_y), 6), round(max(recognition_y), 6)
                ],
                "z_west": [
                    round(min(recognition_z), 6), round(max(recognition_z), 6)
                ],
            },
            "procedural_local_bounds_m": {
                "x_north": [round(min(local_x), 6), round(max(local_x), 6)],
                "y_agl": [round(min(local_y), 6), round(max(local_y), 6)],
                "z_west": [round(min(local_z), 6), round(max(local_z), 6)],
            },
            "ground_drape": {
                "elevation_m_navd88": round(
                    contact.model_base_elevation_m, 6
                ),
                "method": (
                    "exact decoded regional L0 P3DM surface at the anchor"
                ),
                "raw_dem_elevation_m_navd88": round(raw_ground, 6),
                "raw_dem_method": "bilinear sample on the pinned 10 m 3DEP grid",
                "dataset_id": dem_dataset["id"],
                "source_tile_id": source_tile["id"],
                "source_tile_sha256": source_tile["sha256"],
            },
            "terrain_contact": contact.witness,
            "foundation_skirt": {
                "depth_m": contact.foundation_depth_m,
                "bury_margin_m": FOUNDATION_BURY_MARGIN_M,
                "selector_role": foundation_selector_name,
                "selector": foundation_selector,
                "vertices": len(mesh.vertices) - len(recognition_mesh.vertices),
                "triangles": (
                    len(mesh.triangles) - len(recognition_mesh.triangles)
                ),
                "policy": (
                    "four outward walls from local y=0 to a witnessed buried "
                    "bottom; no top or bottom cap"
                ),
            },
            "activation_circle": {
                "center_east_m": round(east - REGIONAL_ORIGIN_EAST_M, 3),
                "center_north_m": round(north - REGIONAL_ORIGIN_NORTH_M, 3),
                "geometry_radius_m": geometry_radius,
                "load_radius_m": spec.load_radius_m,
                "retain_radius_m": spec.load_radius_m + RETENTION_HYSTERESIS_M,
                "policy": "projected-importance recognition radius, not collision range",
            },
            "triangle_budget": spec.triangle_budget,
            "component": component,
        }
        if spec.landmark_id == "mount_diablo":
            record["summit_control_comparison"] = {
                "official_summit_elevation_m": 1173.1752,
                "raw_dem_minus_official_m": round(
                    raw_ground - 1173.1752, 6
                ),
                "rendered_l0_minus_official_m": round(
                    contact.model_base_elevation_m - 1173.1752, 6
                ),
                "policy": (
                    "retain both differences; align the model to rendered L0 "
                    "without relabeling the DEM or point-elevation control"
                ),
            }
        landmark_records.append(record)

    module_bytes = Path(__file__).read_bytes()
    signature = sha256(
        regional_manifest_bytes + landmark_manifest_bytes + module_bytes
    ).hexdigest()
    source_tiles = [
        {
            "id": tile["id"],
            "local_path": tile["local_path"],
            "byte_size": tile["byte_size"],
            "sha256": tile["sha256"],
        }
        for tile in sorted(used_source_tiles.values(), key=lambda item: item["id"])
    ]
    index: dict[str, object] = {
        "schema": "pingo-terrain-procedural-landmark-index",
        "version": 1,
        "agnb_version": "0.3",
        "p3dm_layout_version": 1,
        "build_signature_sha256": signature,
        "source": {
            "regional_manifest": {
                "path": regional_manifest_path.name,
                "sha256": sha256(regional_manifest_bytes).hexdigest(),
            },
            "landmark_control_manifest": {
                "path": landmark_manifest_path.name,
                "sha256": sha256(landmark_manifest_bytes).hexdigest(),
            },
            "ground_dataset": {
                "id": dem_dataset["id"],
                "provider": dem_dataset["provider"],
                "product": dem_dataset["product"],
                "horizontal_crs": dem_dataset["crs"],
                "vertical_datum": dem_dataset["vertical_datum"],
                "license_status": dem_dataset["license_status"],
                "sampled_tiles": source_tiles,
            },
            "geometry": (
                "original deterministic Python primitives; no donor mesh, "
                "imagery, texture bitmap, or network access"
            ),
        },
        "regional_frame": {
            "horizontal_crs": REGIONAL_CRS,
            "origin_easting_m": REGIONAL_ORIGIN_EAST_M,
            "origin_northing_m": REGIONAL_ORIGIN_NORTH_M,
            "vertical_origin_m": REGIONAL_VERTICAL_ORIGIN_M,
            "tile_size_m": REGIONAL_TILE_SIZE_M,
            "columns": REGIONAL_COLUMNS,
            "rows": REGIONAL_ROWS,
            "pingo_axes": {"x": "grid north", "y": "up", "z": "negative grid east"},
            "metres_per_pingo_unit": METRES_PER_PINGO_UNIT,
        },
        "solid_selector_palette": {
            "path": palette_relative.as_posix(),
            "dimensions": [8, 8],
            "bytes": len(SOLID_PALETTE),
            "sha256": sha256(SOLID_PALETTE).hexdigest(),
            "layout": "row-major raw six-bit RGB index; byte = 0xC0 | index",
            "used_cells": {
                name: _selector_record(selector)
                for name, selector in LANDMARK_SELECTORS.items()
            },
            "texture_policy": (
                "selector lookup only; no image-derived color or facade texture"
            ),
        },
        "render_policy": {
            "shading_mode": int(ShadingMode.SOLID_FLAT),
            "illumination": int(IlluminationPolicy.SCENE),
            "material_set": int(MaterialSet.NATIVE_SOLID_PALETTE),
            "dither": False,
        },
        "landmarks": landmark_records,
        "statistics": {
            "landmarks": len(landmark_records),
            "components": len(component_records),
            "vertices": sum(record["vertices"] for record in component_records),
            "triangles": sum(record["triangles"] for record in component_records),
            "container_bytes": sum(record["bytes"] for record in component_records),
            "selected_palette_cells": len(LANDMARK_SELECTORS),
        },
    }
    (output / "LANDMARK.json").write_bytes(_canonical_json_bytes(index))
    return index
