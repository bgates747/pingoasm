#!/usr/bin/env python3
"""Build private CRC1 control and register-resident CRC2 scratch artifacts.

The shared loader already contains hash-pinned legacy, register, and nibble
implementations. This builder leaves it unchanged, selects policy 1 in a
temporary source to reproduce the historical control, then selects policy 2,
audits the complete ADL include closure, and emits only ignored evidence.
Canonical fixture artifacts are never inputs or outputs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping, Sequence
import zlib


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
ACCEPTED_SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-survey.asm"
ACCEPTED_LOADER = ROOT / "fixtures/p3dm-loader-probe/src/p3dm-loader.inc"
ACCEPTED_TARGET = ROOT / "fixtures/terrain-manager-regular-lod-survey/tgt"
ACCEPTED_PROGRAM = ACCEPTED_TARGET / "terrain-manager-regular-lod-survey.bin"
ACCEPTED_LISTING = ACCEPTED_TARGET / "terrain-manager-regular-lod-survey.lst"
ACCEPTED_SYMBOLS = ACCEPTED_TARGET / "terrain-manager-regular-lod-survey.symbols"
ACCEPTED_RUNTIME_INCLUDE = ACCEPTED_TARGET / "regular-lod-runtime.inc"
ACCEPTED_TRANSITION_INCLUDE = ACCEPTED_TARGET / "regular-lod-transitions.inc"
RUNTIME_FIXTURE = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
MANAGER_MANIFEST = RUNTIME_FIXTURE / "MANAGER.json"

DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-crc-register-sibling-build-v4"
)
PROGRAM_STEM = "terrain-manager-regular-lod-crc-register-sibling"
CONTROL_PROGRAM_STEM = "terrain-manager-regular-lod-crc-legacy-control"
LEGACY_CONTROL_PROGRAM_BYTES = 142_763
LEGACY_CONTROL_LISTING_BYTES = 2_304_719
LEGACY_CONTROL_SYMBOLS_BYTES = 66_112
LEGACY_CONTROL_LISTING_SHA256 = (
    "4951950b4f80c56a96c46246c56e1f314e5eae070600ddc9fce0111073439696"
)
LEGACY_CONTROL_SYMBOLS_SHA256 = (
    "b1a9d5e35560df89c556f276b0910c6abf687416f0292d99882d891b46b07262"
)
PROGRAM_LOAD_ADDRESS = 0x040000
PROGRAM_LIMIT_EXCLUSIVE = 0x070000
LAUNCHER_LOAD_ADDRESS = 0x0B0000
P3DM_DATA_OFFSET = 100
P3DM_DESC_CRC32 = 88
P3DM_BUFFER_BYTES = 16_384
EXPECTED_RECORDS = 227
EXPECTED_CONTAINER_BYTES = 787_192
EXPECTED_DATA_BYTES = 764_288
EXPECTED_MAXIMUM_RECORD_BYTES = 4_568
EXPECTED_LEVEL_COUNTS = {"fine": 91, "L1": 11, "L2": 21, "L4": 6, "L8": 98}
EXPECTED_MANAGER_SCHEMA = "pingo-terrain-regular-lod-manager-survey-v2"
EXPECTED_VECTOR_DIGEST_SHA256 = (
    "a438970c746b6c3d26c3bf636a22312744d9ec4c9152f7185ef3bf540561d12e"
)
EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256 = (
    "07be70d9f4f44a79a96e8e740b57b8d8d572561e0595b2fa7622770e1d206671"
)
RESOURCE_NAMES = ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
SCHEMA = "pingo-terrain-regular-lod-crc-register-sibling-build-v1"
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"

ACCEPTED_SOURCE_SHA256 = (
    "760a657db1b16b88c6c8921821f59bfc5ca6a14e56896409db4a6065b351d1fe"
)
ACCEPTED_LOADER_SHA256 = (
    "15215e21d0bb3a3277fa31e9a73d9beae341b3495e2a0a281fc200131472ddc3"
)
ACCEPTED_PROGRAM_SHA256 = (
    "27f09db1eb0b0eec702aad5c17f35e68922f154a6c3391370d07a76027cc57bf"
)
ACCEPTED_LISTING_SHA256 = (
    "0e5dd69b08af467b04b3b73f50ad4a6599caaebfd66fc0a344a7111e819f2eb3"
)
ACCEPTED_SYMBOLS_SHA256 = (
    "e4339e00adfdbd16969a6c77a76a77b00b4534ff3c572cf67395269d470670ce"
)
ACCEPTED_RUNTIME_INCLUDE_SHA256 = (
    "22607a410cb2c3ef3506d30d542a7eb7a14160bec8c73bd68a6abb33f204aff4"
)
ACCEPTED_TRANSITION_INCLUDE_SHA256 = (
    "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749"
)
CANONICAL_CRC_BLOCK_SHA256 = (
    "039b9335f59a1d5b29639a10c835b1ed2ac803a5fb0f6cc419666880706ca3c7"
)
# Filled from the literal below and deliberately checked before every build.
CANDIDATE_CRC_BLOCK_SHA256 = (
    "228a6951cff061f3176803bea3332d46bcfbbfe65cf9ee6c2e9528df1967486b"
)


CRC_START = "p3dm_validate_crc32:\n"
CRC_LEGACY_START = (
    ".if p3dm_crc_policy - p3dm_crc_policy_legacy\n"
    ".else\n"
    + CRC_START
)
CRC_LEGACY_END = (
    ".endif\n\n"
    ".if p3dm_crc_policy - p3dm_crc_policy_register"
)
CRC_POLICY_NIBBLE_DECLARATION = "p3dm_crc_policy: equ 4\n"
CRC_POLICY_LEGACY_DECLARATION = "p3dm_crc_policy: equ 1\n"
CRC_POLICY_REGISTER_DECLARATION = "p3dm_crc_policy: equ 2\n"

CANDIDATE_CRC_BLOCK = """p3dm_validate_crc32:
    ld de,0FFFFh
    ld hl,0FFFFh
    ld ix,p3dm_file_buffer+p3dm_data_offset
    P3DM_LD_U16_BC p3dm_data_size
@byte:
    ld a,b
    or c
    jr z,@finish
    push bc
    ld a,(ix)
    inc ix
    xor l
    ld l,a
    ld b,8
@bit:
    srl d
    rr e
    rr h
    rr l
    jr nc,@no_polynomial
    ld a,l
    xor 020h
    ld l,a
    ld a,h
    xor 083h
    ld h,a
    ld a,e
    xor 0B8h
    ld e,a
    ld a,d
    xor 0EDh
    ld d,a
@no_polynomial:
    djnz @bit
    pop bc
    dec bc
    jr @byte
@finish:
    ld a,l
    cpl
    ld l,a
    ld (p3dm_crc_value+0),a
    ld a,h
    cpl
    ld h,a
    ld (p3dm_crc_value+1),a
    ld a,e
    cpl
    ld e,a
    ld (p3dm_crc_value+2),a
    ld a,d
    cpl
    ld d,a
    ld (p3dm_crc_value+3),a
    ld a,(p3dm_file_buffer+p3dm_desc_crc32+0)
    cp l
    jp nz,p3dm_bad_crc32
    ld a,(p3dm_file_buffer+p3dm_desc_crc32+1)
    cp h
    jp nz,p3dm_bad_crc32
    ld a,(p3dm_file_buffer+p3dm_desc_crc32+2)
    cp e
    jp nz,p3dm_bad_crc32
    ld a,(p3dm_file_buffer+p3dm_desc_crc32+3)
    cp d
    jp nz,p3dm_bad_crc32
    xor a
    ret
"""


class CrcSiblingBuildError(RuntimeError):
    """A canonical-source, CRC, ADL, memory, or corpus gate failed."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, key: str | None = None) -> dict[str, object]:
    resolved = path.resolve()
    if key is None:
        try:
            key = str(resolved.relative_to(ROOT))
        except ValueError:
            key = resolved.name
    return {
        "key": key,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def validate_legacy_control_artifacts(
    build: Path,
    receipt: Mapping[str, object] | None = None,
) -> tuple[Path, Path, Path]:
    """Resolve one receipt-bound CRC1 program/listing/symbol set."""

    build = build.expanduser().resolve()
    if receipt is None:
        receipt_path = build / "BUILD.json"
        try:
            loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CrcSiblingBuildError(
                f"legacy-control receipt is unreadable: {receipt_path}"
            ) from error
        if not isinstance(loaded, dict):
            raise CrcSiblingBuildError("legacy-control receipt root is not an object")
        receipt = loaded
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CrcSiblingBuildError("legacy-control receipt omits artifacts")
    specifications = (
        (
            "legacy_control_program",
            build / f"{CONTROL_PROGRAM_STEM}.bin",
            LEGACY_CONTROL_PROGRAM_BYTES,
            ACCEPTED_PROGRAM_SHA256,
        ),
        (
            "legacy_control_listing",
            build / f"{CONTROL_PROGRAM_STEM}.lst",
            LEGACY_CONTROL_LISTING_BYTES,
            LEGACY_CONTROL_LISTING_SHA256,
        ),
        (
            "legacy_control_symbols",
            build / f"{CONTROL_PROGRAM_STEM}.symbols",
            LEGACY_CONTROL_SYMBOLS_BYTES,
            LEGACY_CONTROL_SYMBOLS_SHA256,
        ),
    )
    paths = []
    for name, path, expected_bytes, expected_sha256 in specifications:
        if path.is_symlink() or not path.is_file():
            raise CrcSiblingBuildError(f"legacy-control artifact is absent: {path}")
        actual = artifact(path, key=f"artifacts/{path.name}")
        expected = {
            "key": f"artifacts/{path.name}",
            "bytes": expected_bytes,
            "sha256": expected_sha256,
        }
        if actual != expected or artifacts.get(name) != expected:
            raise CrcSiblingBuildError(
                f"legacy-control {name} identity/receipt binding changed"
            )
        paths.append(path)
    return paths[0], paths[1], paths[2]


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CrcSiblingBuildError(f"refusing to replace symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def atomic_json(path: Path, document: Mapping[str, object]) -> None:
    atomic_bytes(
        path,
        (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def run(command: Sequence[object], *, cwd: Path) -> str:
    rendered = tuple(str(part) for part in command)
    completed = subprocess.run(
        rendered,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise CrcSiblingBuildError(
            f"command failed ({completed.returncode}): {' '.join(rendered)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def require_sha256(path: Path, expected: str, description: str) -> None:
    if not path.is_file():
        raise CrcSiblingBuildError(f"missing {description}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise CrcSiblingBuildError(
            f"{description} changed: {actual} != {expected}"
        )


def extract_crc_block(loader: str) -> str:
    if loader.count(CRC_LEGACY_START) != 1:
        raise CrcSiblingBuildError("canonical CRC block markers changed")
    _prefix, rest = loader.split(CRC_LEGACY_START, 1)
    if rest.count(CRC_LEGACY_END) != 1:
        raise CrcSiblingBuildError("canonical CRC block end marker changed")
    body, _suffix = rest.split(CRC_LEGACY_END, 1)
    block = CRC_START + body
    if sha256_bytes(block.encode("utf-8")) != CANONICAL_CRC_BLOCK_SHA256:
        raise CrcSiblingBuildError("canonical CRC block hash changed")
    return block


def integrated_policy_witness(
    loader: str,
    candidate_block: str,
    candidate_hash: str,
    policy: int,
) -> dict[str, object]:
    """Prove both qualified literals already coexist in the shared loader."""

    canonical = extract_crc_block(loader)
    actual_candidate_hash = sha256_bytes(candidate_block.encode("utf-8"))
    if actual_candidate_hash != candidate_hash:
        raise CrcSiblingBuildError("integrated candidate CRC block hash changed")
    if loader.count(canonical) != 1 or loader.count(candidate_block) != 1:
        raise CrcSiblingBuildError("integrated CRC policy blocks are not unique")
    return {
        "replacement_count": 0,
        "canonical_block_bytes": len(canonical.encode("utf-8")),
        "canonical_block_sha256": CANONICAL_CRC_BLOCK_SHA256,
        "candidate_block_bytes": len(candidate_block.encode("utf-8")),
        "candidate_block_sha256": actual_candidate_hash,
        "canonical_loader_sha256": sha256_bytes(loader.encode("utf-8")),
        "candidate_loader_sha256": sha256_bytes(loader.encode("utf-8")),
        "integrated_policy_selection": policy,
        "integrated_blocks_unique": True,
        "loader_unmodified": True,
    }


def _relative_symlink(destination: Path, source: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def stage_source_mirror(root: Path) -> tuple[Path, Path]:
    """Create the minimum include-compatible mirror entirely below ``root``."""

    mirror_source = root / "fixtures/terrain-manager-survey/src"
    mirror_source.mkdir(parents=True)
    source = mirror_source / f"{PROGRAM_STEM}.asm"
    source.write_bytes(ACCEPTED_SOURCE.read_bytes())
    for item in SOURCE_DIRECTORY.iterdir():
        if item.name == ACCEPTED_SOURCE.name or item.suffix.lower() in {
            ".bin",
            ".lst",
            ".symbols",
        }:
            continue
        _relative_symlink(mirror_source / item.name, item)

    loader = root / "fixtures/p3dm-loader-probe/src/p3dm-loader.inc"
    loader.parent.mkdir(parents=True)
    loader.write_bytes(ACCEPTED_LOADER.read_bytes())
    fixtures = root / "fixtures"
    for name in (
        "_common",
        "berkeley-flight-triangular-dither",
        "berkeley-flight-fdm",
        "koak-flight-streamed",
        "terrain-manager-regular-lod-survey",
    ):
        _relative_symlink(fixtures / name, ROOT / "fixtures" / name)
    _relative_symlink(root / "build", ROOT / "build")
    _relative_symlink(root / "runtime", ROOT / "runtime")
    return source, loader


def select_crc_policy_source(source: Path, current: int, selected: int) -> bytes:
    """Change only the non-emitting caller policy in one scratch source."""

    text = source.read_text(encoding="ascii")
    declarations = {
        1: CRC_POLICY_LEGACY_DECLARATION,
        2: CRC_POLICY_REGISTER_DECLARATION,
        4: CRC_POLICY_NIBBLE_DECLARATION,
    }
    try:
        before = declarations[current]
        after = declarations[selected]
    except KeyError as error:
        raise CrcSiblingBuildError("unsupported scratch CRC policy") from error
    if text.count(before) != 1:
        raise CrcSiblingBuildError("scratch top-level CRC policy changed")
    changed = text.replace(before, after, 1)
    source.write_text(changed, encoding="ascii")
    return changed.encode("ascii")


def select_legacy_control_source(source: Path) -> bytes:
    return select_crc_policy_source(source, 4, 1)


def assemble_in_mirror(source: Path) -> tuple[bytes, bytes, bytes]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise CrcSiblingBuildError("ez80asm is not available on PATH")
    generated_program = source.with_suffix(".BIN")
    generated_listing = source.with_suffix(".lst")
    generated_symbols = source.with_suffix(".symbols")
    run(
        (assembler, "-l", "-s", source.name, generated_program.name, "-c"),
        cwd=source.parent,
    )
    missing = [
        path for path in (generated_program, generated_listing, generated_symbols)
        if not path.is_file()
    ]
    if missing:
        raise CrcSiblingBuildError(f"ez80asm omitted artifacts: {missing}")
    return (
        generated_program.read_bytes(),
        generated_listing.read_bytes(),
        generated_symbols.read_bytes(),
    )


def audit_candidate(source: Path) -> str:
    return run(
        (
            sys.executable,
            ROOT / "scripts/audit_adl_width.py",
            "--follow-includes",
            "--show-review",
            "--fail-review",
            source,
        ),
        cwd=source.parent,
    ).strip()


def build_program(
    output: Path,
) -> tuple[Path, Path, Path, Path, Path, Path, dict[str, object], str]:
    require_sha256(ACCEPTED_SOURCE, ACCEPTED_SOURCE_SHA256, "accepted source")
    require_sha256(ACCEPTED_LOADER, ACCEPTED_LOADER_SHA256, "accepted loader")
    require_sha256(
        ACCEPTED_RUNTIME_INCLUDE,
        ACCEPTED_RUNTIME_INCLUDE_SHA256,
        "accepted runtime include",
    )
    require_sha256(
        ACCEPTED_TRANSITION_INCLUDE,
        ACCEPTED_TRANSITION_INCLUDE_SHA256,
        "accepted transition include",
    )
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="regular-crc-register-build-") as name:
        source, loader = stage_source_mirror(Path(name))
        legacy_source = select_legacy_control_source(source)
        control_program, control_listing, control_symbols = assemble_in_mirror(source)
        control_hash = sha256_bytes(control_program)
        if control_hash != ACCEPTED_PROGRAM_SHA256:
            raise CrcSiblingBuildError(
                f"temporary control does not reproduce accepted program: "
                f"{control_hash} != {ACCEPTED_PROGRAM_SHA256}"
            )
        canonical_loader = loader.read_text(encoding="utf-8")
        source_patch = integrated_policy_witness(
            canonical_loader,
            CANDIDATE_CRC_BLOCK,
            CANDIDATE_CRC_BLOCK_SHA256,
            2,
        )
        register_source = select_crc_policy_source(source, 1, 2)
        if source.read_bytes() != register_source:
            raise CrcSiblingBuildError("temporary register-policy source changed")
        if loader.read_text(encoding="utf-8") != canonical_loader:
            raise CrcSiblingBuildError("temporary integrated loader changed")
        audit = audit_candidate(source)
        program_bytes, listing_bytes, symbol_bytes = assemble_in_mirror(source)

    program = output / f"{PROGRAM_STEM}.bin"
    listing = output / f"{PROGRAM_STEM}.lst"
    symbols = output / f"{PROGRAM_STEM}.symbols"
    legacy_program = output / f"{CONTROL_PROGRAM_STEM}.bin"
    legacy_listing = output / f"{CONTROL_PROGRAM_STEM}.lst"
    legacy_symbols = output / f"{CONTROL_PROGRAM_STEM}.symbols"
    atomic_bytes(program, program_bytes)
    atomic_bytes(listing, listing_bytes)
    atomic_bytes(symbols, symbol_bytes)
    atomic_bytes(legacy_program, control_program)
    atomic_bytes(legacy_listing, control_listing)
    atomic_bytes(legacy_symbols, control_symbols)
    source_patch.update(
        {
            "accepted_source_sha256": ACCEPTED_SOURCE_SHA256,
            "temporary_top_level_source_exact_except_crc_policy": True,
            "temporary_control_crc_policy": "legacy-memory-bitwise",
            "temporary_candidate_crc_policy": "register-held-bitwise",
            "temporary_control_program_sha256": control_hash,
            "temporary_control_program_exact": True,
            "accepted_files_modified": False,
        }
    )
    return (
        program,
        listing,
        symbols,
        legacy_program,
        legacy_listing,
        legacy_symbols,
        source_patch,
        audit,
    )


SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")


def parse_symbols(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if match is not None:
            result.setdefault(match.group(1), int(match.group(2), 16))
    return result


def validate_memory(program: Path, symbols_path: Path) -> dict[str, object]:
    payload = program.read_bytes()
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise CrcSiblingBuildError("sibling lost common entry/header")
    symbols = parse_symbols(symbols_path)
    required = {
        "filedata",
        "p3dm_validate_container",
        "p3dm_retain_descriptor",
        "p3dm_validate_crc32",
        "p3dm_mirror_validated_z",
        "p3dm_bad_crc32",
        "p3dm_return_error",
        "p3dm_crc_value",
        "p3dm_read_remaining",
        "p3dm_file_buffer",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise CrcSiblingBuildError(f"sibling symbols omit: {missing}")
    program_end = PROGRAM_LOAD_ADDRESS + len(payload)
    if symbols["filedata"] != program_end:
        raise CrcSiblingBuildError("sibling filedata/program end mismatch")
    if not PROGRAM_LOAD_ADDRESS < program_end < PROGRAM_LIMIT_EXCLUSIVE:
        raise CrcSiblingBuildError("sibling escapes fixture load window")
    if symbols["p3dm_validate_crc32"] != 0x0437C7:
        raise CrcSiblingBuildError("CRC entry moved before the isolated replacement")
    if symbols["p3dm_crc_value"] + 4 != symbols["p3dm_read_remaining"]:
        raise CrcSiblingBuildError("p3dm_crc_value is no longer an exact four-byte result")
    buffer_start = symbols["p3dm_file_buffer"]
    buffer_end = buffer_start + P3DM_BUFFER_BYTES
    if buffer_end > program_end or buffer_end >= PROGRAM_LIMIT_EXCLUSIVE:
        raise CrcSiblingBuildError("P3DM buffer escapes sibling program window")
    resources = []
    for name in RESOURCE_NAMES:
        path = RUNTIME_FIXTURE / name
        if not path.is_file():
            raise CrcSiblingBuildError(f"runtime resource is missing: {path}")
        resources.append(artifact(path))
    maximum_resource = max(int(item["bytes"]) for item in resources)
    staging_end = program_end + maximum_resource
    if not staging_end < PROGRAM_LIMIT_EXCLUSIVE < LAUNCHER_LOAD_ADDRESS:
        raise CrcSiblingBuildError("resource staging or launcher memory overlaps sibling")
    if not (
        symbols["p3dm_validate_container"]
        < symbols["p3dm_retain_descriptor"]
        < symbols["p3dm_validate_crc32"]
        < symbols["p3dm_mirror_validated_z"]
        < symbols["p3dm_bad_crc32"]
        <= symbols["p3dm_return_error"]
        < buffer_start
    ):
        raise CrcSiblingBuildError("validation/error/buffer symbol order changed")
    return {
        "program_load_address": PROGRAM_LOAD_ADDRESS,
        "program_end": program_end,
        "program_limit_exclusive": PROGRAM_LIMIT_EXCLUSIVE,
        "resource_staging_maximum_bytes": maximum_resource,
        "resource_staging_end": staging_end,
        "launcher_load_address": LAUNCHER_LOAD_ADDRESS,
        "p3dm_file_buffer": [buffer_start, buffer_end],
        "p3dm_crc_value": [symbols["p3dm_crc_value"], symbols["p3dm_read_remaining"]],
        "p3dm_validate_crc32": symbols["p3dm_validate_crc32"],
        "p3dm_validate_crc32_end": symbols["p3dm_mirror_validated_z"],
        "p3dm_bad_crc32": symbols["p3dm_bad_crc32"],
        "p3dm_return_error": symbols["p3dm_return_error"],
        "resources": resources,
    }


def register_crc32(payload: bytes | bytearray | memoryview) -> int:
    """Model the exact L/H/E/D reflected ISO-HDLC candidate."""

    l = h = e = d = 0xFF
    for byte in payload:
        l ^= int(byte)
        for _bit in range(8):
            carry = l & 1
            l = ((h & 1) << 7) | (l >> 1)
            h = ((e & 1) << 7) | (h >> 1)
            e = ((d & 1) << 7) | (e >> 1)
            d >>= 1
            if carry:
                l ^= 0x20
                h ^= 0x83
                e ^= 0xB8
                d ^= 0xED
    return (
        ((~l) & 0xFF)
        | (((~h) & 0xFF) << 8)
        | (((~e) & 0xFF) << 16)
        | (((~d) & 0xFF) << 24)
    )


def deterministic_vectors() -> tuple[bytes, ...]:
    lengths = (
        0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 99, 100,
        127, 128, 255, 256, 257, 511, 512, 1_023, 1_024, 4_096,
        P3DM_BUFFER_BYTES - P3DM_DATA_OFFSET,
    )
    state = 0xC0DEC0DE
    generated: list[bytes] = []
    for length in lengths:
        value = bytearray()
        for _ in range(length):
            state ^= (state << 13) & 0xFFFFFFFF
            state ^= state >> 17
            state ^= (state << 5) & 0xFFFFFFFF
            state &= 0xFFFFFFFF
            value.append(state & 0xFF)
        generated.append(bytes(value))
    return (
        b"",
        b"123456789",
        bytes(range(256)),
        bytes(range(255, -1, -1)),
        *generated,
    )


def validate_differential_vectors() -> dict[str, object]:
    vectors = deterministic_vectors()
    records = []
    for order, payload in enumerate(vectors):
        expected = zlib.crc32(payload) & 0xFFFFFFFF
        actual = register_crc32(payload)
        if actual != expected:
            raise CrcSiblingBuildError(
                f"register CRC differential failed for vector {order}: "
                f"{actual:08x} != {expected:08x}"
            )
        records.append(
            {
                "order": order,
                "bytes": len(payload),
                "payload_sha256": sha256_bytes(payload),
                "crc32": f"{actual:08x}",
            }
        )
    if register_crc32(b"123456789") != 0xCBF43926:
        raise CrcSiblingBuildError("ISO-HDLC check vector changed")
    digest = sha256_bytes(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    )
    if digest != EXPECTED_VECTOR_DIGEST_SHA256:
        raise CrcSiblingBuildError(
            f"deterministic CRC vector digest changed: {digest} != "
            f"{EXPECTED_VECTOR_DIGEST_SHA256}"
        )
    return {
        "algorithm": "CRC-32/ISO-HDLC reflected bitwise",
        "polynomial": "edb88320",
        "init": "ffffffff",
        "xorout": "ffffffff",
        "register_bytes_low_to_high": ["L", "H", "E", "D"],
        "count": len(records),
        "digest_sha256": digest,
        "vectors": records,
    }


def _uint(record: Mapping[str, object], name: str, order: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CrcSiblingBuildError(
            f"manifest record {order} has invalid {name}: {value!r}"
        )
    return value


def validate_corpus_crc(
    *,
    manifest_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    manifest_path = MANAGER_MANIFEST if manifest_path is None else manifest_path
    root = RUNTIME_FIXTURE if root is None else root
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CrcSiblingBuildError("manager manifest is absent or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrcSiblingBuildError("manager manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != EXPECTED_MANAGER_SCHEMA:
        raise CrcSiblingBuildError("manager manifest schema changed")
    records = manifest.get("initial_view", {}).get("records", ())
    if not isinstance(records, list) or len(records) != EXPECTED_RECORDS:
        raise CrcSiblingBuildError("manager manifest does not contain 227 records")
    coverage = []
    total_container = 0
    total_data = 0
    maximum = 0
    level_counts: Counter[str] = Counter()
    for order, record in enumerate(records):
        if not isinstance(record, dict) or record.get("order") != order:
            raise CrcSiblingBuildError(f"manifest record order changed at {order}")
        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            raise CrcSiblingBuildError(f"manifest record {order} has no path")
        path = root / relative
        payload = path.read_bytes()
        expected_file_hash = record.get("sha256")
        if sha256_bytes(payload) != expected_file_hash:
            raise CrcSiblingBuildError(f"record checksum changed: {relative}")
        file_bytes = _uint(record, "bytes", order)
        data_bytes = _uint(record, "data_bytes", order)
        if len(payload) != file_bytes or len(payload) < P3DM_DATA_OFFSET:
            raise CrcSiblingBuildError(f"record byte size changed: {relative}")
        encoded_data_bytes = int.from_bytes(payload[96:100], "little")
        if encoded_data_bytes != data_bytes:
            raise CrcSiblingBuildError(f"DATA size changed: {relative}")
        data = payload[P3DM_DATA_OFFSET : P3DM_DATA_OFFSET + data_bytes]
        if len(data) != data_bytes or not data:
            raise CrcSiblingBuildError(f"DATA payload missing: {relative}")
        stored = int.from_bytes(
            payload[P3DM_DESC_CRC32 : P3DM_DESC_CRC32 + 4], "little"
        )
        host = zlib.crc32(data) & 0xFFFFFFFF
        register = register_crc32(data)
        if stored != host or register != host:
            raise CrcSiblingBuildError(
                f"record CRC mismatch: {relative}: "
                f"stored={stored:08x} host={host:08x} register={register:08x}"
            )
        corruption_offset = (order * 257 + data_bytes // 2) % data_bytes
        corruption_mask = 1 << (order & 7)
        corrupted = bytearray(data)
        corrupted[corruption_offset] ^= corruption_mask
        corrupt_crc = register_crc32(corrupted)
        if corrupt_crc == stored:
            raise CrcSiblingBuildError(
                f"single-bit corruption escaped CRC: {relative}"
            )
        level = record.get("level")
        if not isinstance(level, str):
            raise CrcSiblingBuildError(f"record level missing: {relative}")
        level_counts[level] += 1
        total_container += file_bytes
        total_data += data_bytes
        maximum = max(maximum, file_bytes)
        coverage.append(
            {
                "order": order,
                "path": relative,
                "file_bytes": file_bytes,
                "file_sha256": expected_file_hash,
                "data_bytes": data_bytes,
                "stored_crc32": f"{stored:08x}",
                "register_crc32": f"{register:08x}",
                "negative_single_bit": {
                    "data_offset": corruption_offset,
                    "mask": corruption_mask,
                    "corrupt_crc32": f"{corrupt_crc:08x}",
                    "rejected": True,
                },
            }
        )
    aggregates = {
        "records": len(coverage),
        "container_bytes": total_container,
        "data_bytes": total_data,
        "maximum_record_bytes": maximum,
        "level_counts": dict(level_counts),
    }
    expected = {
        "records": EXPECTED_RECORDS,
        "container_bytes": EXPECTED_CONTAINER_BYTES,
        "data_bytes": EXPECTED_DATA_BYTES,
        "maximum_record_bytes": EXPECTED_MAXIMUM_RECORD_BYTES,
        "level_counts": EXPECTED_LEVEL_COUNTS,
    }
    if aggregates != expected:
        raise CrcSiblingBuildError(
            f"cold corpus aggregates changed: {aggregates} != {expected}"
        )
    digest = sha256_bytes(
        json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode()
    )
    if digest != EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256:
        raise CrcSiblingBuildError(
            f"cold corpus CRC coverage digest changed: {digest} != "
            f"{EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256}"
        )
    return {
        "qualified": True,
        "manager_semantics": {
            "schema": EXPECTED_MANAGER_SCHEMA,
            "selected_field": "initial_view.records",
            "records": EXPECTED_RECORDS,
            "application_context_not_bound": ["binary", "manager.loader_crc32"],
            "manifest_path_or_file_identity_receipted": False,
        },
        "aggregates": aggregates,
        "coverage_digest_sha256": digest,
        "all_stored_host_register_crcs_exact": True,
        "all_single_bit_corruptions_rejected": True,
        "records": coverage,
    }


def validate_instruction_contract() -> dict[str, object]:
    block = CANDIDATE_CRC_BLOCK
    required_order = (
        "ld de,0FFFFh",
        "ld hl,0FFFFh",
        "xor l",
        "srl d",
        "rr e",
        "rr h",
        "rr l",
        "xor 020h",
        "xor 083h",
        "xor 0B8h",
        "xor 0EDh",
        "ld (p3dm_crc_value+0),a",
        "ld (p3dm_crc_value+1),a",
        "ld (p3dm_crc_value+2),a",
        "ld (p3dm_crc_value+3),a",
        "ld a,(p3dm_file_buffer+p3dm_desc_crc32+0)",
        "ld a,(p3dm_file_buffer+p3dm_desc_crc32+1)",
        "ld a,(p3dm_file_buffer+p3dm_desc_crc32+2)",
        "ld a,(p3dm_file_buffer+p3dm_desc_crc32+3)",
        "xor a\n    ret",
    )
    positions = [block.index(item) for item in required_order]
    if positions != sorted(positions):
        raise CrcSiblingBuildError("candidate instruction/error order changed")
    if block.count("push bc") != 1 or block.count("pop bc") != 1:
        raise CrcSiblingBuildError("candidate byte counter preservation changed")
    if block.count("jp nz,p3dm_bad_crc32") != 4:
        raise CrcSiblingBuildError("candidate descriptor compare count changed")
    if "di" in block.split() or "ei" in block.split():
        raise CrcSiblingBuildError("candidate unexpectedly changes interrupt state")
    return {
        "crc_registers_low_to_high": ["L", "H", "E", "D"],
        "counter_push_pop_exact": True,
        "ix_operations": ["load DATA start", "read byte", "increment once per byte"],
        "final_crc_value_store_order": [0, 1, 2, 3],
        "descriptor_compare_order": [0, 1, 2, 3],
        "crc_failure_target": "p3dm_bad_crc32",
        "success_result": "A=0, Z=1",
        "interrupt_mask_unchanged": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise CrcSiblingBuildError(f"refusing to replace existing output: {output}")
    vectors = validate_differential_vectors()
    corpus = validate_corpus_crc()
    instruction_contract = validate_instruction_contract()
    (
        program,
        listing,
        symbols,
        legacy_program,
        legacy_listing,
        legacy_symbols,
        source_patch,
        audit,
    ) = build_program(output)
    memory = validate_memory(program, symbols)
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "scratch_sibling_only": True,
            "accepted_loader_modified": False,
            "accepted_source_modified": False,
            "accepted_binary_modified": False,
            "accepted_sidecars_modified": False,
            "launcher_modified": False,
        },
        "artifacts": {
            "program": artifact(program, key=f"artifacts/{program.name}"),
            "listing": artifact(listing, key=f"artifacts/{listing.name}"),
            "symbols": artifact(symbols, key=f"artifacts/{symbols.name}"),
            "legacy_control_program": artifact(
                legacy_program, key=f"artifacts/{legacy_program.name}"
            ),
            "legacy_control_listing": artifact(
                legacy_listing, key=f"artifacts/{legacy_listing.name}"
            ),
            "legacy_control_symbols": artifact(
                legacy_symbols, key=f"artifacts/{legacy_symbols.name}"
            ),
        },
        "accepted_inputs": {
            "source": artifact(ACCEPTED_SOURCE),
            "loader": artifact(ACCEPTED_LOADER),
            "runtime_include": artifact(ACCEPTED_RUNTIME_INCLUDE),
            "transition_include": artifact(ACCEPTED_TRANSITION_INCLUDE),
        },
        "source_patch": source_patch,
        "instruction_contract": instruction_contract,
        "adl_audit": {
            "command_succeeded": True,
            "follow_includes": True,
            "fail_review": True,
            "output": audit,
        },
        "memory": memory,
        "host_differential": vectors,
        "cold_corpus_crc": corpus,
    }
    receipt = output / "BUILD.json"
    atomic_json(receipt, report)
    print(f"Regular-LOD CRC-register sibling build passed: {receipt}")
    print(
        f"program_bytes={program.stat().st_size} "
        f"program_sha256={sha256_file(program)} "
        f"records={corpus['aggregates']['records']} "
        f"data_bytes={corpus['aggregates']['data_bytes']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CrcSiblingBuildError as error:
        raise SystemExit(f"regular-LOD CRC-register sibling build failed: {error}") from error
