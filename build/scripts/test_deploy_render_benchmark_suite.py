#!/usr/bin/env python3
"""Tests for the render-benchmark suite deployer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_render_benchmark_suite import DEFAULT_SUITE, autoexec_lines


class AutoexecTests(unittest.TestCase):
    def test_default_suite_is_sequential_and_complete(self) -> None:
        lines = autoexec_lines(DEFAULT_SUITE)
        self.assertEqual(lines[0], "SET KEYBOARD 1")
        self.assertEqual(len(lines), 1 + 3 * len(DEFAULT_SUITE))
        for index, name in enumerate(DEFAULT_SUITE):
            offset = 1 + 3 * index
            self.assertEqual(
                lines[offset],
                "/".join(
                    (
                        "cd ",
                        "mystuff",
                        "pingoasm",
                        "benchmarks",
                        "render-spin",
                        "fixtures",
                        name,
                        "tgt",
                    )
                ),
            )
            self.assertEqual(lines[offset + 1], "load benchmark.bin")
            self.assertEqual(lines[offset + 2], "run")


if __name__ == "__main__":
    unittest.main()
