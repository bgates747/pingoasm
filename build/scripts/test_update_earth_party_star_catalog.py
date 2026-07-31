#!/usr/bin/env python3
"""Regression tests for the explicit Bright Star Catalogue refresh tool."""

from __future__ import annotations

import math
import unittest

import update_earth_party_star_catalog as update


def put(record: list[str], start: int, end: int, value: str) -> None:
    width = end - start
    if len(value) > width:
        raise ValueError("fixture field is too wide")
    record[start:end] = value.rjust(width)


class StarCatalogRefreshTests(unittest.TestCase):
    def test_fixed_width_parser_reads_sirius_fields(self) -> None:
        record = [" "] * 197
        put(record, 0, 4, "2491")
        record[4:14] = list("  9Alp CMa")
        put(record, 75, 77, "6")
        put(record, 77, 79, "45")
        put(record, 79, 83, "8.9")
        record[83] = "-"
        put(record, 84, 86, "16")
        put(record, 86, 88, "42")
        put(record, 88, 90, "58")
        put(record, 102, 107, "-1.46")
        put(record, 109, 114, "0.00")
        record[127:147] = list("A1Vm".ljust(20))

        sirius = update.parse_catalog_line("".join(record))
        self.assertIsNotNone(sirius)
        self.assertEqual(sirius.hr, 2491)
        self.assertEqual(sirius.bayer, "Alp")
        self.assertEqual(sirius.constellation, "CMa")
        self.assertAlmostEqual(sirius.ra_degrees, 101.2870833, places=5)
        self.assertAlmostEqual(sirius.dec_degrees, -16.7161111, places=5)
        self.assertEqual(sirius.vmag, -1.46)
        self.assertEqual(sirius.bv, 0.0)
        self.assertEqual(sirius.spectral_type, "A1Vm")

    def test_close_components_merge_by_flux(self) -> None:
        first = update.CatalogStar(
            hr=1,
            raw_name="Alp1 Tst",
            flamsteed="",
            bayer="Alp",
            component="1",
            constellation="Tst",
            ra_degrees=10.0,
            dec_degrees=20.0,
            vmag=1.0,
            bv=0.5,
            spectral_type="G2V",
            magnitude_code="",
        )
        second = update.CatalogStar(
            hr=2,
            raw_name="Alp2 Tst",
            flamsteed="",
            bayer="Alp",
            component="2",
            constellation="Tst",
            ra_degrees=10.001,
            dec_degrees=20.001,
            vmag=2.0,
            bv=1.0,
            spectral_type="K1V",
            magnitude_code="",
        )
        combined = update.combine_cluster(
            [first, second],
            {1: {"bright"}, 2: {"Tst"}},
        )
        expected = -2.5 * math.log10(
            10.0 ** (-0.4) + 10.0 ** (-0.8)
        )
        self.assertEqual(combined.hrs, (1, 2))
        self.assertAlmostEqual(combined.vmag, expected)
        self.assertLess(combined.vmag, first.vmag)
        self.assertEqual(combined.selections, ("bright", "Tst"))

    def test_editorial_pattern_set_is_stable(self) -> None:
        self.assertEqual(len(update.ICONIC_BAYER_VERTICES), 19)
        self.assertEqual(
            update.ICONIC_BAYER_VERTICES["Ori"],
            ("Alp", "Bet", "Gam", "Del", "Eps", "Zet", "Kap", "Lam"),
        )
        self.assertIn("UMa", update.ICONIC_BAYER_VERTICES)
        self.assertIn("Cru", update.ICONIC_BAYER_VERTICES)


if __name__ == "__main__":
    unittest.main()
