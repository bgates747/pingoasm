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


# Fixture-specific three-class RGBA2222 sources.  The near-field review showed
# that fifteen competing semantic colors read as dazzle camouflage even when
# each was individually valid.  Preserve the source material IDs for geometry
# and provenance, but collapse their presentation to three exact Agon colors:
# palette 20 for water, palette 7 for developed land, and palette 21 for every
# other land-cover class.  Illumination band 15 therefore remains a solid 4x4
# for every material ID; scene illumination may still choose darker patterns.
_AGON_SOLID_TERRAIN_RGB: tuple[RGB8, ...] = (
    (0, 85, 255),  # 11 open water: palette 20, lighter azure
    (170, 170, 170),  # 21 developed open space
    (170, 170, 170),  # 22 developed low intensity
    (170, 170, 170),  # 23 developed medium intensity
    (170, 170, 170),  # 24 developed high intensity: palette 7, light gray
    (0, 170, 85),  # 31 barren land
    (0, 170, 85),  # 41 deciduous forest
    (0, 170, 85),  # 42 evergreen forest
    (0, 170, 85),  # 43 mixed forest
    (0, 170, 85),  # 52 shrub and scrub
    (0, 170, 85),  # 71 grassland
    (0, 170, 85),  # 81 pasture and hay
    (0, 170, 85),  # 82 cultivated crops
    (0, 170, 85),  # 90 woody wetlands
    (0, 170, 85),  # 95 emergent wetlands: palette 21, spring green
)


AGON_SOLID_TERRAIN_MATERIALS: tuple[TerrainMaterial, ...] = tuple(
    TerrainMaterial(
        source.material_id,
        source.nlcd_category,
        source.name,
        rgb,
    )
    for source, rgb in zip(
        BERKELEY_TERRAIN_MATERIALS,
        _AGON_SOLID_TERRAIN_RGB,
        strict=True,
    )
)


NLCD_MATERIALS: dict[int, tuple[str, RGB8]] = {
    0: UNCLASSIFIED_NLCD_MATERIAL,
    **{
        material.nlcd_category: (material.name, material.rgb)
        for material in BERKELEY_TERRAIN_MATERIALS
    },
}
