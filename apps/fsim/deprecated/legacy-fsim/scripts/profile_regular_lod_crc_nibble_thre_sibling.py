#!/usr/bin/env python3
"""Live-qualify CRC-register versus CRC-nibble under one exact THRE MOS.

The control is the already-qualified register-held CRC application and the
candidate is the isolated 16-entry RRD nibble-table application.  Every run
uses the same qualified one-byte THRE MOS sibling.  No accepted source,
program, sidecar, MOS image, or builder is modified.

One fresh normative pair uses only read-call, upload-call, and the matching
``submit_current_render`` call for each record.  The nth successful VDP mesh
publication must occur after its upload boundary and before its own submit
boundary.  A separate fresh pair brackets only ``p3dm_validate_crc32`` entry
and its caller's post-call address, snapshots the final four CRC bytes, and
records final IX for all 227 records.  Two candidate-only negative runs prove
guest error 9 with no publication and error 10 before CRC entry.

The live entry points are deliberately not invoked by the unit tests.  This
profiler must not be launched until the static review gate explicitly clears
it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Mapping, Sequence

import build_regular_lod_crc_nibble_sibling as nibble_builder
import build_regular_lod_crc_register_sibling as register_builder
import profile_regular_lod_crc_mos_uart_thre_combined as combined
import profile_regular_lod_crc_register_sibling as crc_profile
import profile_regular_lod_mos_uart_thre_sibling as mos_profile
import profile_regular_lod_uart_thre_sibling as uart_profile


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTER_BUILD = register_builder.DEFAULT_OUTPUT
DEFAULT_NIBBLE_BUILD = (
    ROOT / "build/evidence/regular-lod-crc-nibble-sibling-build-v2"
)
DEFAULT_MOS_BUILD = mos_profile.builder.DEFAULT_OUTPUT
DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v4"
)
DEFAULT_FAILED_V1_EVIDENCE = (
    ROOT / "build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v1"
)
DEFAULT_RECOVERY_V2_EVIDENCE = (
    ROOT / "build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v2"
)
REPORT_NAME = "regular-lod-crc-nibble-thre-sibling-profile.json"
SCHEMA = "pingo-terrain-regular-lod-crc-nibble-thre-live-profile-v1"
EXPECTED_RECORDS = 227
RECOVERY_NEGATIVE_KINDS = ("crc-data", "index-valid-crc")

# These are the exact scripts used for the failed-v1 and partial-v2 captures.
# The recovery/finalize implementation below necessarily has a new identity,
# so the capture identities are recorded separately instead of being blurred
# into the final analyzer identity.
CAPTURE_PROFILE_SCRIPT_SHA256 = (
    "5852395b301b5761fa3b1929784878df7bb1d28c1cc363fa3a787766ae439455"
)
CAPTURE_SEMANTIC_VALIDATOR_SHA256 = (
    "82dd73e4e72a8b111c71bbe1b1df07ad646b6b9d604172ff7e58cea9f72a2d90"
)

REGISTER_RECEIPT_BYTES = combined.CRC_BUILD_RECEIPT_BYTES
REGISTER_RECEIPT_SHA256 = combined.CRC_BUILD_RECEIPT_SHA256
REGISTER_PROGRAM_BYTES = combined.CRC_PROGRAM_BYTES
REGISTER_PROGRAM_SHA256 = combined.CRC_PROGRAM_SHA256
REGISTER_LISTING_BYTES = combined.CRC_LISTING_BYTES
REGISTER_LISTING_SHA256 = combined.CRC_LISTING_SHA256
REGISTER_SYMBOLS_BYTES = combined.CRC_SYMBOLS_BYTES
REGISTER_SYMBOLS_SHA256 = combined.CRC_SYMBOLS_SHA256
NIBBLE_RECEIPT_BYTES = 90_683
NIBBLE_RECEIPT_SHA256 = (
    "81158c512d31cfd0c7cd85af30e747953d7e4e8d73f9665f439a7cf56cb481d1"
)
NIBBLE_PROGRAM_BYTES = 142_988
NIBBLE_PROGRAM_SHA256 = (
    "ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8"
)
NIBBLE_LISTING_BYTES = 2_297_722
NIBBLE_LISTING_SHA256 = (
    "b882db07ee3fd7c30bbf72b1dc0d9aa1a1140e6a3711fee1529b43e06b88d495"
)
NIBBLE_SYMBOLS_BYTES = 66_020
NIBBLE_SYMBOLS_SHA256 = (
    "c8d57dccf41ef5cf7e057af8d9ff3d0b33c9f9b540f00c64f8f282da66d3a551"
)
RECOVERED_SYMBOL_IDENTITIES = {
    "crc-register-thre-control": (
        65_971,
        "ca1d7e0324388a71ffd74b6b55c9fc000000bc8fc136a88505c64b85ab13efbd",
    ),
    "crc-nibble-thre-candidate": (NIBBLE_SYMBOLS_BYTES, NIBBLE_SYMBOLS_SHA256),
}
NIBBLE_CORPUS_DIGEST_SHA256 = (
    "ae068d40838e5e2f04fc48cbddd18a383d902618c69ddf9ab50f80c54d1bf089"
)

MOS_RECEIPT_BYTES = combined.MOS_BUILD_RECEIPT_BYTES
MOS_RECEIPT_SHA256 = combined.MOS_BUILD_RECEIPT_SHA256
THRE_MOS_SHA256 = combined.PATCHED_MOS_SHA256
PINNED_MAP_SHA256 = combined.PINNED_MAP_SHA256


FAILED_V1_EVIDENCE_MANIFEST = {
    "normative-crc-register-thre-control/P3DRGL.crc-register-thre-control.bin": (
        142_750,
        "a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992",
    ),
    "normative-crc-register-thre-control/P3DRGL.crc-register-thre-control.symbols": (
        65_971,
        "ca1d7e0324388a71ffd74b6b55c9fc000000bc8fc136a88505c64b85ab13efbd",
    ),
    "normative-crc-register-thre-control/autoexec.txt": (
        50,
        "9f6405f015f45625cea87a16c3468ec5ebd79ea95fe512a5b92d05ac107629d4",
    ),
    "normative-crc-register-thre-control/command.json": (
        2_821,
        "0bbe0f3ba2155860f5494c616f129346e4820f8026d1388e96078618fd82ce02",
    ),
    "normative-crc-register-thre-control/emulator.log": (
        153_392,
        "7c64e8b28a5ccb8ac11cbd036db40a2c551dbbc05f95c7808c3403fdb736530f",
    ),
    "normative-crc-register-thre-control/mos_console8_uart_thre_candidate.bin": (
        81_072,
        "c8c347a7c04af35d6be51e0c85c5b50e689d923da39992d42880f4e88eba968c",
    ),
    "normative-crc-register-thre-control/mos_console8_uart_thre_candidate.map": (
        153_448,
        "2d3fb36ec90a073d4e0f5f665f75bd788338275906ffc07309c83e969d0368b0",
    ),
}


def _positive_evidence_manifest() -> dict[str, tuple[int, str]]:
    repeated = {
        "autoexec.txt": (
            50,
            "9f6405f015f45625cea87a16c3468ec5ebd79ea95fe512a5b92d05ac107629d4",
        ),
        "mos_console8_uart_thre_candidate.bin": (
            81_072,
            "c8c347a7c04af35d6be51e0c85c5b50e689d923da39992d42880f4e88eba968c",
        ),
        "mos_console8_uart_thre_candidate.map": (
            153_448,
            "2d3fb36ec90a073d4e0f5f665f75bd788338275906ffc07309c83e969d0368b0",
        ),
    }
    variants = {
        "crc-register-thre-control": {
            "P3DRGL.crc-register-thre-control.bin": (
                142_750,
                "a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992",
            ),
            "P3DRGL.crc-register-thre-control.symbols": (
                65_971,
                "ca1d7e0324388a71ffd74b6b55c9fc000000bc8fc136a88505c64b85ab13efbd",
            ),
        },
        "crc-nibble-thre-candidate": {
            "P3DRGL.crc-nibble-thre-candidate.bin": (
                142_988,
                "ae0a45869dde58e44bcdad82e0294c937c1ff81df1ce4aba142d2e60983812c8",
            ),
            "P3DRGL.crc-nibble-thre-candidate.symbols": (
                66_020,
                "c8d57dccf41ef5cf7e057af8d9ff3d0b33c9f9b540f00c64f8f282da66d3a551",
            ),
        },
    }
    captures = {
        ("normative", "crc-register-thre-control"): {
            "command.json": (
                2_821,
                "fe33085d2a3bf7804209770fb0fe399a643c0d1767ad8bd61cf05874f1c7e69c",
            ),
            "emulator.log": (
                885_159,
                "78cba43ac0ca9a8b4131ba83d09d03296e5f06351461f147b21d35def8b04ea5",
            ),
        },
        ("normative", "crc-nibble-thre-candidate"): {
            "command.json": (
                2_827,
                "80866d5a805c1e15875dadeea559bbbed6c328418d6fad722be9bef16e8a19b9",
            ),
            "emulator.log": (
                884_411,
                "ad500e3baba93656b126649eccb6321abce6ffe560c11aa7dadf1697db86dfd7",
            ),
        },
        ("inner", "crc-register-thre-control"): {
            "command.json": (
                2_744,
                "e14d5029901bd7edf476b646c4d7e2559c80088665b11ef5f8743d0fdbd6b2bd",
            ),
            "emulator.log": (
                774_197,
                "5ad40ebf48d1efbd8653df2612c2e508af910fee3cd4bd766ecba7b210569a21",
            ),
        },
        ("inner", "crc-nibble-thre-candidate"): {
            "command.json": (
                2_750,
                "d4940ce1bf6942abfd6fb753e31dc888b97c1241421349d61a253e1fb874b448",
            ),
            "emulator.log": (
                773_473,
                "01ccbc45f4872c1a19cd4f025e2d20032adee47b8a6f3dd61a7b1b892f6c63b3",
            ),
        },
    }
    manifest: dict[str, tuple[int, str]] = {}
    for (mode, variant), unique in captures.items():
        directory = f"{mode}-{variant}"
        for name, identity in {**repeated, **variants[variant], **unique}.items():
            manifest[f"{directory}/{name}"] = identity
    return manifest


RECOVERY_V2_EVIDENCE_MANIFEST = _positive_evidence_manifest()


class CrcNibbleThreProfileError(RuntimeError):
    """A qualified input, layout, transcript, semantic, or timing gate failed."""


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    role: str
    register_resident: bool
    program: Path
    program_bytes: int
    program_sha256: str
    symbols: Path
    symbols_bytes: int
    symbols_sha256: str


@dataclass(frozen=True, slots=True)
class QualifiedInputs:
    control: Variant
    candidate: Variant
    register_receipt: Path
    nibble_receipt: Path
    mos_receipt: Path
    thre_mos: Path
    identity: Mapping[str, Mapping[str, object]]
    composition: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StagedRun:
    directory: Path
    program: Path
    symbols: Path
    mos: Path
    mos_map: Path


@dataclass(frozen=True, slots=True)
class InnerLayout:
    crc_entry: int
    crc_post: int
    crc_value: int
    file_buffer: int
    return_error: int

    @property
    def events(self) -> tuple[tuple[str, int], ...]:
        return (("crc_entry", self.crc_entry), ("crc_post", self.crc_post))

    @property
    def breakpoints(self) -> tuple[int, ...]:
        addresses = tuple(address for _name, address in self.events)
        if len(addresses) != len(set(addresses)):
            raise CrcNibbleThreProfileError("inner CRC boundaries are not unique")
        return addresses

    def as_dict(self) -> dict[str, object]:
        return {
            "events": [
                {"name": name, "address": address}
                for name, address in self.events
            ],
            "crc_value": self.crc_value,
            "file_buffer": self.file_buffer,
            "return_error": self.return_error,
        }


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--register-build", type=Path, default=DEFAULT_REGISTER_BUILD
    )
    parser.add_argument("--nibble-build", type=Path, default=DEFAULT_NIBBLE_BUILD)
    parser.add_argument("--mos-build", type=Path, default=DEFAULT_MOS_BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--recover-positive-evidence",
        type=Path,
        help=(
            "revalidate the exact immutable four-positive v2 tree and run only "
            "the two missing negatives into a new output root"
        ),
    )
    parser.add_argument(
        "--failed-v1-evidence",
        type=Path,
        default=DEFAULT_FAILED_V1_EVIDENCE,
        help="immutable failed-v1 tree disclosed by recovery/finalize mode",
    )
    parser.add_argument(
        "--vdp-module", type=Path, default=mos_profile.survey.DEFAULT_VDP
    )
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, *, key: str | None = None) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise CrcNibbleThreProfileError(f"missing artifact: {resolved}")
    if key is None:
        try:
            key = str(resolved.relative_to(ROOT))
        except ValueError:
            key = resolved.name
    return {
        "key": key,
        "bytes": resolved.stat().st_size,
        "sha256": sha256(resolved),
    }


def require_file(
    path: Path, expected_bytes: int, expected_sha256: str, description: str
) -> Path:
    if (
        not path.is_file()
        or path.stat().st_size != expected_bytes
        or sha256(path) != expected_sha256
    ):
        actual_bytes = path.stat().st_size if path.is_file() else None
        actual_sha256 = sha256(path) if path.is_file() else None
        raise CrcNibbleThreProfileError(
            f"{description} identity changed: bytes={actual_bytes} "
            f"sha256={actual_sha256}"
        )
    return path


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrcNibbleThreProfileError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CrcNibbleThreProfileError(f"JSON root is not an object: {path}")
    return value


def validate_nibble_build(build: Path) -> tuple[Path, Path, Path, Path]:
    receipt_path = require_file(
        build / "BUILD.json",
        NIBBLE_RECEIPT_BYTES,
        NIBBLE_RECEIPT_SHA256,
        "qualified current CRC-nibble BUILD receipt",
    )
    receipt = load_json(receipt_path)
    if receipt.get("schema") != nibble_builder.SCHEMA or receipt.get(
        "qualified"
    ) is not True:
        raise CrcNibbleThreProfileError("CRC-nibble BUILD is not qualified")
    scope = receipt.get("scope")
    false_scope = (
        "accepted_loader_modified",
        "accepted_source_modified",
        "accepted_binary_modified",
        "accepted_sidecars_modified",
        "register_sibling_modified",
        "launcher_modified",
        "emulator_run",
    )
    if not isinstance(scope, dict) or any(
        scope.get(name) is not False for name in false_scope
    ) or scope.get("scratch_sibling_only") is not True:
        raise CrcNibbleThreProfileError("CRC-nibble BUILD scope changed")
    paths = {
        "program": build / f"{nibble_builder.PROGRAM_STEM}.bin",
        "listing": build / f"{nibble_builder.PROGRAM_STEM}.lst",
        "symbols": build / f"{nibble_builder.PROGRAM_STEM}.symbols",
    }
    identities = {
        "program": (NIBBLE_PROGRAM_BYTES, NIBBLE_PROGRAM_SHA256),
        "listing": (NIBBLE_LISTING_BYTES, NIBBLE_LISTING_SHA256),
        "symbols": (NIBBLE_SYMBOLS_BYTES, NIBBLE_SYMBOLS_SHA256),
    }
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CrcNibbleThreProfileError("CRC-nibble artifacts are missing")
    for name, path in paths.items():
        size, digest = identities[name]
        require_file(path, size, digest, f"CRC-nibble {name}")
        if artifacts.get(name) != {
            "key": f"artifacts/{path.name}",
            "bytes": size,
            "sha256": digest,
        }:
            raise CrcNibbleThreProfileError(
                f"CRC-nibble receipt {name} binding changed"
            )
    patch = receipt.get("source_patch")
    if not isinstance(patch, dict) or (
        patch.get("canonical_block_sha256")
        != nibble_builder.CANONICAL_CRC_BLOCK_SHA256
        or patch.get("candidate_block_sha256")
        != nibble_builder.CANDIDATE_CRC_BLOCK_SHA256
        or patch.get("temporary_control_program_sha256")
        != register_builder.ACCEPTED_PROGRAM_SHA256
        or patch.get("temporary_control_program_exact") is not True
        or patch.get("reverse_substitution_exact") is not True
    ):
        raise CrcNibbleThreProfileError("CRC-nibble source/control binding changed")
    host = receipt.get("host_differential")
    corpus = receipt.get("cold_corpus_crc")
    if not isinstance(host, dict) or (
        host.get("count") != 30
        or host.get("digest_sha256")
        != register_builder.EXPECTED_VECTOR_DIGEST_SHA256
    ):
        raise CrcNibbleThreProfileError("CRC-nibble host vectors changed")
    if not isinstance(corpus, dict) or (
        corpus.get("qualified") is not True
        or corpus.get("coverage_digest_sha256") != NIBBLE_CORPUS_DIGEST_SHA256
        or corpus.get("aggregates", {}).get("records") != EXPECTED_RECORDS
        or corpus.get("aggregates", {}).get("data_bytes") != 764_288
        or corpus.get("all_stored_host_nibble_crcs_exact") is not True
        or corpus.get("all_single_bit_corruptions_rejected") is not True
    ):
        raise CrcNibbleThreProfileError("CRC-nibble corpus gates changed")
    table = receipt.get("table")
    instruction = receipt.get("instruction_contract")
    static = receipt.get("static_design")
    precedence = receipt.get("error_precedence")
    if not isinstance(table, dict) or (
        table.get("entries") != 16
        or table.get("bytes") != 64
        or table.get("alignment") != 256
        or table.get("little_endian_sha256")
        != "9af680c2988bbb73e930ba9b2e9a51a28303c3add723b5685f2d5e9a9d1eb8a8"
    ):
        raise CrcNibbleThreProfileError("CRC-nibble table contract changed")
    if not isinstance(instruction, dict) or (
        instruction.get("nibble_passes_unrolled") != 2
        or instruction.get("rrd_operations_per_byte") != 8
        or instruction.get("interrupt_mask_unchanged") is not True
        or instruction.get("shadow_registers_unchanged") is not True
        or "BC, DE, HL, and IX"
        not in str(instruction.get("asynchronous_handler_caveat"))
    ):
        raise CrcNibbleThreProfileError("CRC-nibble instruction contract changed")
    if not isinstance(static, dict) or (
        static.get("candidate_cycles_per_data_byte") != 130
        or static.get("fab_rrd_guest_cycles") != 4
        or static.get("um0077_rrd_hardware_cycles") != 5
        or static.get("candidate_hardware_instruction_baseline_cycles_per_data_byte")
        != 138
    ):
        raise CrcNibbleThreProfileError("CRC-nibble timing caveat changed")
    expected_precedence = [
        "padding",
        "position_indices",
        "uv_indices",
        "crc32",
        "retain_descriptor",
    ]
    if not isinstance(precedence, dict) or (
        precedence.get("call_order") != expected_precedence
        or precedence.get("invalid_position_index_returns_before_crc") is not True
        or precedence.get("invalid_uv_index_returns_before_crc") is not True
        or precedence.get("descriptor_publication_after_crc") is not True
    ):
        raise CrcNibbleThreProfileError("CRC-nibble error precedence changed")
    memory = receipt.get("memory")
    if not isinstance(memory, dict) or (
        memory.get("p3dm_validate_crc32") != 0x0437C7
        or memory.get("p3dm_validate_crc32_end") != 0x043940
        or memory.get("p3dm_crc32_nibble_table") != [0x043900, 0x043940]
    ):
        raise CrcNibbleThreProfileError("CRC-nibble machine layout changed")
    adl = receipt.get("adl_audit")
    if not isinstance(adl, dict) or (
        adl.get("command_succeeded") is not True
        or adl.get("follow_includes") is not True
        or adl.get("fail_review") is not True
    ):
        raise CrcNibbleThreProfileError("CRC-nibble ADL audit changed")
    return paths["program"], paths["symbols"], paths["listing"], receipt_path


def validate_inputs(
    register_build: Path, nibble_build: Path, mos_build: Path
) -> QualifiedInputs:
    register_build = register_build.expanduser().resolve()
    nibble_build = nibble_build.expanduser().resolve()
    mos_build = mos_build.expanduser().resolve()
    register_program, register_symbols, register_listing, register_receipt = (
        combined.validate_crc_build(register_build)
    )
    nibble_program, nibble_symbols, nibble_listing, nibble_receipt = (
        validate_nibble_build(nibble_build)
    )
    _temt_mos, thre_mos, mos_receipt = combined.validate_mos_build(mos_build)
    mos_profile.builder.require_accepted_inputs()
    mos_profile.builder.validate_pinned_contract()
    mos_profile.builder.validate_reference_source_context()
    mos_profile.builder.validate_runtime_corpus()
    require_file(
        thre_mos,
        mos_profile.builder.PINNED_MOS_BYTES,
        THRE_MOS_SHA256,
        "qualified THRE MOS",
    )
    variants = (
        (
            register_program,
            register_symbols,
            REGISTER_PROGRAM_SHA256,
            0x04396C,
            0x043AF3,
        ),
        (
            nibble_program,
            nibble_symbols,
            NIBBLE_PROGRAM_SHA256,
            0x043A5A,
            0x043BE1,
        ),
    )
    uart_evidence = []
    for program, symbols, digest, sender_call, file_buffer in variants:
        layout = uart_profile.resolve_layout(program, symbols, candidate=False)
        symbol_values = mos_profile.staged.parse_symbols(symbols)
        local = sorted(
            name for name in symbol_values if name.startswith("p3dm_uart0_")
        )
        if (
            sha256(program) != digest
            or layout.sender_call != sender_call
            or layout.file_buffer != file_buffer
            or layout.sender_kind != "Console8 RST18 counted DATA write"
            or local
        ):
            raise CrcNibbleThreProfileError(
                "application gained a UART patch or shifted unexpectedly"
            )
        uart_evidence.append(
            {
                "program_sha256": digest,
                "sender_call": sender_call,
                "file_buffer": file_buffer,
                "sender_kind": layout.sender_kind,
                "application_local_uart_symbols": local,
            }
        )
    identity_paths = {
        "register_build_receipt": register_receipt,
        "register_program": register_program,
        "register_symbols": register_symbols,
        "register_listing": register_listing,
        "nibble_build_receipt": nibble_receipt,
        "nibble_program": nibble_program,
        "nibble_symbols": nibble_symbols,
        "nibble_listing": nibble_listing,
        "mos_build_receipt": mos_receipt,
        "thre_mos": thre_mos,
        "pinned_map": mos_profile.builder.PINNED_MAP,
        "manager_manifest": mos_profile.builder.MANAGER_MANIFEST,
        "world_manifest": mos_profile.builder.WORLD_MANIFEST,
    }
    return QualifiedInputs(
        control=Variant(
            name="crc-register-thre-control",
            role="qualified register-held CRC + qualified THRE MOS",
            register_resident=True,
            program=register_program,
            program_bytes=REGISTER_PROGRAM_BYTES,
            program_sha256=REGISTER_PROGRAM_SHA256,
            symbols=register_symbols,
            symbols_bytes=REGISTER_SYMBOLS_BYTES,
            symbols_sha256=REGISTER_SYMBOLS_SHA256,
        ),
        candidate=Variant(
            name="crc-nibble-thre-candidate",
            role="qualified 16-entry RRD nibble CRC + qualified THRE MOS",
            register_resident=False,
            program=nibble_program,
            program_bytes=NIBBLE_PROGRAM_BYTES,
            program_sha256=NIBBLE_PROGRAM_SHA256,
            symbols=nibble_symbols,
            symbols_bytes=NIBBLE_SYMBOLS_BYTES,
            symbols_sha256=NIBBLE_SYMBOLS_SHA256,
        ),
        register_receipt=register_receipt,
        nibble_receipt=nibble_receipt,
        mos_receipt=mos_receipt,
        thre_mos=thre_mos,
        identity={name: artifact(path) for name, path in identity_paths.items()},
        composition={
            "application_pair": "qualified CRC-register versus CRC-nibble",
            "mos_pair": "the exact same qualified THRE MOS image",
            "thre_mos_sha256_both_variants": THRE_MOS_SHA256,
            "third_code_patch": False,
            "accepted_program_used_as_runtime_variant": False,
            "register_crc_block_sha256": register_builder.CANDIDATE_CRC_BLOCK_SHA256,
            "nibble_crc_block_sha256": nibble_builder.CANDIDATE_CRC_BLOCK_SHA256,
            "canonical_crc_block_sha256": nibble_builder.CANONICAL_CRC_BLOCK_SHA256,
            "uart_evidence": uart_evidence,
        },
    )


EXPECTED_LAYOUTS = {
    REGISTER_PROGRAM_SHA256: {
        "read_call": 0x043067,
        "upload_call": 0x04307B,
        "submit_target": 0x042E27,
        "startup_submit_call": 0x0629B4,
        "loop_submit_call": 0x0629FC,
        "startup_window": "cd272e04cd6c0004",
        "loop_window": "cd272e0418b6cde7",
        "inner": {
            "crc_entry": 0x0437C7,
            "crc_post": 0x0435EA,
            "crc_value": 0x043AC5,
            "file_buffer": 0x043AF3,
            "return_error": 0x043A2D,
        },
    },
    NIBBLE_PROGRAM_SHA256: {
        "read_call": 0x043067,
        "upload_call": 0x04307B,
        "submit_target": 0x042E27,
        "startup_submit_call": 0x062AA2,
        "loop_submit_call": 0x062AEA,
        "startup_window": "cd272e04cd6c0004",
        "loop_window": "cd272e0418b6cdd5",
        "inner": {
            "crc_entry": 0x0437C7,
            "crc_post": 0x0435EA,
            "crc_value": 0x043BB3,
            "file_buffer": 0x043BE1,
            "return_error": 0x043B1B,
        },
    },
}


def _offsets(payload: bytes, needle: bytes) -> list[int]:
    result = []
    cursor = 0
    while True:
        offset = payload.find(needle, cursor)
        if offset < 0:
            return result
        result.append(offset)
        cursor = offset + 1


def resolve_normative_layout(
    program: Path, symbols_path: Path
) -> mos_profile.NormativeLayout:
    digest = sha256(program)
    expected = EXPECTED_LAYOUTS.get(digest)
    if expected is None:
        raise CrcNibbleThreProfileError("normative program is not qualified")
    symbols = mos_profile.staged.parse_symbols(symbols_path)
    phases = mos_profile.cold.resolve_phase_spans(program, symbols)
    by_name = {phase.name: phase for phase in phases}
    required = {"main", "manager_survey_apply_radius_request", "submit_current_render"}
    missing = sorted(required - symbols.keys())
    if missing:
        raise CrcNibbleThreProfileError(f"normative symbols omit: {missing}")
    target = symbols["submit_current_render"]
    if target != expected["submit_target"]:
        raise CrcNibbleThreProfileError("submit_current_render target changed")
    image = program.read_bytes()
    load = mos_profile.PROGRAM_LOAD_ADDRESS
    main_start = symbols["main"]
    main_end = symbols["manager_survey_apply_radius_request"]
    if not load <= main_start < main_end <= load + len(image):
        raise CrcNibbleThreProfileError("main body escaped qualified program")
    body = image[main_start - load : main_end - load]
    encoded = bytes((0xCD,)) + target.to_bytes(3, "little")
    calls = [main_start + offset for offset in _offsets(body, encoded)]
    wanted = [expected["startup_submit_call"], expected["loop_submit_call"]]
    if calls != wanted:
        raise CrcNibbleThreProfileError(f"own-image submit sites changed: {calls}")
    for name in ("startup", "loop"):
        address = int(expected[f"{name}_submit_call"])
        window = bytes.fromhex(str(expected[f"{name}_window"]))
        if image[address - load : address - load + len(window)] != window:
            raise CrcNibbleThreProfileError(
                f"{name} submit opcode window changed at 0x{address:06x}"
            )
    layout = mos_profile.NormativeLayout(
        read_call=by_name["read_container_fatfs"].call,
        upload_call=by_name["upload_vdu_staging"].call,
        startup_submit_call=int(expected["startup_submit_call"]),
        loop_submit_call=int(expected["loop_submit_call"]),
    )
    if (
        layout.read_call != expected["read_call"]
        or layout.upload_call != expected["upload_call"]
    ):
        raise CrcNibbleThreProfileError("read/upload boundaries changed")
    layout.breakpoints
    return layout


def resolve_inner_layout(program: Path, symbols_path: Path) -> InnerLayout:
    digest = sha256(program)
    expected = EXPECTED_LAYOUTS.get(digest)
    if expected is None or not isinstance(expected.get("inner"), dict):
        raise CrcNibbleThreProfileError("inner CRC program is not qualified")
    full = crc_profile.resolve_layout(program, symbols_path)
    layout = InnerLayout(
        crc_entry=full.crc_entry,
        crc_post=full.crc_post,
        crc_value=full.crc_value,
        file_buffer=full.file_buffer,
        return_error=full.return_error,
    )
    if layout.as_dict() != {
        "events": [
            {"name": "crc_entry", "address": expected["inner"]["crc_entry"]},
            {"name": "crc_post", "address": expected["inner"]["crc_post"]},
        ],
        "crc_value": expected["inner"]["crc_value"],
        "file_buffer": expected["inner"]["file_buffer"],
        "return_error": expected["inner"]["return_error"],
    }:
        raise CrcNibbleThreProfileError("own-image inner CRC layout changed")
    layout.breakpoints
    return layout


def layout_evidence(
    program: Path, layout: mos_profile.NormativeLayout | InnerLayout
) -> dict[str, object]:
    value = layout.as_dict()
    value.update(
        {
            "program_sha256": sha256(program),
            "resolved_from_own_program_and_symbols": True,
            "expected_identity": EXPECTED_LAYOUTS[sha256(program)],
        }
    )
    return value


def prepare_run_output(
    output: Path, mode: str, variant: Variant, thre_mos: Path
) -> StagedRun:
    directory = output / f"{mode}-{variant.name}"
    directory.mkdir()
    program = directory / f"P3DRGL.{variant.name}.bin"
    symbols = directory / f"P3DRGL.{variant.name}.symbols"
    mos = directory / thre_mos.name
    mos_map = mos.with_suffix(".map")
    shutil.copyfile(variant.program, program)
    shutil.copyfile(variant.symbols, symbols)
    shutil.copyfile(thre_mos, mos)
    shutil.copyfile(mos_profile.builder.PINNED_MAP, mos_map)
    mos_profile.write_exact_autoexec(directory / "autoexec.txt")
    staged_run = StagedRun(directory, program, symbols, mos, mos_map)
    validate_staged_run(staged_run, variant)
    return staged_run


def validate_staged_run(
    staged_run: StagedRun, variant: Variant, *, recovered_evidence: bool = False
) -> None:
    require_file(
        staged_run.program,
        variant.program_bytes,
        variant.program_sha256,
        "run-local program",
    )
    symbol_bytes, symbol_sha256 = (
        RECOVERED_SYMBOL_IDENTITIES[variant.name]
        if recovered_evidence
        else (variant.symbols_bytes, variant.symbols_sha256)
    )
    require_file(
        staged_run.symbols,
        symbol_bytes,
        symbol_sha256,
        "run-local symbols",
    )
    require_file(
        staged_run.mos,
        mos_profile.builder.PINNED_MOS_BYTES,
        THRE_MOS_SHA256,
        "run-local THRE MOS",
    )
    require_file(
        staged_run.mos_map,
        mos_profile.builder.PINNED_MAP_BYTES,
        PINNED_MAP_SHA256,
        "run-local same-stem MOS map",
    )
    autoexec = staged_run.directory / "autoexec.txt"
    require_file(
        autoexec,
        len(mos_profile.AUTOEXEC),
        mos_profile.AUTOEXEC_SHA256,
        "run-local autoexec",
    )
    if autoexec.read_bytes() != mos_profile.AUTOEXEC:
        raise CrcNibbleThreProfileError("run-local autoexec bytes changed")


def validate_immutable_evidence_tree(
    root: Path,
    manifest: Mapping[str, tuple[int, str]],
    description: str,
) -> dict[str, object]:
    """Require one exact immutable evidence tree, including its file set."""

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise CrcNibbleThreProfileError(f"missing {description}: {root}")
    entries = list(root.rglob("*"))
    links = sorted(str(path.relative_to(root)) for path in entries if path.is_symlink())
    if links:
        raise CrcNibbleThreProfileError(f"{description} contains links: {links}")
    actual_files = sorted(
        str(path.relative_to(root)) for path in entries if path.is_file()
    )
    expected_files = sorted(manifest)
    if actual_files != expected_files:
        raise CrcNibbleThreProfileError(
            f"{description} file set changed: actual={actual_files}"
        )
    expected_directories = sorted(
        {
            str(parent)
            for name in manifest
            for parent in Path(name).parents
            if str(parent) != "."
        }
    )
    actual_directories = sorted(
        str(path.relative_to(root)) for path in entries if path.is_dir()
    )
    if actual_directories != expected_directories:
        raise CrcNibbleThreProfileError(
            f"{description} directory set changed: actual={actual_directories}"
        )
    digest = hashlib.sha256()
    files = []
    for name in expected_files:
        size, expected_sha256 = manifest[name]
        path = require_file(root / name, size, expected_sha256, f"{description} {name}")
        evidence = artifact(path)
        files.append(evidence)
        digest.update(
            f"{name}\0{size}\0{expected_sha256}\n".encode("utf-8")
        )
    return {
        "root": str(root),
        "file_count": len(files),
        "tree_digest_sha256": digest.hexdigest(),
        "files": files,
        "exact_file_and_directory_set": True,
        "all_file_bytes_and_sha256_exact": True,
    }


def recovered_staged_run(
    root: Path, mode: str, variant: Variant, thre_mos: Path
) -> StagedRun:
    directory = root / f"{mode}-{variant.name}"
    staged_run = StagedRun(
        directory=directory,
        program=directory / f"P3DRGL.{variant.name}.bin",
        symbols=directory / f"P3DRGL.{variant.name}.symbols",
        mos=directory / thre_mos.name,
        mos_map=(directory / thre_mos.name).with_suffix(".map"),
    )
    validate_staged_run(staged_run, variant, recovered_evidence=True)
    return staged_run


def validate_recovered_command(
    staged_run: StagedRun,
    variant: Variant,
    mode: str,
    layout: mos_profile.NormativeLayout | InnerLayout,
) -> None:
    command = load_json(staged_run.directory / "command.json")
    expected_mode = (
        "normative-publication-complete"
        if mode == "normative"
        else "direct-inner-crc-entry-post"
    )
    if (
        command.get("mode") != expected_mode
        or command.get("variant") != variant.name
        or command.get("program") != artifact(staged_run.program)
        or command.get("symbols") != artifact(staged_run.symbols)
        or command.get("mos") != artifact(staged_run.mos)
        or command.get("mos_map") != artifact(staged_run.mos_map)
        or command.get("layout") != layout_evidence(staged_run.program, layout)
    ):
        raise CrcNibbleThreProfileError(
            f"recovered {mode} {variant.name} command binding changed"
        )


def run_normative(
    variant: Variant,
    *,
    thre_mos: Path,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    staged_run = prepare_run_output(output, "normative", variant, thre_mos)
    layout = resolve_normative_layout(staged_run.program, staged_run.symbols)
    log_path = staged_run.directory / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: mos_profile.NormativeProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"nibble-norm-{variant.name}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"nibble-norm-{variant.name}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        mos_profile.staged.stage_fixture(sd_root, staged_run.program)
        corpus_before = mos_profile.builder.validate_runtime_corpus(sd_root / "survey")
        mos_profile.write_exact_autoexec(sd_root / "autoexec.txt")
        command = mos_profile.emulator_command(
            sd_root, vdp, staged_run.mos, THRE_MOS_SHA256, layout.breakpoints
        )
        (staged_run.directory / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "normative-publication-complete",
                    "variant": variant.name,
                    "role": variant.role,
                    "program": artifact(staged_run.program),
                    "symbols": artifact(staged_run.symbols),
                    "mos": artifact(staged_run.mos),
                    "mos_map": artifact(staged_run.mos_map),
                    "layout": layout_evidence(staged_run.program, layout),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=cwd_name,
                    env=mos_profile.emulator_environment(),
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                profiler = mos_profile.NormativeProfiler(
                    process, layout, EXPECTED_RECORDS
                )
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: (
                        mos_profile.staged.COLD_RENDER_MARKER in value
                        and profiler.complete
                    ),
                    f"{variant.name} normative cold fill",
                    service=profiler.service,
                )
                profiler.require_complete()
                mos_profile.shutdown(process, log_path, deadline)
                corpus_after = mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                if corpus_after != corpus_before:
                    raise CrcNibbleThreProfileError(
                        f"{variant.name} corpus changed during normative run"
                    )
        finally:
            if process is not None and process.poll() is None:
                mos_profile.input_trace.stop_process(process)
    assert (
        process is not None
        and profiler is not None
        and corpus_before is not None
        and corpus_after is not None
    )
    validate_staged_run(staged_run, variant)
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = mos_profile.validate_run_semantics(
        contents
    )
    bound = mos_profile.bind_publications(publications)
    states = mos_profile.parse_normative_states(contents, layout, EXPECTED_RECORDS)
    marker_offsets = mos_profile.publication_marker_offsets(contents)
    records = mos_profile.reconstruct_normative_records(
        states, publications, marker_offsets, bound
    )
    upload_cycles = [
        int(record["upload_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    read_cycles = [
        int(record["read_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    return {
        "mode": "normative-publication-complete",
        "variant": variant.name,
        "role": variant.role,
        "fresh_process": True,
        "program": artifact(staged_run.program),
        "symbols": artifact(staged_run.symbols),
        "mos": artifact(staged_run.mos),
        "mos_map": artifact(staged_run.mos_map),
        "command": artifact(staged_run.directory / "command.json"),
        "autoexec": artifact(staged_run.directory / "autoexec.txt"),
        "log": artifact(log_path),
        "layout": layout_evidence(staged_run.program, layout),
        "live": profiler.require_complete(),
        "runtime_corpus": {
            "before": mos_profile.corpus_witness(corpus_before),
            "after": mos_profile.corpus_witness(corpus_after),
            "unchanged": True,
        },
        "cold_endpoint": endpoint,
        "publication_semantics": mos_profile.publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "metrics": {
            "upload_to_publication_complete_submit": {
                "cycles": upload_cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    upload_cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    upload_cycles[1:]
                ).as_dict(),
                "startup_record_0": upload_cycles[0],
                "completion_equivalent": True,
            },
            "read_to_publication_complete_submit": {
                "cycles": read_cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    read_cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    read_cycles[1:]
                ).as_dict(),
                "startup_record_0": read_cycles[0],
                "completion_equivalent": True,
            },
        },
        "records": records,
        "emulator_exit_status": process.returncode,
    }


class InnerCrcProfiler:
    """Drive two exact CRC boundaries and one four-byte snapshot per record."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        layout: InnerLayout,
        expected_records: int,
    ) -> None:
        self.process = process
        self.layout = layout
        self.events = layout.events
        self.expected_records = expected_records
        self.cursor = 0
        self.event_index = 0
        self.record_index = 0
        self.waiting = "pause"
        self.cycles: list[dict[str, int | str]] = []
        self.crc_memory: list[bytes] = []
        self.complete = False

    def _advance(self) -> None:
        self.event_index += 1
        if self.event_index == len(self.events):
            self.event_index = 0
            self.record_index += 1
        if self.record_index == self.expected_records:
            for address in self.layout.breakpoints:
                crc_profile.debugger.write_debugger(
                    self.process, f"delete 0x{address:x}"
                )
            self.complete = True
        self.waiting = "pause"
        crc_profile.debugger.write_debugger(self.process, "continue")

    def service(self, contents: str) -> None:
        if self.complete:
            return
        expected_name, expected_address = self.events[self.event_index]
        if self.waiting == "pause":
            pause = mos_profile.staged.SELECTOR_PAUSE_RE.search(contents, self.cursor)
            if pause is None:
                return
            candidates = []
            for _name, address in self.events:
                marker = contents.find(f"* {address:06x}:", pause.end())
                if marker >= 0:
                    candidates.append((marker, address))
            if not candidates:
                return
            marker, address = min(candidates)
            if address != expected_address:
                raise CrcNibbleThreProfileError(
                    f"inner order changed at record {self.record_index}: "
                    f"0x{address:06x} != {expected_name}=0x{expected_address:06x}"
                )
            self.cursor = marker + len(f"* {address:06x}:")
            self.waiting = "state"
            crc_profile.debugger.write_debugger(self.process, "state")
            return
        if self.waiting == "state":
            cycles = mos_profile.staged.SELECTOR_CYCLES_RE.search(
                contents, self.cursor
            )
            if cycles is None:
                return
            self.cycles.append(
                {
                    "record": self.record_index,
                    "event": expected_name,
                    "address": expected_address,
                    "cycles_since_previous_boundary": int(cycles.group(1)),
                }
            )
            self.cursor = cycles.end()
            if expected_name == "crc_post":
                self.waiting = "memory"
                crc_profile.debugger.write_debugger(
                    self.process, f"memory 0x{self.layout.crc_value:x} 4"
                )
            else:
                self._advance()
            return
        if self.waiting == "memory":
            pattern = re.compile(
                crc_profile.MEMORY_RE_TEMPLATE.format(
                    address=self.layout.crc_value
                )
            )
            match = pattern.search(contents, self.cursor)
            if match is None:
                return
            value = bytes(int(token, 16) for token in match.group(1).split())
            if len(value) != crc_profile.CRC_VALUE_BYTES:
                raise CrcNibbleThreProfileError("inner CRC memory length changed")
            self.crc_memory.append(value)
            self.cursor = match.end()
            self._advance()

    def require_complete(self) -> dict[str, object]:
        if (
            not self.complete
            or self.record_index != self.expected_records
            or self.event_index != 0
            or self.waiting != "pause"
            or len(self.cycles) != self.expected_records * 2
            or len(self.crc_memory) != self.expected_records
        ):
            raise CrcNibbleThreProfileError(
                f"incomplete inner CRC profile: records={self.record_index}/"
                f"{self.expected_records}, event={self.event_index}, "
                f"cycles={len(self.cycles)}, memory={len(self.crc_memory)}"
            )
        return {
            "record_count": self.record_index,
            "events_per_record": 2,
            "cycle_state_count": len(self.cycles),
            "crc_memory_snapshot_count": len(self.crc_memory),
        }


def reconstruct_inner_records(
    states: Sequence[Mapping[str, int | str]],
    memory: Sequence[bytes],
    layout: InnerLayout,
    variant: Variant,
    bound: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    expected = crc_profile.regular_capture.initial_records()
    if (
        len(states) != EXPECTED_RECORDS * 2
        or len(memory) != EXPECTED_RECORDS
        or len(bound) != EXPECTED_RECORDS
        or len(expected) != EXPECTED_RECORDS
    ):
        raise CrcNibbleThreProfileError("inner record cardinality changed")
    records = []
    for order, (record, binding) in enumerate(zip(expected, bound)):
        chunk = states[order * 2 : (order + 1) * 2]
        by_name = {str(item["event"]): item for item in chunk}
        if set(by_name) != {"crc_entry", "crc_post"}:
            raise CrcNibbleThreProfileError(
                f"inner record {order} events changed"
            )
        post = by_name["crc_post"]
        payload, data, stored = crc_profile.expected_record_payload(record)
        del payload
        expected_crc = stored.to_bytes(4, "little")
        if memory[order] != expected_crc:
            raise CrcNibbleThreProfileError(
                f"record {order} final CRC memory changed"
            )
        expected_ix = layout.file_buffer + register_builder.P3DM_DATA_OFFSET + len(data)
        if int(post["ix"]) != expected_ix:
            raise CrcNibbleThreProfileError(
                f"record {order} final IX changed: {int(post['ix']):06x} "
                f"!= {expected_ix:06x}"
            )
        if (int(post["af"]) >> 8) != 0 or int(post["bc"]) != 0:
            raise CrcNibbleThreProfileError(
                f"record {order} CRC success A/BC changed"
            )
        register_crc = None
        if variant.register_resident:
            hl = int(post["hl"])
            de = int(post["de"])
            register_crc = bytes(
                (hl & 0xFF, (hl >> 8) & 0xFF, de & 0xFF, (de >> 8) & 0xFF)
            )
            if register_crc != expected_crc:
                raise CrcNibbleThreProfileError(
                    f"record {order} register-held CRC changed"
                )
        if (
            binding.get("order") != order
            or binding.get("path") != record.get("path")
            or binding.get("file_sha256") != record.get("sha256")
            or binding.get("data_bytes") != len(data)
        ):
            raise CrcNibbleThreProfileError(
                f"record {order} manifest/publication binding changed"
            )
        records.append(
            {
                "order": order,
                "path": record["path"],
                "file_sha256": record["sha256"],
                "data_bytes": len(data),
                "stored_crc32": f"{stored:08x}",
                "p3dm_crc_value_hex": memory[order].hex(),
                "final_ix": int(post["ix"]),
                "expected_final_ix": expected_ix,
                "final_ix_from_file_buffer": int(post["ix"]) - layout.file_buffer,
                "register_crc_hex": (
                    None if register_crc is None else register_crc.hex()
                ),
                "crc_entry_line": by_name["crc_entry"]["line_number"],
                "crc_post_line": post["line_number"],
                "inner_crc_guest_cycles": int(
                    post["cycles_since_previous_boundary"]
                ),
            }
        )
    return records


def run_inner(
    variant: Variant,
    *,
    thre_mos: Path,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    staged_run = prepare_run_output(output, "inner", variant, thre_mos)
    layout = resolve_inner_layout(staged_run.program, staged_run.symbols)
    log_path = staged_run.directory / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: InnerCrcProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"nibble-inner-{variant.name}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"nibble-inner-{variant.name}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        mos_profile.staged.stage_fixture(sd_root, staged_run.program)
        corpus_before = mos_profile.builder.validate_runtime_corpus(sd_root / "survey")
        mos_profile.write_exact_autoexec(sd_root / "autoexec.txt")
        command = mos_profile.emulator_command(
            sd_root, vdp, staged_run.mos, THRE_MOS_SHA256, layout.breakpoints
        )
        (staged_run.directory / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "direct-inner-crc-entry-post",
                    "variant": variant.name,
                    "role": variant.role,
                    "program": artifact(staged_run.program),
                    "symbols": artifact(staged_run.symbols),
                    "mos": artifact(staged_run.mos),
                    "mos_map": artifact(staged_run.mos_map),
                    "layout": layout_evidence(staged_run.program, layout),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=cwd_name,
                    env=mos_profile.emulator_environment(),
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                profiler = InnerCrcProfiler(process, layout, EXPECTED_RECORDS)
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: (
                        mos_profile.staged.COLD_RENDER_MARKER in value
                        and profiler.complete
                    ),
                    f"{variant.name} direct inner CRC cold fill",
                    service=profiler.service,
                )
                profiler.require_complete()
                mos_profile.shutdown(process, log_path, deadline)
                corpus_after = mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                if corpus_after != corpus_before:
                    raise CrcNibbleThreProfileError(
                        f"{variant.name} corpus changed during inner run"
                    )
        finally:
            if process is not None and process.poll() is None:
                mos_profile.input_trace.stop_process(process)
    assert (
        process is not None
        and profiler is not None
        and corpus_before is not None
        and corpus_after is not None
    )
    validate_staged_run(staged_run, variant)
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = mos_profile.validate_run_semantics(
        contents
    )
    states = crc_profile.parse_boundary_states(contents, layout, EXPECTED_RECORDS)
    memory = crc_profile.parse_crc_memory(contents, layout.crc_value)
    if list(memory) != profiler.crc_memory:
        raise CrcNibbleThreProfileError("live/reparsed inner CRC memory differs")
    bound = mos_profile.bind_publications(publications)
    records = reconstruct_inner_records(states, memory, layout, variant, bound)
    cycles = [int(record["inner_crc_guest_cycles"]) for record in records]
    return {
        "mode": "direct-inner-crc-entry-post",
        "variant": variant.name,
        "role": variant.role,
        "fresh_process": True,
        "program": artifact(staged_run.program),
        "symbols": artifact(staged_run.symbols),
        "mos": artifact(staged_run.mos),
        "mos_map": artifact(staged_run.mos_map),
        "command": artifact(staged_run.directory / "command.json"),
        "autoexec": artifact(staged_run.directory / "autoexec.txt"),
        "log": artifact(log_path),
        "layout": layout_evidence(staged_run.program, layout),
        "live": profiler.require_complete(),
        "runtime_corpus": {
            "before": mos_profile.corpus_witness(corpus_before),
            "after": mos_profile.corpus_witness(corpus_after),
            "unchanged": True,
        },
        "cold_endpoint": endpoint,
        "publication_semantics": mos_profile.publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "metrics": {
            "inner_crc_entry_to_post": {
                "cycles": cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    cycles[1:]
                ).as_dict(),
                "startup_record_0": cycles[0],
                "direct_inner_measurement": True,
                "completion_equivalent": False,
            }
        },
        "records": records,
        "emulator_exit_status": process.returncode,
    }


def recovered_runtime_corpus(
    canonical_corpus: Mapping[str, object],
) -> dict[str, object]:
    witness = mos_profile.corpus_witness(canonical_corpus)
    return {
        "before": witness,
        "after": witness,
        "unchanged": True,
        "capture_time_before_after_gate_completed_before_analyzer": True,
        "current_canonical_corpus_revalidated": True,
        "ephemeral_capture_stage_no_longer_present": True,
    }


def recover_normative(
    root: Path,
    variant: Variant,
    *,
    thre_mos: Path,
    canonical_corpus: Mapping[str, object],
) -> dict[str, object]:
    staged_run = recovered_staged_run(root, "normative", variant, thre_mos)
    layout = resolve_normative_layout(staged_run.program, staged_run.symbols)
    validate_recovered_command(staged_run, variant, "normative", layout)
    log_path = staged_run.directory / "emulator.log"
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = mos_profile.validate_run_semantics(
        contents
    )
    bound = mos_profile.bind_publications(publications)
    states = mos_profile.parse_normative_states(contents, layout, EXPECTED_RECORDS)
    marker_offsets = mos_profile.publication_marker_offsets(contents)
    records = mos_profile.reconstruct_normative_records(
        states, publications, marker_offsets, bound
    )
    if len(states) != EXPECTED_RECORDS * 3 or len(records) != EXPECTED_RECORDS:
        raise CrcNibbleThreProfileError(
            f"recovered normative {variant.name} cardinality changed"
        )
    upload_cycles = [
        int(record["upload_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    read_cycles = [
        int(record["read_to_publication_complete_submit_guest_cycles"])
        for record in records
    ]
    return {
        "mode": "normative-publication-complete",
        "variant": variant.name,
        "role": variant.role,
        "fresh_process": True,
        "captured_in_current_invocation": False,
        "recovered_from_immutable_positive_evidence": True,
        "capture_completed_shutdown_and_corpus_gate_before_analyzer": True,
        "program": artifact(staged_run.program),
        "symbols": artifact(staged_run.symbols),
        "mos": artifact(staged_run.mos),
        "mos_map": artifact(staged_run.mos_map),
        "command": artifact(staged_run.directory / "command.json"),
        "autoexec": artifact(staged_run.directory / "autoexec.txt"),
        "log": artifact(log_path),
        "layout": layout_evidence(staged_run.program, layout),
        "live": {
            "record_count": EXPECTED_RECORDS,
            "events_per_record": 3,
            "cycle_state_count": len(states),
            "publication_before_submit_count": len(records),
            "reparsed_from_raw_log": True,
        },
        "runtime_corpus": recovered_runtime_corpus(canonical_corpus),
        "cold_endpoint": endpoint,
        "publication_semantics": mos_profile.publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "metrics": {
            "upload_to_publication_complete_submit": {
                "cycles": upload_cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    upload_cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    upload_cycles[1:]
                ).as_dict(),
                "startup_record_0": upload_cycles[0],
                "completion_equivalent": True,
            },
            "read_to_publication_complete_submit": {
                "cycles": read_cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    read_cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    read_cycles[1:]
                ).as_dict(),
                "startup_record_0": read_cycles[0],
                "completion_equivalent": True,
            },
        },
        "records": records,
        "emulator_exit_status": 0,
    }


def recover_inner(
    root: Path,
    variant: Variant,
    *,
    thre_mos: Path,
    canonical_corpus: Mapping[str, object],
) -> dict[str, object]:
    staged_run = recovered_staged_run(root, "inner", variant, thre_mos)
    layout = resolve_inner_layout(staged_run.program, staged_run.symbols)
    validate_recovered_command(staged_run, variant, "inner", layout)
    log_path = staged_run.directory / "emulator.log"
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    endpoint, publications, render_evidence = mos_profile.validate_run_semantics(
        contents
    )
    states = crc_profile.parse_boundary_states(contents, layout, EXPECTED_RECORDS)
    memory = crc_profile.parse_crc_memory(contents, layout.crc_value)
    bound = mos_profile.bind_publications(publications)
    records = reconstruct_inner_records(states, memory, layout, variant, bound)
    if (
        len(states) != EXPECTED_RECORDS * 2
        or len(memory) != EXPECTED_RECORDS
        or len(records) != EXPECTED_RECORDS
    ):
        raise CrcNibbleThreProfileError(
            f"recovered inner {variant.name} cardinality changed"
        )
    cycles = [int(record["inner_crc_guest_cycles"]) for record in records]
    return {
        "mode": "direct-inner-crc-entry-post",
        "variant": variant.name,
        "role": variant.role,
        "fresh_process": True,
        "captured_in_current_invocation": False,
        "recovered_from_immutable_positive_evidence": True,
        "capture_completed_shutdown_and_corpus_gate_before_analyzer": True,
        "program": artifact(staged_run.program),
        "symbols": artifact(staged_run.symbols),
        "mos": artifact(staged_run.mos),
        "mos_map": artifact(staged_run.mos_map),
        "command": artifact(staged_run.directory / "command.json"),
        "autoexec": artifact(staged_run.directory / "autoexec.txt"),
        "log": artifact(log_path),
        "layout": layout_evidence(staged_run.program, layout),
        "live": {
            "record_count": EXPECTED_RECORDS,
            "events_per_record": 2,
            "cycle_state_count": len(states),
            "crc_memory_snapshot_count": len(memory),
            "reparsed_from_raw_log": True,
        },
        "runtime_corpus": recovered_runtime_corpus(canonical_corpus),
        "cold_endpoint": endpoint,
        "publication_semantics": mos_profile.publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "metrics": {
            "inner_crc_entry_to_post": {
                "cycles": cycles,
                "summary_all_227": mos_profile.summarize_distribution(
                    cycles
                ).as_dict(),
                "summary_loop_226": mos_profile.summarize_distribution(
                    cycles[1:]
                ).as_dict(),
                "startup_record_0": cycles[0],
                "direct_inner_measurement": True,
                "completion_equivalent": False,
            }
        },
        "records": records,
        "emulator_exit_status": 0,
    }


def run_negative(
    kind: str,
    variant: Variant,
    *,
    thre_mos: Path,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    staged_run = prepare_run_output(output, f"negative-{kind}", variant, thre_mos)
    layout = resolve_inner_layout(staged_run.program, staged_run.symbols)
    record, relative, original = crc_profile.first_record()
    mutated, mutation = crc_profile.mutate_negative(kind, record, original)
    log_path = staged_run.directory / "emulator.log"
    deadline = time.monotonic() + timeout
    process: subprocess.Popen[bytes] | None = None
    breakpoints = [layout.return_error]
    if kind == "index-valid-crc":
        breakpoints.append(layout.crc_entry)
    with (
        tempfile.TemporaryDirectory(prefix=f"nibble-negative-{kind}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"nibble-negative-{kind}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        mos_profile.staged.stage_fixture(sd_root, staged_run.program)
        tree = sd_root / "survey/TRH"
        if not tree.is_symlink():
            raise CrcNibbleThreProfileError("staged TRH is not the expected symlink")
        tree.unlink()
        target = sd_root / "survey" / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(mutated)
        mos_profile.write_exact_autoexec(sd_root / "autoexec.txt")
        command = mos_profile.emulator_command(
            sd_root, vdp, staged_run.mos, THRE_MOS_SHA256, breakpoints
        )
        (staged_run.directory / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "guest-negative",
                    "kind": kind,
                    "variant": variant.name,
                    "record": dict(record),
                    "mutation": mutation,
                    "program": artifact(staged_run.program),
                    "symbols": artifact(staged_run.symbols),
                    "mos": artifact(staged_run.mos),
                    "mos_map": artifact(staged_run.mos_map),
                    "breakpoints": breakpoints,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    command,
                    cwd=cwd_name,
                    env=mos_profile.emulator_environment(),
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: "CPU paused (breakpoint)" in value,
                    f"guest {kind} failure breakpoint",
                )
                crc_profile.debugger.write_debugger(process, "state")
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: mos_profile.staged.SELECTOR_CYCLES_RE.search(value)
                    is not None,
                    f"guest {kind} failure state",
                )
                crc_profile.debugger.write_debugger(
                    process, f"memory 0x{layout.crc_value:x} 4"
                )
                pattern = re.compile(
                    crc_profile.MEMORY_RE_TEMPLATE.format(
                        address=layout.crc_value
                    )
                )
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: pattern.search(
                        crc_profile.debugger.ANSI_RE.sub("", value)
                    )
                    is not None,
                    f"guest {kind} CRC result memory",
                )
                crc_profile.debugger.write_debugger(process, "exit")
                process.wait(timeout=max(1.0, deadline - time.monotonic()))
                if target.read_bytes() != mutated:
                    raise CrcNibbleThreProfileError(
                        f"guest {kind} mutation changed during run"
                    )
        finally:
            if process is not None and process.poll() is None:
                mos_profile.input_trace.stop_process(process)
    assert process is not None
    validate_staged_run(staged_run, variant)
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    plain = crc_profile.debugger.ANSI_RE.sub("", contents)
    pause_addresses = [
        int(value, 16)
        for value in re.findall(r"\* ([0-9a-fA-F]{6}):", plain)
    ]
    first_target = next(
        (address for address in pause_addresses if address in breakpoints), None
    )
    if first_target != layout.return_error:
        raise CrcNibbleThreProfileError(
            f"{kind} reached 0x{first_target or 0:06x}, expected return_error"
        )
    state = crc_profile.parse_last_full_state(contents, layout.return_error)
    error = (state["af"] >> 8) & 0xFF
    expected_error = int(mutation["expected_error"])
    if error != expected_error:
        raise CrcNibbleThreProfileError(
            f"{kind} guest error {error} != {expected_error}"
        )
    memory = crc_profile.parse_crc_memory(contents, layout.crc_value)
    if len(memory) != 1:
        raise CrcNibbleThreProfileError(
            f"{kind} returned {len(memory)} CRC snapshots"
        )
    if crc_profile.parse_mesh_replace_records(contents):
        raise CrcNibbleThreProfileError(
            f"{kind} published a mesh before rejection"
        )
    if mos_profile.staged.COLD_RENDER_MARKER in contents:
        raise CrcNibbleThreProfileError(f"{kind} reached cold endpoint")
    actual_crc = int(str(mutation["actual_data_crc32"]), 16)
    stored_crc = int(str(mutation["stored_crc32"]), 16)
    if kind == "crc-data":
        if memory[0] != actual_crc.to_bytes(4, "little") or actual_crc == stored_crc:
            raise CrcNibbleThreProfileError("guest error-9 CRC result changed")
    elif (
        actual_crc != stored_crc
        or layout.crc_entry in pause_addresses
        or first_target == layout.crc_entry
    ):
        raise CrcNibbleThreProfileError(
            "guest error-10 no longer precedes CRC entry"
        )
    if process.returncode != 0:
        raise CrcNibbleThreProfileError(
            f"{kind} emulator returned {process.returncode}"
        )
    return {
        "mode": "guest-negative",
        "kind": kind,
        "variant": variant.name,
        "fresh_process": True,
        "guest_executed": True,
        "record_order": 0,
        "path": relative.as_posix(),
        "mutation": mutation,
        "first_breakpoint": first_target,
        "return_error_address": layout.return_error,
        "crc_entry_address": layout.crc_entry,
        "crc_entry_reached": layout.crc_entry in pause_addresses,
        "guest_error": error,
        "p3dm_crc_value_hex": memory[0].hex(),
        "mesh_publications_before_rejection": 0,
        "cold_endpoint_reached": False,
        "program": artifact(staged_run.program),
        "symbols": artifact(staged_run.symbols),
        "mos": artifact(staged_run.mos),
        "mos_map": artifact(staged_run.mos_map),
        "command": artifact(staged_run.directory / "command.json"),
        "autoexec": artifact(staged_run.directory / "autoexec.txt"),
        "log": artifact(log_path),
        "emulator_exit_status": process.returncode,
    }


def validate_failed_v1_race(
    root: Path, inputs: QualifiedInputs
) -> dict[str, object]:
    receipt = validate_immutable_evidence_tree(
        root, FAILED_V1_EVIDENCE_MANIFEST, "failed-v1 evidence"
    )
    staged_run = recovered_staged_run(
        root.expanduser().resolve(), "normative", inputs.control, inputs.thre_mos
    )
    layout = resolve_normative_layout(staged_run.program, staged_run.symbols)
    validate_recovered_command(staged_run, inputs.control, "normative", layout)
    log_path = staged_run.directory / "emulator.log"
    contents = log_path.read_text(encoding="utf-8", errors="replace")
    plain = crc_profile.debugger.ANSI_RE.sub("", contents).replace("\r", "")
    pause_pattern = re.compile(
        rf"CPU paused \(breakpoint\)\n\* {layout.loop_submit_call:06x}:"
    )
    submit_pauses = list(pause_pattern.finditer(plain))
    if not submit_pauses:
        raise CrcNibbleThreProfileError("failed-v1 loop submit pause is missing")
    failed_submit = submit_pauses[-1]
    publications_before = plain[: failed_submit.start()].count(
        mos_profile.PUBLICATION_MARKER
    )
    late_publication = plain.find(
        mos_profile.PUBLICATION_MARKER, failed_submit.end()
    )
    total_publications = plain.count(mos_profile.PUBLICATION_MARKER)
    if (
        publications_before != 8
        or late_publication < 0
        or total_publications != 9
        or mos_profile.staged.COLD_RENDER_MARKER in plain
    ):
        raise CrcNibbleThreProfileError(
            "failed-v1 no longer proves record-8 publication-after-submit race"
        )
    return {
        "evidence": receipt,
        "log": artifact(log_path),
        "command": artifact(staged_run.directory / "command.json"),
        "variant": inputs.control.name,
        "record_index": 8,
        "successful_publications_at_submit": publications_before,
        "successful_publications_required": 9,
        "matching_publication_appeared_after_submit": True,
        "stripped_submit_log_offset": failed_submit.start(),
        "stripped_late_publication_log_offset": late_publication,
        "strict_publication_gate_held": True,
        "cold_endpoint_reached": False,
    }


def recover_positive_evidence(
    root: Path,
    inputs: QualifiedInputs,
    canonical_corpus: Mapping[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    root = root.expanduser().resolve()
    receipt = validate_immutable_evidence_tree(
        root, RECOVERY_V2_EVIDENCE_MANIFEST, "recovery-v2 positive evidence"
    )
    normative_control = recover_normative(
        root,
        inputs.control,
        thre_mos=inputs.thre_mos,
        canonical_corpus=canonical_corpus,
    )
    normative_candidate = recover_normative(
        root,
        inputs.candidate,
        thre_mos=inputs.thre_mos,
        canonical_corpus=canonical_corpus,
    )
    mos_profile.assert_semantic_equivalence(
        normative_control, normative_candidate
    )
    inner_control = recover_inner(
        root,
        inputs.control,
        thre_mos=inputs.thre_mos,
        canonical_corpus=canonical_corpus,
    )
    inner_candidate = recover_inner(
        root,
        inputs.candidate,
        thre_mos=inputs.thre_mos,
        canonical_corpus=canonical_corpus,
    )
    assert_inner_semantic_equivalence(inner_control, inner_candidate)
    for normative, inner in (
        (normative_control, inner_control),
        (normative_candidate, inner_candidate),
    ):
        for name in ("cold_endpoint", "publication_semantics", "render_sequences"):
            if normative[name] != inner[name]:
                raise CrcNibbleThreProfileError(
                    f"recovered normative/inner {normative['variant']} {name} differs"
                )
    candidate_render = inner_candidate["render_evidence"]
    if (
        not isinstance(candidate_render, Mapping)
        or candidate_render.get("endpoint_out") != 0
        or candidate_render.get("post_endpoint_tail_out") != [1]
        or candidate_render.get("tail_stable_counters_identical") is not True
        or candidate_render.get("out_classification")
        != "timing_overhead_not_scene_state"
    ):
        raise CrcNibbleThreProfileError(
            "recovery-v2 no longer proves out-only analyzer correction"
        )
    return (
        normative_control,
        normative_candidate,
        inner_control,
        inner_candidate,
        receipt,
    )


def assert_inner_semantic_equivalence(
    control: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    for name in ("cold_endpoint", "publication_semantics", "render_sequences"):
        if control.get(name) != candidate.get(name):
            raise CrcNibbleThreProfileError(f"inner {name} differs")
    left = control.get("records")
    right = candidate.get("records")
    if (
        not isinstance(left, list)
        or not isinstance(right, list)
        or len(left) != EXPECTED_RECORDS
        or len(right) != EXPECTED_RECORDS
    ):
        raise CrcNibbleThreProfileError("inner semantic records are missing")
    stable = (
        "order",
        "path",
        "file_sha256",
        "data_bytes",
        "stored_crc32",
        "p3dm_crc_value_hex",
        "final_ix_from_file_buffer",
    )
    for order, (before, after) in enumerate(zip(left, right)):
        if any(before.get(name) != after.get(name) for name in stable):
            raise CrcNibbleThreProfileError(
                f"inner semantic record differs at {order}"
            )


def paired_inner_metric(
    control: Mapping[str, object], candidate: Mapping[str, object], summary: str
) -> dict[str, object]:
    try:
        before = control["metrics"]["inner_crc_entry_to_post"][summary]["total"]
        after = candidate["metrics"]["inner_crc_entry_to_post"][summary]["total"]
    except (KeyError, TypeError) as error:
        raise CrcNibbleThreProfileError("inner metric summary is missing") from error
    if (
        isinstance(before, bool)
        or isinstance(after, bool)
        or not isinstance(before, int)
        or not isinstance(after, int)
        or before <= 0
    ):
        raise CrcNibbleThreProfileError("inner metric total is invalid")
    return {
        "control_cycles": before,
        "candidate_cycles": after,
        "delta_cycles": after - before,
        "candidate_vs_control_percent": (after - before) * 100.0 / before,
        "boundary": summary,
        "direct_inner_measurement": True,
        "completion_equivalent": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.timeout <= 0:
        raise CrcNibbleThreProfileError("--timeout must be positive")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise CrcNibbleThreProfileError(
            f"refusing to replace existing output: {output}"
        )
    inputs = validate_inputs(
        args.register_build, args.nibble_build, args.mos_build
    )
    initial_identity = dict(inputs.identity)
    canonical_corpus = mos_profile.builder.validate_runtime_corpus()
    vdp = mos_profile.staged.require_file(args.vdp_module, "diagnostic VDP module")
    mos_profile.survey.require_diagnostic_vdp(vdp)
    emulator_sha256 = sha256(mos_profile.input_trace.FAB_BINARY)
    vdp_sha256 = sha256(vdp)
    script_sha256 = sha256(Path(__file__))
    semantic_validator = Path(mos_profile.__file__).resolve()
    semantic_validator_sha256 = sha256(semantic_validator)
    recovery_mode = args.recover_positive_evidence is not None
    recovery_root: Path | None = None
    failed_v1: dict[str, object] | None = None
    recovery_receipt: dict[str, object] | None = None
    if recovery_mode:
        recovery_root = args.recover_positive_evidence.expanduser().resolve()
        failed_root = args.failed_v1_evidence.expanduser().resolve()
        if (
            output == recovery_root
            or recovery_root in output.parents
            or output == failed_root
            or failed_root in output.parents
        ):
            raise CrcNibbleThreProfileError(
                "recovery output must not overlap immutable v1/v2 evidence"
            )
        failed_v1 = validate_failed_v1_race(failed_root, inputs)
        (
            normative_control,
            normative_candidate,
            inner_control,
            inner_candidate,
            recovery_receipt,
        ) = recover_positive_evidence(recovery_root, inputs, canonical_corpus)
        output.mkdir(parents=True)
    else:
        output.mkdir(parents=True)
        normative_control = run_normative(
            inputs.control,
            thre_mos=inputs.thre_mos,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        normative_candidate = run_normative(
            inputs.candidate,
            thre_mos=inputs.thre_mos,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        mos_profile.assert_semantic_equivalence(
            normative_control, normative_candidate
        )
        inner_control = run_inner(
            inputs.control,
            thre_mos=inputs.thre_mos,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        inner_candidate = run_inner(
            inputs.candidate,
            thre_mos=inputs.thre_mos,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        assert_inner_semantic_equivalence(inner_control, inner_candidate)
        for normative, inner in (
            (normative_control, inner_control),
            (normative_candidate, inner_candidate),
        ):
            for name in ("cold_endpoint", "publication_semantics", "render_sequences"):
                if normative[name] != inner[name]:
                    raise CrcNibbleThreProfileError(
                        f"normative/inner {normative['variant']} {name} differs"
                    )

    negatives = [
        run_negative(
            kind,
            inputs.candidate,
            thre_mos=inputs.thre_mos,
            vdp=vdp,
            output=output,
            timeout=args.timeout,
        )
        for kind in RECOVERY_NEGATIVE_KINDS
    ]

    final_inputs = validate_inputs(
        args.register_build, args.nibble_build, args.mos_build
    )
    if dict(final_inputs.identity) != initial_identity:
        raise CrcNibbleThreProfileError(
            "qualified component identities changed during profile"
        )
    if mos_profile.builder.validate_runtime_corpus() != canonical_corpus:
        raise CrcNibbleThreProfileError(
            "canonical runtime corpus changed during profile"
        )
    if sha256(mos_profile.input_trace.FAB_BINARY) != emulator_sha256:
        raise CrcNibbleThreProfileError("emulator identity changed during profile")
    if sha256(vdp) != vdp_sha256:
        raise CrcNibbleThreProfileError("VDP identity changed during profile")
    if sha256(Path(__file__)) != script_sha256:
        raise CrcNibbleThreProfileError("profile script changed during execution")
    if sha256(semantic_validator) != semantic_validator_sha256:
        raise CrcNibbleThreProfileError(
            "semantic validator changed during profile"
        )
    if recovery_mode:
        assert recovery_root is not None and failed_v1 is not None
        final_recovery_receipt = validate_immutable_evidence_tree(
            recovery_root,
            RECOVERY_V2_EVIDENCE_MANIFEST,
            "recovery-v2 positive evidence",
        )
        final_failed_v1 = validate_failed_v1_race(
            args.failed_v1_evidence.expanduser().resolve(), final_inputs
        )
        if (
            final_recovery_receipt != recovery_receipt
            or final_failed_v1 != failed_v1
        ):
            raise CrcNibbleThreProfileError(
                "immutable v1/v2 recovery evidence changed during finalization"
            )

    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "accepted_files_modified": False,
            "register_builder_modified": False,
            "nibble_builder_modified": False,
            "mos_builder_modified": False,
            "third_code_patch_created": False,
            "same_exact_thre_mos_every_run": True,
            "fresh_process_per_run": True,
            "all_six_runs_one_uninterrupted_invocation": not recovery_mode,
            "current_invocation_process_count": 2 if recovery_mode else 6,
            "recovered_positive_run_count": 4 if recovery_mode else 0,
            "current_invocation_negative_run_count": 2,
            "normative_pair_count": 1,
            "direct_inner_pair_count": 1,
            "candidate_negative_run_count": 2,
            "positive_records_per_run": EXPECTED_RECORDS,
            "normative_events_per_record": 3,
            "direct_inner_events_per_record": 2,
            "no_normative_breakpoint_after_upload_before_own_submit": True,
            "publication_must_precede_matching_submit_marker": True,
            "all_227_runtime_files_exact_before_and_after_every_positive_run": True,
            "run_local_program_symbols_mos_map_autoexec_exact_pre_and_post": True,
            "own_image_shifted_symbols_and_submit_sites_resolved_independently": True,
        },
        "identity": {
            **initial_identity,
            "profile_script": artifact(Path(__file__)),
            "semantic_validator_script": artifact(semantic_validator),
            "emulator": artifact(mos_profile.input_trace.FAB_BINARY),
            "vdp": artifact(vdp),
            "runtime_corpus": mos_profile.corpus_witness(canonical_corpus),
        },
        "component_matrix": {
            "control": {
                "application": REGISTER_PROGRAM_SHA256,
                "symbols": REGISTER_SYMBOLS_SHA256,
                "mos": THRE_MOS_SHA256,
            },
            "candidate": {
                "application": NIBBLE_PROGRAM_SHA256,
                "symbols": NIBBLE_SYMBOLS_SHA256,
                "mos": THRE_MOS_SHA256,
            },
            "no_cross_built_or_new_combined_binary": True,
            "static_composition": inputs.composition,
        },
        "semantic_equivalence": {
            "all_four_positive_runs_exact": True,
            "publications_each_positive_run": EXPECTED_RECORDS,
            "publication_order_shapes_and_manifest_files_exact": True,
            "cold_endpoint_exact": True,
            "render_prefix_0_through_226_exact": True,
            "final_crc_memory_and_ix_exact_all_227_both_inner_runs": True,
            "shutdown_tails_bounded_and_scene_stable": True,
        },
        "normative_comparison": {
            metric: {
                "loop_records_1_through_226": mos_profile.paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_loop_226",
                ),
                "all_records_including_startup_0": mos_profile.paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_all_227",
                ),
                "completion_equivalent": True,
                "interpretation": (
                    "guest cycles through each matching own-image submit call "
                    "after that record's successful VDP publication"
                ),
            }
            for metric in (
                "upload_to_publication_complete_submit",
                "read_to_publication_complete_submit",
            )
        },
        "direct_inner_crc_comparison": {
            "loop_records_1_through_226": paired_inner_metric(
                inner_control, inner_candidate, "summary_loop_226"
            ),
            "all_records_including_startup_0": paired_inner_metric(
                inner_control, inner_candidate, "summary_all_227"
            ),
            "entry_and_caller_post_breakpoints_only": True,
            "final_crc_memory_snapshots": EXPECTED_RECORDS * 2,
            "completion_equivalent": False,
        },
        "negative_qualification": {
            "crc_data_guest_error_9_no_publication": negatives[0],
            "invalid_index_valid_crc_guest_error_10_before_crc": negatives[1],
        },
        "runs": [
            normative_control,
            normative_candidate,
            inner_control,
            inner_candidate,
        ],
        "limitations": {
            "single_emulator_pair_does_not_establish_repeatability": True,
            "six_runs_not_one_uninterrupted_invocation": recovery_mode,
            "failed_v1_record8_publication_after_submit_race": recovery_mode,
            "thre_scheduling_can_nondeterministically_miss_completion_boundary": (
                recovery_mode
            ),
            "v2_stopped_after_four_positives_on_out_analyzer_misclassification": (
                recovery_mode
            ),
            "exact_image_emulator_evidence_only": True,
            "hardware_crc_timing_qualification_open": True,
            "fab_models_rrd_as_4_cycles_um0077_lists_5": True,
            "candidate_main_registers_must_be_preserved_by_interrupt_handlers": True,
            "hardware_uart_cts_fifo_timing_qualification_open": True,
            "thre_return_does_not_imply_transmitter_idle": True,
            "must_not_install_or_distribute_patched_mos_blob": True,
            "normal_mos_source_rebuild_required_for_promotion": True,
        },
    }
    if recovery_mode:
        assert (
            recovery_root is not None
            and recovery_receipt is not None
            and failed_v1 is not None
        )
        report["recovery_finalization"] = {
            "mode": "revalidate-v2-four-positives-run-v3-two-negatives",
            "positive_capture_script_sha256": CAPTURE_PROFILE_SCRIPT_SHA256,
            "positive_capture_semantic_validator_sha256": (
                CAPTURE_SEMANTIC_VALIDATOR_SHA256
            ),
            "current_analyzer_script": artifact(Path(__file__)),
            "current_semantic_validator_script": artifact(semantic_validator),
            "immutable_v2_positive_evidence": recovery_receipt,
            "failed_v1_publication_boundary_race": failed_v1,
            "v2_analyzer_stop": {
                "message": "post-endpoint render 227 changed stable counters",
                "positive_processes_completed": 4,
                "negative_processes_started": 0,
                "endpoint_render_sequence": 226,
                "shutdown_tail_render_sequence": 227,
                "endpoint_out": inner_candidate["render_evidence"]["endpoint_out"],
                "shutdown_tail_out": inner_candidate["render_evidence"][
                    "post_endpoint_tail_out"
                ],
                "all_structural_stable_fields_identical": True,
                "out_is_required_timing_not_scene_state": True,
                "corrected_analyzer_revalidation_passed": True,
            },
            "positive_runs_reparsed_from_pinned_raw_logs": True,
            "negative_runs_only_in_new_output_root": True,
            "all_six_runs_one_uninterrupted_invocation": False,
            "failed_v1_and_partial_v2_preserved": True,
        }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"CRC-nibble under same THRE MOS profile passed: {report_path}")
    direct = report["direct_inner_crc_comparison"][
        "all_records_including_startup_0"
    ]
    print(
        f"inner_crc: control={direct['control_cycles']} "
        f"candidate={direct['candidate_cycles']} "
        f"percent={direct['candidate_vs_control_percent']}"
    )
    for metric, comparison in report["normative_comparison"].items():
        total = comparison["all_records_including_startup_0"]
        print(
            f"{metric}: control={total['control_cycles']} "
            f"candidate={total['candidate_cycles']} "
            f"percent={total['candidate_vs_control_percent']} "
            "publication_complete=True"
        )
    if recovery_mode:
        print(
            "recovered_positive_runs=4 fresh_negative_runs=2 "
            "single_uninterrupted_invocation=False same_thre_mos=True"
        )
    else:
        print("fresh_runs=6 positive_records_each=227 same_thre_mos=True")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        CrcNibbleThreProfileError,
        combined.CombinedProfileError,
        crc_profile.CrcSiblingProfileError,
        mos_profile.MosUartThreProfileError,
        mos_profile.builder.MosUartThreBuildError,
    ) as error:
        raise SystemExit(f"CRC-nibble THRE profile failed: {error}") from error
