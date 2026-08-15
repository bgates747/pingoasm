"""Pure parsers and deterministic summaries for regular-LOD profile logs.

Emulator output may precede a ``PINGO_*`` marker on the same line. Everything
after a recognized marker is nevertheless treated as evidence and parsed
strictly. This module performs no I/O, so capture tools can share it without
coupling receipts to a particular emulator runner.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence


# The implementation body is useful to disassemblers. Cycle profiling stops
# at the CALL instruction so Fab can pause and report the next break exactly.
SELECTOR_IMPLEMENTATION_ADDRESS = 0x05F9AC
SELECTOR_CALL_ADDRESS = 0x05FD96
SELECTOR_POST_CALL_ADDRESS = 0x05FD9A

_RENDER_MARKER = "PINGO_RENDER "
_MESH_PREFIX = "PINGO_STREAM mesh_replace"
_STREAM_MARKER = "PINGO_STREAM "
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER_RE = re.compile(r"-?[0-9]+\Z")
_STATE_RE = re.compile(r"\*\s+([0-9A-Fa-f]{6}):")
_CYCLES_RE = re.compile(r"Cycles since last break:\s*([^\s]+)")

FieldValue = int | str
FieldItems = tuple[tuple[str, FieldValue], ...]


class ProfileEvidenceError(ValueError):
    """A profile transcript is malformed or internally incomplete."""


@dataclass(frozen=True, slots=True)
class RenderRecord:
    """One parsed ``PINGO_RENDER`` diagnostic."""

    line_number: int
    log_offset: int
    fields: FieldItems

    def value(self, name: str) -> FieldValue:
        for key, value in self.fields:
            if key == name:
                return value
        raise ProfileEvidenceError(
            f"PINGO_RENDER line {self.line_number} lacks field {name!r}"
        )

    def integer(self, name: str) -> int:
        value = self.value(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProfileEvidenceError(
                f"PINGO_RENDER line {self.line_number} field {name!r} "
                f"is not an integer: {value!r}"
            )
        return value

    @property
    def sequence(self) -> int:
        return self.integer("seq")

    @property
    def bitmap_id(self) -> int:
        return self.integer("bmid")

    @property
    def render_us(self) -> int:
        return self.integer("render_us")

    def as_dict(self) -> dict[str, FieldValue]:
        return dict(self.fields)


@dataclass(frozen=True, slots=True)
class MeshReplaceRecord:
    """One successful command-50 mesh publication."""

    line_number: int
    log_offset: int
    stage_buffer_id: int
    mesh_id: int
    data_bytes: int
    vertices: int
    position_indices: int
    texture_coordinates: int
    texture_indices: int
    publication_us: int

    def as_dict(self) -> dict[str, int]:
        return {
            "line_number": self.line_number,
            "log_offset": self.log_offset,
            "stage_buffer_id": self.stage_buffer_id,
            "mesh_id": self.mesh_id,
            "data_bytes": self.data_bytes,
            "vertices": self.vertices,
            "position_indices": self.position_indices,
            "texture_coordinates": self.texture_coordinates,
            "texture_indices": self.texture_indices,
            "publication_us": self.publication_us,
        }


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    """A stable integer distribution using a nearest-rank p95."""

    count: int
    total: int
    minimum: int
    maximum: int
    mean: float
    median: float
    p95: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "count": self.count,
            "total": self.total,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "mean": self.mean,
            "median": self.median,
            "p95": self.p95,
        }


@dataclass(frozen=True, slots=True)
class RenderWindowSummary:
    """Summaries for one exact contiguous render sequence window."""

    bitmap_id: int
    first_sequence: int
    last_sequence: int
    frame_count: int
    metrics: tuple[tuple[str, DistributionSummary], ...]

    def metric(self, name: str) -> DistributionSummary:
        for metric_name, summary in self.metrics:
            if metric_name == name:
                return summary
        raise KeyError(name)

    def as_dict(self) -> dict[str, object]:
        return {
            "bitmap_id": self.bitmap_id,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "frame_count": self.frame_count,
            "metrics": {
                name: summary.as_dict() for name, summary in self.metrics
            },
        }


@dataclass(frozen=True, slots=True)
class DebuggerTriggerState:
    """A target debugger state and its associated cycle report."""

    address: int
    line_number: int
    cycles_line_number: int
    cycles_since_last_break: int


@dataclass(frozen=True, slots=True)
class SelectorCyclePair:
    """One exact call-site/post-call selector measurement."""

    entry: DebuggerTriggerState
    post_call: DebuggerTriggerState

    @property
    def selector_cycles(self) -> int:
        return self.post_call.cycles_since_last_break

    def as_dict(self) -> dict[str, int]:
        return {
            "entry_line_number": self.entry.line_number,
            "entry_cycles_since_previous_break": (
                self.entry.cycles_since_last_break
            ),
            "post_call_line_number": self.post_call.line_number,
            "selector_cycles": self.selector_cycles,
        }


@dataclass(frozen=True, slots=True)
class RegularLodProfileLog:
    renders: tuple[RenderRecord, ...]
    mesh_replacements: tuple[MeshReplaceRecord, ...]
    selector_pairs: tuple[SelectorCyclePair, ...]


def _iter_lines(contents: str) -> Iterable[tuple[int, int, str]]:
    offset = 0
    for number, raw in enumerate(contents.splitlines(keepends=True), 1):
        yield number, offset, raw.rstrip("\r\n")
        offset += len(raw)


def _suffix(line: str, marker: str, line_number: int) -> str:
    if line.count(marker) != 1:
        raise ProfileEvidenceError(
            f"line {line_number} does not contain exactly one "
            f"{marker.strip()!r} marker"
        )
    return line.split(marker, 1)[1]


def _fields(payload: str, kind: str, line_number: int) -> FieldItems:
    tokens = payload.strip().split()
    if not tokens:
        raise ProfileEvidenceError(f"{kind} line {line_number} has no fields")
    result: list[tuple[str, FieldValue]] = []
    seen: set[str] = set()
    for token in tokens:
        if token.count("=") != 1:
            raise ProfileEvidenceError(
                f"{kind} line {line_number} has malformed token {token!r}"
            )
        key, encoded = token.split("=", 1)
        if _KEY_RE.fullmatch(key) is None or not encoded:
            raise ProfileEvidenceError(
                f"{kind} line {line_number} has malformed token {token!r}"
            )
        if key in seen:
            raise ProfileEvidenceError(
                f"{kind} line {line_number} repeats field {key!r}"
            )
        seen.add(key)
        value: FieldValue = (
            int(encoded, 10)
            if _INTEGER_RE.fullmatch(encoded) is not None
            else encoded
        )
        result.append((key, value))
    return tuple(result)


def _required_uint(
    fields: FieldItems, name: str, kind: str, line_number: int
) -> int:
    values = [value for key, value in fields if key == name]
    if not values:
        raise ProfileEvidenceError(
            f"{kind} line {line_number} lacks required field {name!r}"
        )
    value = values[0]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProfileEvidenceError(
            f"{kind} line {line_number} field {name!r} "
            f"is not a non-negative integer: {value!r}"
        )
    return value


def parse_render_records(contents: str) -> tuple[RenderRecord, ...]:
    """Parse every render diagnostic, rejecting malformed marked lines."""

    result = []
    for line_number, log_offset, line in _iter_lines(contents):
        if "PINGO_RENDER" not in line:
            continue
        fields = _fields(
            _suffix(line, _RENDER_MARKER, line_number),
            "PINGO_RENDER",
            line_number,
        )
        for name in ("seq", "bmid", "render_us"):
            _required_uint(fields, name, "PINGO_RENDER", line_number)
        result.append(RenderRecord(line_number, log_offset, fields))
    return tuple(result)


def parse_mesh_replace_records(contents: str) -> tuple[MeshReplaceRecord, ...]:
    """Parse every successful command-50 mesh publication diagnostic."""

    result = []
    required = ("stage", "mid", "bytes", "v", "i", "u", "t", "us")
    for line_number, log_offset, line in _iter_lines(contents):
        if _MESH_PREFIX not in line:
            continue
        fields = _fields(
            _suffix(line, _STREAM_MARKER, line_number),
            "PINGO_STREAM mesh_replace",
            line_number,
        )
        if dict(fields).get("mesh_replace") != "ok":
            raise ProfileEvidenceError(
                f"mesh_replace line {line_number} does not report success"
            )
        values = {
            name: _required_uint(
                fields, name, "PINGO_STREAM mesh_replace", line_number
            )
            for name in required
        }
        result.append(
            MeshReplaceRecord(
                line_number,
                log_offset,
                values["stage"],
                values["mid"],
                values["bytes"],
                values["v"],
                values["i"],
                values["u"],
                values["t"],
                values["us"],
            )
        )
    return tuple(result)


def _linear_percentile(values: Sequence[int], percentile: int) -> float:
    scaled = (len(values) - 1) * percentile
    lower_index, remainder = divmod(scaled, 100)
    lower = values[lower_index]
    if remainder == 0:
        return float(lower)
    upper = values[lower_index + 1]
    return (lower * (100 - remainder) + upper * remainder) / 100


def summarize_distribution(values: Iterable[int]) -> DistributionSummary:
    """Summarize integers with median interpolation and nearest-rank p95."""

    ordered = sorted(values)
    if not ordered:
        raise ProfileEvidenceError("cannot summarize an empty distribution")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in ordered
    ):
        raise TypeError("distribution values must be integers")
    total = sum(ordered)
    return DistributionSummary(
        len(ordered),
        total,
        ordered[0],
        ordered[-1],
        total / len(ordered),
        _linear_percentile(ordered, 50),
        float(ordered[((95 * len(ordered) + 99) // 100) - 1]),
    )


def summarize_render_window(
    records: Sequence[RenderRecord],
    *,
    first_sequence: int | None = None,
    last_sequence: int | None = None,
    bitmap_id: int | None = None,
    metric_names: Sequence[str] | None = None,
) -> RenderWindowSummary:
    """Summarize an exact contiguous sequence range for one bitmap.

    With no explicit metrics, every integer field except ``seq`` and ``bmid``
    must have an identical schema throughout the window and is summarized in
    lexical order.
    """

    if not records:
        raise ProfileEvidenceError("cannot summarize empty render records")
    ids = {record.bitmap_id for record in records}
    if bitmap_id is None:
        if len(ids) != 1:
            raise ProfileEvidenceError(
                "render records contain multiple bitmap IDs; select one"
            )
        bitmap_id = next(iter(ids))
    bitmap_records = [record for record in records if record.bitmap_id == bitmap_id]
    if not bitmap_records:
        raise ProfileEvidenceError(f"no render records use bitmap ID {bitmap_id}")
    first = (
        min(record.sequence for record in bitmap_records)
        if first_sequence is None
        else first_sequence
    )
    last = (
        max(record.sequence for record in bitmap_records)
        if last_sequence is None
        else last_sequence
    )
    if first < 0 or last < first:
        raise ValueError("invalid render window bounds")
    window = [
        record for record in bitmap_records if first <= record.sequence <= last
    ]
    expected = tuple(range(first, last + 1))
    actual = tuple(record.sequence for record in window)
    if actual != expected:
        raise ProfileEvidenceError(
            f"render window is not exact and contiguous: expected {expected}, "
            f"got {actual}"
        )

    if metric_names is None:
        schemas = [
            {
                key
                for key, value in record.fields
                if isinstance(value, int) and key not in {"seq", "bmid"}
            }
            for record in window
        ]
        if any(schema != schemas[0] for schema in schemas[1:]):
            raise ProfileEvidenceError(
                "render numeric field schema changes inside the window"
            )
        names = tuple(sorted(schemas[0]))
    else:
        names = tuple(metric_names)
        if not names or len(names) != len(set(names)):
            raise ValueError("metric names must be nonempty and unique")

    return RenderWindowSummary(
        bitmap_id,
        first,
        last,
        len(window),
        tuple(
            (
                name,
                summarize_distribution(record.integer(name) for record in window),
            )
            for name in names
        ),
    )


def parse_selector_cycle_pairs(
    contents: str,
    *,
    entry_address: int = SELECTOR_CALL_ADDRESS,
    post_call_address: int = SELECTOR_POST_CALL_ADDRESS,
) -> tuple[SelectorCyclePair, ...]:
    """Parse exact alternating pausing-debugger call/post-call states.

    Fab may print ``Cycles since last break`` on the state line or on the
    following full-state detail line. A target state without that report, two
    adjacent entries, a post-call without an entry, or a dangling entry all
    fail closed. The post-call report is the selector duration sample.
    """

    if not 0 <= entry_address <= 0xFFFFFF:
        raise ValueError("entry address lies outside 24-bit space")
    if not 0 <= post_call_address <= 0xFFFFFF:
        raise ValueError("post-call address lies outside 24-bit space")
    if entry_address == post_call_address:
        raise ValueError("entry and post-call addresses must differ")
    targets = {entry_address, post_call_address}
    pending: tuple[int, int] | None = None
    states: list[DebuggerTriggerState] = []

    for line_number, _offset, line in _iter_lines(contents):
        state_matches = tuple(_STATE_RE.finditer(line))
        if len(state_matches) > 1:
            raise ProfileEvidenceError(
                f"debugger line {line_number} has multiple states"
            )
        if state_matches:
            address = int(state_matches[0].group(1), 16)
            if pending is not None:
                pending_address, state_line = pending
                if address != pending_address:
                    raise ProfileEvidenceError(
                        f"target {pending_address:06x} at line {state_line} "
                        "has no cycles before the next debugger state"
                    )
                # A pausing breakpoint can print a compact state, after which
                # the profiler's explicit `state` command prints the same PC
                # in full and emits the cycle line. Associate cycles with the
                # latter state without weakening call/post-call ordering.
                pending = (address, line_number)
            else:
                pending = (address, line_number) if address in targets else None

        cycle_matches = tuple(_CYCLES_RE.finditer(line))
        if len(cycle_matches) > 1:
            raise ProfileEvidenceError(
                f"debugger line {line_number} has multiple cycle reports"
            )
        if cycle_matches and pending is not None:
            encoded = cycle_matches[0].group(1)
            if _INTEGER_RE.fullmatch(encoded) is None:
                raise ProfileEvidenceError(
                    f"cycle report at line {line_number} is malformed: {encoded!r}"
                )
            cycles = int(encoded, 10)
            if cycles < 0:
                raise ProfileEvidenceError(
                    f"cycle report at line {line_number} is negative"
                )
            address, state_line = pending
            states.append(
                DebuggerTriggerState(address, state_line, line_number, cycles)
            )
            pending = None

    if pending is not None:
        address, state_line = pending
        raise ProfileEvidenceError(
            f"target {address:06x} at line {state_line} has no cycle report"
        )

    pairs = []
    entry: DebuggerTriggerState | None = None
    for state in states:
        if state.address == entry_address:
            if entry is not None:
                raise ProfileEvidenceError(
                    f"entry at line {state.line_number} follows unpaired entry "
                    f"at line {entry.line_number}"
                )
            entry = state
        elif entry is None:
            raise ProfileEvidenceError(
                f"post-call at line {state.line_number} has no preceding entry"
            )
        else:
            pairs.append(SelectorCyclePair(entry, state))
            entry = None
    if entry is not None:
        raise ProfileEvidenceError(
            f"entry at line {entry.line_number} has no post-call state"
        )
    return tuple(pairs)


def parse_regular_lod_profile(contents: str) -> RegularLodProfileLog:
    """Parse all supported records from one transcript."""

    return RegularLodProfileLog(
        parse_render_records(contents),
        parse_mesh_replace_records(contents),
        parse_selector_cycle_pairs(contents),
    )
