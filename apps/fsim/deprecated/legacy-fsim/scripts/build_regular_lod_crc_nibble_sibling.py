#!/usr/bin/env python3
"""Build an isolated regular-LOD sibling with a 16-entry CRC-32 table.

The shared loader's three CRC implementations remain immutable inputs. This
builder selects policy 1 in a temporary source to reproduce the historical
control, then restores the production policy 4 selection and emits only
separately named scratch artifacts. Canonical fixture artifacts are never
inputs or outputs.

The candidate keeps the CRC in its existing four-byte memory object.  Four
``RRD`` operations shift it by one nibble while returning the discarded low
nibble in A; a 256-byte-aligned, 64-byte table then applies the reflected
CRC-32/ISO-HDLC polynomial.  The two nibble passes are deliberately unrolled so
BC remains the uninterrupted outer byte counter and no shadow-register or
interrupt-mask change is introduced.  BC, DE, HL, and IX are live throughout
the inner path, so target qualification must still retain the normal contract
that asynchronous handlers preserve the interrupted main register set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Mapping, Sequence
import zlib

import build_regular_lod_crc_register_sibling as register


ROOT = register.ROOT
DEFAULT_OUTPUT = ROOT / "build/evidence/regular-lod-crc-nibble-sibling-build-v4"
PROGRAM_STEM = "terrain-manager-regular-lod-crc-nibble-sibling"
SCHEMA = "pingo-terrain-regular-lod-crc-nibble-sibling-build-v1"
TABLE_ALIGNMENT = 256
TABLE_ENTRIES = 16
TABLE_BYTES = 64

ACCEPTED_SOURCE = register.ACCEPTED_SOURCE
ACCEPTED_LOADER = register.ACCEPTED_LOADER
ACCEPTED_PROGRAM = register.ACCEPTED_PROGRAM
ACCEPTED_LISTING = register.ACCEPTED_LISTING
ACCEPTED_SYMBOLS = register.ACCEPTED_SYMBOLS
ACCEPTED_RUNTIME_INCLUDE = register.ACCEPTED_RUNTIME_INCLUDE
ACCEPTED_TRANSITION_INCLUDE = register.ACCEPTED_TRANSITION_INCLUDE
MANAGER_MANIFEST = register.MANAGER_MANIFEST
RUNTIME_FIXTURE = register.RUNTIME_FIXTURE

CANONICAL_CRC_BLOCK_SHA256 = register.CANONICAL_CRC_BLOCK_SHA256
CANDIDATE_CRC_BLOCK_SHA256 = (
    "8f6dc38930676419d29cd511ba0589f999f315405d7bc232ef13fcf849a78809"
)


NIBBLE_TABLE = (
    0x00000000,
    0x1DB71064,
    0x3B6E20C8,
    0x26D930AC,
    0x76DC4190,
    0x6B6B51F4,
    0x4DB26158,
    0x5005713C,
    0xEDB88320,
    0xF00F9344,
    0xD6D6A3E8,
    0xCB61B38C,
    0x9B64C2B0,
    0x86D3D2D4,
    0xA00AE278,
    0xBDBDF21C,
)


NIBBLE_PASS = """    xor a
    rrd
    dec hl
    rrd
    dec hl
    rrd
    dec hl
    rrd
    add a,a
    add a,a
    ld e,a
    ld a,(de)
    xor (hl)
    ld (hl),a
    inc de
    inc hl
    ld a,(de)
    xor (hl)
    ld (hl),a
    inc de
    inc hl
    ld a,(de)
    xor (hl)
    ld (hl),a
    inc de
    inc hl
    ld a,(de)
    xor (hl)
    ld (hl),a
"""


CANDIDATE_CRC_BLOCK = f"""p3dm_validate_crc32:
    ld a,0FFh
    ld (p3dm_crc_value+0),a
    ld (p3dm_crc_value+1),a
    ld (p3dm_crc_value+2),a
    ld (p3dm_crc_value+3),a
    ld de,p3dm_crc32_nibble_table
    ld hl,p3dm_crc_value+3
    ld ix,p3dm_file_buffer+p3dm_data_offset
    P3DM_LD_U16_BC p3dm_data_size
@byte:
    ld a,b
    or c
    jr z,@finish
    ld a,(ix)
    inc ix
    dec hl
    dec hl
    dec hl
    xor (hl)
    ld (hl),a
    inc hl
    inc hl
    inc hl
{NIBBLE_PASS}{NIBBLE_PASS}    dec bc
    jr @byte
@finish:
    ld b,4
    ld hl,p3dm_crc_value
@complement:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz @complement
    ld hl,p3dm_crc_value
    ld de,p3dm_file_buffer+p3dm_desc_crc32
    ld b,4
@compare:
    ld a,(de)
    cp (hl)
    jp nz,p3dm_bad_crc32
    inc de
    inc hl
    djnz @compare
    xor a
    ret

    .align 256
p3dm_crc32_nibble_table:
    db 000h,000h,000h,000h
    db 064h,010h,0B7h,01Dh
    db 0C8h,020h,06Eh,03Bh
    db 0ACh,030h,0D9h,026h
    db 090h,041h,0DCh,076h
    db 0F4h,051h,06Bh,06Bh
    db 058h,061h,0B2h,04Dh
    db 03Ch,071h,005h,050h
    db 020h,083h,0B8h,0EDh
    db 044h,093h,00Fh,0F0h
    db 0E8h,0A3h,0D6h,0D6h
    db 08Ch,0B3h,061h,0CBh
    db 0B0h,0C2h,064h,09Bh
    db 0D4h,0D2h,0D3h,086h
    db 078h,0E2h,00Ah,0A0h
    db 01Ch,0F2h,0BDh,0BDh
"""


CrcNibbleSiblingBuildError = register.CrcSiblingBuildError


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def nibble_crc32(payload: bytes | bytearray | memoryview) -> int:
    """Model the exact memory bytes, RRD walk, and table XOR instructions."""

    crc = bytearray((0xFF, 0xFF, 0xFF, 0xFF))
    for byte in payload:
        crc[0] ^= int(byte)
        for _pass in range(2):
            accumulator = 0
            for offset in (3, 2, 1, 0):
                memory = crc[offset]
                crc[offset] = ((accumulator & 0x0F) << 4) | (memory >> 4)
                accumulator = (accumulator & 0xF0) | (memory & 0x0F)
            row = NIBBLE_TABLE[accumulator].to_bytes(4, "little")
            for offset in range(4):
                crc[offset] ^= row[offset]
    return int.from_bytes(bytes(value ^ 0xFF for value in crc), "little")


def validate_table() -> dict[str, object]:
    generated = []
    for nibble in range(TABLE_ENTRIES):
        value = nibble
        for _bit in range(4):
            value = (value >> 1) ^ (0xEDB88320 if value & 1 else 0)
        generated.append(value)
    if tuple(generated) != NIBBLE_TABLE:
        raise CrcNibbleSiblingBuildError("nibble table is not derived from EDB88320")
    encoded = b"".join(value.to_bytes(4, "little") for value in NIBBLE_TABLE)
    if len(encoded) != TABLE_BYTES:
        raise CrcNibbleSiblingBuildError("nibble table is not exactly 64 bytes")
    return {
        "entries": TABLE_ENTRIES,
        "bytes": TABLE_BYTES,
        "alignment": TABLE_ALIGNMENT,
        "polynomial": "edb88320",
        "little_endian_sha256": sha256_bytes(encoded),
        "derived_exact": True,
    }


def validate_differential_vectors() -> dict[str, object]:
    baseline = register.validate_differential_vectors()
    records = []
    for order, payload in enumerate(register.deterministic_vectors()):
        expected = zlib.crc32(payload) & 0xFFFFFFFF
        actual = nibble_crc32(payload)
        if actual != expected:
            raise CrcNibbleSiblingBuildError(
                f"nibble CRC differential failed for vector {order}: "
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
    if nibble_crc32(b"123456789") != 0xCBF43926:
        raise CrcNibbleSiblingBuildError("ISO-HDLC check vector changed")
    return {
        "algorithm": "CRC-32/ISO-HDLC reflected 4-bit table",
        "polynomial": "edb88320",
        "init": "ffffffff",
        "xorout": "ffffffff",
        "count": len(records),
        "digest_sha256": sha256_bytes(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        ),
        "same_payload_set_as_register_sibling": (
            len(records) == baseline["count"]
        ),
        "vectors": records,
    }


def validate_corpus_crc(
    *,
    manifest_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    root = RUNTIME_FIXTURE if root is None else root
    baseline = register.validate_corpus_crc(
        manifest_path=manifest_path,
        root=root,
    )
    records = []
    for record in baseline["records"]:
        path = root / str(record["path"])
        payload = path.read_bytes()
        data_bytes = int(record["data_bytes"])
        data = payload[
            register.P3DM_DATA_OFFSET : register.P3DM_DATA_OFFSET + data_bytes
        ]
        stored = int(str(record["stored_crc32"]), 16)
        actual = nibble_crc32(data)
        if actual != stored:
            raise CrcNibbleSiblingBuildError(
                f"nibble CRC corpus mismatch: {record['path']}"
            )
        negative = record["negative_single_bit"]
        corrupted = bytearray(data)
        corrupted[int(negative["data_offset"])] ^= int(negative["mask"])
        corrupt_crc = nibble_crc32(corrupted)
        if corrupt_crc == stored:
            raise CrcNibbleSiblingBuildError(
                f"single-bit corruption escaped nibble CRC: {record['path']}"
            )
        records.append(
            {
                "order": record["order"],
                "path": record["path"],
                "data_bytes": data_bytes,
                "stored_crc32": f"{stored:08x}",
                "nibble_crc32": f"{actual:08x}",
                "negative_single_bit": {
                    "data_offset": negative["data_offset"],
                    "mask": negative["mask"],
                    "corrupt_crc32": f"{corrupt_crc:08x}",
                    "rejected": True,
                },
            }
        )
    return {
        "qualified": True,
        "manager_semantics": baseline["manager_semantics"],
        "aggregates": baseline["aggregates"],
        "records": records,
        "coverage_digest_sha256": sha256_bytes(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        ),
        "same_exact_227_record_set_as_register_sibling": True,
        "all_stored_host_nibble_crcs_exact": True,
        "all_single_bit_corruptions_rejected": True,
    }


def validate_instruction_contract() -> dict[str, object]:
    block = CANDIDATE_CRC_BLOCK
    required_order = (
        "ld (p3dm_crc_value+0),a",
        "ld de,p3dm_crc32_nibble_table",
        "ld hl,p3dm_crc_value+3",
        "ld ix,p3dm_file_buffer+p3dm_data_offset",
        "P3DM_LD_U16_BC p3dm_data_size",
        "ld a,(ix)",
        "xor (hl)",
        NIBBLE_PASS,
        NIBBLE_PASS,
        "dec bc",
        "ld b,4\n    ld hl,p3dm_crc_value",
        "jp nz,p3dm_bad_crc32",
        "xor a\n    ret",
        ".align 256",
        "p3dm_crc32_nibble_table:",
    )
    cursor = 0
    for token in required_order:
        position = block.find(token, cursor)
        if position < 0:
            raise CrcNibbleSiblingBuildError(
                f"candidate instruction/error order lost {token!r}"
            )
        cursor = position + len(token)
    forbidden = ("push bc", "pop bc", "exx", "di", "ei")
    instructions = [
        line.strip().split()[0]
        for line in block.splitlines()
        if line.startswith("    ") and line.strip()
    ]
    if (
        "push bc" in block
        or "pop bc" in block
        or any(token in instructions for token in ("exx", "di", "ei"))
    ):
        raise CrcNibbleSiblingBuildError("candidate gained unsafe register/IRQ state")
    if block.count("rrd") != 8 or block.count("add a,a") != 4:
        raise CrcNibbleSiblingBuildError("candidate is not exactly two nibble passes")
    if block.count("ld e,a") != 2 or block.count("ld de,p3dm_crc32_nibble_table") != 1:
        raise CrcNibbleSiblingBuildError("aligned table-base contract changed")
    if block.count("jp nz,p3dm_bad_crc32") != 1:
        raise CrcNibbleSiblingBuildError("descriptor compare failure target changed")
    return {
        "crc_storage_low_to_high": [
            "p3dm_crc_value+0",
            "p3dm_crc_value+1",
            "p3dm_crc_value+2",
            "p3dm_crc_value+3",
        ],
        "outer_counter": "BC, never stacked or shadow-swapped",
        "table_base": "DE upper 16 bits retained; E selects aligned row",
        "data_pointer": "IX increments exactly once per byte",
        "nibble_passes_unrolled": 2,
        "rrd_operations_per_byte": 8,
        "descriptor_compare_order": [0, 1, 2, 3],
        "crc_failure_target": "p3dm_bad_crc32",
        "success_result": "A=0, Z=1",
        "interrupt_mask_unchanged": True,
        "shadow_registers_unchanged": True,
        "asynchronous_handler_caveat": (
            "BC, DE, HL, and IX are live; an interrupt handler must preserve "
            "the interrupted main register set"
        ),
    }


def validate_error_precedence() -> dict[str, object]:
    loader = ACCEPTED_LOADER.read_text(encoding="utf-8")
    witness = register.integrated_policy_witness(
        loader,
        CANDIDATE_CRC_BLOCK,
        CANDIDATE_CRC_BLOCK_SHA256,
        4,
    )
    sequence = (
        "call p3dm_validate_padding\n    ret nz",
        "call p3dm_validate_position_indices\n    ret nz",
        "call p3dm_validate_uv_indices\n    ret nz",
        "call p3dm_validate_crc32\n    ret nz",
        "call p3dm_retain_descriptor",
    )
    positions = [loader.index(token) for token in sequence]
    if positions != sorted(positions):
        raise CrcNibbleSiblingBuildError("index/CRC/publication precedence changed")
    return {
        "call_order": [
            "padding",
            "position_indices",
            "uv_indices",
            "crc32",
            "retain_descriptor",
        ],
        "invalid_position_index_returns_before_crc": True,
        "invalid_uv_index_returns_before_crc": True,
        "descriptor_publication_after_crc": True,
        "shared_loader_unmodified": witness["loader_unmodified"],
    }


def validate_static_design(corpus: Mapping[str, object]) -> dict[str, object]:
    data_bytes = int(corpus["aggregates"]["data_bytes"])
    records = int(corpus["aggregates"]["records"])
    register_polynomial_applications = 0
    for item in corpus["records"]:
        payload = (
            RUNTIME_FIXTURE / str(item["path"])
        ).read_bytes()[
            register.P3DM_DATA_OFFSET :
            register.P3DM_DATA_OFFSET + int(item["data_bytes"])
        ]
        crc = 0xFFFFFFFF
        for byte in payload:
            crc ^= byte
            for _bit in range(8):
                carry = crc & 1
                register_polynomial_applications += carry
                crc = (crc >> 1) ^ (0xEDB88320 if carry else 0)
    register_variable_cycles = (
        152 * data_bytes + 14 * register_polynomial_applications
    )
    register_estimated_cycles = register_variable_cycles + 114 * records
    live_register_cycles = 159_093_967
    live_over_static_model = live_register_cycles - register_estimated_cycles
    nibble_estimated_cycles = 130 * data_bytes + 172 * records
    calibrated_nibble_estimated_cycles = (
        nibble_estimated_cycles + live_over_static_model
    )
    return {
        "basis": "Fab eZ80 memory-fetch/internal-cycle model; no emulator run",
        "candidate_cycles_per_data_byte": 130,
        "fab_rrd_guest_cycles": 4,
        "um0077_rrd_hardware_cycles": 5,
        "candidate_hardware_instruction_baseline_cycles_per_data_byte": 138,
        "hardware_cycle_caveat": (
            "138 adjusts only the eight RRD instructions from Fab's 4-cycle "
            "guest model to UM0077's 5-cycle timing; it is not a complete "
            "physical wait-state or interrupt measurement"
        ),
        "register_cycles_per_data_byte_formula": "152 + 14*k",
        "register_polynomial_applications": register_polynomial_applications,
        "register_mean_k_per_data_byte": (
            register_polynomial_applications / data_bytes
        ),
        "register_variable_cycles": register_variable_cycles,
        "register_fixed_cycles_per_record": 114,
        "register_estimated_cycles": register_estimated_cycles,
        "live_register_cycles_over_static_model": live_over_static_model,
        "candidate_estimated_cycles": nibble_estimated_cycles,
        "candidate_fixed_cycles_per_record": 172,
        "candidate_estimated_reduction_from_live_register_crc_percent": (
            100.0 * (1.0 - nibble_estimated_cycles / live_register_cycles)
        ),
        "candidate_calibrated_cycles_if_live_overhead_is_shared": (
            calibrated_nibble_estimated_cycles
        ),
        "candidate_calibrated_reduction_from_live_register_crc_percent": (
            100.0
            * (1.0 - calibrated_nibble_estimated_cycles / live_register_cycles)
        ),
        "candidate_code_bytes_before_alignment": 165,
        "candidate_alignment_padding_bytes_at_fixed_entry": 148,
        "candidate_table_bytes": TABLE_BYTES,
        "candidate_block_machine_bytes": 377,
        "register_block_machine_bytes": 139,
        "candidate_block_growth_bytes": 238,
        "live_register_crc_cycles_reference": live_register_cycles,
    }


def build_program(
    output: Path,
) -> tuple[Path, Path, Path, dict[str, object], str]:
    register.require_sha256(
        ACCEPTED_SOURCE, register.ACCEPTED_SOURCE_SHA256, "accepted source"
    )
    register.require_sha256(
        ACCEPTED_LOADER, register.ACCEPTED_LOADER_SHA256, "accepted loader"
    )
    register.require_sha256(
        ACCEPTED_RUNTIME_INCLUDE,
        register.ACCEPTED_RUNTIME_INCLUDE_SHA256,
        "accepted runtime include",
    )
    register.require_sha256(
        ACCEPTED_TRANSITION_INCLUDE,
        register.ACCEPTED_TRANSITION_INCLUDE_SHA256,
        "accepted transition include",
    )
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="regular-crc-nibble-build-") as name:
        source, loader = register.stage_source_mirror(Path(name))
        legacy_source = register.select_legacy_control_source(source)
        control_program, _control_listing, _control_symbols = (
            register.assemble_in_mirror(source)
        )
        control_hash = sha256_bytes(control_program)
        if control_hash != register.ACCEPTED_PROGRAM_SHA256:
            raise CrcNibbleSiblingBuildError(
                "temporary control does not reproduce accepted program: "
                f"{control_hash} != {register.ACCEPTED_PROGRAM_SHA256}"
            )
        canonical_loader = loader.read_text(encoding="utf-8")
        source_patch = register.integrated_policy_witness(
            canonical_loader,
            CANDIDATE_CRC_BLOCK,
            CANDIDATE_CRC_BLOCK_SHA256,
            4,
        )
        nibble_source = register.select_crc_policy_source(source, 1, 4)
        if source.read_bytes() != nibble_source:
            raise CrcNibbleSiblingBuildError(
                "temporary nibble-policy source changed"
            )
        if loader.read_text(encoding="utf-8") != canonical_loader:
            raise CrcNibbleSiblingBuildError(
                "temporary integrated loader changed"
            )
        audit = register.audit_candidate(source)
        program_bytes, listing_bytes, symbol_bytes = register.assemble_in_mirror(source)

    program = output / f"{PROGRAM_STEM}.bin"
    listing = output / f"{PROGRAM_STEM}.lst"
    symbols = output / f"{PROGRAM_STEM}.symbols"
    register.atomic_bytes(program, program_bytes)
    register.atomic_bytes(listing, listing_bytes)
    register.atomic_bytes(symbols, symbol_bytes)
    source_patch.update(
        {
            "accepted_source_sha256": register.ACCEPTED_SOURCE_SHA256,
            "temporary_top_level_source_exact": True,
            "temporary_control_crc_policy": "legacy-memory-bitwise",
            "temporary_candidate_crc_policy": "16-entry-rrd-nibble",
            "temporary_control_program_sha256": control_hash,
            "temporary_control_program_exact": True,
            "accepted_files_modified": False,
        }
    )
    return program, listing, symbols, source_patch, audit


def validate_machine_layout(
    program: Path, symbols: Path, static: Mapping[str, object]
) -> dict[str, object]:
    memory = register.validate_memory(program, symbols)
    parsed = register.parse_symbols(symbols)
    table = parsed.get("p3dm_crc32_nibble_table")
    mirror = parsed.get("p3dm_mirror_validated_z")
    if table is None or mirror is None:
        raise CrcNibbleSiblingBuildError("nibble table/mirror symbols are missing")
    if table % TABLE_ALIGNMENT != 0 or mirror - table != TABLE_BYTES:
        raise CrcNibbleSiblingBuildError("nibble table alignment/extent changed")
    image = program.read_bytes()
    encoded_table = b"".join(
        value.to_bytes(4, "little") for value in NIBBLE_TABLE
    )
    offset = table - register.PROGRAM_LOAD_ADDRESS
    if image[offset : offset + TABLE_BYTES] != encoded_table:
        raise CrcNibbleSiblingBuildError("assembled nibble table bytes changed")
    entry = int(memory["p3dm_validate_crc32"])
    if mirror - entry != int(static["candidate_block_machine_bytes"]):
        raise CrcNibbleSiblingBuildError("assembled candidate block size changed")
    memory.update(
        {
            "p3dm_crc32_nibble_table": [table, mirror],
            "p3dm_crc32_nibble_table_alignment": TABLE_ALIGNMENT,
        }
    )
    return memory


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise CrcNibbleSiblingBuildError(
            f"refusing to replace existing output: {output}"
        )
    table = validate_table()
    vectors = validate_differential_vectors()
    corpus = validate_corpus_crc()
    instruction_contract = validate_instruction_contract()
    error_precedence = validate_error_precedence()
    static = validate_static_design(corpus)
    program, listing, symbols, source_patch, audit = build_program(output)
    memory = validate_machine_layout(program, symbols, static)
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "scratch_sibling_only": True,
            "accepted_loader_modified": False,
            "accepted_source_modified": False,
            "accepted_binary_modified": False,
            "accepted_sidecars_modified": False,
            "register_sibling_modified": False,
            "launcher_modified": False,
            "emulator_run": False,
        },
        "artifacts": {
            "program": register.artifact(
                program, key=f"artifacts/{program.name}"
            ),
            "listing": register.artifact(
                listing, key=f"artifacts/{listing.name}"
            ),
            "symbols": register.artifact(
                symbols, key=f"artifacts/{symbols.name}"
            ),
        },
        "accepted_inputs": {
            "source": register.artifact(ACCEPTED_SOURCE),
            "loader": register.artifact(ACCEPTED_LOADER),
            "runtime_include": register.artifact(ACCEPTED_RUNTIME_INCLUDE),
            "transition_include": register.artifact(ACCEPTED_TRANSITION_INCLUDE),
        },
        "source_patch": source_patch,
        "table": table,
        "instruction_contract": instruction_contract,
        "error_precedence": error_precedence,
        "static_design": static,
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
    register.atomic_json(receipt, report)
    print(f"Regular-LOD CRC-nibble sibling build passed: {receipt}")
    print(
        f"program_bytes={program.stat().st_size} "
        f"program_sha256={register.sha256_file(program)} "
        f"records={corpus['aggregates']['records']} "
        f"data_bytes={corpus['aggregates']['data_bytes']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CrcNibbleSiblingBuildError as error:
        raise SystemExit(
            f"regular-LOD CRC-nibble sibling build failed: {error}"
        ) from error
