#!/usr/bin/env python3
"""Generate deterministic sampled Pingo object-orientation cycles.

The eZ80 and VDP deliberately use two nearby but distinct angle domains:

* Pingo wire Euler angles encode one turn as 32767 units.
* AgonMaths' fast internal trigonometry uses a 32768-unit binary turn.

A generated sample therefore carries both the fine wire Euler pose and its
matching signed-Q15 local-to-world matrix.  Applying a sample never performs
runtime inverse trigonometry and never accumulates orientation error.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


WIRE_TURN = 32767
INTERNAL_TURN = 32768
Q15_ONE = 32767
POSE_SAMPLE_SIZE = 24
AXES = ("x", "y", "z")
SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Matrix = tuple[float, ...]
Q15Matrix = tuple[int, ...]
Euler = tuple[int, int, int]


@dataclass(frozen=True)
class PoseCycleSpec:
    """One periodic local-axis orientation sequence."""

    symbol: str
    base_euler: Euler
    local_axis: str = "y"
    sample_count: int = 256

    def validate(self) -> None:
        if not SYMBOL_RE.fullmatch(self.symbol) or not self.symbol.isascii():
            raise ValueError(f"assembly-unsafe pose-cycle symbol: {self.symbol!r}")
        if self.local_axis not in AXES:
            raise ValueError(f"local_axis must be one of {AXES}, not {self.local_axis!r}")
        if not 2 <= self.sample_count <= 256:
            raise ValueError("sample_count must be in 2..256 for the 8-bit loader")
        if len(self.base_euler) != 3:
            raise ValueError("base_euler must contain X, Y, and Z")
        if any(not -32768 <= value <= 32767 for value in self.base_euler):
            raise ValueError("base_euler values must be signed 16-bit words")


@dataclass(frozen=True)
class PoseSample:
    wire_euler: Euler
    orientation_q15: Q15Matrix

    def packed(self) -> bytes:
        return struct.pack("<12h", *self.wire_euler, *self.orientation_q15)


@dataclass(frozen=True)
class PoseCycle:
    spec: PoseCycleSpec
    base_orientation_q15: Q15Matrix
    samples: tuple[PoseSample, ...]

    def packed(self) -> bytes:
        return b"".join(sample.packed() for sample in self.samples)


def round_half_away_from_zero(value: float) -> int:
    """Return deterministic nearest-integer rounding with symmetric ties."""

    magnitude = math.floor(abs(value) + 0.5)
    return -magnitude if value < 0.0 else magnitude


def round_div_q15(value: int) -> int:
    """Mirror AgonMaths' signed divide-by-32767 nearest rounding."""

    magnitude = (abs(value) + (Q15_ONE // 2)) // Q15_ONE
    return -magnitude if value < 0 else magnitude


def coarse_sincos(angle: int) -> tuple[int, int]:
    """Mirror p3d_sincos16's 256-phase internal Q15 contract."""

    magnitude = abs(angle)
    phase = ((magnitude + 64) // 128) & 0xFF
    radians = math.tau * phase / 256.0
    sine = round_half_away_from_zero(math.sin(radians) * Q15_ONE)
    cosine = round_half_away_from_zero(math.cos(radians) * Q15_ONE)
    if angle < 0:
        sine = -sine
    return sine, cosine


def q15_axis_matrix(axis: str, angle: int) -> Q15Matrix:
    sine, cosine = coarse_sincos(angle)
    if axis == "x":
        return (
            Q15_ONE, 0, 0,
            0, cosine, -sine,
            0, sine, cosine,
        )
    if axis == "y":
        return (
            cosine, 0, sine,
            0, Q15_ONE, 0,
            -sine, 0, cosine,
        )
    if axis == "z":
        return (
            cosine, -sine, 0,
            sine, cosine, 0,
            0, 0, Q15_ONE,
        )
    raise ValueError(f"unknown axis: {axis!r}")


def q15_matrix_multiply(left: Q15Matrix, right: Q15Matrix) -> Q15Matrix:
    values: list[int] = []
    for row in range(3):
        for column in range(3):
            numerator = sum(
                left[row * 3 + inner] * right[inner * 3 + column]
                for inner in range(3)
            )
            result = round_div_q15(numerator)
            if not -32767 <= result <= 32767:
                raise OverflowError(f"Q15 matrix coefficient overflowed: {result}")
            values.append(result)
    return tuple(values)


def base_orientation_q15(euler: Euler) -> Q15Matrix:
    """Build Rz(z)*Ry(y)*Rx(x) with the current coarse eZ80 arithmetic."""

    matrix: Q15Matrix = (
        Q15_ONE, 0, 0,
        0, Q15_ONE, 0,
        0, 0, Q15_ONE,
    )
    for axis, angle in (("z", euler[2]), ("y", euler[1]), ("x", euler[0])):
        matrix = q15_matrix_multiply(matrix, q15_axis_matrix(axis, angle))
    return matrix


def float_axis_matrix(axis: str, radians: float) -> Matrix:
    sine = math.sin(radians)
    cosine = math.cos(radians)
    if axis == "x":
        return (
            1.0, 0.0, 0.0,
            0.0, cosine, -sine,
            0.0, sine, cosine,
        )
    if axis == "y":
        return (
            cosine, 0.0, sine,
            0.0, 1.0, 0.0,
            -sine, 0.0, cosine,
        )
    if axis == "z":
        return (
            cosine, -sine, 0.0,
            sine, cosine, 0.0,
            0.0, 0.0, 1.0,
        )
    raise ValueError(f"unknown axis: {axis!r}")


def matrix_multiply(left: Matrix, right: Matrix) -> Matrix:
    return tuple(
        sum(
            left[row * 3 + inner] * right[inner * 3 + column]
            for inner in range(3)
        )
        for row in range(3)
        for column in range(3)
    )


def canonical_radians(angle: float) -> float:
    wrapped = (angle + math.pi) % math.tau - math.pi
    return -math.pi if wrapped == math.pi else wrapped


def encode_wire_angle(radians: float) -> int:
    """Encode the documented 32767-units-per-turn Pingo wire contract."""

    value = round_half_away_from_zero(
        canonical_radians(radians) * WIRE_TURN / math.tau
    )
    if value == 32768:
        value = -16384
    if not -32768 <= value <= 32767:
        raise OverflowError(f"wire angle overflowed: {value}")
    return value


def matrix_to_wire_euler(matrix: Matrix) -> Euler:
    """Extract canonical XYZ words for R=Rz(z)*Ry(y)*Rx(x)."""

    sine_y = min(1.0, max(-1.0, -matrix[6]))
    y = math.asin(sine_y)
    if abs(math.cos(y)) > 1.0e-12:
        x = math.atan2(matrix[7], matrix[8])
        z = math.atan2(matrix[3], matrix[0])
    else:
        x = math.atan2(-matrix[5], matrix[4])
        z = 0.0
    return (
        encode_wire_angle(x),
        encode_wire_angle(y),
        encode_wire_angle(z),
    )


def quantize_matrix(matrix: Matrix) -> Q15Matrix:
    values = tuple(
        round_half_away_from_zero(value * Q15_ONE) for value in matrix
    )
    if any(not -32767 <= value <= 32767 for value in values):
        raise OverflowError("sample matrix is outside signed-Q15 range")
    return values


def generate_pose_cycle(spec: PoseCycleSpec) -> PoseCycle:
    """Generate one closed local-axis cycle from an immutable base pose."""

    spec.validate()
    base_q15 = base_orientation_q15(spec.base_euler)
    base = tuple(value / Q15_ONE for value in base_q15)
    samples: list[PoseSample] = []
    for index in range(spec.sample_count):
        phase = math.tau * index / spec.sample_count
        target = matrix_multiply(base, float_axis_matrix(spec.local_axis, phase))
        samples.append(
            PoseSample(
                wire_euler=matrix_to_wire_euler(target),
                orientation_q15=quantize_matrix(target),
            )
        )
    return PoseCycle(spec, base_q15, tuple(samples))


def assembly_rows(values: Sequence[int]) -> Iterable[str]:
    for start in range(0, len(values), 3):
        yield "    dw " + ",".join(str(value) for value in values[start : start + 3])


def render_pose_cycle_include(
    cycle: PoseCycle,
    *,
    generator: str,
    authoritative_input: str,
) -> str:
    """Render one self-describing portable assembly include."""

    spec = cycle.spec
    lines = [
        "; =============================================================================",
        "; AUTO-GENERATED FILE - DO NOT EDIT",
        f"; Generated by: {generator}",
        f"; Generated from: {authoritative_input}",
        "; Edit the generator or its authoritative inputs instead.",
        ";",
        "; Each record stores six bytes of fine Pingo wire Euler angles followed",
        "; by the matching 18-byte signed-Q15 local-to-world orientation matrix.",
        "; This intentionally keeps the 32767-unit wire-angle domain separate from",
        "; AgonMaths' 32768-unit internal binary-turn trigonometry.",
        "; =============================================================================",
        "",
        f"{spec.symbol}_sample_count: equ {spec.sample_count}",
        f"{spec.symbol}_sample_size: equ {POSE_SAMPLE_SIZE}",
        f"{spec.symbol}_base_x: equ {spec.base_euler[0]}",
        f"{spec.symbol}_base_y: equ {spec.base_euler[1]}",
        f"{spec.symbol}_base_z: equ {spec.base_euler[2]}",
        f"{spec.symbol}_local_axis: equ p3d_pose_axis_{spec.local_axis}",
        "",
        f"{spec.symbol}_base_orientation:",
        *assembly_rows(cycle.base_orientation_q15),
        "",
        f"{spec.symbol}_samples:",
    ]
    for index, sample in enumerate(cycle.samples):
        lines.append(f"; sample {index}")
        lines.extend(assembly_rows(sample.wire_euler))
        lines.extend(assembly_rows(sample.orientation_q15))
    lines.append("")
    return "\n".join(lines)


def write_pose_cycle_include(
    output: Path,
    spec: PoseCycleSpec,
    *,
    generator: str,
    authoritative_input: str,
) -> PoseCycle:
    cycle = generate_pose_cycle(spec)
    output.write_text(
        render_pose_cycle_include(
            cycle,
            generator=generator,
            authoritative_input=authoritative_input,
        ),
        encoding="utf-8",
    )
    return cycle


def write_generated_snapshot(
    source: Path,
    output: Path,
    *,
    generator: str,
    source_label: str,
) -> None:
    body = "\n".join(line.rstrip() for line in source.read_text(encoding="utf-8").splitlines())
    output.write_text(
        "\n".join(
            (
                "; =============================================================================",
                "; AUTO-GENERATED FILE - DO NOT EDIT",
                f"; Generated by: {generator}",
                f"; Generated from: {source_label}",
                "; Edit the generator or its authoritative inputs instead.",
                "; =============================================================================",
                "",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--base-euler", nargs=3, type=int, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--axis", choices=AXES, default="y")
    parser.add_argument("--samples", type=int, default=256)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec = PoseCycleSpec(
        symbol=args.symbol,
        base_euler=tuple(args.base_euler),
        local_axis=args.axis,
        sample_count=args.samples,
    )
    write_pose_cycle_include(
        args.output,
        spec,
        generator="build/scripts/generate_pose_cycle.py",
        authoritative_input="command-line pose-cycle specification",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
