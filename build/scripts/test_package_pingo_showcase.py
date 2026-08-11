#!/usr/bin/env python3
"""Regression tests for the Pingo-only Discord showcase packager."""

from __future__ import annotations

import unittest

import package_pingo_showcase as package


class PackagePingoShowcaseTests(unittest.TestCase):
    def test_archive_date_is_a_valid_deterministic_zip_time(self) -> None:
        self.assertEqual(
            package.parse_archive_date("2026-08-10"),
            (2026, 8, 10, 0, 0, 0),
        )
        with self.assertRaises(ValueError):
            package.parse_archive_date("not-a-date")

    def test_generated_readme_has_paths_controls_and_rights(self) -> None:
        identity = {
            "remote": "https://example.invalid/repo",
            "branch": "main",
            "commit": "a" * 40,
            "dirty": False,
        }
        text = package.readme(identity, identity, "b" * 64, "demo_2026-08-10")
        self.assertIn("flash vdp firmware.bin", text)
        self.assertIn("cd /PingoShowcase/Lara", text)
        self.assertIn("cd /PingoShowcase/EarthParty", text)
        self.assertIn("Page Up / Page Down", text)
        self.assertIn("128 real bright stars", text)
        self.assertIn("CC BY-NC 4.0", text)
        self.assertIn("contains no Wolf3DOrig implementation", text)
        self.assertIn("tree/demo_2026-08-10", text)


if __name__ == "__main__":
    unittest.main()
