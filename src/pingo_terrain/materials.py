"""Authored terrain material colors shared by offline generators.

These colors are an artistic source specification.  They deliberately are not
restricted to colors that can be represented by one opaque RGBA2222 pixel.
"""

from __future__ import annotations

from dataclasses import dataclass


RGB8 = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class TerrainMaterial:
    """One compact runtime material and its source NLCD category."""

    material_id: int
    nlcd_category: int
    name: str
    rgb: RGB8


UNCLASSIFIED_NLCD_MATERIAL: tuple[str, RGB8] = (
    "unclassified",
    (89, 94, 87),
)


_BERKELEY_NLCD_COLORS: tuple[tuple[int, str, RGB8], ...] = (
    (11, "open water", (43, 102, 128)),
    (21, "developed open space", (135, 144, 120)),
    (22, "developed low intensity", (143, 139, 123)),
    (23, "developed medium intensity", (119, 118, 111)),
    (24, "developed high intensity", (96, 97, 95)),
    (31, "barren land", (154, 139, 103)),
    (41, "deciduous forest", (75, 116, 68)),
    (42, "evergreen forest", (49, 88, 59)),
    (43, "mixed forest", (62, 104, 64)),
    (52, "shrub and scrub", (102, 115, 66)),
    (71, "grassland", (126, 135, 80)),
    (81, "pasture and hay", (112, 130, 75)),
    (82, "cultivated crops", (154, 140, 74)),
    (90, "woody wetlands", (53, 95, 84)),
    (95, "emergent wetlands", (82, 119, 106)),
)


BERKELEY_TERRAIN_MATERIALS: tuple[TerrainMaterial, ...] = tuple(
    TerrainMaterial(material_id, category, name, rgb)
    for material_id, (category, name, rgb) in enumerate(_BERKELEY_NLCD_COLORS)
)


NLCD_MATERIALS: dict[int, tuple[str, RGB8]] = {
    0: UNCLASSIFIED_NLCD_MATERIAL,
    **{
        material.nlcd_category: (material.name, material.rgb)
        for material in BERKELEY_TERRAIN_MATERIALS
    },
}

