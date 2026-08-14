"""Deterministic FAA NASR airport selection and Pingo runway geometry.

The module deliberately does not download data.  It consumes one checksum-
qualified FAA APT CSV archive, retains surveyed runway values, and emits an
intermediate whose meshes can later be translated to P3DM or assembly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
import io
import json
import math
from pathlib import Path
from typing import Callable, Iterable
from zipfile import ZipFile


NASR_EFFECTIVE_DATE = "2026-07-09"
NASR_CSV_EFFECTIVE_DATE = "2026/07/09"
NASR_ARCHIVE_NAME = "09_Jul_2026_APT_CSV.zip"
NASR_ARCHIVE_SIZE = 8_031_616
NASR_ARCHIVE_SHA256 = (
    "8f2ee852d26a87e5298957b9ee3d7737835be701b9b518f2a38c89a65305f898"
)
TARGET_ICAO_IDS = ("KSFO", "KOAK", "KHWD", "KSQL", "KCCR")

FEET_TO_METRES = 0.3048

# Airport meshes are intentionally conspicuous and independent of the sun.
PAVEMENT_RGBA2222 = 0xD5  # opaque native mid-gray: (85, 85, 85)
MARKING_RGBA2222 = 0xFF  # opaque native white: (255, 255, 255)
TAXIWAY_RGBA2222 = 0xCF  # opaque native yellow, reserved for later geometry
PAVEMENT_OFFSET_M = 0.15
MARKING_OFFSET_M = 0.18
EDGE_LINE_WIDTH_M = 1.25
CENTERLINE_WIDTH_M = 1.50
CENTERLINE_DASH_M = 30.0
CENTERLINE_PERIOD_M = 60.0
THRESHOLD_STRIPE_LENGTH_M = 30.0
THRESHOLD_STRIPE_WIDTH_M = 1.50
THRESHOLD_STRIPE_GAP_M = 1.50
THRESHOLD_INSET_M = 6.0
START_CLEARANCE_M = 1.50

# NAD83 uses the GRS80 ellipsoid.  FAA elevations in this product are feet MSL,
# not ellipsoid heights, so ECEF is used only for the horizontal tangent-plane
# projection and source elevations supply local up independently.
GRS80_SEMIMAJOR_M = 6_378_137.0
GRS80_INVERSE_FLATTENING = 298.257222101


@dataclass(frozen=True)
class GeoPoint:
    latitude_deg: float
    longitude_deg: float
    elevation_ft_msl: float

    @property
    def elevation_m_msl(self) -> float:
        return self.elevation_ft_msl * FEET_TO_METRES


@dataclass(frozen=True)
class RunwayEnd:
    identifier: str
    true_alignment_deg: int
    physical_end: GeoPoint
    displaced_threshold: GeoPoint | None
    displaced_threshold_length_ft: int | None
    position_source: str
    position_source_date: str
    elevation_source: str
    elevation_source_date: str

    @property
    def threshold(self) -> GeoPoint:
        return self.displaced_threshold or self.physical_end


@dataclass(frozen=True)
class Runway:
    identifier: str
    length_ft: int
    width_ft: int
    surface_type: str
    condition: str
    length_source: str
    length_source_date: str
    ends: tuple[RunwayEnd, RunwayEnd]


@dataclass(frozen=True)
class Airport:
    icao_id: str
    faa_id: str
    site_number: str
    name: str
    reference_point: GeoPoint
    position_source: str
    position_source_date: str
    elevation_source: str
    elevation_source_date: str
    runways: tuple[Runway, ...]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_nasr_archive(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"FAA NASR archive is missing: {path}")
    size = path.stat().st_size
    if size != NASR_ARCHIVE_SIZE:
        raise ValueError(
            f"FAA NASR archive size mismatch: expected {NASR_ARCHIVE_SIZE}, got {size}"
        )
    actual = file_sha256(path)
    if actual != NASR_ARCHIVE_SHA256:
        raise ValueError(
            f"FAA NASR archive checksum mismatch: expected {NASR_ARCHIVE_SHA256}, "
            f"got {actual}"
        )


def _csv_rows(archive: ZipFile, member: str) -> list[dict[str, str]]:
    with archive.open(member) as raw:
        stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(stream))


def _required(row: dict[str, str], field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"required FAA field {field} is empty")
    return value


def _point(row: dict[str, str], *, displaced: bool = False) -> GeoPoint | None:
    if displaced:
        lat_field = "LAT_DISPLACED_THR_DECIMAL"
        lon_field = "LONG_DISPLACED_THR_DECIMAL"
        elev_field = "DISPLACED_THR_ELEV"
        values = tuple(row.get(field, "").strip() for field in (lat_field, lon_field))
        if values == ("", ""):
            if row.get(elev_field, "").strip():
                raise ValueError("displaced-threshold elevation exists without position")
            return None
        if any(not value for value in values):
            raise ValueError("partial displaced-threshold position")
    else:
        lat_field = "LAT_DECIMAL"
        lon_field = "LONG_DECIMAL"
        elev_field = "RWY_END_ELEV"
    return GeoPoint(
        latitude_deg=float(_required(row, lat_field)),
        longitude_deg=float(_required(row, lon_field)),
        elevation_ft_msl=float(_required(row, elev_field)),
    )


def _ordered_ends(runway_id: str, rows: Iterable[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    expected = runway_id.split("/")
    if len(expected) != 2:
        raise ValueError(f"unsupported FAA runway identifier: {runway_id}")
    by_id = {_required(row, "RWY_END_ID"): row for row in rows}
    if set(by_id) != set(expected):
        raise ValueError(
            f"runway {runway_id} has ends {sorted(by_id)}, expected {expected}"
        )
    return by_id[expected[0]], by_id[expected[1]]


def load_airports(path: Path, icao_ids: tuple[str, ...] = TARGET_ICAO_IDS) -> tuple[Airport, ...]:
    """Load exactly the selected airports from the pinned FAA archive."""

    verify_nasr_archive(path)
    with ZipFile(path) as archive:
        base_rows = _csv_rows(archive, "APT_BASE.csv")
        runway_rows = _csv_rows(archive, "APT_RWY.csv")
        end_rows = _csv_rows(archive, "APT_RWY_END.csv")

    base_by_icao = {
        row.get("ICAO_ID", "").strip(): row
        for row in base_rows
        if row.get("ICAO_ID", "").strip() in icao_ids
    }
    if set(base_by_icao) != set(icao_ids):
        missing = sorted(set(icao_ids) - set(base_by_icao))
        raise ValueError(f"FAA archive lacks requested airports: {missing}")

    airports: list[Airport] = []
    for icao_id in icao_ids:
        base = base_by_icao[icao_id]
        if _required(base, "EFF_DATE") != NASR_CSV_EFFECTIVE_DATE:
            raise ValueError(f"unexpected FAA effective date for {icao_id}")
        site_number = _required(base, "SITE_NO")
        faa_id = _required(base, "ARPT_ID")
        selected_runways = [
            row
            for row in runway_rows
            if row.get("SITE_NO", "").strip() == site_number
            and row.get("ARPT_ID", "").strip() == faa_id
        ]
        selected_ends = [
            row
            for row in end_rows
            if row.get("SITE_NO", "").strip() == site_number
            and row.get("ARPT_ID", "").strip() == faa_id
        ]
        if not selected_runways:
            raise ValueError(f"FAA archive has no runways for {icao_id}")

        runways: list[Runway] = []
        for row in sorted(selected_runways, key=lambda value: value["RWY_ID"]):
            runway_id = _required(row, "RWY_ID")
            related_ends = [value for value in selected_ends if value["RWY_ID"] == runway_id]
            ordered = _ordered_ends(runway_id, related_ends)
            parsed_ends: list[RunwayEnd] = []
            for end in ordered:
                displaced = _point(end, displaced=True)
                displaced_length = end.get("DISPLACED_THR_LEN", "").strip()
                if bool(displaced) != bool(displaced_length):
                    raise ValueError(
                        f"runway {runway_id} end {end['RWY_END_ID']} has inconsistent "
                        "displaced-threshold fields"
                    )
                parsed_ends.append(
                    RunwayEnd(
                        identifier=_required(end, "RWY_END_ID"),
                        true_alignment_deg=int(_required(end, "TRUE_ALIGNMENT")),
                        physical_end=_point(end),  # type: ignore[arg-type]
                        displaced_threshold=displaced,
                        displaced_threshold_length_ft=(
                            int(displaced_length) if displaced_length else None
                        ),
                        position_source=_required(end, "RWY_END_PSN_SOURCE"),
                        position_source_date=_required(end, "RWY_END_PSN_DATE"),
                        elevation_source=_required(end, "RWY_END_ELEV_SOURCE"),
                        elevation_source_date=_required(end, "RWY_END_ELEV_DATE"),
                    )
                )
            runways.append(
                Runway(
                    identifier=runway_id,
                    length_ft=int(_required(row, "RWY_LEN")),
                    width_ft=int(_required(row, "RWY_WIDTH")),
                    surface_type=_required(row, "SURFACE_TYPE_CODE"),
                    condition=_required(row, "COND"),
                    length_source=_required(row, "RWY_LEN_SOURCE"),
                    length_source_date=_required(row, "LENGTH_SOURCE_DATE"),
                    ends=(parsed_ends[0], parsed_ends[1]),
                )
            )
        airports.append(
            Airport(
                icao_id=icao_id,
                faa_id=faa_id,
                site_number=site_number,
                name=_required(base, "ARPT_NAME"),
                reference_point=GeoPoint(
                    latitude_deg=float(_required(base, "LAT_DECIMAL")),
                    longitude_deg=float(_required(base, "LONG_DECIMAL")),
                    elevation_ft_msl=float(_required(base, "ELEV")),
                ),
                position_source=_required(base, "ARPT_PSN_SOURCE"),
                position_source_date=_required(base, "POSITION_SRC_DATE"),
                elevation_source=_required(base, "ARPT_ELEV_SOURCE"),
                elevation_source_date=_required(base, "ELEVATION_SRC_DATE"),
                runways=tuple(runways),
            )
        )
    return tuple(airports)


def _nad83_surface_ecef(latitude_deg: float, longitude_deg: float) -> tuple[float, float, float]:
    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_deg)
    flattening = 1.0 / GRS80_INVERSE_FLATTENING
    eccentricity_squared = flattening * (2.0 - flattening)
    sin_latitude = math.sin(latitude)
    prime_vertical = GRS80_SEMIMAJOR_M / math.sqrt(
        1.0 - eccentricity_squared * sin_latitude * sin_latitude
    )
    return (
        prime_vertical * math.cos(latitude) * math.cos(longitude),
        prime_vertical * math.cos(latitude) * math.sin(longitude),
        prime_vertical * (1.0 - eccentricity_squared) * sin_latitude,
    )


def local_enu_m(origin: GeoPoint, point: GeoPoint) -> tuple[float, float, float]:
    """Return east, north, up metres in a NAD83 local tangent frame."""

    origin_ecef = _nad83_surface_ecef(origin.latitude_deg, origin.longitude_deg)
    point_ecef = _nad83_surface_ecef(point.latitude_deg, point.longitude_deg)
    dx, dy, dz = (
        point_ecef[index] - origin_ecef[index] for index in range(3)
    )
    latitude = math.radians(origin.latitude_deg)
    longitude = math.radians(origin.longitude_deg)
    east = -math.sin(longitude) * dx + math.cos(longitude) * dy
    north = (
        -math.sin(latitude) * math.cos(longitude) * dx
        - math.sin(latitude) * math.sin(longitude) * dy
        + math.cos(latitude) * dz
    )
    up = point.elevation_m_msl - origin.elevation_m_msl
    return east, north, up


def local_pingo_m(origin: GeoPoint, point: GeoPoint) -> tuple[float, float, float]:
    east, north, up = local_enu_m(origin, point)
    return north, up, -east


def _round_vector(vector: tuple[float, float, float]) -> list[float]:
    return [round(value, 6) for value in vector]


class _MeshBuilder:
    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        self.vertices: list[list[float]] = []
        self.triangles: list[list[int]] = []
        self._indices: dict[tuple[float, float, float], int] = {}
        self.role_counts: dict[str, int] = {}

    def _vertex(self, point: tuple[float, float, float]) -> int:
        key = tuple(round(value, 6) for value in point)
        if key not in self._indices:
            self._indices[key] = len(self.vertices)
            self.vertices.append(list(key))
        return self._indices[key]

    @staticmethod
    def _up_component(
        first: tuple[float, float, float],
        second: tuple[float, float, float],
        third: tuple[float, float, float],
    ) -> float:
        ab_x, ab_z = second[0] - first[0], second[2] - first[2]
        ac_x, ac_z = third[0] - first[0], third[2] - first[2]
        return ab_z * ac_x - ab_x * ac_z

    def add_quad(
        self,
        corners: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        material_id: int,
        role: str,
    ) -> None:
        first, second, third, fourth = corners
        if self._up_component(first, second, third) < 0.0:
            second, fourth = fourth, second
        indices = [self._vertex(point) for point in (first, second, third, fourth)]
        self.triangles.extend(
            (
                [indices[0], indices[1], indices[2], material_id],
                [indices[0], indices[2], indices[3], material_id],
            )
        )
        self.role_counts[role] = self.role_counts.get(role, 0) + 2

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "render": {
                "pingo_shading_mode": 1,
                "illumination": "self",
                "dither": False,
                "merge_with_terrain": False,
            },
            "vertices_pingo_m": self.vertices,
            "triangles": self.triangles,
            "triangle_format": ["vertex_0", "vertex_1", "vertex_2", "material_id"],
            "triangle_roles": dict(sorted(self.role_counts.items())),
        }


def _horizontal_unit(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    dx, dz = second[0] - first[0], second[2] - first[2]
    length = math.hypot(dx, dz)
    if length <= 0.0:
        raise ValueError("zero-length runway centerline")
    return dx / length, length, dz / length


def _centerline_point(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    distance_m: float,
    vertical_offset_m: float,
) -> tuple[float, float, float]:
    unit_x, length, unit_z = _horizontal_unit(first, second)
    fraction = max(0.0, min(1.0, distance_m / length))
    return (
        first[0] + unit_x * distance_m,
        first[1] + (second[1] - first[1]) * fraction + vertical_offset_m,
        first[2] + unit_z * distance_m,
    )


def _strip(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    start_m: float,
    end_m: float,
    width_m: float,
    lateral_m: float,
    vertical_offset_m: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    unit_x, _length, unit_z = _horizontal_unit(first, second)
    lateral_x, lateral_z = -unit_z, unit_x
    start = _centerline_point(first, second, start_m, vertical_offset_m)
    end = _centerline_point(first, second, end_m, vertical_offset_m)
    half_width = width_m / 2.0

    def shifted(
        point: tuple[float, float, float], offset: float
    ) -> tuple[float, float, float]:
        total = lateral_m + offset
        return (
            point[0] + lateral_x * total,
            point[1],
            point[2] + lateral_z * total,
        )

    return (
        shifted(start, -half_width),
        shifted(end, -half_width),
        shifted(end, half_width),
        shifted(start, half_width),
    )


def _distance_along(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    point: tuple[float, float, float],
) -> float:
    unit_x, _length, unit_z = _horizontal_unit(first, second)
    return (point[0] - first[0]) * unit_x + (point[2] - first[2]) * unit_z


def _threshold_stripe_count(width_m: float) -> int:
    if width_m >= 55.0:
        return 12
    if width_m >= 40.0:
        return 8
    return 4


def _point_dict(point: GeoPoint) -> dict[str, float]:
    return {
        "latitude_deg": point.latitude_deg,
        "longitude_deg": point.longitude_deg,
        "elevation_ft_msl": point.elevation_ft_msl,
        "elevation_m_msl": round(point.elevation_m_msl, 6),
    }


def runway_dict(runway: Runway) -> dict[str, object]:
    ends = []
    for end in runway.ends:
        ends.append(
            {
                "id": end.identifier,
                "true_alignment_deg_faa_nearest_degree": end.true_alignment_deg,
                "physical_end": _point_dict(end.physical_end),
                "displaced_threshold": (
                    _point_dict(end.displaced_threshold)
                    if end.displaced_threshold is not None
                    else None
                ),
                "displaced_threshold_length_ft": end.displaced_threshold_length_ft,
                "position_source": end.position_source,
                "position_source_date": end.position_source_date,
                "elevation_source": end.elevation_source,
                "elevation_source_date": end.elevation_source_date,
            }
        )
    return {
        "id": runway.identifier,
        "physical_length_ft": runway.length_ft,
        "physical_length_m": round(runway.length_ft * FEET_TO_METRES, 4),
        "physical_width_ft": runway.width_ft,
        "physical_width_m": round(runway.width_ft * FEET_TO_METRES, 4),
        "surface_type": runway.surface_type,
        "condition": runway.condition,
        "length_source": runway.length_source,
        "length_source_date": runway.length_source_date,
        "ends": ends,
    }


def airport_record(airport: Airport) -> dict[str, object]:
    return {
        "icao_id": airport.icao_id,
        "faa_id": airport.faa_id,
        "site_number": airport.site_number,
        "name": airport.name,
        "reference_point": _point_dict(airport.reference_point),
        "reference_position_source": airport.position_source,
        "reference_position_source_date": airport.position_source_date,
        "reference_elevation_source": airport.elevation_source,
        "reference_elevation_source_date": airport.elevation_source_date,
        "runways": [runway_dict(runway) for runway in airport.runways],
    }


def airport_manifest_record(airport: Airport) -> dict[str, object]:
    """Return the compact, exact FAA measurements pinned by the manifest."""

    runways: list[dict[str, object]] = []
    for runway in airport.runways:
        ends: list[dict[str, object]] = []
        for end in runway.ends:
            ends.append(
                {
                    "id": end.identifier,
                    "true_alignment_deg": end.true_alignment_deg,
                    "physical_end_lat_lon_elev_ft_msl": [
                        end.physical_end.latitude_deg,
                        end.physical_end.longitude_deg,
                        end.physical_end.elevation_ft_msl,
                    ],
                    "displaced_threshold_lat_lon_elev_ft_msl": (
                        [
                            end.displaced_threshold.latitude_deg,
                            end.displaced_threshold.longitude_deg,
                            end.displaced_threshold.elevation_ft_msl,
                        ]
                        if end.displaced_threshold is not None
                        else None
                    ),
                    "displaced_threshold_length_ft": end.displaced_threshold_length_ft,
                }
            )
        runways.append(
            {
                "id": runway.identifier,
                "length_ft": runway.length_ft,
                "width_ft": runway.width_ft,
                "surface_type": runway.surface_type,
                "ends": ends,
            }
        )
    return {
        "icao_id": airport.icao_id,
        "faa_id": airport.faa_id,
        "site_number": airport.site_number,
        "name": airport.name,
        "reference_lat_lon_elev_ft_msl": [
            airport.reference_point.latitude_deg,
            airport.reference_point.longitude_deg,
            airport.reference_point.elevation_ft_msl,
        ],
        "runways": runways,
    }


def _canonical_start(airport: Airport) -> dict[str, object]:
    if airport.icao_id != "KOAK":
        raise ValueError("canonical start is defined only for KOAK")
    runway = next(
        (value for value in airport.runways if value.identifier == "10R/28L"), None
    )
    if runway is None:
        raise ValueError("KOAK runway 10R/28L is missing")
    by_id = {end.identifier: end for end in runway.ends}
    start_end = by_id["28L"]
    opposite_end = by_id["10R"]
    start = local_pingo_m(airport.reference_point, start_end.threshold)
    opposite = local_pingo_m(airport.reference_point, opposite_end.threshold)
    dx, dz = opposite[0] - start[0], opposite[2] - start[2]
    horizontal = math.hypot(dx, dz)
    forward_pingo = (dx / horizontal, 0.0, dz / horizontal)
    # Compute the reported true bearing in the threshold's own tangent plane;
    # the Pingo forward vector remains in the airport-reference tangent frame
    # so that it is exactly parallel to the generated runway mesh.
    east, north, _up = local_enu_m(start_end.threshold, opposite_end.threshold)
    heading_true_deg = math.degrees(math.atan2(east, north)) % 360
    aircraft_position = (start[0], start[1] + START_CLEARANCE_M, start[2])
    return {
        "airport_icao": "KOAK",
        "runway_id": "10R/28L",
        "runway_end_id": "28L",
        "threshold_source": (
            "FAA displaced threshold" if start_end.displaced_threshold else "FAA physical runway end"
        ),
        "threshold": _point_dict(start_end.threshold),
        "opposite_threshold": _point_dict(opposite_end.threshold),
        "faa_true_alignment_deg_nearest_degree": start_end.true_alignment_deg,
        "heading_true_deg_from_threshold_centerline": round(heading_true_deg, 6),
        "surface_position_pingo_m": _round_vector(start),
        "aircraft_position_pingo_m": _round_vector(aircraft_position),
        "initial_clearance_m": START_CLEARANCE_M,
        "forward_pingo_unit": _round_vector(forward_pingo),
    }


def build_airport_meshes(
    airport: Airport,
    project_point: Callable[[GeoPoint], tuple[float, float, float]],
) -> tuple[_MeshBuilder, _MeshBuilder, dict[str, float]]:
    """Build airport meshes in a caller-selected metre coordinate frame.

    ``project_point`` returns Pingo-axis metres (north, elevation, west).  The
    default airport intermediate uses a local NAD83 tangent plane; the
    regional P3DM compiler supplies EPSG:32610 coordinates instead.  Keeping
    the marking construction here guarantees that both products use exactly
    the same FAA-derived runway and visibility-cue policy.
    """

    pavement = _MeshBuilder("runway_pavement")
    markings = _MeshBuilder("runway_markings")
    endpoint_span_deltas: dict[str, float] = {}

    for runway in airport.runways:
        first = project_point(runway.ends[0].physical_end)
        second = project_point(runway.ends[1].physical_end)
        _unit_x, span_m, _unit_z = _horizontal_unit(first, second)
        width_m = runway.width_ft * FEET_TO_METRES
        endpoint_span_deltas[runway.identifier] = round(
            span_m - runway.length_ft * FEET_TO_METRES, 6
        )

        pavement.add_quad(
            _strip(
                first,
                second,
                0.0,
                span_m,
                width_m,
                0.0,
                PAVEMENT_OFFSET_M,
            ),
            material_id=0,
            role="pavement",
        )

        threshold_positions = [
            project_point(end.threshold) for end in runway.ends
        ]
        threshold_distances = [
            max(0.0, min(span_m, _distance_along(first, second, point)))
            for point in threshold_positions
        ]
        usable_start, usable_end = sorted(threshold_distances)

        edge_lateral = width_m / 2.0 - EDGE_LINE_WIDTH_M / 2.0
        for side in (-1.0, 1.0):
            markings.add_quad(
                _strip(
                    first,
                    second,
                    usable_start,
                    usable_end,
                    EDGE_LINE_WIDTH_M,
                    side * edge_lateral,
                    MARKING_OFFSET_M,
                ),
                material_id=1,
                role="edge_line",
            )

        center_start = usable_start + THRESHOLD_INSET_M + THRESHOLD_STRIPE_LENGTH_M + 10.0
        center_end = usable_end - THRESHOLD_INSET_M - THRESHOLD_STRIPE_LENGTH_M - 10.0
        dash_start = center_start
        while dash_start < center_end:
            dash_end = min(dash_start + CENTERLINE_DASH_M, center_end)
            if dash_end > dash_start:
                markings.add_quad(
                    _strip(
                        first,
                        second,
                        dash_start,
                        dash_end,
                        CENTERLINE_WIDTH_M,
                        0.0,
                        MARKING_OFFSET_M,
                    ),
                    material_id=1,
                    role="centerline_dash",
                )
            dash_start += CENTERLINE_PERIOD_M

        stripe_count = _threshold_stripe_count(width_m)
        pairs = stripe_count // 2
        for end_index, threshold_distance in enumerate(threshold_distances):
            direction = 1.0 if end_index == 0 else -1.0
            inner_start = threshold_distance + direction * THRESHOLD_INSET_M
            inner_end = inner_start + direction * THRESHOLD_STRIPE_LENGTH_M
            start_m, end_m = sorted((inner_start, inner_end))
            start_m = max(0.0, start_m)
            end_m = min(span_m, end_m)
            for pair in range(pairs):
                offset = (
                    THRESHOLD_STRIPE_GAP_M / 2.0
                    + THRESHOLD_STRIPE_WIDTH_M / 2.0
                    + pair * (THRESHOLD_STRIPE_WIDTH_M + THRESHOLD_STRIPE_GAP_M)
                )
                for side in (-1.0, 1.0):
                    markings.add_quad(
                        _strip(
                            first,
                            second,
                            start_m,
                            end_m,
                            THRESHOLD_STRIPE_WIDTH_M,
                            side * offset,
                            MARKING_OFFSET_M,
                        ),
                        material_id=1,
                        role="threshold_stripe",
                    )

    return pavement, markings, endpoint_span_deltas


def build_airport_geometry(airport: Airport) -> dict[str, object]:
    pavement, markings, endpoint_span_deltas = build_airport_meshes(
        airport,
        lambda point: local_pingo_m(airport.reference_point, point),
    )

    result: dict[str, object] = {
        "schema": "pingo-terrain-airport-geometry",
        "version": 1,
        "source": {
            "provider": "Federal Aviation Administration",
            "product": "28 Day NASR Subscription, APT CSV",
            "effective_date": NASR_EFFECTIVE_DATE,
            "archive_sha256": NASR_ARCHIVE_SHA256,
        },
        "airport": airport_record(airport),
        "coordinate_frame": {
            "origin": _point_dict(airport.reference_point),
            "horizontal_datum": "NAD83",
            "horizontal_projection": "local tangent plane on GRS80",
            "vertical_reference": (
                "FAA feet MSL converted exactly by 0.3048 m/ft; product does not "
                "name a more specific vertical datum"
            ),
            "units": "metres",
            "pingo_axes": {"x": "north", "y": "up", "z": "west (-east)"},
        },
        "render_policy": {
            "pingo_shading_mode": 1,
            "illumination": "self",
            "dither": False,
            "merge_with_terrain": False,
            "terrain_pattern_lookup": False,
            "pavement_vertical_offset_m": PAVEMENT_OFFSET_M,
            "marking_vertical_offset_m": MARKING_OFFSET_M,
        },
        "materials": [
            {
                "id": 0,
                "name": "runway_pavement",
                "rgba2222": PAVEMENT_RGBA2222,
                "rgba8888": [85, 85, 85, 255],
            },
            {
                "id": 1,
                "name": "runway_white",
                "rgba2222": MARKING_RGBA2222,
                "rgba8888": [255, 255, 255, 255],
            },
            {
                "id": 2,
                "name": "taxiway_yellow_reserved",
                "rgba2222": TAXIWAY_RGBA2222,
                "rgba8888": [255, 255, 0, 255],
            },
        ],
        "marking_model": {
            "purpose": "visibility-optimized cues for a 320-pixel-class viewport",
            "regulatory_fidelity": False,
            "edge_line_width_m": EDGE_LINE_WIDTH_M,
            "centerline_width_m": CENTERLINE_WIDTH_M,
            "centerline_dash_m": CENTERLINE_DASH_M,
            "centerline_period_m": CENTERLINE_PERIOD_M,
            "threshold_stripe_length_m": THRESHOLD_STRIPE_LENGTH_M,
            "threshold_stripe_width_m": THRESHOLD_STRIPE_WIDTH_M,
        },
        "meshes": [pavement.as_dict(), markings.as_dict()],
        "endpoint_span_minus_published_length_m": endpoint_span_deltas,
    }
    if airport.icao_id == "KOAK":
        result["canonical_start"] = _canonical_start(airport)

    meshes = result["meshes"]
    assert isinstance(meshes, list)
    result["statistics"] = {
        "meshes": len(meshes),
        "vertices": sum(len(mesh["vertices_pingo_m"]) for mesh in meshes),
        "triangles": sum(len(mesh["triangles"]) for mesh in meshes),
        "runways": len(airport.runways),
    }
    return result


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
