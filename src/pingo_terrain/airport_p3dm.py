"""Regional FAA-airport P3DM compiler.

The source APT records are NAD83 latitude/longitude with FAA elevations in
feet MSL.  This module projects their horizontal coordinates onto the Bay Area
EPSG:32610 grid, builds the shared runway geometry, partitions only when a
single Pingo object's Q8.8 scale would overflow, and writes solid-flat P3DM
components plus a deterministic regional airport index.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from .airports import (
    Airport,
    GeoPoint,
    MARKING_RGBA2222,
    NASR_ARCHIVE_SHA256,
    NASR_EFFECTIVE_DATE,
    PAVEMENT_RGBA2222,
    START_CLEARANCE_M,
    TAXIWAY_RGBA2222,
    airport_record,
    build_airport_geometry,
    build_airport_meshes,
    canonical_json_bytes,
)
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


REGIONAL_CRS = "EPSG:32610"
REGIONAL_ORIGIN_EAST_M = 521_728
REGIONAL_ORIGIN_NORTH_M = 4_100_096
REGIONAL_VERTICAL_ORIGIN_M = 608.0
REGIONAL_TILE_SIZE_M = 512
REGIONAL_COLUMNS = 201
REGIONAL_ROWS = 252
REGIONAL_EAST_LIMIT_M = 624_640
REGIONAL_NORTH_LIMIT_M = 4_229_120

METRES_PER_PINGO_UNIT = 8
Q8_8_ONE = 256
P3D_NORM_MAX = 32_767
MAX_OBJECT_SCALE_WIRE = 65_535
# An integer-metre half extent of 2048 would require wire scale 65536.  Keep
# every generated component at or below the largest exactly representable
# integer-metre scale.
MAX_MODEL_HALF_EXTENT_M = MAX_OBJECT_SCALE_WIRE // (
    Q8_8_ONE // METRES_PER_PINGO_UNIT
)
STAGING_BUFFER_ID = 0x7400

# The solid palette is the raw opaque AABBGGRR cube in row-major six-bit color
# order.  This is intentionally not the historical MOS-first colors64 order.
SOLID_PALETTE = bytes(range(0xC0, 0x100))
PAVEMENT_SELECTOR = PAVEMENT_RGBA2222 & 0x3F  # 0x15 = 21
WHITE_SELECTOR = MARKING_RGBA2222 & 0x3F  # 0x3f = 63
YELLOW_SELECTOR = TAXIWAY_RGBA2222 & 0x3F  # 0x0f = 15, reserved

ACTIVATION_MARGIN_M = 2_048
RETENTION_HYSTERESIS_M = REGIONAL_TILE_SIZE_M

# WGS84 parameters used by EPSG:32610.  FAA NAD83 angular coordinates are
# treated as numerically coincident with WGS84 for this prototype; the index
# records that this is only a ballpark horizontal datum transformation.
WGS84_SEMIMAJOR_M = 6_378_137.0
WGS84_INVERSE_FLATTENING = 298.257223563
UTM_SCALE = 0.9996
UTM_ZONE_10_CENTRAL_MERIDIAN_DEG = -123.0


@dataclass(frozen=True)
class ModelFrame:
    """Shared transform used by one pavement/marking component pair."""

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
            Q8_8_ONE // METRES_PER_PINGO_UNIT
        )


def project_wgs84_utm10(
    latitude_deg: float, longitude_deg: float
) -> tuple[float, float]:
    """Project numeric WGS84 latitude/longitude to UTM zone 10 north.

    This is the EPSG Guidance Note series expansion used for UTM.  It avoids a
    runtime dependency on PROJ while retaining millimetre agreement with
    PROJ 9.4 for the pinned Bay Area source points.
    """

    if not -80.0 <= latitude_deg <= 84.0:
        raise ValueError(f"latitude is outside UTM coverage: {latitude_deg}")
    if not -126.0 <= longitude_deg <= -120.0:
        raise ValueError(f"longitude is outside UTM zone 10: {longitude_deg}")

    flattening = 1.0 / WGS84_INVERSE_FLATTENING
    eccentricity_squared = flattening * (2.0 - flattening)
    second_eccentricity_squared = eccentricity_squared / (
        1.0 - eccentricity_squared
    )
    latitude = math.radians(latitude_deg)
    longitude_delta = math.radians(
        longitude_deg - UTM_ZONE_10_CENTRAL_MERIDIAN_DEG
    )
    sin_latitude = math.sin(latitude)
    cos_latitude = math.cos(latitude)
    tan_latitude = math.tan(latitude)
    n = WGS84_SEMIMAJOR_M / math.sqrt(
        1.0 - eccentricity_squared * sin_latitude * sin_latitude
    )
    t = tan_latitude * tan_latitude
    c = second_eccentricity_squared * cos_latitude * cos_latitude
    a = cos_latitude * longitude_delta
    e4 = eccentricity_squared * eccentricity_squared
    e6 = e4 * eccentricity_squared
    meridional_arc = WGS84_SEMIMAJOR_M * (
        (1.0 - eccentricity_squared / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0)
        * latitude
        - (3.0 * eccentricity_squared / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0)
        * math.sin(2.0 * latitude)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0)
        * math.sin(4.0 * latitude)
        - 35.0 * e6 / 3072.0 * math.sin(6.0 * latitude)
    )
    easting = 500_000.0 + UTM_SCALE * n * (
        a
        + (1.0 - t + c) * a**3 / 6.0
        + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * second_eccentricity_squared)
        * a**5
        / 120.0
    )
    northing = UTM_SCALE * (
        meridional_arc
        + n
        * tan_latitude
        * (
            a * a / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c * c) * a**4 / 24.0
            + (
                61.0
                - 58.0 * t
                + t * t
                + 600.0 * c
                - 330.0 * second_eccentricity_squared
            )
            * a**6
            / 720.0
        )
    )
    return easting, northing


def project_faa_point(point: GeoPoint) -> tuple[float, float, float]:
    """Return regional Pingo-axis metres: north, FAA MSL elevation, west."""

    east, north = project_wgs84_utm10(
        point.latitude_deg, point.longitude_deg
    )
    return north, point.elevation_m_msl, -east


def _cell_center_word(cell: int, dimension: int = 8) -> int:
    if not 0 <= cell < dimension:
        raise ValueError(f"palette cell is outside 0..{dimension - 1}: {cell}")
    scale = dimension - 1
    lower = (cell * 65_535 + scale - 1) // scale
    upper = (
        65_535
        if cell == scale
        else ((cell + 1) * 65_535 + scale - 1) // scale - 1
    )
    return (lower + upper) // 2


def solid_palette_uv(selector: int) -> tuple[int, int]:
    """Return an interior UV selecting one raw six-bit color cube cell."""

    if not 0 <= selector < 64:
        raise ValueError(f"solid palette selector is outside 0..63: {selector}")
    column, row = selector % 8, selector // 8
    return _cell_center_word(column), 65_535 - _cell_center_word(row)


def resolve_solid_palette_uv(uv: tuple[int, int]) -> int:
    column = uv[0] * 7 // 65_535
    row = (65_535 - uv[1]) * 7 // 65_535
    return row * 8 + column


def _mesh_dicts(
    airport: Airport, runways: Sequence
) -> tuple[dict[str, object], dict[str, object]]:
    subset = replace(airport, runways=tuple(runways))
    pavement, markings, _deltas = build_airport_meshes(
        subset, project_faa_point
    )
    return pavement.as_dict(), markings.as_dict()


def _vertices(mesh: dict[str, object]) -> list[list[float]]:
    values = mesh["vertices_pingo_m"]
    if not isinstance(values, list) or not values:
        raise ValueError("airport mesh has no vertices")
    return values  # type: ignore[return-value]


def _triangles(mesh: dict[str, object]) -> list[list[int]]:
    values = mesh["triangles"]
    if not isinstance(values, list) or not values:
        raise ValueError("airport mesh has no triangles")
    return values  # type: ignore[return-value]


def _nearest_integer(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


def _frame_for_meshes(meshes: Iterable[dict[str, object]]) -> ModelFrame:
    vertices = [vertex for mesh in meshes for vertex in _vertices(mesh)]
    eastings = [-vertex[2] for vertex in vertices]
    northings = [vertex[0] for vertex in vertices]
    center_east = _nearest_integer((min(eastings) + max(eastings)) / 2.0)
    center_north = _nearest_integer((min(northings) + max(northings)) / 2.0)
    maximum = max(
        max(abs(vertex[0] - center_north), abs(-vertex[2] - center_east))
        for vertex in vertices
    )
    maximum = max(
        maximum,
        max(abs(vertex[1] - REGIONAL_VERTICAL_ORIGIN_M) for vertex in vertices),
    )
    # Always retain a positive sub-metre pad, including when a bound happens
    # to lie at an exact integer.  The integer witness is then sufficient to
    # prove every normalized coordinate is strictly inside the signed limit.
    half_extent = math.floor(maximum) + 1
    return ModelFrame(center_east, center_north, half_extent)


def _partition_runways(
    airport: Airport,
) -> list[tuple[tuple, dict[str, object], dict[str, object], ModelFrame]]:
    """Greedily form stable, minimal-in-order safe runway groups."""

    groups: list[list] = []
    for runway in airport.runways:
        for group in groups:
            candidate = (*group, runway)
            pavement, markings = _mesh_dicts(airport, candidate)
            if (
                _frame_for_meshes((pavement, markings)).model_half_extent_m
                <= MAX_MODEL_HALF_EXTENT_M
            ):
                group.append(runway)
                break
        else:
            pavement, markings = _mesh_dicts(airport, (runway,))
            frame = _frame_for_meshes((pavement, markings))
            if frame.model_half_extent_m > MAX_MODEL_HALF_EXTENT_M:
                raise ValueError(
                    f"{airport.icao_id} runway {runway.identifier} alone needs "
                    f"{frame.model_half_extent_m} m model half extent"
                )
            groups.append([runway])

    result = []
    for group in groups:
        pavement, markings = _mesh_dicts(airport, group)
        frame = _frame_for_meshes((pavement, markings))
        result.append((tuple(group), pavement, markings, frame))
    return result


def _normalized_position(
    vertex: Sequence[float], frame: ModelFrame
) -> tuple[int, int, int]:
    local = (
        vertex[0] - frame.center_north_abs_m,
        vertex[1] - REGIONAL_VERTICAL_ORIGIN_M,
        vertex[2] + frame.center_east_abs_m,
    )
    normalized = tuple(
        _nearest_integer(value * P3D_NORM_MAX / frame.model_half_extent_m)
        for value in local
    )
    if any(abs(value) > P3D_NORM_MAX for value in normalized):
        raise ValueError(f"normalization overflow in model frame {frame}: {local}")
    return normalized  # type: ignore[return-value]


def _mesh_tile(
    mesh: dict[str, object],
    frame: ModelFrame,
    layer: LayerKind,
    material_id: int,
    selector: int,
) -> tuple[P3DMTile, dict[str, object]]:
    vertices = _vertices(mesh)
    triangles = _triangles(mesh)
    if any(triangle[3] != material_id for triangle in triangles):
        raise ValueError(f"{mesh['id']} contains an unexpected material")
    positions = tuple(_normalized_position(vertex, frame) for vertex in vertices)
    indices = tuple(index for triangle in triangles for index in triangle[:3])
    for offset in range(0, len(indices), 3):
        first, second, third = (positions[indices[offset + index]] for index in range(3))
        ab_x, ab_z = second[0] - first[0], second[2] - first[2]
        ac_x, ac_z = third[0] - first[0], third[2] - first[2]
        if ab_z * ac_x - ab_x * ac_z <= 0:
            raise ValueError(
                f"{mesh['id']} triangle {offset // 3} lost upward winding during quantization"
            )

    elevations = [vertex[1] for vertex in vertices]
    tile = P3DMTile(
        stage_buffer_id=STAGING_BUFFER_ID,
        meta=P3DMMeta(
            layer_kind=layer,
            lod=0,
            shading_mode=ShadingMode.SOLID_FLAT,
            illumination=IlluminationPolicy.SELF,
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
        position_indices=indices,
        uvs=(solid_palette_uv(selector),),
        uv_indices=(0,) * len(indices),
    )
    errors = []
    decoded_vertices = []
    for source, encoded in zip(vertices, positions, strict=True):
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
    witness = {
        "source_elevation_bounds_faa_msl_m": [
            round(min(elevations), 6),
            round(max(elevations), 6),
        ],
        "descriptor_elevation_bounds_dm": [
            tile.meta.minimum_elevation_dm,
            tile.meta.maximum_elevation_dm,
        ],
        "maximum_decode_error_m": round(max(errors), 9),
        "theoretical_decode_error_bound_m": round(
            frame.model_half_extent_m / (2 * P3D_NORM_MAX), 9
        ),
        "encoded_axis_bounds": [
            [min(position[axis] for position in positions), max(position[axis] for position in positions)]
            for axis in range(3)
        ],
        "decoded_elevation_bounds_faa_msl_m": [
            round(min(vertex[1] for vertex in decoded_vertices), 6),
            round(max(vertex[1] for vertex in decoded_vertices), 6),
        ],
    }
    return tile, witness


def _meta_record(meta: P3DMMeta) -> dict[str, int]:
    result = asdict(meta)
    result["layer_kind"] = int(meta.layer_kind)
    result["shading_mode"] = int(meta.shading_mode)
    result["illumination"] = int(meta.illumination)
    result["material_set"] = int(meta.material_set)
    return result


def _component_record(
    output: Path,
    relative: Path,
    tile: P3DMTile,
    witness: dict[str, object],
    frame: ModelFrame,
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
        "selector": resolve_solid_palette_uv(tile.uvs[0]),
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
            "uniform_model_half_extent_m": frame.model_half_extent_m,
            "uniform_object_scale_internal": frame.model_half_extent_m
            / METRES_PER_PINGO_UNIT,
            "uniform_object_scale_q8_8": frame.scale_wire_q8_8,
        },
        "normalization_witness": witness,
    }


def _canonical_start(
    airport: Airport,
    group_records: Sequence[dict[str, object]],
) -> dict[str, object]:
    source = build_airport_geometry(airport)["canonical_start"]
    runway = next(value for value in airport.runways if value.identifier == "10R/28L")
    by_end = {end.identifier: end for end in runway.ends}
    start_end, opposite_end = by_end["28L"], by_end["10R"]
    start_east, start_north = project_wgs84_utm10(
        start_end.threshold.latitude_deg, start_end.threshold.longitude_deg
    )
    opposite_east, opposite_north = project_wgs84_utm10(
        opposite_end.threshold.latitude_deg, opposite_end.threshold.longitude_deg
    )
    delta_east = opposite_east - start_east
    delta_north = opposite_north - start_north
    length = math.hypot(delta_east, delta_north)
    forward_x = delta_north / length
    forward_z = -delta_east / length
    camera_yaw_radians = math.atan2(-forward_x, -forward_z)
    camera_yaw_word = _nearest_integer(
        camera_yaw_radians / (2.0 * math.pi) * 32_768
    )
    group = next(
        record
        for record in group_records
        if "10R/28L" in record["runways"]  # type: ignore[operator]
    )
    preload = [
        group["components"][0]["path"],  # type: ignore[index]
        group["components"][1]["path"],  # type: ignore[index]
    ]
    surface_elevation = start_end.threshold.elevation_m_msl
    tile_x = int(
        (start_east - REGIONAL_ORIGIN_EAST_M) // REGIONAL_TILE_SIZE_M
    )
    tile_y = int(
        (start_north - REGIONAL_ORIGIN_NORTH_M) // REGIONAL_TILE_SIZE_M
    )
    coarse_center_east = (
        REGIONAL_ORIGIN_EAST_M
        + tile_x * REGIONAL_TILE_SIZE_M
        + REGIONAL_TILE_SIZE_M // 2
    )
    coarse_center_north = (
        REGIONAL_ORIGIN_NORTH_M
        + tile_y * REGIONAL_TILE_SIZE_M
        + REGIONAL_TILE_SIZE_M // 2
    )
    camera_counts = {
        "x_north": _nearest_integer((start_north - coarse_center_north) * 16.0),
        "y_absolute_altitude": _nearest_integer(
            (surface_elevation + START_CLEARANCE_M) * 16.0
        ),
        "z_west": _nearest_integer(-(start_east - coarse_center_east) * 16.0),
    }
    group_transform = group["components"][0]["object_transform"]  # type: ignore[index]
    group_origin = group_transform["origin_absolute_m"]  # type: ignore[index]
    group_counts = {
        "x_north": int(
            (group_origin["north"] - coarse_center_north) * 16  # type: ignore[index,operator]
        ),
        "y_absolute_model_origin": int(group_origin["elevation"] * 16),  # type: ignore[index,operator]
        "z_west": int(
            -(group_origin["east"] - coarse_center_east) * 16  # type: ignore[index,operator]
        ),
    }
    return {
        "airport_icao": "KOAK",
        "runway_id": "10R/28L",
        "runway_end_id": "28L",
        "threshold_source": source["threshold_source"],  # type: ignore[index]
        "threshold_latitude_deg_nad83": start_end.threshold.latitude_deg,
        "threshold_longitude_deg_nad83": start_end.threshold.longitude_deg,
        "surface_elevation_ft_faa_msl": start_end.threshold.elevation_ft_msl,
        "surface_elevation_m_faa_msl": round(surface_elevation, 6),
        "faa_true_alignment_deg_nearest_degree": start_end.true_alignment_deg,
        "heading_true_deg_from_threshold_centerline": source[
            "heading_true_deg_from_threshold_centerline"
        ],
        "heading_grid_deg_from_projected_centerline": round(
            math.degrees(math.atan2(delta_east, delta_north)) % 360.0, 6
        ),
        "surface_position_absolute_utm_m": [
            round(start_east, 6),
            round(start_north, 6),
            round(surface_elevation, 6),
        ],
        "surface_position_relative_to_region_m": [
            round(start_east - REGIONAL_ORIGIN_EAST_M, 6),
            round(start_north - REGIONAL_ORIGIN_NORTH_M, 6),
            round(surface_elevation, 6),
        ],
        "aircraft_position_pingo_relative_to_region_m": [
            round(start_north - REGIONAL_ORIGIN_NORTH_M, 6),
            round(
                surface_elevation
                + START_CLEARANCE_M
                - REGIONAL_VERTICAL_ORIGIN_M,
                6,
            ),
            round(-(start_east - REGIONAL_ORIGIN_EAST_M), 6),
        ],
        "aircraft_position_pingo_relative_to_region_m_convention": (
            "X/Z are relative to the regional horizontal origin; Y is altitude "
            "relative to the shared 608.0 m mesh vertical origin. This is a model "
            "coordinate, not the camera translation packet."
        ),
        "initial_clearance_m": START_CLEARANCE_M,
        "forward_pingo_unit": [
            round(forward_x, 9),
            0.0,
            round(forward_z, 9),
        ],
        "anchor_tile": {
            "tile_x": tile_x,
            "tile_y": tile_y,
        },
        "pingo_wire_start_witness": {
            "translation_counts_per_metre": 16,
            "coarse_cell_center_absolute_utm_m": {
                "east": coarse_center_east,
                "north": coarse_center_north,
            },
            "camera_translation_counts": camera_counts,
            "camera_translation_convention": (
                "X/Z are fine offsets from the coarse cell center; camera Y is "
                "absolute altitude, including initial clearance, not relative to "
                "the 608 m mesh origin"
            ),
            "camera_euler_rotation_words": {
                "pitch_x": 0,
                "yaw_y": camera_yaw_word,
                "roll_z": 0,
                "yaw_y_unsigned_hex": f"0x{camera_yaw_word & 0xFFFF:04X}",
            },
            "camera_yaw_derivation": {
                "library_contract": (
                    "p3d_camera_aim_at_point16 upright yaw = atan2(-dx,-dz); "
                    "one Pingo binary turn is 32768 words"
                ),
                "yaw_degrees_signed": round(math.degrees(camera_yaw_radians), 6),
                "unrounded_word": round(
                    camera_yaw_radians / (2.0 * math.pi) * 32_768, 9
                ),
                "rounding": "symmetric nearest, halves away from zero",
            },
            "required_group_object": {
                "group": group["group"],
                "paths": preload,
                "origin_absolute_m": group_origin,
                "translation_counts": group_counts,
                "uniform_object_scale_q8_8": group_transform[
                    "uniform_object_scale_q8_8"
                ],  # type: ignore[index]
                "object_euler_rotation_words": [0, 0, 0],
                "object_rotation_reason": (
                    "mesh local axes were generated directly as grid north, up, "
                    "and west; no placement yaw is required"
                ),
            },
        },
        "activation_group": group["group"],
        "required_before_first_render": preload,
        "publication_barrier": "both ordered components resident before activating the KOAK start scene",
    }


def build_airport_p3dm_corpus(
    airports: Sequence[Airport], output: Path
) -> dict[str, object]:
    """Write airport components and return the canonical AIRPORTS index."""

    output.mkdir(parents=True, exist_ok=True)
    palette_relative = Path("APT") / "SOLID64.RG2"
    palette_path = output / palette_relative
    palette_path.parent.mkdir(parents=True, exist_ok=True)
    palette_path.write_bytes(SOLID_PALETTE)

    airport_records = []
    all_components = []
    for airport in airports:
        group_records = []
        all_source_vertices: list[list[float]] = []
        for group_index, (runways, pavement, markings, frame) in enumerate(
            _partition_runways(airport)
        ):
            if not 0 <= frame.tile_x < REGIONAL_COLUMNS or not 0 <= frame.tile_y < REGIONAL_ROWS:
                raise ValueError(f"{airport.icao_id} component center is outside regional grid")
            all_source_vertices.extend(_vertices(pavement))
            all_source_vertices.extend(_vertices(markings))
            pavement_tile, pavement_witness = _mesh_tile(
                pavement,
                frame,
                LayerKind.AIRPORT_PAVEMENT,
                material_id=0,
                selector=PAVEMENT_SELECTOR,
            )
            marking_tile, marking_witness = _mesh_tile(
                markings,
                frame,
                LayerKind.AIRPORT_MARKING,
                material_id=1,
                selector=WHITE_SELECTOR,
            )
            root = Path("APT") / airport.icao_id
            components = [
                _component_record(
                    output,
                    root / f"P{group_index:02d}.AGN",
                    pavement_tile,
                    pavement_witness,
                    frame,
                ),
                _component_record(
                    output,
                    root / f"M{group_index:02d}.AGN",
                    marking_tile,
                    marking_witness,
                    frame,
                ),
            ]
            group_vertices = _vertices(pavement) + _vertices(markings)
            group_radius = max(
                math.hypot(
                    -vertex[2] - frame.center_east_abs_m,
                    vertex[0] - frame.center_north_abs_m,
                )
                for vertex in group_vertices
            )
            record = {
                "group": group_index,
                "runways": [runway.identifier for runway in runways],
                "anchor_tile": {
                    "tile_x": frame.tile_x,
                    "tile_y": frame.tile_y,
                    "tile_id": frame.tile_y * REGIONAL_COLUMNS + frame.tile_x,
                },
                "activation_circle": {
                    "center_east_m": frame.center_east_m,
                    "center_north_m": frame.center_north_m,
                    "geometry_radius_m": math.ceil(group_radius),
                    "load_radius_m": math.ceil(group_radius) + ACTIVATION_MARGIN_M,
                    "retain_radius_m": math.ceil(group_radius)
                    + ACTIVATION_MARGIN_M
                    + RETENTION_HYSTERESIS_M,
                },
                "components": components,
            }
            group_records.append(record)
            all_components.extend(components)

        reference_east, reference_north = project_wgs84_utm10(
            airport.reference_point.latitude_deg,
            airport.reference_point.longitude_deg,
        )
        geometry_center_east = (
            min(-vertex[2] for vertex in all_source_vertices)
            + max(-vertex[2] for vertex in all_source_vertices)
        ) / 2.0
        geometry_center_north = (
            min(vertex[0] for vertex in all_source_vertices)
            + max(vertex[0] for vertex in all_source_vertices)
        ) / 2.0
        geometry_radius = max(
            math.hypot(
                -vertex[2] - geometry_center_east,
                vertex[0] - geometry_center_north,
            )
            for vertex in all_source_vertices
        )
        airport_records.append(
            {
                "icao_id": airport.icao_id,
                "faa_id": airport.faa_id,
                "name": airport.name,
                "reference_point_absolute_utm_m": [
                    round(reference_east, 6),
                    round(reference_north, 6),
                    round(airport.reference_point.elevation_m_msl, 6),
                ],
                "reference_point_relative_to_region_m": [
                    round(reference_east - REGIONAL_ORIGIN_EAST_M, 6),
                    round(reference_north - REGIONAL_ORIGIN_NORTH_M, 6),
                    round(airport.reference_point.elevation_m_msl, 6),
                ],
                "activation_circle": {
                    "center_east_m": round(geometry_center_east - REGIONAL_ORIGIN_EAST_M, 3),
                    "center_north_m": round(geometry_center_north - REGIONAL_ORIGIN_NORTH_M, 3),
                    "geometry_radius_m": math.ceil(geometry_radius),
                    "load_radius_m": math.ceil(geometry_radius) + ACTIVATION_MARGIN_M,
                    "retain_radius_m": math.ceil(geometry_radius)
                    + ACTIVATION_MARGIN_M
                    + RETENTION_HYSTERESIS_M,
                },
                "groups": group_records,
                "faa_source_metadata": airport_record(airport),
            }
        )

    koak = next(airport for airport in airports if airport.icao_id == "KOAK")
    koak_record = next(record for record in airport_records if record["icao_id"] == "KOAK")
    index: dict[str, object] = {
        "schema": "pingo-terrain-regional-airport-index",
        "version": 1,
        "agnb_version": "0.3",
        "p3dm_layout_version": 1,
        "source": {
            "provider": "Federal Aviation Administration",
            "product": "28 Day NASR Subscription, APT CSV",
            "effective_date": NASR_EFFECTIVE_DATE,
            "archive_sha256": NASR_ARCHIVE_SHA256,
        },
        "regional_frame": {
            "horizontal_crs": REGIONAL_CRS,
            "origin_easting_m": REGIONAL_ORIGIN_EAST_M,
            "origin_northing_m": REGIONAL_ORIGIN_NORTH_M,
            "east_limit_m": REGIONAL_EAST_LIMIT_M,
            "north_limit_m": REGIONAL_NORTH_LIMIT_M,
            "tile_size_m": REGIONAL_TILE_SIZE_M,
            "columns": REGIONAL_COLUMNS,
            "rows": REGIONAL_ROWS,
            "vertical_origin_m": REGIONAL_VERTICAL_ORIGIN_M,
            "pingo_axes": {"x": "grid north", "y": "up", "z": "negative grid east"},
            "metres_per_pingo_unit": METRES_PER_PINGO_UNIT,
        },
        "datum_contract": {
            "faa_horizontal_source": "NAD83 latitude/longitude from NASR APT",
            "model_horizontal_target": "WGS 84 / UTM zone 10N (EPSG:32610)",
            "horizontal_transform": (
                "ballpark numeric-coordinate NAD83-to-WGS84 approximation, then "
                "deterministic UTM zone 10 projection; no realization/grid shift"
            ),
            "horizontal_accuracy_status": (
                "unknown; adequate for this prototype but not an authoritative survey transform"
            ),
            "terrain_vertical_source": "USGS 3DEP NAVD88 metres",
            "airport_vertical_source": (
                "FAA feet MSL converted exactly by 0.3048 m/ft; NASR does not identify "
                "a more specific vertical datum in the consumed fields"
            ),
            "vertical_alignment_status": (
                "unresolved: airport FAA MSL is not relabelled or asserted equal to NAVD88"
            ),
        },
        "normalization_contract": {
            "formula": (
                "i16 = symmetric_round((axis_m - component_origin_axis_m) * 32767 "
                "/ model_half_extent_m)"
            ),
            "vertical_component_origin_m": REGIONAL_VERTICAL_ORIGIN_M,
            "uniform_scale": True,
            "maximum_model_half_extent_m": MAX_MODEL_HALF_EXTENT_M,
            "maximum_object_scale_q8_8": MAX_OBJECT_SCALE_WIRE,
        },
        "solid_palette": {
            "path": palette_relative.as_posix(),
            "dimensions": [8, 8],
            "layout": "row-major raw six-bit RGB index; byte = 0xC0 | index",
            "bytes": len(SOLID_PALETTE),
            "sha256": sha256(SOLID_PALETTE).hexdigest(),
            "selectors": {
                "runway_pavement_gray": {
                    "index": PAVEMENT_SELECTOR,
                    "rgba2222": PAVEMENT_RGBA2222,
                },
                "runway_marking_white": {
                    "index": WHITE_SELECTOR,
                    "rgba2222": MARKING_RGBA2222,
                },
                "taxiway_yellow_reserved": {
                    "index": YELLOW_SELECTOR,
                    "rgba2222": TAXIWAY_RGBA2222,
                },
            },
        },
        "render_policy": {
            "shading_mode": int(ShadingMode.SOLID_FLAT),
            "illumination": int(IlluminationPolicy.SELF),
            "material_set": int(MaterialSet.NATIVE_SOLID_PALETTE),
            "dither": False,
        },
        "airports": airport_records,
        "canonical_start": _canonical_start(koak, koak_record["groups"]),  # type: ignore[arg-type,index]
        "statistics": {
            "airports": len(airport_records),
            "groups": sum(len(record["groups"]) for record in airport_records),  # type: ignore[arg-type]
            "components": len(all_components),
            "vertices": sum(record["vertices"] for record in all_components),  # type: ignore[arg-type]
            "triangles": sum(record["triangles"] for record in all_components),  # type: ignore[arg-type]
            "container_bytes": sum(record["bytes"] for record in all_components),  # type: ignore[arg-type]
        },
    }
    (output / "AIRPORTS.json").write_bytes(canonical_json_bytes(index))
    return index
