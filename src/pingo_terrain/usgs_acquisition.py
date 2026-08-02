"""Pinned USGS acquisition plan for the regional Bay Area source corpus."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .geotiff import GeoTiffExpectation, validate_geotiff


REGION_ID = "bay-area"
RETRIEVAL_DATE = "2026-08-02"
TILE_EDGE = 2048
USER_AGENT = "pingo-terrain/0.0.0 (+local USGS source acquisition)"

THREE_DEP_SERVICE = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer"
)
THREE_DEP_EXPORT = THREE_DEP_SERVICE + "/exportImage"
THREE_DEP_SOURCE_QUERY = THREE_DEP_SERVICE + "/query"
NLCD_WCS = (
    "https://dmsdata.cr.usgs.gov/geoserver/"
    "mrlc_Land-Cover-Native_conus_year_data/wcs"
)
NLCD_COVERAGE = (
    "mrlc_Land-Cover-Native_conus_year_data:"
    "Land-Cover-Native_conus_year_data"
)
NLCD_TIME = "2025-01-01T00:00:00.000Z"


@dataclass(frozen=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    @property
    def tuple(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north

    def contains(self, longitude: float, latitude: float) -> bool:
        return self.west <= longitude <= self.east and self.south <= latitude <= self.north


@dataclass(frozen=True)
class RasterGrid:
    dataset_id: str
    epsg: int
    bounds: Bounds
    pixel_size: float
    bits_per_sample: int
    sample_format: int
    nodata: float | int
    filename_prefix: str

    @property
    def width(self) -> int:
        cells = (self.bounds.east - self.bounds.west) / self.pixel_size
        if not math.isclose(cells, round(cells), abs_tol=1e-8):
            raise ValueError(f"Grid width is not integral: {cells}")
        return round(cells)

    @property
    def height(self) -> int:
        cells = (self.bounds.north - self.bounds.south) / self.pixel_size
        if not math.isclose(cells, round(cells), abs_tol=1e-8):
            raise ValueError(f"Grid height is not integral: {cells}")
        return round(cells)


@dataclass(frozen=True)
class RasterTile:
    grid: RasterGrid
    row: int
    column: int
    width: int
    height: int
    bounds: Bounds
    relative_path: Path
    request_url: str

    @property
    def id(self) -> str:
        return f"r{self.row:02d}-c{self.column:02d}"

    @property
    def expectation(self) -> GeoTiffExpectation:
        return GeoTiffExpectation(
            width=self.width,
            height=self.height,
            epsg=self.grid.epsg,
            bbox=self.bounds.tuple,
            bits_per_sample=self.grid.bits_per_sample,
            sample_format=self.grid.sample_format,
            nodata=self.grid.nodata,
            pixel_size=self.grid.pixel_size,
        )


# The WGS84 rectangle is intentionally broader than a direct projected crop.
# It includes Pacific water west of Marin/San Francisco, Suisun Bay northward,
# Morgan Hill southward, and a margin east of Mount Diablo.
REQUESTED_WGS84_BOUNDS = Bounds(-122.75, 37.05, -121.60, 38.20)

# Reference points prove coverage only; they are not surveyed source geometry.
COVERAGE_REFERENCES_WGS84 = {
    "Pacific Ocean sample": (-122.70, 37.75),
    "Mount Tamalpais": (-122.5965, 37.9235),
    "Yerba Buena Island": (-122.3669, 37.8101),
    "Treasure Island": (-122.3701, 37.8235),
    "Suisun Bay": (-122.069, 38.073),
    "Mount Diablo": (-121.9142, 37.8816),
    "Morgan Hill": (-121.6544, 37.1305),
    "KSFO": (-122.3754, 37.6188),
    "KOAK": (-122.2211, 37.7126),
    "KHWD": (-122.1217, 37.6589),
    "KSQL": (-122.2495, 37.5119),
    "KCCR": (-122.0569, 37.9897),
}

# Envelopes of the WGS84 perimeter transformed with PROJ 9.1.1, then expanded
# outward to the native cell lattice.  DEM is a 10 m working grid in UTM 10N.
# NLCD is aligned to its published EPSG:5070 origin (-2415585, 164805).
DEM_GRID = RasterGrid(
    dataset_id="usgs-3dep-10m-utm10n",
    epsg=32610,
    bounds=Bounds(521880.0, 4100440.0, 624490.0, 4228940.0),
    pixel_size=10.0,
    bits_per_sample=32,
    sample_format=3,
    nodata=-9999,
    filename_prefix="dem",
)
NLCD_GRID = RasterGrid(
    dataset_id="usgs-annual-nlcd-2025-epsg5070",
    epsg=5070,
    bounds=Bounds(-2325735.0, 1858305.0, -2193915.0, 2009685.0),
    pixel_size=30.0,
    bits_per_sample=8,
    sample_format=1,
    nodata=250,
    filename_prefix="nlcd",
)


def _number(value: float | int) -> str:
    return str(int(value)) if float(value).is_integer() else format(value, ".12g")


def three_dep_url(bounds: Bounds, width: int, height: int) -> str:
    query = urlencode(
        {
            "bbox": ",".join(_number(value) for value in bounds.tuple),
            "bboxSR": DEM_GRID.epsg,
            "size": f"{width},{height}",
            "imageSR": DEM_GRID.epsg,
            "format": "tiff",
            "pixelType": "F32",
            "interpolation": "RSP_BilinearInterpolation",
            "noData": DEM_GRID.nodata,
            "f": "image",
        }
    )
    return f"{THREE_DEP_EXPORT}?{query}"


def nlcd_url(bounds: Bounds, width: int, height: int) -> str:
    query = urlencode(
        {
            "service": "WCS",
            "version": "1.0.0",
            "request": "GetCoverage",
            "coverage": NLCD_COVERAGE,
            "bbox": ",".join(_number(value) for value in bounds.tuple),
            "crs": f"EPSG:{NLCD_GRID.epsg}",
            "response_crs": f"EPSG:{NLCD_GRID.epsg}",
            "width": width,
            "height": height,
            "format": "GeoTIFF",
            "time": NLCD_TIME,
        }
    )
    return f"{NLCD_WCS}?{query}"


def source_query_url() -> str:
    query = urlencode(
        {
            "where": "1=1",
            "geometry": ",".join(_number(value) for value in DEM_GRID.bounds.tuple),
            "geometryType": "esriGeometryEnvelope",
            "inSR": DEM_GRID.epsg,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": (
                "Name,ProductName,VerticalDatum,Resolution_X,Resolution_Y,"
                "Source,URL,pubdate"
            ),
            "returnGeometry": "false",
            "resultRecordCount": 1000,
            "f": "json",
        }
    )
    return f"{THREE_DEP_SOURCE_QUERY}?{query}"


def _balanced_spans(total: int, maximum: int) -> tuple[int, ...]:
    """Split a grid axis into near-equal spans no larger than ``maximum``."""

    count = math.ceil(total / maximum)
    base, extra = divmod(total, count)
    return tuple(base + (index < extra) for index in range(count))


def plan_tiles(grid: RasterGrid, url_builder: Callable[[Bounds, int, int], str]) -> tuple[RasterTile, ...]:
    tiles: list[RasterTile] = []
    row_heights = _balanced_spans(grid.height, TILE_EDGE)
    column_widths = _balanced_spans(grid.width, TILE_EDGE)
    consumed_rows = 0
    for row, height in enumerate(row_heights):
        north = grid.bounds.north - consumed_rows * grid.pixel_size
        south = north - height * grid.pixel_size
        consumed_columns = 0
        for column, width in enumerate(column_widths):
            west = grid.bounds.west + consumed_columns * grid.pixel_size
            east = west + width * grid.pixel_size
            bounds = Bounds(west, south, east, north)
            name = f"{grid.filename_prefix}-r{row:02d}-c{column:02d}.tif"
            tiles.append(
                RasterTile(
                    grid=grid,
                    row=row,
                    column=column,
                    width=width,
                    height=height,
                    bounds=bounds,
                    relative_path=Path(grid.dataset_id) / name,
                    request_url=url_builder(bounds, width, height),
                )
            )
            consumed_columns += width
        consumed_rows += height
    return tuple(tiles)


def acquisition_plan() -> tuple[RasterTile, ...]:
    return plan_tiles(DEM_GRID, three_dep_url) + plan_tiles(NLCD_GRID, nlcd_url)


def download_tile(
    tile: RasterTile,
    root: str | Path,
    *,
    retries: int = 5,
    timeout: float = 180.0,
    progress: Callable[[str], None] = print,
) -> tuple[Path, int]:
    """Download one tile atomically, returning its path and retry count."""

    root_path = Path(root)
    destination = root_path / tile.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            validate_geotiff(destination, tile.expectation, tolerance=0.02)
            return destination, 0
        except (OSError, ValueError):
            pass
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if partial.exists():
                partial.unlink()
            request = Request(tile.request_url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
                if response.status != 200:
                    raise OSError(f"HTTP status {response.status}")
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            validate_geotiff(partial, tile.expectation, tolerance=0.02)
            partial.replace(destination)
            return destination, attempt
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            if partial.exists():
                partial.unlink()
            if attempt >= retries:
                break
            delay = min(2**attempt, 16)
            progress(
                f"retry {attempt + 1}/{retries} {tile.grid.dataset_id}/{tile.id}: "
                f"{error}; waiting {delay}s"
            )
            time.sleep(delay)
    raise RuntimeError(
        f"failed {tile.grid.dataset_id}/{tile.id} after {retries + 1} attempts"
    ) from last_error


def read_source_query_summary(path: str | Path) -> dict[str, object]:
    """Validate and summarize a saved 3DEP source-footprint query response."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("error"):
        raise ValueError(f"3DEP source query failed: {payload['error']}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("3DEP source query has no feature list")
    attributes = [feature.get("attributes", {}) for feature in features]
    data_records = [item for item in attributes if item.get("ProductName")]
    vertical_datums = sorted(
        {item.get("VerticalDatum") for item in data_records if item.get("VerticalDatum")}
    )
    products = sorted(
        {item.get("ProductName") for item in data_records if item.get("ProductName")}
    )
    return {
        "intersecting_records": len(attributes),
        "data_records": len(data_records),
        "overview_records": len(attributes) - len(data_records),
        "vertical_datums": vertical_datums,
        "products": products,
        "exceeded_transfer_limit": bool(payload.get("exceededTransferLimit", False)),
    }
