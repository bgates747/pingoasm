"""Static checks for eZ80 ADL multibyte width mistakes.

In ADL mode an unsuffixed ``ld (address),hl`` (and the corresponding loads
and other multibyte registers) transfers 24 bits.  An assembler ``dw`` only
allocates two bytes; it does not change the instruction width.  This module
finds the high-confidence form of that defect while retaining an inventory of
indirect and unresolved accesses for human review.  It also catches the
high-confidence address form in which ``MLT rr`` leaves a stale upper byte and
the 16-bit product is then consumed by an unsuffixed 24-bit ``ADD HL,rr``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


WIDE_REGISTERS = frozenset({"bc", "de", "hl", "ix", "iy", "sp"})
SAFE_ANNOTATION = "ADL24 OK:"

_LABEL_RE = re.compile(r"^\s*([@A-Za-z_.$?][@\w.$?]*):\s*(.*)$")
_MACRO_RE = re.compile(r"^\s*macro\s+([A-Za-z_.$?][\w.$?]*)\b", re.I)
_ENDMACRO_RE = re.compile(r"^\s*endmacro\b", re.I)
_ASSUME_RE = re.compile(r"^\s*\.?assume\s+adl\s*=\s*([01])\b", re.I)
_DATA_RE = re.compile(
    r"^\s*\.?(dw24|dw32|defb|defw|ascii|asciz|byte|word|"
    r"blkb|blkw|blkp|blkl|defs|db|dw|dl|ds)\b\s+(.+?)\s*$",
    re.I,
)
_LD_RE = re.compile(
    r"^\s*ld(?:\.(sis|sil|lis|lil|s|l|is|il))?\s+(.+?)\s*,\s*(.+?)\s*$",
    re.I,
)
_SYMBOL_RE = re.compile(r"^\s*([@A-Za-z_.$?][@\w.$?]*)")
_REGISTER_RE = re.compile(r"\b(?:af|bc|de|hl|ix|iy|sp)\b", re.I)
_ANNOTATION_RE = re.compile(r"\bADL24\s+OK:\s+\S", re.I)
_INCLUDE_RE = re.compile(r'^\s*\.?include\s+["\']([^"\']+)["\']', re.I)
_MLT_RE = re.compile(r"^\s*mlt\s+(bc|de|hl|sp)\s*$", re.I)
_ADD_HL_RE = re.compile(
    r"^\s*add(?:\.(sis|sil|lis|lil|s|l|is|il))?\s+hl\s*,\s*(bc|de|hl|sp)\s*$",
    re.I,
)
_PAIR_LOAD_RE = re.compile(
    r"^\s*ld(?:\.(sis|sil|lis|lil|s|l|is|il))?\s+"
    r"(bc|de|hl|sp)\s*,\s*([^,]+?)\s*$",
    re.I,
)
_SHORT_PAIR_OP_RE = re.compile(
    r"^\s*(?:inc|dec)\.(?:sis|sil|s|is|il)\s+(bc|de|hl|sp)\s*$",
    re.I,
)
_CONTROL_FLOW_RE = re.compile(r"^\s*(?:call|rst|ret|reti|retn)\b", re.I)
_EXCHANGE_RE = re.compile(r"^\s*ex\s+", re.I)


@dataclass(frozen=True)
class Storage:
    """A statically declared assembly storage location."""

    path: Path
    line: int
    scope: str
    label: str
    directive: str
    units: int | None


@dataclass(frozen=True)
class Access:
    """One wide-register memory transfer and its audit classification."""

    path: Path
    line: int
    source: str
    direction: str
    register: str
    data_bits: int
    expression: str
    classification: str
    storage: Storage | None = None
    annotated: bool = False

    @property
    def is_hazard(self) -> bool:
        return self.classification in {
            "word-overrun",
            "upper-byte-address",
        } and not self.annotated

    @property
    def needs_review(self) -> bool:
        return (
            self.classification in {"indirect", "unresolved"}
            and not self.annotated
        )


@dataclass(frozen=True)
class AuditResult:
    """Complete audit inventory for a set of source paths."""

    accesses: tuple[Access, ...]

    @property
    def hazards(self) -> tuple[Access, ...]:
        return tuple(access for access in self.accesses if access.is_hazard)

    @property
    def review_items(self) -> tuple[Access, ...]:
        return tuple(access for access in self.accesses if access.needs_review)


@dataclass
class _ParsedFile:
    path: Path
    lines: list[str]
    scopes: list[str]
    adl_modes: list[int]
    storages: dict[tuple[str, str], Storage]
    global_storages: dict[str, Storage]


def _strip_comment(line: str) -> tuple[str, str]:
    source, separator, comment = line.partition(";")
    return source.rstrip(), comment.strip() if separator else ""


def _count_values(operands: str) -> int:
    """Count comma-separated assembler values without splitting strings."""

    count = 1
    quote: str | None = None
    escaped = False
    for character in operands:
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote is not None:
            escaped = True
            continue
        if character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
            continue
        if character == "," and quote is None:
            count += 1
    return count


def _parse_integer(value: str) -> int | None:
    token = value.strip().lower().replace("_", "")
    try:
        if token.startswith("$"):
            return int(token[1:], 16)
        if token.endswith("h") and token[:-1]:
            return int(token[:-1], 16)
        return int(token, 0)
    except ValueError:
        return None


def _normalize_directive(directive: str) -> str:
    aliases = {
        "defb": "db",
        "ascii": "db",
        "asciz": "db",
        "byte": "db",
        "defw": "dw",
        "word": "dw",
        "dw24": "dl",
        "defs": "ds",
    }
    lowered = directive.lower()
    return aliases.get(lowered, lowered)


def _parse_file(path: Path, default_adl: int) -> _ParsedFile:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scope = f"file:{path}"
    saved_scopes: list[str] = []
    pending_labels: list[tuple[str, str, int]] = []
    adl_mode = default_adl
    scopes: list[str] = []
    adl_modes: list[int] = []
    storages: dict[tuple[str, str], Storage] = {}
    global_storages: dict[str, Storage] = {}

    for line_number, original in enumerate(lines, 1):
        source, _ = _strip_comment(original)
        assume = _ASSUME_RE.match(source)
        if assume:
            adl_mode = int(assume.group(1))

        macro = _MACRO_RE.match(source)
        if macro:
            saved_scopes.append(scope)
            scope = f"macro:{macro.group(1)}"
            pending_labels.clear()
        elif _ENDMACRO_RE.match(source):
            pending_labels.clear()
            scope = saved_scopes.pop() if saved_scopes else f"file:{path}"

        remainder = source
        labels_on_line: list[tuple[str, str, int]] = []
        while True:
            label_match = _LABEL_RE.match(remainder)
            if not label_match:
                break
            label = label_match.group(1)
            if not label.startswith("@"):
                scope = label
            labels_on_line.append((scope, label, line_number))
            remainder = label_match.group(2)
            if not remainder:
                break

        scopes.append(scope)
        adl_modes.append(adl_mode)

        declarations = pending_labels + labels_on_line
        data = _DATA_RE.match(remainder)
        if data and declarations:
            raw_directive = data.group(1).lower()
            directive = _normalize_directive(raw_directive)
            operands = data.group(2)
            if directive in {"ds", "blkb", "blkw", "blkp", "blkl"}:
                units = _parse_integer(operands.split(",", 1)[0])
            else:
                units = _count_values(operands)
            for declaration_scope, label, declaration_line in declarations:
                storage = Storage(
                    path=path,
                    line=declaration_line,
                    scope=declaration_scope,
                    label=label,
                    directive=directive,
                    units=units,
                )
                storages[(declaration_scope, label)] = storage
                if not label.startswith("@"):
                    global_storages[label] = storage
            pending_labels.clear()
        elif labels_on_line and not remainder.strip():
            pending_labels.extend(labels_on_line)
        elif remainder.strip():
            pending_labels.clear()

    return _ParsedFile(
        path=path,
        lines=lines,
        scopes=scopes,
        adl_modes=adl_modes,
        storages=storages,
        global_storages=global_storages,
    )


def _data_bits(suffix: str | None, adl_mode: int) -> int:
    if suffix is None:
        return 24 if adl_mode else 16
    suffix = suffix.lower()
    if suffix.startswith("s"):
        return 16
    if suffix.startswith("l"):
        return 24
    # In ADL mode .is/.il are aliases for .lis/.lil; both retain a long
    # data block.  In Z80 mode they are aliases for .sis/.sil.
    return 24 if adl_mode else 16


def _memory_expression(operand: str) -> str | None:
    operand = operand.strip()
    if len(operand) >= 3 and operand.startswith("(") and operand.endswith(")"):
        return operand[1:-1].strip()
    return None


def _resolve_storage(
    parsed: _ParsedFile,
    scope: str,
    expression: str,
    global_index: dict[str, tuple[Storage, ...]],
) -> Storage | None:
    symbol_match = _SYMBOL_RE.match(expression)
    if not symbol_match:
        return None
    symbol = symbol_match.group(1)
    if symbol.startswith("@"):
        return parsed.storages.get((scope, symbol))
    local = parsed.global_storages.get(symbol)
    if local is not None:
        return local
    candidates = global_index.get(symbol, ())
    return candidates[0] if len(candidates) == 1 else None


def _classify_storage(storage: Storage | None) -> str:
    if storage is None:
        return "unresolved"
    if storage.directive == "dw":
        # A label on DW denotes a 16-bit field even when more DW values follow.
        return "word-overrun"
    if storage.directive == "db" and (storage.units is None or storage.units < 3):
        return "word-overrun"
    if storage.directive == "dl":
        return "24-bit-storage"
    unit_bytes = {
        "ds": 1,
        "blkb": 1,
        "blkw": 2,
        "blkp": 3,
        "blkl": 4,
        "dw32": 4,
    }.get(storage.directive)
    if (
        unit_bytes is not None
        and storage.units is not None
        and unit_bytes * storage.units >= 3
    ):
        return "reserved-storage"
    return "byte-storage"


def audit_paths(paths: Iterable[Path], *, default_adl: int = 1) -> AuditResult:
    """Audit assembly paths, returning every wide-register memory access.

    The high-confidence error is a 24-bit data transfer whose named target is
    declared with ``dw`` (or fewer than three ``db`` values).  Register-
    indirect and macro-parameter targets remain explicit review items because
    their pointee width cannot be proven statically.
    """

    accesses: list[Access] = []
    parsed_files = [
        _parse_file(Path(candidate), default_adl) for candidate in paths
    ]
    mutable_global_index: dict[str, list[Storage]] = {}
    for parsed in parsed_files:
        for label, storage in parsed.global_storages.items():
            mutable_global_index.setdefault(label, []).append(storage)
    global_index = {
        label: tuple(storages)
        for label, storages in mutable_global_index.items()
    }

    for parsed in parsed_files:
        path = parsed.path
        for index, original in enumerate(parsed.lines):
            source, comment = _strip_comment(original)
            match = _LD_RE.match(source)
            if not match:
                continue
            suffix, destination, origin = match.groups()
            destination_memory = _memory_expression(destination)
            origin_memory = _memory_expression(origin)
            destination_register = destination.strip().lower()
            origin_register = origin.strip().lower()
            if destination_memory is not None and origin_register in WIDE_REGISTERS:
                direction = "store"
                register = origin_register
                expression = destination_memory
            elif origin_memory is not None and destination_register in WIDE_REGISTERS:
                direction = "load"
                register = destination_register
                expression = origin_memory
            else:
                continue

            bits = _data_bits(suffix, parsed.adl_modes[index])
            annotated = _ANNOTATION_RE.search(comment) is not None
            if bits == 16:
                classification = "explicit-16-bit"
                storage = _resolve_storage(
                    parsed, parsed.scopes[index], expression, global_index
                )
            elif _REGISTER_RE.search(expression):
                classification = "indirect"
                storage = None
            else:
                storage = _resolve_storage(
                    parsed, parsed.scopes[index], expression, global_index
                )
                classification = _classify_storage(storage)
            accesses.append(
                Access(
                    path=path,
                    line=index + 1,
                    source=original.rstrip(),
                    direction=direction,
                    register=register,
                    data_bits=bits,
                    expression=expression,
                    classification=classification,
                    storage=storage,
                    annotated=annotated,
                )
            )

        # MLT writes only the low 16 bits of its register pair.  In ADL mode,
        # a later unsuffixed ADD HL,rr consumes all 24 bits.  Track only this
        # straight-line, high-confidence form: it caught the family-plan table
        # bug without pretending to be a complete control-flow analyser.
        upper_zero = {register: False for register in ("bc", "de", "hl", "sp")}
        mlt_product = {register: False for register in upper_zero}
        current_scope = None
        for index, original in enumerate(parsed.lines):
            source, comment = _strip_comment(original)
            scope = parsed.scopes[index]
            if scope != current_scope and not scope.startswith("macro:"):
                upper_zero = {register: False for register in upper_zero}
                mlt_product = {register: False for register in mlt_product}
                current_scope = scope

            remainder = source
            while True:
                label = _LABEL_RE.match(remainder)
                if not label:
                    break
                remainder = label.group(2)
                if not remainder:
                    break

            pair_load = _PAIR_LOAD_RE.match(remainder)
            if pair_load:
                suffix, register, operand = pair_load.groups()
                register = register.lower()
                bits = _data_bits(suffix, parsed.adl_modes[index])
                immediate = _parse_integer(operand)
                upper_zero[register] = (
                    bits == 24 and immediate is not None and 0 <= immediate <= 0xFFFF
                )
                mlt_product[register] = False
                continue

            mlt = _MLT_RE.match(remainder)
            if mlt:
                register = mlt.group(1).lower()
                mlt_product[register] = True
                continue

            # The established Agon normalization idiom uses a short pair
            # INC/DEC to zero-extend the retained 16-bit value.
            short_pair = _SHORT_PAIR_OP_RE.match(remainder)
            if short_pair:
                upper_zero[short_pair.group(1).lower()] = True
                continue

            add = _ADD_HL_RE.match(remainder)
            if add:
                suffix, register = add.groups()
                register = register.lower()
                bits = _data_bits(suffix, parsed.adl_modes[index])
                if bits == 24 and mlt_product[register] and not upper_zero[register]:
                    accesses.append(
                        Access(
                            path=path,
                            line=index + 1,
                            source=original.rstrip(),
                            direction="address-arithmetic",
                            register=register,
                            data_bits=24,
                            expression=f"{register.upper()}U retained by MLT",
                            classification="upper-byte-address",
                            annotated=_ANNOTATION_RE.search(comment) is not None,
                        )
                    )
                continue

            if _CONTROL_FLOW_RE.match(remainder) or _EXCHANGE_RE.match(remainder):
                upper_zero = {register: False for register in upper_zero}
                mlt_product = {register: False for register in mlt_product}
    return AuditResult(tuple(accesses))


def assembly_paths(roots: Iterable[Path]) -> tuple[Path, ...]:
    """Expand files/directories to a sorted assembly-source list."""

    paths: set[Path] = set()
    for candidate in roots:
        root = Path(candidate)
        if root.is_file():
            paths.add(root)
        elif root.is_dir():
            paths.update(root.rglob("*.asm"))
            paths.update(root.rglob("*.inc"))
            paths.update(root.rglob("*.s"))
    return tuple(sorted(paths))


def include_closure(entries: Iterable[Path]) -> tuple[Path, ...]:
    """Return entry files and all recursively quoted assembly includes."""

    pending = [Path(entry).resolve() for entry in entries]
    paths: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in paths:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        paths.add(path)
        for original in path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            source, _ = _strip_comment(original)
            include = _INCLUDE_RE.match(source)
            if include:
                pending.append((path.parent / include.group(1)).resolve())
    return tuple(sorted(paths))
