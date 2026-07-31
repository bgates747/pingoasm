#!/usr/bin/env python3
"""Regression tests for Earth Party's real-star mesh generator."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import generate_earth_party_starfield as stars


PROFILE = json.loads(stars.DEFAULT_PROFILE.read_text(encoding="utf-8"))
CONFIGURATION = PROFILE["starfield"]
CATALOG = stars.PROJECT_ROOT / CONFIGURATION["catalog_source"]


class StarfieldGeneratorTests(unittest.TestCase):
    def test_catalog_has_bright_and_iconic_real_star_anchors(self) -> None:
        catalog = stars.read_catalog(CATALOG)
        self.assertEqual(len(catalog), 128)
        names = {star.display_name for star in catalog}
        self.assertTrue(stars.REQUIRED_ANCHORS <= names)
        selections = {
            selection
            for star in catalog
            for selection in star.selection.split(",")
        }
        self.assertTrue(
            {
                "bright",
                "Ori",
                "UMa",
                "UMi",
                "Cas",
                "Cyg",
                "Sco",
                "Cru",
                "Leo",
                "Tau",
                "Gem",
                "Sgr",
                "Peg",
                "And",
                "Aql",
                "Lyr",
                "Aur",
                "Per",
                "Boo",
                "CMa",
            }
            <= selections
        )

    def test_brightness_size_is_monotonic_and_clamped(self) -> None:
        magnitudes = (-2.0, -1.46, 0.0, 1.0, 2.0, 4.5)
        radii = [
            stars.magnitude_radius_pixels(magnitude, 2.0, 5.5)
            for magnitude in magnitudes
        ]
        self.assertEqual(radii[0], 5.5)
        self.assertEqual(radii[1], 5.5)
        self.assertEqual(radii[-1], 2.0)
        self.assertTrue(
            all(left >= right for left, right in zip(radii, radii[1:]))
        )

    def test_requested_color_exaggeration_is_explicit(self) -> None:
        catalog = {
            star.display_name: star for star in stars.read_catalog(CATALOG)
        }
        self.assertEqual(
            stars.palette_index_for_bv(catalog["Sirius"].bv),
            0,
        )
        self.assertEqual(stars.PALETTE[0].display_rgb, "#00AAFF")
        self.assertEqual(
            stars.palette_index_for_bv(catalog["Betelgeuse"].bv),
            len(stars.PALETTE) - 1,
        )
        self.assertEqual(stars.PALETTE[-1].display_rgb, "#FF0000")

    def test_generation_is_deterministic_and_sectorized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_include = root / "first.inc"
            first_texture = root / "first.rgba2"
            second_include = root / "second.inc"
            second_texture = root / "second.rgba2"
            first = stars.generate(
                CATALOG,
                first_include,
                first_texture,
                CONFIGURATION,
                provenance_path=str(CONFIGURATION["catalog_source"]),
            )
            second = stars.generate(
                CATALOG,
                second_include,
                second_texture,
                CONFIGURATION,
                provenance_path=str(CONFIGURATION["catalog_source"]),
            )

            self.assertEqual(first, second)
            self.assertEqual(first.star_count, 128)
            self.assertEqual(first.vertex_count, 128 * 11)
            self.assertEqual(first.triangle_count, 128 * 10)
            self.assertEqual(set(first.sector_star_counts), set(stars.SECTOR_NAMES))
            self.assertTrue(all(first.sector_star_counts.values()))
            self.assertEqual(sum(first.sector_star_counts.values()), 128)
            self.assertEqual(first.texture_size, 48)
            self.assertEqual(
                hashlib.sha256(first_include.read_bytes()).digest(),
                hashlib.sha256(second_include.read_bytes()).digest(),
            )
            self.assertEqual(first_texture.read_bytes(), second_texture.read_bytes())

    def test_every_generated_triangle_is_inward_and_q15_safe(self) -> None:
        configuration = CONFIGURATION
        tilt = stars.earth_tilt_matrix(
            configuration["earth_tilt_x_units"],
            configuration["earth_tilt_z_units"],
        )
        for source in stars.read_catalog(CATALOG):
            generated = stars.generate_star(
                source,
                shell_radius=configuration["shell_radius"],
                ra_center_hours=configuration["ra_center_hours"],
                fov_radians=configuration["fov_radians"],
                viewport_height=configuration["viewport_height"],
                minimum_radius_pixels=configuration["minimum_radius_pixels"],
                maximum_radius_pixels=configuration["maximum_radius_pixels"],
                tilt=tilt,
            )
            self.assertEqual(len(generated.vertices), 11)
            self.assertEqual(len(generated.triangles), 10)
            self.assertTrue(
                all(
                    -stars.Q15_ONE <= coordinate <= stars.Q15_ONE
                    for vertex in generated.vertices
                    for coordinate in vertex
                )
            )
            for triangle in generated.triangles:
                a, b, c = (
                    generated.vertices[index] for index in triangle
                )
                normal = stars.cross(
                    stars.subtract_int(b, a),
                    stars.subtract_int(c, a),
                )
                self.assertGreater(
                    stars.dot_int_float(normal, generated.inward),
                    0.0,
                )

    def test_celestial_north_tracks_earths_fixed_tilt_axis(self) -> None:
        catalog = {
            star.display_name: star for star in stars.read_catalog(CATALOG)
        }
        configuration = CONFIGURATION
        tilt = stars.earth_tilt_matrix(
            configuration["earth_tilt_x_units"],
            configuration["earth_tilt_z_units"],
        )
        polaris = stars.generate_star(
            catalog["Polaris"],
            shell_radius=configuration["shell_radius"],
            ra_center_hours=configuration["ra_center_hours"],
            fov_radians=configuration["fov_radians"],
            viewport_height=configuration["viewport_height"],
            minimum_radius_pixels=configuration["minimum_radius_pixels"],
            maximum_radius_pixels=configuration["maximum_radius_pixels"],
            tilt=tilt,
        )
        center = polaris.vertices[0]
        magnitude = math.sqrt(sum(value * value for value in center))
        center_direction = tuple(value / magnitude for value in center)
        earth_north = tuple(row[1] for row in tilt)
        alignment = sum(
            left * right
            for left, right in zip(center_direction, earth_north)
        )
        self.assertGreater(alignment, 0.9998)


if __name__ == "__main__":
    unittest.main()
