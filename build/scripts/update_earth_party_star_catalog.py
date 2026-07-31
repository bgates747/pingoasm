#!/usr/bin/env python3
"""Refresh Earth Party's small, offline Bright Star Catalogue selection.

The ordinary application build never uses the network.  This maintenance tool
downloads (or accepts with --catalog) the CDS V/50 Bright Star Catalogue,
verifies the exact source archive, selects the bright and iconic-pattern stars,
merges unresolved visual components, and writes the tracked TSV consumed by the
starfield mesh generator.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import math
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "apps" / "earth-party-local" / "assets" / "stars.tsv"
)
BSC5_URL = "https://cdsarc.cds.unistra.fr/ftp/V/50/catalog.gz"
BSC5_SHA256 = "3dc44b1e90be8fbe5bcc7656032560f51275f985c7e3f783c9028e1838ec7bed"
BRIGHT_MAGNITUDE_LIMIT = 2.00
MERGE_ANGLE_DEGREES = 0.01

# The IAU defines constellation boundaries, not stick figures.  These are an
# intentionally compact editorial selection of the principal Bayer vertices
# used in familiar Western figures.  The complete bright-star cut is unioned
# with this list, so important bright stars outside these figures remain.
ICONIC_BAYER_VERTICES: dict[str, tuple[str, ...]] = {
    "Ori": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Kap", "Lam"),
    "UMa": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Eta"),
    "UMi": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Eta"),
    "Cas": ("Alp", "Bet", "Gam", "Del", "Eps"),
    "Cyg": ("Alp", "Bet", "Gam", "Del", "Eps"),
    "Sco": (
        "Alp",
        "Bet",
        "Del",
        "Eps",
        "Zet",
        "Eta",
        "The",
        "Iot",
        "Kap",
        "Lam",
    ),
    "Cru": ("Alp", "Bet", "Gam", "Del"),
    "Leo": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "The"),
    "Tau": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Eta", "Lam"),
    "Gem": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Eta", "Mu"),
    "Sgr": ("Gam", "Del", "Eps", "Zet", "Lam", "Phi", "Sig", "Tau"),
    "Peg": ("Alp", "Bet", "Gam"),
    "And": ("Alp", "Bet", "Gam"),
    "Aql": ("Alp", "Bet", "Gam"),
    "Lyr": ("Alp", "Bet", "Gam", "Del", "Zet"),
    "Aur": ("Alp", "Bet", "The", "Iot"),
    "Per": ("Alp", "Bet", "Gam", "Del", "Eps", "Zet"),
    "Boo": ("Alp", "Bet", "Gam", "Del", "Eps", "Eta"),
    "CMa": ("Alp", "Bet", "Del", "Eps", "Eta"),
}

# Stable display labels for the well-known subset.  Names are IAU WGSN
# spellings.  Geometry and selection use the catalogue identifiers, never
# these labels.
PROPER_NAMES_BY_HR: dict[int, str] = {
    15: "Alpheratz",
    21: "Caph",
    39: "Algenib",
    168: "Schedar",
    264: "Cih",
    337: "Mirach",
    403: "Ruchbah",
    424: "Polaris",
    472: "Achernar",
    542: "Segin",
    603: "Almach",
    617: "Hamal",
    936: "Algol",
    1017: "Mirfak",
    1165: "Alcyone",
    1346: "Prima Hyadum",
    1373: "Secunda Hyadum",
    1409: "Ain",
    1457: "Aldebaran",
    1577: "Hassaleh",
    1708: "Capella",
    1713: "Rigel",
    1790: "Bellatrix",
    1791: "Elnath",
    1852: "Mintaka",
    1879: "Meissa",
    1903: "Alnilam",
    1910: "Tianguan",
    1948: "Alnitak",
    2004: "Saiph",
    2061: "Betelgeuse",
    2088: "Menkalinan",
    2095: "Mahasim",
    2216: "Propus",
    2286: "Tejat",
    2294: "Mirzam",
    2326: "Canopus",
    2421: "Alhena",
    2473: "Mebsuta",
    2491: "Sirius",
    2618: "Adhara",
    2650: "Mekbuda",
    2693: "Wezen",
    2777: "Wasat",
    2827: "Aludra",
    2891: "Castor",
    2943: "Procyon",
    2990: "Pollux",
    3307: "Avior",
    3485: "Alsephina",
    3685: "Miaplacidus",
    3748: "Alphard",
    3873: "Ras Elased Australis",
    3982: "Regulus",
    4031: "Adhafera",
    4057: "Algieba",
    4295: "Merak",
    4301: "Dubhe",
    4357: "Zosma",
    4359: "Chertan",
    4534: "Denebola",
    4554: "Phecda",
    4656: "Imai",
    4660: "Megrez",
    4730: "Acrux",
    4763: "Gacrux",
    4853: "Mimosa",
    4905: "Alioth",
    5054: "Mizar",
    5056: "Spica",
    5191: "Alkaid",
    5235: "Muphrid",
    5267: "Hadar",
    5340: "Arcturus",
    5435: "Seginus",
    5459: "Rigil Kentaurus",
    5460: "Toliman",
    5563: "Kochab",
    5602: "Nekkar",
    5735: "Pherkad",
    5953: "Dschubba",
    5984: "Acrab",
    6134: "Antares",
    6217: "Atria",
    6241: "Larawag",
    6527: "Shaula",
    6553: "Sargas",
    6746: "Alnasl",
    6789: "Yildun",
    6859: "Kaus Media",
    6879: "Kaus Australis",
    6913: "Kaus Borealis",
    7001: "Vega",
    7106: "Sheliak",
    7121: "Nunki",
    7178: "Sulafat",
    7194: "Ascella",
    7417: "Albireo",
    7525: "Tarazed",
    7528: "Fawaris",
    7557: "Altair",
    7602: "Alshain",
    7790: "Peacock",
    7796: "Sadr",
    7924: "Deneb",
    7949: "Aljanah",
    8425: "Alnair",
    8728: "Fomalhaut",
    8775: "Scheat",
    8781: "Markab",
}


@dataclass(frozen=True)
class CatalogStar:
    hr: int
    raw_name: str
    flamsteed: str
    bayer: str
    component: str
    constellation: str
    ra_degrees: float
    dec_degrees: float
    vmag: float
    bv: float | None
    spectral_type: str
    magnitude_code: str


@dataclass(frozen=True)
class SelectedStar:
    display_name: str
    hrs: tuple[int, ...]
    bayer: str
    constellation: str
    ra_degrees: float
    dec_degrees: float
    vmag: float
    bv: float
    spectral_type: str
    selections: tuple[str, ...]


def parse_float(value: str) -> float | None:
    value = value.strip()
    return float(value) if value else None


def parse_catalog_line(line: str) -> CatalogStar | None:
    if len(line) < 90:
        raise ValueError(f"short V/50 catalog record: {len(line)} bytes")
    line = line.ljust(197)

    hr_text = line[0:4].strip()
    ra_hour = line[75:77].strip()
    dec_degree = line[84:86].strip()
    vmag = parse_float(line[102:107])
    if not hr_text or not ra_hour or not dec_degree or vmag is None:
        return None

    name = line[4:14]
    ra = (
        int(ra_hour)
        + int(line[77:79]) / 60.0
        + float(line[79:83]) / 3600.0
    ) * 15.0
    declination = (
        int(dec_degree)
        + int(line[86:88]) / 60.0
        + int(line[88:90]) / 3600.0
    )
    if line[83] == "-":
        declination = -declination
    elif line[83] != "+":
        raise ValueError(f"HR {hr_text}: invalid declination sign")

    return CatalogStar(
        hr=int(hr_text),
        raw_name=name.strip(),
        flamsteed=name[0:3].strip(),
        bayer=name[3:6].strip(),
        component=name[6:7].strip(),
        constellation=name[7:10].strip(),
        ra_degrees=ra,
        dec_degrees=declination,
        vmag=vmag,
        bv=parse_float(line[109:114]),
        spectral_type=line[127:147].strip(),
        magnitude_code=line[107:108].strip(),
    )


def read_catalog(archive: Path) -> list[CatalogStar]:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != BSC5_SHA256:
        raise ValueError(
            "unexpected CDS V/50 archive hash: "
            f"{digest}; expected {BSC5_SHA256}"
        )
    with gzip.open(archive, "rt", encoding="ascii") as source:
        stars = [
            star
            for line in source
            if (star := parse_catalog_line(line.rstrip("\n"))) is not None
        ]
    if len(stars) != 9_096:
        raise ValueError(f"expected 9,096 stellar records, found {len(stars)}")
    return stars


def unit_vector(star: CatalogStar) -> tuple[float, float, float]:
    ra = math.radians(star.ra_degrees)
    dec = math.radians(star.dec_degrees)
    cos_dec = math.cos(dec)
    return cos_dec * math.cos(ra), cos_dec * math.sin(ra), math.sin(dec)


def angular_separation(a: CatalogStar, b: CatalogStar) -> float:
    av = unit_vector(a)
    bv = unit_vector(b)
    cosine = max(-1.0, min(1.0, sum(x * y for x, y in zip(av, bv))))
    return math.degrees(math.acos(cosine))


def combine_cluster(
    cluster: list[CatalogStar],
    reasons: dict[int, set[str]],
) -> SelectedStar:
    cluster.sort(key=lambda star: (star.vmag, star.hr))
    primary = cluster[0]
    v_fluxes = [10.0 ** (-0.4 * star.vmag) for star in cluster]
    total_v_flux = sum(v_fluxes)
    vmag = -2.5 * math.log10(total_v_flux)

    weighted = [0.0, 0.0, 0.0]
    for star, flux in zip(cluster, v_fluxes):
        for axis, component in enumerate(unit_vector(star)):
            weighted[axis] += component * flux
    length = math.sqrt(sum(component * component for component in weighted))
    weighted = [component / length for component in weighted]
    ra = math.degrees(math.atan2(weighted[1], weighted[0])) % 360.0
    dec = math.degrees(math.asin(weighted[2]))

    if all(star.bv is not None for star in cluster):
        total_b_flux = sum(
            10.0 ** (-0.4 * (star.vmag + float(star.bv)))
            for star in cluster
        )
        bv = -2.5 * math.log10(total_b_flux) - vmag
    elif primary.bv is not None:
        bv = primary.bv
    else:
        bv = 0.65

    display_name = next(
        (
            PROPER_NAMES_BY_HR[star.hr]
            for star in cluster
            if star.hr in PROPER_NAMES_BY_HR
        ),
        primary.raw_name or f"HR {primary.hr}",
    )
    selections = sorted(
        {reason for star in cluster for reason in reasons[star.hr]},
        key=lambda value: (value != "bright", value),
    )
    return SelectedStar(
        display_name=display_name,
        hrs=tuple(sorted(star.hr for star in cluster)),
        bayer=primary.bayer,
        constellation=primary.constellation,
        ra_degrees=ra,
        dec_degrees=dec,
        vmag=vmag,
        bv=bv,
        spectral_type=primary.spectral_type,
        selections=tuple(selections),
    )


def select_stars(catalog: list[CatalogStar]) -> list[SelectedStar]:
    normal = [star for star in catalog if not star.magnitude_code]
    reasons: dict[int, set[str]] = {}

    for star in normal:
        if star.vmag <= BRIGHT_MAGNITUDE_LIMIT:
            reasons.setdefault(star.hr, set()).add("bright")

    by_bayer: dict[tuple[str, str], list[CatalogStar]] = {}
    for star in catalog:
        if star.constellation and star.bayer:
            by_bayer.setdefault(
                (star.constellation, star.bayer), []
            ).append(star)

    for constellation, bayers in ICONIC_BAYER_VERTICES.items():
        for bayer in bayers:
            candidates = by_bayer.get((constellation, bayer), [])
            if not candidates:
                raise ValueError(f"missing Bayer vertex {bayer} {constellation}")
            representative = min(candidates, key=lambda star: (star.vmag, star.hr))
            reasons.setdefault(representative.hr, set()).add(constellation)

    selected = [star for star in catalog if star.hr in reasons]
    parent = list(range(len(selected)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(selected)):
        for right in range(left + 1, len(selected)):
            if angular_separation(selected[left], selected[right]) <= MERGE_ANGLE_DEGREES:
                union(left, right)

    clusters: dict[int, list[CatalogStar]] = {}
    for index, star in enumerate(selected):
        clusters.setdefault(root(index), []).append(star)

    result = [
        combine_cluster(cluster, reasons)
        for cluster in clusters.values()
    ]
    result.sort(key=lambda star: (star.ra_degrees, star.dec_degrees))
    return result


def write_selection(stars: list[SelectedStar], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    stream.write("# Earth Party real-star selection\n")
    stream.write("# Source: CDS V/50 Bright Star Catalogue, 5th Revised Ed.\n")
    stream.write(f"# Source URL: {BSC5_URL}\n")
    stream.write(f"# Source SHA-256: {BSC5_SHA256}\n")
    stream.write("# Coordinates: J2000 equatorial; magnitude: Johnson V; color: B-V\n")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(
        (
            "display_name",
            "hr",
            "bayer",
            "constellation",
            "ra_degrees",
            "dec_degrees",
            "vmag",
            "bv",
            "spectral_type",
            "selection",
        )
    )
    for star in stars:
        writer.writerow(
            (
                star.display_name,
                "+".join(str(hr) for hr in star.hrs),
                star.bayer,
                star.constellation,
                f"{star.ra_degrees:.8f}",
                f"{star.dec_degrees:.8f}",
                f"{star.vmag:.3f}",
                f"{star.bv:.3f}",
                star.spectral_type,
                ",".join(star.selections),
            )
        )
    output.write_text(stream.getvalue(), encoding="utf-8")


def obtain_catalog(path: Path | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path is not None:
        return path, None
    temporary = tempfile.TemporaryDirectory(prefix="earth-party-bsc5-")
    destination = Path(temporary.name) / "catalog.gz"
    with urllib.request.urlopen(BSC5_URL, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination, temporary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        help="existing CDS V/50 catalog.gz (default: download official source)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    catalog_path, temporary = obtain_catalog(arguments.catalog)
    try:
        catalog = read_catalog(catalog_path)
        selection = select_stars(catalog)
        write_selection(selection, arguments.output)
    finally:
        if temporary is not None:
            temporary.cleanup()
    print(
        f"Wrote {len(selection)} real stars to "
        f"{arguments.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
