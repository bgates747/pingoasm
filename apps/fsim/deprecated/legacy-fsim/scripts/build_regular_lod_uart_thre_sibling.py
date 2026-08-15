#!/usr/bin/env python3
"""Build an isolated regular-LOD sibling with a DATA-only UART THRE sender.

The shared loader and fixture source are immutable inputs. The builder selects
the explicit legacy CRC policy in a temporary source and requires the
byte-exact historical program. It then replaces only the hash-pinned
``p3dm_upload_data`` block, assembles the candidate twice, audits its complete
ADL include closure, and emits separately named ignored evidence artifacts.

The direct path is deliberately tied to the pinned Console8 MOS.  It is used
only when MOS reports UART0 enabled with hardware flow control and UART0 DLAB
is clear; otherwise the exact RST18 block write remains the fallback.  Clear,
upload-header, consolidate, and command-50 writes always remain on RST18.
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
from typing import Mapping, Sequence
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
WORLD_MANIFEST = RUNTIME_FIXTURE / "WORLD.json"

FAB_ROOT = Path.home() / "Agon/mystuff/fab-agon-emulator"
CONSOLE8_MOS = FAB_ROOT / "firmware/mos_console8.bin"
CONSOLE8_MAP = FAB_ROOT / "firmware/mos_console8.map"

DEFAULT_OUTPUT = ROOT / "build/evidence/regular-lod-uart-thre-sibling-build-v3"
PROGRAM_STEM = "terrain-manager-regular-lod-uart-thre-sibling"
PROGRAM_LOAD_ADDRESS = 0x040000
PROGRAM_LIMIT_EXCLUSIVE = 0x070000
LAUNCHER_LOAD_ADDRESS = 0x0B0000
P3DM_DATA_OFFSET = 100
P3DM_DESC_CRC32 = 88
P3DM_BUFFER_BYTES = 16_384
P3DM_STAGE_BUFFER_ID = 0x7400
EXPECTED_RECORDS = 227
EXPECTED_CONTAINER_BYTES = 787_192
EXPECTED_DATA_BYTES = 764_288
EXPECTED_MAXIMUM_RECORD_BYTES = 4_568
EXPECTED_MINIMUM_DATA_BYTES = 358
EXPECTED_MAXIMUM_DATA_BYTES = 4_468
EXPECTED_LEVEL_COUNTS = {"fine": 91, "L1": 11, "L2": 21, "L4": 6, "L8": 98}
EXPECTED_MANAGER_SCHEMA = "pingo-terrain-regular-lod-manager-survey-v2"
EXPECTED_UPLOAD_TRANSCRIPT_BYTES = EXPECTED_DATA_BYTES + EXPECTED_RECORDS * 20
RESOURCE_NAMES = ("MATID.RG2", "PATLUT.BIN", "PATTERN.RG2")
SCHEMA = "pingo-terrain-regular-lod-uart-thre-sibling-build-v1"
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
WORLD_MANIFEST_SHA256 = (
    "382e7c7e9ec46ddb4d57bd51db706e441a37e52b7538d2af1b384fa9a053c04e"
)
CONSOLE8_MOS_SHA256 = (
    "5fbacb749ee037f0428aeac39817b5a6d465adc020f92d4020bb7dcb046d39fe"
)
CONSOLE8_MAP_SHA256 = (
    "2d3fb36ec90a073d4e0f5f665f75bd788338275906ffc07309c83e969d0368b0"
)

CANONICAL_UPLOAD_BLOCK_SHA256 = (
    "7ce7fb98c904a53d358288009a3132067fcdedfb2f3b93943ebe7cf9d56bc139"
)
# Filled from the exact literal below and checked before every build.
CANDIDATE_UPLOAD_BLOCK_SHA256 = (
    "d4d3bbbc25f3a5813b22604cd04d26b9510707d8620d923b35cbf8c461f089dd"
)
# Filled from the deterministic host transcript model and checked on every run.
EXPECTED_UPLOAD_COVERAGE_DIGEST_SHA256 = (
    "d9854f9b0c9b7a399cb00f6a5202c5d452094fc5a9cdda8fab60f714ed4a7612"
)

UPLOAD_START = "p3dm_upload_data:\n"
UPLOAD_END = "\n; Pingo subcommand 50."

# _serialFlags is private MOS state.  The address is independently required
# from the pinned map before the literal may enable the fast path.
MOS_SERIAL_FLAGS_ADDRESS = 0x0BC32D
UART0_PD_DR = 0xA2
UART0_THR = 0xC0
UART0_LCR = 0xC3
UART0_LSR = 0xC5
UART0_THRE_MASK = 0x20
UART0_TEMT_MASK = 0x40
UART0_NOT_CTS_MASK = 0x08

CANDIDATE_UPLOAD_BLOCK = """p3dm_upload_data:
    ld hl,@clear
    ld bc,@clear_end-@clear
    rst.lil 18h
    jp @clear_end
@clear:
    db 23,0,0A0h
    dw p3dm_stage_buffer_id
    db 2
@clear_end:
    P3DM_LD_U16_HL p3dm_data_size
    ld a,l
    ld (@length),a
    ld a,h
    ld (@length+1),a
    ld hl,@upload
    ld bc,@upload_end-@upload
    rst.lil 18h
    jp @upload_end
@upload:
    db 23,0,0A0h
    dw p3dm_stage_buffer_id
    db 0
@length:
    dw 0
@upload_end:
    ld hl,p3dm_file_buffer+p3dm_data_offset
    P3DM_LD_U16_BC p3dm_data_size
    call p3dm_uart0_write_block_thre
    ld hl,p3dm_stage_buffer_id
    call vdu_consolidate_buffer
    xor a
    ret

; Exact-u16 DATA-only sender for the pinned Console8 UART0 configuration.
; An unexpected MOS serial mode or DLAB state takes the original RST18 path.
; Zero is an explicit no-write return and cannot enter RST18 delimiter mode.
; The fast path preserves the successful counted-RST18 architectural result:
; AF=0044h, HL=end, BC=0, E=input A; MB, D/DEU, IX, IY, SP, I, alternate
; registers, and IFF1/IFF2 are unchanged.  Refresh R is timing-dependent.
p3dm_uart0_write_block_thre:
    push af
    ld a,b
    or c
    jr z,p3dm_uart0_write_block_zero
    ld a,mb
    or a
    jr nz,p3dm_uart0_write_block_fallback
    ld a,(0BC32Dh)
    and 03h
    cp 03h
    jr nz,p3dm_uart0_write_block_fallback
    in0 a,(0C3h)
    and 080h
    jr nz,p3dm_uart0_write_block_fallback
    pop af
    ld e,a
p3dm_uart0_write_block_byte:
p3dm_uart0_write_block_wait_cts:
    in0 a,(0A2h)
    tst 08h
    jr nz,p3dm_uart0_write_block_wait_cts
p3dm_uart0_write_block_wait_thre:
    in0 a,(0C5h)
    and 020h
    jr z,p3dm_uart0_write_block_wait_thre
    ld a,(hl)
    out0 (0C0h),a
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,p3dm_uart0_write_block_byte
    ret
p3dm_uart0_write_block_zero:
    pop af
    ld e,a
    xor a
    ret
p3dm_uart0_write_block_fallback:
    pop af
    rst.lil 18h
    ret
"""


class UartThreSiblingBuildError(RuntimeError):
    """A canonical-input, UART, ADL, memory, or transcript gate failed."""


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
    return {"key": key, "bytes": resolved.stat().st_size, "sha256": sha256_file(resolved)}


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UartThreSiblingBuildError(f"refusing to replace symlink: {path}")
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
        raise UartThreSiblingBuildError(
            f"command failed ({completed.returncode}): {' '.join(rendered)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def require_sha256(path: Path, expected: str, description: str) -> None:
    if not path.is_file():
        raise UartThreSiblingBuildError(f"missing {description}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise UartThreSiblingBuildError(f"{description} changed: {actual} != {expected}")


def extract_upload_block(loader: str) -> str:
    if loader.count(UPLOAD_START) != 1:
        raise UartThreSiblingBuildError("canonical upload block markers changed")
    _prefix, rest = loader.split(UPLOAD_START, 1)
    if rest.count(UPLOAD_END) != 1:
        raise UartThreSiblingBuildError("canonical upload block end marker changed")
    body, _suffix = rest.split(UPLOAD_END, 1)
    block = UPLOAD_START + body
    if sha256_bytes(block.encode("utf-8")) != CANONICAL_UPLOAD_BLOCK_SHA256:
        raise UartThreSiblingBuildError("canonical upload block hash changed")
    return block


def patch_loader(loader: str) -> tuple[str, dict[str, object]]:
    canonical = extract_upload_block(loader)
    candidate_hash = sha256_bytes(CANDIDATE_UPLOAD_BLOCK.encode("utf-8"))
    if candidate_hash != CANDIDATE_UPLOAD_BLOCK_SHA256:
        raise UartThreSiblingBuildError(
            f"candidate upload block changed: {candidate_hash} != "
            f"{CANDIDATE_UPLOAD_BLOCK_SHA256}"
        )
    if loader.count(canonical) != 1:
        raise UartThreSiblingBuildError("canonical upload block is not unique")
    candidate = loader.replace(canonical, CANDIDATE_UPLOAD_BLOCK, 1)
    if candidate.count(CANDIDATE_UPLOAD_BLOCK) != 1:
        raise UartThreSiblingBuildError("candidate upload block is not unique")
    if candidate.replace(CANDIDATE_UPLOAD_BLOCK, canonical, 1) != loader:
        raise UartThreSiblingBuildError("loader source diff escaped the upload block")
    return candidate, {
        "replacement_count": 1,
        "canonical_block_bytes": len(canonical.encode("utf-8")),
        "canonical_block_sha256": CANONICAL_UPLOAD_BLOCK_SHA256,
        "candidate_block_bytes": len(CANDIDATE_UPLOAD_BLOCK.encode("utf-8")),
        "candidate_block_sha256": candidate_hash,
        "canonical_loader_sha256": sha256_bytes(loader.encode("utf-8")),
        "candidate_loader_sha256": sha256_bytes(candidate.encode("utf-8")),
        "reverse_substitution_exact": True,
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


def assemble_in_mirror(source: Path) -> tuple[bytes, bytes, bytes]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise UartThreSiblingBuildError("ez80asm is not available on PATH")
    generated_program = source.with_suffix(".BIN")
    generated_listing = source.with_suffix(".lst")
    generated_symbols = source.with_suffix(".symbols")
    run((assembler, "-l", "-s", source.name, generated_program.name, "-c"), cwd=source.parent)
    missing = [
        path
        for path in (generated_program, generated_listing, generated_symbols)
        if not path.is_file()
    ]
    if missing:
        raise UartThreSiblingBuildError(f"ez80asm omitted artifacts: {missing}")
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


def require_all_inputs() -> None:
    for path, expected, description in (
        (ACCEPTED_SOURCE, ACCEPTED_SOURCE_SHA256, "accepted source"),
        (ACCEPTED_LOADER, ACCEPTED_LOADER_SHA256, "accepted loader"),
        (ACCEPTED_RUNTIME_INCLUDE, ACCEPTED_RUNTIME_INCLUDE_SHA256, "accepted runtime include"),
        (ACCEPTED_TRANSITION_INCLUDE, ACCEPTED_TRANSITION_INCLUDE_SHA256, "accepted transition include"),
        (WORLD_MANIFEST, WORLD_MANIFEST_SHA256, "world manifest"),
        (CONSOLE8_MOS, CONSOLE8_MOS_SHA256, "Console8 MOS"),
        (CONSOLE8_MAP, CONSOLE8_MAP_SHA256, "Console8 MOS map"),
    ):
        require_sha256(path, expected, description)


def build_program(output: Path) -> tuple[Path, Path, Path, dict[str, object], str]:
    require_all_inputs()
    output.mkdir(parents=True, exist_ok=True)
    candidate_runs: list[tuple[bytes, bytes, bytes]] = []
    source_patch: dict[str, object] | None = None
    audit = ""
    control_hash = ""
    for repeat in range(2):
        with tempfile.TemporaryDirectory(prefix=f"regular-uart-thre-build-{repeat + 1}-") as name:
            source, loader = stage_source_mirror(Path(name))
            source_text = source.read_text(encoding="ascii")
            nibble_policy = "p3dm_crc_policy: equ 4\n"
            legacy_policy = "p3dm_crc_policy: equ 1\n"
            if source_text.count(nibble_policy) != 1:
                raise UartThreSiblingBuildError(
                    "accepted top-level CRC policy changed"
                )
            legacy_source = source_text.replace(
                nibble_policy, legacy_policy, 1
            ).encode("ascii")
            source.write_bytes(legacy_source)
            control_program, _control_listing, _control_symbols = assemble_in_mirror(source)
            current_control_hash = sha256_bytes(control_program)
            if current_control_hash != ACCEPTED_PROGRAM_SHA256:
                raise UartThreSiblingBuildError(
                    "temporary control does not reproduce accepted program: "
                    f"{current_control_hash} != {ACCEPTED_PROGRAM_SHA256}"
                )
            if repeat == 0:
                control_hash = current_control_hash
            elif current_control_hash != control_hash:
                raise UartThreSiblingBuildError("temporary controls are not deterministic")
            canonical_loader = loader.read_text(encoding="utf-8")
            candidate_loader, current_patch = patch_loader(canonical_loader)
            loader.write_text(candidate_loader, encoding="utf-8")
            if source.read_bytes() != legacy_source:
                raise UartThreSiblingBuildError(
                    "temporary legacy-policy source changed"
                )
            current_audit = audit_candidate(source)
            candidate_runs.append(assemble_in_mirror(source))
            if repeat == 0:
                source_patch = current_patch
                audit = current_audit
            elif current_patch != source_patch or current_audit != audit:
                raise UartThreSiblingBuildError("candidate source/audit evidence is not deterministic")

    if candidate_runs[0] != candidate_runs[1]:
        raise UartThreSiblingBuildError("two independent candidate assemblies differ")
    assert source_patch is not None
    program_bytes, listing_bytes, symbol_bytes = candidate_runs[0]
    program = output / f"{PROGRAM_STEM}.bin"
    listing = output / f"{PROGRAM_STEM}.lst"
    symbols = output / f"{PROGRAM_STEM}.symbols"
    atomic_bytes(program, program_bytes)
    atomic_bytes(listing, listing_bytes)
    atomic_bytes(symbols, symbol_bytes)
    source_patch.update(
        {
            "accepted_source_sha256": ACCEPTED_SOURCE_SHA256,
            "temporary_top_level_source_exact_except_crc_policy": True,
            "temporary_crc_policy": "legacy-memory-bitwise",
            "temporary_control_program_sha256": control_hash,
            "temporary_control_program_exact": True,
            "candidate_independent_builds": 2,
            "candidate_program_listing_symbols_byte_exact": True,
            "accepted_files_modified": False,
        }
    )
    return program, listing, symbols, source_patch, audit


SYMBOL_RE = re.compile(r"^([^\s]+) \$([0-9a-fA-F]+)$")


def parse_symbols(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SYMBOL_RE.fullmatch(line)
        if match is not None:
            result.setdefault(match.group(1), int(match.group(2), 16))
    return result


MOS_MAP_RE = re.compile(r"^([^\s]+)\s+[CD]:([0-9A-Fa-f]{6})\b")


def parse_mos_map(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = MOS_MAP_RE.match(line)
        if match is not None:
            result.setdefault(match.group(1), int(match.group(2), 16))
    return result


def _exact_window(image: bytes, offset: int, expected_hex: str, name: str) -> dict[str, object]:
    expected = bytes.fromhex(expected_hex)
    actual = image[offset : offset + len(expected)]
    if actual != expected:
        raise UartThreSiblingBuildError(
            f"Console8 {name} opcodes changed at 0x{offset:06x}: "
            f"{actual.hex()} != {expected.hex()}"
        )
    return {"offset": offset, "bytes": len(expected), "hex": actual.hex()}


def validate_console8_contract() -> dict[str, object]:
    require_sha256(CONSOLE8_MOS, CONSOLE8_MOS_SHA256, "Console8 MOS")
    require_sha256(CONSOLE8_MAP, CONSOLE8_MAP_SHA256, "Console8 MOS map")
    image = CONSOLE8_MOS.read_bytes()
    symbols = parse_mos_map(CONSOLE8_MAP)
    required = {
        "UART0_serial_PUTCH": 0x0010CA,
        "UART0_serial_TX": 0x001056,
        "_serialFlags": MOS_SERIAL_FLAGS_ADDRESS,
    }
    for name, expected in required.items():
        if symbols.get(name) != expected:
            raise UartThreSiblingBuildError(
                f"Console8 map {name} changed: {symbols.get(name)!r} != 0x{expected:06x}"
            )
    vector = _exact_window(image, 0x18, "5bc3221400", "RST18 vector")
    rst18 = _exact_window(
        image,
        0x1422,
        "5fed6eb7c4f4070078b1280d7ecdca1000230b78b120f55bc9",
        "RST18 counted loop",
    )
    putch = _exact_window(
        image,
        0x10CA,
        "f53a2dc30bed64012828ed6402c4441000f1cd56100030fac9",
        "UART0 PUTCH",
    )
    cts = _exact_window(image, 0x1044, "ed38a2ed640820f8c9", "UART0 CTS wait")
    tx = _exact_window(
        image,
        0x1056,
        "c5f501004000ed38c5e64020090b78b120f4f1c1b7c9f1ed39c0c137c9",
        "UART0 TX",
    )
    if image[0x142F : 0x1433] != bytes.fromhex("cdca1000"):
        raise UartThreSiblingBuildError("RST18 standard loop no longer calls UART0 PUTCH")
    if image[0x105C : 0x1061] != bytes.fromhex("ed38c5e640"):
        raise UartThreSiblingBuildError("UART0 TX no longer polls LSR/TEMT")
    if image[0x106D : 0x1070] != bytes.fromhex("ed39c0"):
        raise UartThreSiblingBuildError("UART0 TX no longer writes UART0 THR")
    return {
        "mos": artifact(CONSOLE8_MOS),
        "map": artifact(CONSOLE8_MAP),
        "map_symbols": required,
        "opcode_windows": {
            "rst18_vector": vector,
            "rst18_counted_loop": rst18,
            "uart0_putch": putch,
            "uart0_cts_wait": cts,
            "uart0_tx": tx,
        },
        "rst18_target": 0x001422,
        "rst18_counted_uart_call_offset": 0x00142F,
        "uart0_putch_target": 0x0010CA,
        "uart0_tx_target": 0x001056,
        "uart0_tx_lsr_poll_offset": 0x00105C,
        "uart0_tx_readiness_mask_offset": 0x001060,
        "uart0_tx_readiness_mask": UART0_TEMT_MASK,
        "uart0_tx_readiness": "TEMT: FIFO/holding register empty and transmitter idle",
        "uart0_tx_thr_write_offset": 0x00106D,
        "uart0_cts_port": UART0_PD_DR,
        "uart0_cts_mask": UART0_NOT_CTS_MASK,
        "uart0_cts_polarity": "physical CTS is asserted low; PD_DR bit 3=1 means NOT-CTS and loops",
        "uart0_lsr_port": UART0_LSR,
        "uart0_thr_port": UART0_THR,
        "private_serial_flags_address": MOS_SERIAL_FLAGS_ADDRESS,
    }


def bytes_at(payload: bytes, address: int, count: int) -> bytes:
    offset = address - PROGRAM_LOAD_ADDRESS
    if offset < 0 or offset + count > len(payload):
        raise UartThreSiblingBuildError(f"candidate opcode window escapes program: 0x{address:06x}")
    return payload[offset : offset + count]


def validate_candidate_opcodes(program: Path, symbols_path: Path) -> dict[str, object]:
    payload = program.read_bytes()
    symbols = parse_symbols(symbols_path)
    required = {
        "p3dm_upload_data",
        "p3dm_uart0_write_block_thre",
        "p3dm_uart0_write_block_byte",
        "p3dm_uart0_write_block_wait_cts",
        "p3dm_uart0_write_block_wait_thre",
        "p3dm_uart0_write_block_zero",
        "p3dm_uart0_write_block_fallback",
        "pingo_replace_mesh_from_buffer",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise UartThreSiblingBuildError(f"candidate symbols omit: {missing}")
    if not (
        symbols["p3dm_upload_data"]
        < symbols["p3dm_uart0_write_block_thre"]
        <= symbols["p3dm_uart0_write_block_byte"]
        <= symbols["p3dm_uart0_write_block_wait_cts"]
        < symbols["p3dm_uart0_write_block_wait_thre"]
        < symbols["p3dm_uart0_write_block_zero"]
        < symbols["p3dm_uart0_write_block_fallback"]
        < symbols["pingo_replace_mesh_from_buffer"]
    ):
        raise UartThreSiblingBuildError("candidate upload/sender/command-50 order changed")

    checks = {
        "cts_poll": (
            symbols["p3dm_uart0_write_block_wait_cts"],
            bytes.fromhex("ed38a2ed6408"),
        ),
        "thre_poll": (
            symbols["p3dm_uart0_write_block_wait_thre"],
            bytes.fromhex("ed38c5e620"),
        ),
    }
    windows: dict[str, object] = {}
    for name, (address, expected) in checks.items():
        actual = bytes_at(payload, address, len(expected))
        if actual != expected:
            raise UartThreSiblingBuildError(
                f"candidate {name} opcodes changed: {actual.hex()} != {expected.hex()}"
            )
        windows[name] = {"address": address, "bytes": len(actual), "hex": actual.hex()}

    sender_start = symbols["p3dm_uart0_write_block_thre"]
    sender_end = symbols["pingo_replace_mesh_from_buffer"]
    sender = bytes_at(payload, sender_start, sender_end - sender_start)
    required_once = {
        "mbase_zero_guard": bytes.fromhex("ed6eb7"),
        "serial_flags_absolute_load": bytes.fromhex("3a2dc30b"),
        "lcr_dlab_guard": bytes.fromhex("ed38c3e680"),
        "uart_thr_write": bytes.fromhex("ed39c0"),
        "rst18_fallback": bytes.fromhex("5bdf"),
    }
    for name, opcode in required_once.items():
        if sender.count(opcode) != 1:
            raise UartThreSiblingBuildError(
                f"candidate sender expected one {name}, found {sender.count(opcode)}"
            )
        address = sender_start + sender.index(opcode)
        windows[name] = {"address": address, "bytes": len(opcode), "hex": opcode.hex()}
    if bytes((UART0_TEMT_MASK,)) in bytes_at(
        payload,
        symbols["p3dm_uart0_write_block_wait_thre"],
        symbols["p3dm_uart0_write_block_fallback"]
        - symbols["p3dm_uart0_write_block_wait_thre"],
    ):
        raise UartThreSiblingBuildError("candidate fast loop unexpectedly contains TEMT mask")
    return {
        "symbols": {name: symbols[name] for name in sorted(required)},
        "opcode_windows": windows,
        "fast_readiness_mask": UART0_THRE_MASK,
        "fast_readiness": "THRE: FIFO/transmit holding register empty",
        "fast_cts_source": "PD_DR bit 3: CTS asserted at 0; loop while NOT-CTS bit is 1",
        "zero_count": "explicit no-write success; never enters RST18 delimited mode",
        "fallback": "RST18 for MBASE nonzero, serial flags != 0x03, or DLAB set",
    }


def validate_memory(program: Path, symbols_path: Path) -> dict[str, object]:
    payload = program.read_bytes()
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise UartThreSiblingBuildError("sibling lost common entry/header")
    symbols = parse_symbols(symbols_path)
    required = {
        "filedata",
        "p3dm_validate_container",
        "p3dm_mirror_validated_z",
        "p3dm_upload_data",
        "p3dm_uart0_write_block_thre",
        "pingo_replace_mesh_from_buffer",
        "p3dm_return_error",
        "p3dm_file_buffer",
    }
    missing = sorted(required - symbols.keys())
    if missing:
        raise UartThreSiblingBuildError(f"sibling symbols omit: {missing}")
    program_end = PROGRAM_LOAD_ADDRESS + len(payload)
    if symbols["filedata"] != program_end:
        raise UartThreSiblingBuildError("sibling filedata/program end mismatch")
    if not PROGRAM_LOAD_ADDRESS < program_end < PROGRAM_LIMIT_EXCLUSIVE:
        raise UartThreSiblingBuildError("sibling escapes fixture load window")
    buffer_start = symbols["p3dm_file_buffer"]
    buffer_end = buffer_start + P3DM_BUFFER_BYTES
    if buffer_end > program_end or buffer_end >= PROGRAM_LIMIT_EXCLUSIVE:
        raise UartThreSiblingBuildError("P3DM buffer escapes sibling program window")
    resources = []
    for name in RESOURCE_NAMES:
        path = RUNTIME_FIXTURE / name
        if not path.is_file():
            raise UartThreSiblingBuildError(f"runtime resource is missing: {path}")
        resources.append(artifact(path))
    maximum_resource = max(int(item["bytes"]) for item in resources)
    staging_end = program_end + maximum_resource
    if not staging_end < PROGRAM_LIMIT_EXCLUSIVE < LAUNCHER_LOAD_ADDRESS:
        raise UartThreSiblingBuildError("resource staging or launcher memory overlaps sibling")
    if not (
        symbols["p3dm_validate_container"]
        < symbols["p3dm_mirror_validated_z"]
        < symbols["p3dm_upload_data"]
        < symbols["p3dm_uart0_write_block_thre"]
        < symbols["pingo_replace_mesh_from_buffer"]
        < symbols["p3dm_return_error"]
        < buffer_start
    ):
        raise UartThreSiblingBuildError("validation/upload/error/buffer symbol order changed")
    return {
        "program_load_address": PROGRAM_LOAD_ADDRESS,
        "program_end": program_end,
        "program_limit_exclusive": PROGRAM_LIMIT_EXCLUSIVE,
        "resource_staging_maximum_bytes": maximum_resource,
        "resource_staging_end": staging_end,
        "launcher_load_address": LAUNCHER_LOAD_ADDRESS,
        "p3dm_file_buffer": [buffer_start, buffer_end],
        "p3dm_upload_data": symbols["p3dm_upload_data"],
        "p3dm_uart0_write_block_thre": symbols["p3dm_uart0_write_block_thre"],
        "pingo_replace_mesh_from_buffer": symbols["pingo_replace_mesh_from_buffer"],
        "resources": resources,
    }


def _uint(record: Mapping[str, object], name: str, order: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UartThreSiblingBuildError(f"manifest record {order} has invalid {name}: {value!r}")
    return value


def mirror_validated_data(data: bytes, record: Mapping[str, object], order: int) -> bytes:
    vertices = _uint(record, "vertices", order)
    position_indices = _uint(record, "position_indices", order)
    uvs = _uint(record, "texture_coordinates", order)
    uv_indices = _uint(record, "texture_indices", order)
    expected = 6 * vertices + 2 * position_indices + 4 * uvs + 2 * uv_indices
    if expected != len(data) or position_indices != uv_indices or position_indices % 3:
        raise UartThreSiblingBuildError(f"record {order} DATA layout changed")
    changed = bytearray(data)
    for vertex in range(vertices):
        offset = vertex * 6 + 4
        value = int.from_bytes(changed[offset : offset + 2], "little", signed=True)
        if value == -32768:
            raise UartThreSiblingBuildError(f"record {order} contains unrepresentable Z")
        changed[offset : offset + 2] = (-value).to_bytes(2, "little", signed=True)
    position_start = 6 * vertices
    for index in range(0, position_indices, 3):
        second = position_start + 2 * (index + 1)
        third = second + 2
        changed[second : second + 2], changed[third : third + 2] = (
            changed[third : third + 2],
            changed[second : second + 2],
        )
    uv_index_start = 6 * vertices + 2 * position_indices + 4 * uvs
    for index in range(0, uv_indices, 3):
        second = uv_index_start + 2 * (index + 1)
        third = second + 2
        changed[second : second + 2], changed[third : third + 2] = (
            changed[third : third + 2],
            changed[second : second + 2],
        )
    return bytes(changed)


def upload_transcript(data: bytes) -> bytes:
    length = len(data)
    if not 0 < length <= 0xFFFF:
        raise UartThreSiblingBuildError(f"DATA count is not positive u16: {length}")
    clear = bytes((23, 0, 0xA0, 0x00, 0x74, 2))
    header = bytes((23, 0, 0xA0, 0x00, 0x74, 0, length & 0xFF, length >> 8))
    consolidate = bytes((23, 0, 0xA0, 0x00, 0x74, 14))
    return clear + header + data + consolidate


def model_uart_thre_sender(
    payload: bytes,
    *,
    entry_a: int,
    serial_flags: int = 0x03,
    dlab: bool = False,
    mbase: int = 0,
    schedule_seed: int = 0,
) -> dict[str, object]:
    """Execute the candidate's count/order/readiness state machine on host.

    The deterministic adversarial schedule holds CTS false for 0..3 polls and
    THRE false for 0..4 polls independently before every byte.  A write is
    accepted only after both loops have observed their ready state.  Invalid
    entry configuration models the positive-count RST18 fallback; zero is
    always the candidate's explicit no-write return and can never enter
    RST18's delimiter mode.
    """

    if (
        not 0 <= entry_a <= 0xFF
        or not 0 <= serial_flags <= 0xFF
        or not 0 <= mbase <= 0xFF
    ):
        raise ValueError("entry A, serial flags, and MBASE must be bytes")
    count = len(payload)
    if count > 0xFFFF:
        raise ValueError("sender payload exceeds exact u16")
    final = {
        "AF": 0x0044,
        "BC": 0,
        "E": entry_a,
        "HL_advance": count,
        "MB_unchanged": True,
        "D_DEU_unchanged": True,
        "IX_IY_SP_unchanged": True,
        "alternate_registers_unchanged": True,
        "I_unchanged": True,
        "IFF1_IFF2_unchanged": True,
        "R_timing_dependent_not_compared": True,
    }
    if count == 0:
        return {
            "output": b"",
            "fallback": False,
            "zero_no_write": True,
            "cts_polls": 0,
            "thre_polls": 0,
            "writes": 0,
            "writes_before_both_ready": 0,
            "final_registers": final,
        }
    if mbase != 0 or serial_flags & 0x03 != 0x03 or dlab:
        return {
            "output": bytes(payload),
            "fallback": True,
            "zero_no_write": False,
            "cts_polls": 0,
            "thre_polls": 0,
            "writes": count,
            "writes_before_both_ready": 0,
            "final_registers": final,
        }

    output = bytearray()
    cts_polls = 0
    thre_polls = 0
    premature = 0
    for index, byte in enumerate(payload):
        cts_false = (schedule_seed + index * 3) & 3
        thre_false = (schedule_seed * 3 + index * 5) % 5
        cts_ready = False
        thre_ready = False
        for _poll in range(cts_false):
            cts_polls += 1
            if cts_ready and thre_ready:
                premature += 1
        cts_polls += 1
        cts_ready = True
        for _poll in range(thre_false):
            thre_polls += 1
            if cts_ready and thre_ready:
                premature += 1
        thre_polls += 1
        thre_ready = True
        if not cts_ready or not thre_ready:
            premature += 1
        else:
            output.append(byte)
    if premature or bytes(output) != payload:
        raise UartThreSiblingBuildError("host sender violated readiness/count/order")
    return {
        "output": bytes(output),
        "fallback": False,
        "zero_no_write": False,
        "cts_polls": cts_polls,
        "thre_polls": thre_polls,
        "writes": len(output),
        "writes_before_both_ready": premature,
        "final_registers": final,
    }


def validate_upload_transcripts(
    *,
    manifest_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    manifest_path = MANAGER_MANIFEST if manifest_path is None else manifest_path
    root = RUNTIME_FIXTURE if root is None else root
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise UartThreSiblingBuildError("manager manifest is absent or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UartThreSiblingBuildError("manager manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != EXPECTED_MANAGER_SCHEMA:
        raise UartThreSiblingBuildError("manager manifest schema changed")
    records = manifest.get("initial_view", {}).get("records", ())
    if not isinstance(records, list) or len(records) != EXPECTED_RECORDS:
        raise UartThreSiblingBuildError("manager manifest does not contain 227 records")
    coverage = []
    total_container = 0
    total_data = 0
    total_transcript = 0
    maximum = 0
    minimum_data = 0x10000
    maximum_data = 0
    total_cts_polls = 0
    total_thre_polls = 0
    level_counts: Counter[str] = Counter()
    aggregate_stream = hashlib.sha256()
    for order, record in enumerate(records):
        if not isinstance(record, dict) or record.get("order") != order:
            raise UartThreSiblingBuildError(f"manifest record order changed at {order}")
        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            raise UartThreSiblingBuildError(f"manifest record {order} has no path")
        path = root / relative
        payload = path.read_bytes()
        file_hash = sha256_bytes(payload)
        if file_hash != record.get("sha256"):
            raise UartThreSiblingBuildError(f"record checksum changed: {relative}")
        file_bytes = _uint(record, "bytes", order)
        data_bytes = _uint(record, "data_bytes", order)
        if len(payload) != file_bytes or not 0 < data_bytes <= 0xFFFF:
            raise UartThreSiblingBuildError(f"record size/count changed: {relative}")
        if int.from_bytes(payload[96:100], "little") != data_bytes:
            raise UartThreSiblingBuildError(f"record DATA header changed: {relative}")
        disk_data = payload[P3DM_DATA_OFFSET : P3DM_DATA_OFFSET + data_bytes]
        if len(disk_data) != data_bytes:
            raise UartThreSiblingBuildError(f"record DATA missing: {relative}")
        stored = int.from_bytes(payload[P3DM_DESC_CRC32 : P3DM_DESC_CRC32 + 4], "little")
        if stored != zlib.crc32(disk_data) & 0xFFFFFFFF:
            raise UartThreSiblingBuildError(f"record CRC changed: {relative}")
        published_data = mirror_validated_data(disk_data, record, order)
        accepted = upload_transcript(published_data)
        sender = model_uart_thre_sender(
            published_data,
            entry_a=data_bytes >> 8,
            schedule_seed=order,
        )
        candidate_output = sender["output"]
        if not isinstance(candidate_output, bytes):
            raise UartThreSiblingBuildError("host sender output is not bytes")
        candidate = upload_transcript(candidate_output)
        if candidate != accepted:
            raise UartThreSiblingBuildError(f"candidate transcript differs: {relative}")
        aggregate_stream.update(accepted)
        initial_a = data_bytes >> 8
        final_registers = sender["final_registers"]
        coverage.append(
            {
                "order": order,
                "path": relative,
                "file_bytes": file_bytes,
                "file_sha256": file_hash,
                "data_bytes": data_bytes,
                "disk_data_sha256": sha256_bytes(disk_data),
                "published_mirrored_data_sha256": sha256_bytes(published_data),
                "accepted_transcript_sha256": sha256_bytes(accepted),
                "candidate_transcript_sha256": sha256_bytes(candidate),
                "transcript_bytes": len(candidate),
                "byte_exact": True,
                "entry_A": initial_a,
                "final_registers": final_registers,
                "adversarial_schedule": {
                    "cts_polls": sender["cts_polls"],
                    "thre_polls": sender["thre_polls"],
                    "writes": sender["writes"],
                    "writes_before_both_ready": sender[
                        "writes_before_both_ready"
                    ],
                },
            }
        )
        total_container += file_bytes
        total_data += data_bytes
        total_transcript += len(candidate)
        maximum = max(maximum, file_bytes)
        minimum_data = min(minimum_data, data_bytes)
        maximum_data = max(maximum_data, data_bytes)
        total_cts_polls += int(sender["cts_polls"])
        total_thre_polls += int(sender["thre_polls"])
        level = record.get("level")
        if not isinstance(level, str):
            raise UartThreSiblingBuildError(f"record level missing: {relative}")
        level_counts[level] += 1
    aggregates = {
        "records": len(coverage),
        "container_bytes": total_container,
        "data_bytes": total_data,
        "upload_transcript_bytes": total_transcript,
        "maximum_record_bytes": maximum,
        "minimum_data_bytes": EXPECTED_MINIMUM_DATA_BYTES,
        "maximum_data_bytes": EXPECTED_MAXIMUM_DATA_BYTES,
        "level_counts": dict(level_counts),
    }
    expected = {
        "records": EXPECTED_RECORDS,
        "container_bytes": EXPECTED_CONTAINER_BYTES,
        "data_bytes": EXPECTED_DATA_BYTES,
        "upload_transcript_bytes": EXPECTED_UPLOAD_TRANSCRIPT_BYTES,
        "maximum_record_bytes": EXPECTED_MAXIMUM_RECORD_BYTES,
        "minimum_data_bytes": minimum_data,
        "maximum_data_bytes": maximum_data,
        "level_counts": EXPECTED_LEVEL_COUNTS,
    }
    if aggregates != expected:
        raise UartThreSiblingBuildError(f"cold corpus aggregates changed: {aggregates} != {expected}")
    digest = sha256_bytes(json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode())
    if digest != EXPECTED_UPLOAD_COVERAGE_DIGEST_SHA256:
        raise UartThreSiblingBuildError(
            f"upload coverage digest changed: {digest} != {EXPECTED_UPLOAD_COVERAGE_DIGEST_SHA256}"
        )
    zero = model_uart_thre_sender(b"", entry_a=0xA5, schedule_seed=0x5A)
    if (
        zero["output"] != b""
        or zero["writes"] != 0
        or zero["fallback"] is not False
        or zero["zero_no_write"] is not True
    ):
        raise UartThreSiblingBuildError("zero-count host sender is not no-write")
    fallback = model_uart_thre_sender(b"\x00\xff\x5a", entry_a=0xA7, mbase=1)
    if fallback["output"] != b"\x00\xff\x5a" or fallback["fallback"] is not True:
        raise UartThreSiblingBuildError("positive-count host fallback changed")
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
        "concatenated_transcript_sha256": aggregate_stream.hexdigest(),
        "all_accepted_candidate_transcripts_byte_exact": True,
        "all_counts_positive_u16": True,
        "all_stage_buffer_ids": P3DM_STAGE_BUFFER_ID,
        "all_return_register_contracts_exact": True,
        "adversarial_readiness_schedule": {
            "cts_false_polls_before_ready_per_byte": "(record + 3*byte) mod 4",
            "thre_false_polls_before_ready_per_byte": "(3*record + 5*byte) mod 5",
            "cts_polls": total_cts_polls,
            "thre_polls": total_thre_polls,
            "writes": total_data,
            "writes_before_both_ready": 0,
        },
        "zero_count": {
            "explicit_no_write": True,
            "rst18_delimited_mode_not_entered": True,
            "final_registers": zero["final_registers"],
        },
        "unexpected_configuration_fallback": {
            "positive_count_rst18_modeled": True,
            "conditions": [
                "MBASE nonzero",
                "serialFlags low bits != 3",
                "DLAB set",
            ],
            "byte_exact": True,
        },
        "records": coverage,
    }


def validate_source_contract() -> dict[str, object]:
    block = CANDIDATE_UPLOAD_BLOCK
    required_order = (
        "rst.lil 18h\n    jp @clear_end",
        "rst.lil 18h\n    jp @upload_end",
        "call p3dm_uart0_write_block_thre",
        "call vdu_consolidate_buffer",
        "p3dm_uart0_write_block_thre:",
        "ld a,b\n    or c\n    jr z,p3dm_uart0_write_block_zero",
        "ld a,mb\n    or a\n    jr nz,p3dm_uart0_write_block_fallback",
        "ld a,(0BC32Dh)",
        "in0 a,(0C3h)",
        "p3dm_uart0_write_block_wait_cts:",
        "in0 a,(0A2h)",
        "p3dm_uart0_write_block_wait_thre:",
        "in0 a,(0C5h)",
        "and 020h",
        "ld a,(hl)",
        "out0 (0C0h),a",
        "inc hl",
        "dec bc",
        "ld a,b\n    or c\n    jr nz,p3dm_uart0_write_block_byte",
        "p3dm_uart0_write_block_zero:\n    pop af\n    ld e,a\n    xor a\n    ret",
        "p3dm_uart0_write_block_fallback:\n    pop af\n    rst.lil 18h",
    )
    positions = [block.index(item) for item in required_order]
    if positions != sorted(positions):
        raise UartThreSiblingBuildError("candidate instruction/protocol order changed")
    lowered_tokens = re.findall(r"[A-Za-z_.]+", block.lower())
    if "di" in lowered_tokens or "ei" in lowered_tokens:
        raise UartThreSiblingBuildError("candidate unexpectedly changes interrupt state")
    if block.count("out0 (0C0h),a") != 1:
        raise UartThreSiblingBuildError("candidate has an unexpected UART write count")
    if block.count("rst.lil 18h") != 3:
        raise UartThreSiblingBuildError("candidate RST18 clear/header/fallback topology changed")
    return {
        "changed_operation": "validated P3DM DATA bytes only",
        "rst18_operations_unchanged": ["stage clear", "upload header", "consolidate", "command 50"],
        "fast_path_guards": [
            "MBASE is zero (otherwise preserve RST18 pointer conversion)",
            "MOS _serialFlags bits 0..1 equal 0x03",
            "UART0 LCR DLAB bit is clear",
            "BC is a positive exact u16",
        ],
        "fallback": "original RST18 counted block write",
        "cts": "PD_DR 0xA2 bit 3: CTS asserted at 0; loop while NOT-CTS bit is 1, identical to pinned MOS",
        "readiness_change": "UART0 LSR 0xC5 mask 0x20 THRE replaces pinned MOS mask 0x40 TEMT",
        "write": "one OUT0 to UART0 THR 0xC0 per DATA byte",
        "return_contract": (
            "AF=0x0044, BC=0, HL=end, E=input A; MB, D/DEU, IX, IY, SP, "
            "I, and alternate registers unchanged; IFF1/IFF2 unchanged by the "
            "routine; refresh R is timing-dependent and is not compared"
        ),
        "interrupt_mask_unchanged": True,
        "loader_errors_unchanged": True,
        "reason_errors_unchanged": "all validation/error branches precede the sole patched upload block",
        "no_concurrent_uart_writer_required": True,
        "uart_configuration_must_not_change_during_block": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise UartThreSiblingBuildError(f"refusing to replace existing output: {output}")
    console8 = validate_console8_contract()
    source_contract = validate_source_contract()
    transcripts = validate_upload_transcripts()
    program, listing, symbols, source_patch, audit = build_program(output)
    memory = validate_memory(program, symbols)
    opcodes = validate_candidate_opcodes(program, symbols)
    require_all_inputs()
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "scratch_sibling_only": True,
            "accepted_loader_modified": False,
            "accepted_source_modified": False,
            "accepted_binary_modified": False,
            "accepted_sidecars_modified": False,
            "crc_sibling_modified": False,
            "launcher_modified": False,
            "docs_modified": False,
        },
        "artifacts": {
            "program": artifact(program, key=f"artifacts/{program.name}"),
            "listing": artifact(listing, key=f"artifacts/{listing.name}"),
            "symbols": artifact(symbols, key=f"artifacts/{symbols.name}"),
        },
        "accepted_inputs": {
            "source": artifact(ACCEPTED_SOURCE),
            "loader": artifact(ACCEPTED_LOADER),
            "runtime_include": artifact(ACCEPTED_RUNTIME_INCLUDE),
            "transition_include": artifact(ACCEPTED_TRANSITION_INCLUDE),
            "world_manifest": artifact(WORLD_MANIFEST),
        },
        "source_patch": source_patch,
        "source_contract": source_contract,
        "console8_contract": console8,
        "candidate_opcode_contract": opcodes,
        "adl_audit": {
            "command_succeeded": True,
            "follow_includes": True,
            "fail_review": True,
            "output": audit,
        },
        "memory": memory,
        "host_upload_transcripts": transcripts,
        "limitations": {
            "console8_specific": True,
            "exact_mos_required_sha256": CONSOLE8_MOS_SHA256,
            "must_not_run_or_deploy_with_another_mos": True,
            "mos_identity_caveat": (
                "private _serialFlags 0x0BC32D and GPIO-PD3 CTS wiring are "
                "valid only for the exact pinned MOS; fallback covers "
                "configuration drift within that image, not MOS identity drift"
            ),
            "no_concurrent_uart_writer": True,
            "dlab_must_remain_clear": True,
            "uart_configuration_must_remain_stable": True,
            "hardware_timing_not_claimed": True,
            "emulator_timing_not_in_build_receipt": True,
            "fallback_covers_unexpected_entry_configuration_within_pinned_mos": True,
            "physical_qualification_requires_exact_pinned_mos": True,
        },
    }
    receipt = output / "BUILD.json"
    atomic_json(receipt, report)
    print(f"Regular-LOD UART-THRE sibling build passed: {receipt}")
    print(
        f"program_bytes={program.stat().st_size} "
        f"program_sha256={sha256_file(program)} "
        f"records={transcripts['aggregates']['records']} "
        f"data_bytes={transcripts['aggregates']['data_bytes']} "
        f"transcript_bytes={transcripts['aggregates']['upload_transcript_bytes']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UartThreSiblingBuildError as error:
        raise SystemExit(f"regular-LOD UART-THRE sibling build failed: {error}") from error
