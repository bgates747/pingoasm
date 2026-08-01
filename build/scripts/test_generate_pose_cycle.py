#!/usr/bin/env python3
"""Numerical and provenance regressions for sampled Pingo pose cycles."""

from __future__ import annotations

import hashlib
import math
import struct
import tempfile
import unittest
from pathlib import Path

from generate_pose_cycle import (
    POSE_SAMPLE_SIZE,
    Q15_ONE,
    WIRE_TURN,
    PoseCycleSpec,
    float_axis_matrix,
    generate_pose_cycle,
    matrix_multiply,
    round_half_away_from_zero,
    write_generated_snapshot,
    write_pose_cycle_include,
)


EARTH_SPEC = PoseCycleSpec(
    symbol="earth_spin_pose",
    base_euler=(1536, 0, 1536),
    local_axis="y",
    sample_count=256,
)
EARTH_EULER_SHA256 = "d491ca1ec17035bc921c8de70aada5674cfc8a7bf104831c04c94d528453b7f3"
EARTH_FULL_SHA256 = "f0ab80b0936c652fbec05fd071c5dfd9965e322b10d6a53f25e2be144c70a5d8"


def wire_matrix(euler: tuple[int, int, int]) -> tuple[float, ...]:
    x, y, z = (value * math.tau / WIRE_TURN for value in euler)
    matrix = float_axis_matrix("z", z)
    matrix = matrix_multiply(matrix, float_axis_matrix("y", y))
    return matrix_multiply(matrix, float_axis_matrix("x", x))


def frobenius(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def relative_angle(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    # trace(left.T * right) is the elementwise dot product of two matrices.
    trace = sum(a * b for a, b in zip(left, right))
    value = min(1.0, max(-1.0, (trace - 1.0) / 2.0))
    return math.degrees(math.acos(value))


class PoseCycleGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cycle = generate_pose_cycle(EARTH_SPEC)

    def test_earth_cycle_reproduces_known_basis_and_landmarks(self) -> None:
        self.assertEqual(
            self.cycle.base_orientation_q15,
            (31356, -9102, 2761, 9512, 30006, -9102, 0, 9512, 31356),
        )
        expected = {
            0: (1536, 0, 1536),
            1: (1536, 122, 1573),
            16: (1655, 1955, 2160),
            64: (8192, 6656, 9728),
            95: (14222, 3993, 16376),
            96: (14270, 3876, -16321),
            128: (14848, 0, -14848),
            192: (8192, -6656, -6656),
            255: (1536, -122, 1499),
        }
        for index, euler in expected.items():
            self.assertEqual(self.cycle.samples[index].wire_euler, euler)

    def test_binary_payload_is_stable_and_has_two_explicit_domains(self) -> None:
        euler_payload = b"".join(
            struct.pack("<hhh", *sample.wire_euler)
            for sample in self.cycle.samples
        )
        self.assertEqual(len(euler_payload), 256 * 6)
        self.assertEqual(hashlib.sha256(euler_payload).hexdigest(), EARTH_EULER_SHA256)
        self.assertEqual(len(self.cycle.packed()), 256 * POSE_SAMPLE_SIZE)
        self.assertEqual(hashlib.sha256(self.cycle.packed()).hexdigest(), EARTH_FULL_SHA256)
        self.assertEqual(
            self.cycle.samples[0].orientation_q15,
            self.cycle.base_orientation_q15,
        )

    def test_cycle_is_unique_continuous_and_close_to_target(self) -> None:
        self.assertEqual(
            len({sample.wire_euler for sample in self.cycle.samples}),
            256,
        )
        base = tuple(value / Q15_ONE for value in self.cycle.base_orientation_q15)
        rendered: list[tuple[float, ...]] = []
        maximum_error = 0.0
        for index, sample in enumerate(self.cycle.samples):
            target = matrix_multiply(
                base,
                float_axis_matrix("y", math.tau * index / 256.0),
            )
            decoded = wire_matrix(sample.wire_euler)
            rendered.append(decoded)
            maximum_error = max(maximum_error, frobenius(target, decoded))
            expected_q15 = tuple(
                round_half_away_from_zero(value * Q15_ONE)
                for value in target
            )
            self.assertEqual(sample.orientation_q15, expected_q15)
        self.assertLess(maximum_error, 2.7e-4)

        steps = [
            relative_angle(rendered[index], rendered[(index + 1) & 0xFF])
            for index in range(256)
        ]
        self.assertGreater(min(steps), 1.396)
        self.assertLess(max(steps), 1.416)

    def test_phase_index_closes_without_record_256(self) -> None:
        phase = 0
        indices: list[int] = []
        for _ in range(256):
            phase = (phase + 128) & 0x7FFF
            index = ((phase + 64) & 0x7FFF) >> 7
            indices.append(index)
        self.assertEqual(indices[:2], [1, 2])
        self.assertEqual(indices[-2:], [255, 0])
        self.assertEqual(phase, 0)
        self.assertEqual(max(indices), 255)

    def test_generator_is_axis_and_sample_count_general(self) -> None:
        for axis in ("x", "y", "z"):
            with self.subTest(axis=axis):
                cycle = generate_pose_cycle(
                    PoseCycleSpec(
                        symbol=f"test_{axis}",
                        base_euler=(128, -256, 384),
                        local_axis=axis,
                        sample_count=64,
                    )
                )
                self.assertEqual(len(cycle.samples), 64)
                self.assertEqual(len(cycle.packed()), 64 * POSE_SAMPLE_SIZE)

    def test_generated_files_are_loud_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.inc"
            second = root / "second.inc"
            for path in (first, second):
                write_pose_cycle_include(
                    path,
                    EARTH_SPEC,
                    generator="build/scripts/example.py",
                    authoritative_input="apps/example/profile.json",
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            text = first.read_text(encoding="utf-8")
            self.assertIn("AUTO-GENERATED FILE - DO NOT EDIT", text)
            self.assertIn("Generated by: build/scripts/example.py", text)
            self.assertIn("earth_spin_pose_samples:", text)
            self.assertIn("earth_spin_pose_sample_size: equ 24", text)

            source = root / "common.inc"
            source.write_text("answer: equ 42\n", encoding="utf-8")
            snapshot = root / "snapshot.inc"
            write_generated_snapshot(
                source,
                snapshot,
                generator="build/scripts/example.py",
                source_label="tests/apps/_common/common.inc",
            )
            snapshot_text = snapshot.read_text(encoding="utf-8")
            self.assertIn("AUTO-GENERATED FILE - DO NOT EDIT", snapshot_text)
            self.assertIn("answer: equ 42", snapshot_text)

    def test_invalid_specs_fail_before_writing(self) -> None:
        for spec in (
            PoseCycleSpec("bad-name", (0, 0, 0)),
            PoseCycleSpec("ok", (0, 0, 0), local_axis="q"),
            PoseCycleSpec("ok", (0, 0, 0), sample_count=1),
            PoseCycleSpec("ok", (0, 0, 40000)),
        ):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                generate_pose_cycle(spec)


if __name__ == "__main__":
    unittest.main()
