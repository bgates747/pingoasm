#!/usr/bin/env python3
"""Profile the qualified CRC-register app together with qualified THRE MOS.

The control is the exact accepted P3DRGL program under the pinned TEMT
Console8 MOS.  The candidate combines the already-qualified register-CRC
program with the already-qualified one-byte THRE MOS sibling.  This script
creates no third code patch.

The normative pair uses only read-call, upload-call, and the matching
``submit_current_render`` call for each record.  The nth successful mesh
publication must precede its submit breakpoint in the raw log.  A separate
fresh pair measures the five ordinary loader phases for attribution; those
call spans are diagnostic, not transmitter-completion-equivalent.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Mapping, Sequence

import build_regular_lod_crc_register_sibling as crc_builder
import profile_regular_lod_crc_register_sibling as crc_profile
import profile_regular_lod_mos_uart_thre_sibling as mos_profile
import profile_regular_lod_uart_thre_sibling as uart_profile


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CRC_BUILD = crc_builder.DEFAULT_OUTPUT
DEFAULT_MOS_BUILD = mos_profile.builder.DEFAULT_OUTPUT
DEFAULT_OUTPUT = (
    ROOT / "build/evidence/regular-lod-crc-mos-uart-thre-combined-profile-v3"
)
REPORT_NAME = "regular-lod-crc-mos-uart-thre-combined-profile.json"
SCHEMA = "pingo-terrain-regular-lod-crc-mos-uart-thre-combined-live-profile-v1"
EXPECTED_RECORDS = 227

CRC_BUILD_RECEIPT_BYTES = 115_860
CRC_BUILD_RECEIPT_SHA256 = (
    "8707b09cd92205551a41e35c18f5a09abc297ffbc24a82752f43ef64fe60873c"
)
CRC_PROGRAM_BYTES = 142_750
CRC_PROGRAM_SHA256 = (
    "a4a88621ee4ed3af42ad6006bebf5e48037d19ad4375568b3b9032594f139992"
)
CRC_SYMBOLS_BYTES = 66_035
CRC_SYMBOLS_SHA256 = (
    "2f0a3d706096597933093a67c863bdd4e1b8f3c2e63fdfb9fd5b48d550b82331"
)
CRC_LISTING_BYTES = 2_304_719
CRC_LISTING_SHA256 = (
    "4733b0a5cd9cd2c6a73f3510038b03493e03a77bf0d86fc9500624125be54073"
)
CRC_CORPUS_DIGEST_SHA256 = (
    "07be70d9f4f44a79a96e8e740b57b8d8d572561e0595b2fa7622770e1d206671"
)

MOS_BUILD_RECEIPT_BYTES = 58_287
MOS_BUILD_RECEIPT_SHA256 = (
    "054cee76aaf70adcf40edd7f2ed5a270158af77b1303b463fc838afb38f61ad8"
)
ACCEPTED_PROGRAM_BYTES = 142_763
ACCEPTED_PROGRAM_SHA256 = (
    "27f09db1eb0b0eec702aad5c17f35e68922f154a6c3391370d07a76027cc57bf"
)
ACCEPTED_SYMBOLS_BYTES = 66_112
ACCEPTED_SYMBOLS_SHA256 = (
    "b1a9d5e35560df89c556f276b0910c6abf687416f0292d99882d891b46b07262"
)
ACCEPTED_LISTING_BYTES = 2_304_719
ACCEPTED_LISTING_SHA256 = (
    "4951950b4f80c56a96c46246c56e1f314e5eae070600ddc9fce0111073439696"
)
PINNED_MOS_SHA256 = mos_profile.builder.PINNED_MOS_SHA256
PATCHED_MOS_SHA256 = mos_profile.builder.PATCHED_MOS_SHA256
PINNED_MAP_SHA256 = mos_profile.builder.PINNED_MAP_SHA256


class CombinedProfileError(RuntimeError):
    """A qualified input, transcript, semantic, or timing gate failed."""


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    role: str
    program: Path
    program_bytes: int
    program_sha256: str
    symbols: Path
    symbols_bytes: int
    symbols_sha256: str
    mos: Path
    mos_sha256: str


@dataclass(frozen=True, slots=True)
class QualifiedInputs:
    control: Variant
    candidate: Variant
    crc_receipt: Path
    mos_receipt: Path
    identity: Mapping[str, Mapping[str, object]]
    composition: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StagedRun:
    directory: Path
    program: Path
    symbols: Path
    mos: Path
    mos_map: Path


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crc-build", type=Path, default=DEFAULT_CRC_BUILD)
    parser.add_argument("--mos-build", type=Path, default=DEFAULT_MOS_BUILD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=900.0)
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
        raise CombinedProfileError(f"missing artifact: {resolved}")
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
        raise CombinedProfileError(
            f"{description} identity changed: bytes={actual_bytes} "
            f"sha256={actual_sha256}"
        )
    return path


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CombinedProfileError(f"unreadable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CombinedProfileError(f"JSON root is not an object: {path}")
    return value


def load_canonical_receipt(path: Path, description: str) -> dict[str, object]:
    """Load a fail-closed BUILD receipt without pinning irrelevant context bytes."""

    if path.is_symlink() or not path.is_file():
        raise CombinedProfileError(f"missing {description}: {path}")
    receipt = load_json(path)
    canonical = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    if path.read_bytes() != canonical:
        raise CombinedProfileError(f"{description} is not canonical JSON")
    return receipt


def validate_crc_build(build: Path) -> tuple[Path, Path, Path, Path]:
    receipt_path = require_file(
        build / "BUILD.json",
        CRC_BUILD_RECEIPT_BYTES,
        CRC_BUILD_RECEIPT_SHA256,
        "qualified CRC BUILD receipt",
    )
    canonical_receipt = load_canonical_receipt(
        receipt_path, "qualified CRC BUILD receipt"
    )
    program, symbols, receipt = crc_profile.validate_build(build)
    if receipt != canonical_receipt:
        raise CombinedProfileError("CRC BUILD receipt changed while validating")
    listing = build / f"{crc_builder.PROGRAM_STEM}.lst"
    require_file(program, CRC_PROGRAM_BYTES, CRC_PROGRAM_SHA256, "CRC program")
    require_file(symbols, CRC_SYMBOLS_BYTES, CRC_SYMBOLS_SHA256, "CRC symbols")
    require_file(listing, CRC_LISTING_BYTES, CRC_LISTING_SHA256, "CRC listing")
    artifacts = receipt.get("artifacts")
    expected = {
        "program": (program, CRC_PROGRAM_BYTES, CRC_PROGRAM_SHA256),
        "symbols": (symbols, CRC_SYMBOLS_BYTES, CRC_SYMBOLS_SHA256),
        "listing": (listing, CRC_LISTING_BYTES, CRC_LISTING_SHA256),
    }
    if not isinstance(artifacts, dict):
        raise CombinedProfileError("CRC receipt artifacts changed")
    for name, (path, size, digest) in expected.items():
        entry = artifacts.get(name)
        if not isinstance(entry, dict) or entry != {
            "key": f"artifacts/{path.name}",
            "bytes": size,
            "sha256": digest,
        }:
            raise CombinedProfileError(f"CRC receipt {name} binding changed")
    corpus = receipt.get("cold_corpus_crc")
    if not isinstance(corpus, dict) or (
        corpus.get("qualified") is not True
        or corpus.get("coverage_digest_sha256") != CRC_CORPUS_DIGEST_SHA256
        or corpus.get("aggregates", {}).get("records") != EXPECTED_RECORDS
    ):
        raise CombinedProfileError("CRC receipt corpus qualification changed")
    manager_semantics = corpus.get("manager_semantics")
    accepted_inputs = receipt.get("accepted_inputs")
    if (
        manager_semantics
        != {
            "schema": crc_builder.EXPECTED_MANAGER_SCHEMA,
            "selected_field": "initial_view.records",
            "records": EXPECTED_RECORDS,
            "application_context_not_bound": ["binary", "manager.loader_crc32"],
            "manifest_path_or_file_identity_receipted": False,
        }
        or not isinstance(accepted_inputs, Mapping)
        or "manager_manifest" in accepted_inputs
    ):
        raise CombinedProfileError("CRC receipt manager semantic witness changed")
    host = receipt.get("host_differential")
    if not isinstance(host, dict) or (
        host.get("count") != 30
        or host.get("digest_sha256") != crc_builder.EXPECTED_VECTOR_DIGEST_SHA256
    ):
        raise CombinedProfileError("CRC host differential qualification changed")
    if (
        corpus.get("all_stored_host_register_crcs_exact") is not True
        or corpus.get("all_single_bit_corruptions_rejected") is not True
    ):
        raise CombinedProfileError("CRC corpus positive/negative gates changed")
    instruction = receipt.get("instruction_contract")
    if not isinstance(instruction, dict) or (
        instruction.get("crc_registers_low_to_high") != ["L", "H", "E", "D"]
        or instruction.get("interrupt_mask_unchanged") is not True
        or instruction.get("success_result") != "A=0, Z=1"
    ):
        raise CombinedProfileError("CRC instruction contract changed")
    adl = receipt.get("adl_audit")
    if not isinstance(adl, dict) or (
        adl.get("command_succeeded") is not True
        or adl.get("fail_review") is not True
        or adl.get("follow_includes") is not True
    ):
        raise CombinedProfileError("CRC ADL audit qualification changed")
    return program, symbols, listing, receipt_path


def validate_mos_build(build: Path) -> tuple[Path, Path, Path]:
    receipt_path = require_file(
        build / mos_profile.builder.REPORT_NAME,
        MOS_BUILD_RECEIPT_BYTES,
        MOS_BUILD_RECEIPT_SHA256,
        "qualified MOS BUILD receipt",
    )
    canonical_receipt = load_canonical_receipt(
        receipt_path, "qualified MOS BUILD receipt"
    )
    control, candidate, receipt = mos_profile.validate_build(build)
    if receipt != canonical_receipt:
        raise CombinedProfileError("MOS BUILD receipt changed while validating")
    require_file(
        control,
        mos_profile.builder.PINNED_MOS_BYTES,
        PINNED_MOS_SHA256,
        "pinned TEMT MOS control",
    )
    require_file(
        candidate,
        mos_profile.builder.PINNED_MOS_BYTES,
        PATCHED_MOS_SHA256,
        "qualified THRE MOS candidate",
    )
    patch = receipt.get("patch")
    if not isinstance(patch, dict) or (
        patch.get("changed_offsets") != [mos_profile.builder.UART0_TX_MASK_OFFSET]
        or patch.get("before") != mos_profile.builder.TEMT_MASK
        or patch.get("after") != mos_profile.builder.THRE_MASK
        or patch.get("all_other_bytes_exact") is not True
        or patch.get("reverse_patch_exact") is not True
    ):
        raise CombinedProfileError("qualified MOS one-byte patch changed")
    runtime_corpus = receipt.get("runtime_corpus")
    inputs = receipt.get("inputs")
    if (
        not isinstance(runtime_corpus, Mapping)
        or runtime_corpus.get("manager_semantics")
        != {
            "schema": mos_profile.builder.EXPECTED_MANAGER_SCHEMA,
            "selected_field": "initial_view.records",
            "records": EXPECTED_RECORDS,
            "application_context_not_bound": ["binary", "manager.loader_crc32"],
            "manifest_path_or_file_identity_receipted": False,
        }
        or not isinstance(inputs, Mapping)
        or "current_manager_manifest" in inputs
    ):
        raise CombinedProfileError("MOS receipt manager semantic witness changed")
    return control, candidate, receipt_path


def validate_inputs(crc_build: Path, mos_build: Path) -> QualifiedInputs:
    crc_build = crc_build.expanduser().resolve()
    mos_build = mos_build.expanduser().resolve()
    crc_program, crc_symbols, crc_listing, crc_receipt = validate_crc_build(crc_build)
    control_mos, candidate_mos, mos_receipt = validate_mos_build(mos_build)
    accepted_program, accepted_listing, accepted_symbols = (
        crc_profile.validate_legacy_control(crc_build)
    )
    require_file(
        accepted_program,
        ACCEPTED_PROGRAM_BYTES,
        ACCEPTED_PROGRAM_SHA256,
        "private historical CRC1 control program",
    )
    require_file(
        accepted_listing,
        ACCEPTED_LISTING_BYTES,
        ACCEPTED_LISTING_SHA256,
        "private historical CRC1 control listing",
    )
    require_file(
        accepted_symbols,
        ACCEPTED_SYMBOLS_BYTES,
        ACCEPTED_SYMBOLS_SHA256,
        "private historical CRC1 control symbols",
    )
    mos_control_program, mos_control_listing, mos_control_symbols = (
        mos_profile.validate_crc1_control(mos_build)
    )
    for name, left, right in (
        ("program", accepted_program, mos_control_program),
        ("listing", accepted_listing, mos_control_listing),
        ("symbols", accepted_symbols, mos_control_symbols),
    ):
        if left.read_bytes() != right.read_bytes():
            raise CombinedProfileError(
                f"CRC and MOS builds bind different private CRC1 {name}"
            )
    mos_profile.builder.require_accepted_inputs()
    mos_profile.builder.validate_pinned_contract()
    mos_profile.builder.validate_reference_source_context()
    mos_profile.builder.validate_runtime_corpus()
    identity_paths = {
        "crc_build_receipt": crc_receipt,
        "crc_program": crc_program,
        "crc_symbols": crc_symbols,
        "crc_listing": crc_listing,
        "mos_build_receipt": mos_receipt,
        "control_mos": control_mos,
        "candidate_mos": candidate_mos,
        "historical_crc1_program": accepted_program,
        "historical_crc1_listing": accepted_listing,
        "historical_crc1_symbols": accepted_symbols,
        "pinned_map": mos_profile.builder.PINNED_MAP,
        "manager_manifest": mos_profile.builder.MANAGER_MANIFEST,
        "world_manifest": mos_profile.builder.WORLD_MANIFEST,
    }
    identity = {name: artifact(path) for name, path in identity_paths.items()}
    control_uart = uart_profile.resolve_layout(
        accepted_program, accepted_symbols, candidate=False
    )
    candidate_uart = uart_profile.resolve_layout(
        crc_program, crc_symbols, candidate=False
    )
    candidate_symbol_values = mos_profile.staged.parse_symbols(crc_symbols)
    local_uart_symbols = sorted(
        name for name in candidate_symbol_values if name.startswith("p3dm_uart0_")
    )
    if (
        control_uart.sender_call != 0x043979
        or candidate_uart.sender_call != 0x04396C
        or control_uart.sender_kind != "Console8 RST18 counted DATA write"
        or candidate_uart.sender_kind != "Console8 RST18 counted DATA write"
        or local_uart_symbols
        or candidate_uart.file_buffer != 0x043AF3
    ):
        raise CombinedProfileError("candidate composition is not CRC-only app plus MOS")
    composition = {
        "application_patch_count": 1,
        "application_patch": "qualified register-resident CRC block only",
        "mos_patch_count": 1,
        "mos_patch": "qualified UART0 TX mask byte 0x40 to 0x20 only",
        "third_patch": False,
        "control_rst18_data_sender": control_uart.sender_call,
        "candidate_rst18_data_sender": candidate_uart.sender_call,
        "candidate_sender_shift": candidate_uart.sender_call - control_uart.sender_call,
        "candidate_file_buffer": candidate_uart.file_buffer,
        "candidate_application_local_uart_symbols": local_uart_symbols,
        "three_rst18_uploads_retained": True,
    }
    return QualifiedInputs(
        control=Variant(
            name="accepted-temt-control",
            role="private historical CRC1 P3DRGL + pinned TEMT MOS",
            program=accepted_program,
            program_bytes=ACCEPTED_PROGRAM_BYTES,
            program_sha256=ACCEPTED_PROGRAM_SHA256,
            symbols=accepted_symbols,
            symbols_bytes=ACCEPTED_SYMBOLS_BYTES,
            symbols_sha256=ACCEPTED_SYMBOLS_SHA256,
            mos=control_mos,
            mos_sha256=PINNED_MOS_SHA256,
        ),
        candidate=Variant(
            name="crc-register-thre-candidate",
            role="qualified CRC-register P3DRGL + qualified THRE MOS",
            program=crc_program,
            program_bytes=CRC_PROGRAM_BYTES,
            program_sha256=CRC_PROGRAM_SHA256,
            symbols=crc_symbols,
            symbols_bytes=CRC_SYMBOLS_BYTES,
            symbols_sha256=CRC_SYMBOLS_SHA256,
            mos=candidate_mos,
            mos_sha256=PATCHED_MOS_SHA256,
        ),
        crc_receipt=crc_receipt,
        mos_receipt=mos_receipt,
        identity=identity,
        composition=composition,
    )


def _offsets(payload: bytes, needle: bytes) -> list[int]:
    result = []
    cursor = 0
    while True:
        offset = payload.find(needle, cursor)
        if offset < 0:
            return result
        result.append(offset)
        cursor = offset + 1


EXPECTED_LAYOUTS = {
    ACCEPTED_PROGRAM_SHA256: {
        "read_call": 0x043067,
        "upload_call": 0x04307B,
        "submit_target": 0x042E27,
        "startup_submit_call": 0x0629C1,
        "loop_submit_call": 0x062A09,
        "startup_window": "cd272e04cd6c0004",
        "loop_window": "cd272e0418b6cdf4",
    },
    CRC_PROGRAM_SHA256: {
        "read_call": 0x043067,
        "upload_call": 0x04307B,
        "submit_target": 0x042E27,
        "startup_submit_call": 0x0629B4,
        "loop_submit_call": 0x0629FC,
        "startup_window": "cd272e04cd6c0004",
        "loop_window": "cd272e0418b6cde7",
    },
}


def resolve_normative_layout(
    program: Path, symbols_path: Path
) -> mos_profile.NormativeLayout:
    digest = sha256(program)
    expected = EXPECTED_LAYOUTS.get(digest)
    if expected is None:
        raise CombinedProfileError("normative program identity is not qualified")
    symbols = mos_profile.staged.parse_symbols(symbols_path)
    phases = mos_profile.cold.resolve_phase_spans(program, symbols)
    by_name = {phase.name: phase for phase in phases}
    required = {"main", "manager_survey_apply_radius_request", "submit_current_render"}
    missing = sorted(required - symbols.keys())
    if missing:
        raise CombinedProfileError(f"normative symbols omit: {missing}")
    target = symbols["submit_current_render"]
    if target != expected["submit_target"]:
        raise CombinedProfileError("submit_current_render target changed")
    image = program.read_bytes()
    main_start = symbols["main"]
    main_end = symbols["manager_survey_apply_radius_request"]
    load = mos_profile.PROGRAM_LOAD_ADDRESS
    if not load <= main_start < main_end <= load + len(image):
        raise CombinedProfileError("main body escaped qualified program")
    body = image[main_start - load : main_end - load]
    encoded = bytes((0xCD,)) + target.to_bytes(3, "little")
    calls = [main_start + offset for offset in _offsets(body, encoded)]
    wanted_calls = [expected["startup_submit_call"], expected["loop_submit_call"]]
    if calls != wanted_calls:
        raise CombinedProfileError(f"submit call sites changed: {calls}")
    for name in ("startup", "loop"):
        address = int(expected[f"{name}_submit_call"])
        wanted = bytes.fromhex(str(expected[f"{name}_window"]))
        actual = image[address - load : address - load + len(wanted)]
        if actual != wanted:
            raise CombinedProfileError(
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
        raise CombinedProfileError("read/upload normative boundary changed")
    layout.breakpoints
    return layout


def layout_evidence(
    program: Path, layout: mos_profile.NormativeLayout
) -> dict[str, object]:
    value = layout.as_dict()
    value.update(
        {
            "program_sha256": sha256(program),
            "submit_calls_resolved_from_own_symbols_and_program": True,
            "expected_identity": EXPECTED_LAYOUTS[sha256(program)],
        }
    )
    return value


def prepare_run_output(output: Path, mode: str, variant: Variant) -> StagedRun:
    directory = output / f"{mode}-{variant.name}"
    directory.mkdir()
    program = directory / f"P3DRGL.{variant.name}.bin"
    symbols = directory / f"P3DRGL.{variant.name}.symbols"
    mos = directory / variant.mos.name
    mos_map = mos.with_suffix(".map")
    shutil.copyfile(variant.program, program)
    shutil.copyfile(variant.symbols, symbols)
    shutil.copyfile(variant.mos, mos)
    shutil.copyfile(mos_profile.builder.PINNED_MAP, mos_map)
    require_file(program, variant.program_bytes, variant.program_sha256, "run program")
    require_file(symbols, variant.symbols_bytes, variant.symbols_sha256, "run symbols")
    require_file(
        mos,
        mos_profile.builder.PINNED_MOS_BYTES,
        variant.mos_sha256,
        "run MOS",
    )
    require_file(
        mos_map,
        mos_profile.builder.PINNED_MAP_BYTES,
        PINNED_MAP_SHA256,
        "run same-stem MOS map",
    )
    mos_profile.write_exact_autoexec(directory / "autoexec.txt")
    staged_run = StagedRun(directory, program, symbols, mos, mos_map)
    validate_staged_run(staged_run, variant)
    return staged_run


def validate_staged_run(staged_run: StagedRun, variant: Variant) -> None:
    require_file(
        staged_run.program,
        variant.program_bytes,
        variant.program_sha256,
        "run-local program",
    )
    require_file(
        staged_run.symbols,
        variant.symbols_bytes,
        variant.symbols_sha256,
        "run-local symbols",
    )
    require_file(
        staged_run.mos,
        mos_profile.builder.PINNED_MOS_BYTES,
        variant.mos_sha256,
        "run-local MOS",
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
        raise CombinedProfileError("run-local autoexec bytes changed")


def run_normative(
    variant: Variant,
    *,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    staged_run = prepare_run_output(output, "normative", variant)
    layout = resolve_normative_layout(staged_run.program, staged_run.symbols)
    log_path = staged_run.directory / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: mos_profile.NormativeProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"combo-norm-{variant.name}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"combo-norm-{variant.name}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        mos_profile.staged.stage_fixture(sd_root, staged_run.program)
        corpus_before = mos_profile.builder.validate_runtime_corpus(sd_root / "survey")
        mos_profile.write_exact_autoexec(sd_root / "autoexec.txt")
        command = mos_profile.emulator_command(
            sd_root, vdp, staged_run.mos, variant.mos_sha256, layout.breakpoints
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
                profiler = mos_profile.NormativeProfiler(process, layout, EXPECTED_RECORDS)
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: (
                        mos_profile.staged.COLD_RENDER_MARKER in value
                        and profiler.complete
                    ),
                    f"{variant.name} combined normative cold fill",
                    service=profiler.service,
                )
                profiler.require_complete()
                mos_profile.shutdown(process, log_path, deadline)
                corpus_after = mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                if corpus_after != corpus_before:
                    raise CombinedProfileError(
                        f"{variant.name} staged corpus changed during normative run"
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


def run_diagnostic(
    variant: Variant,
    *,
    vdp: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    staged_run = prepare_run_output(output, "diagnostic", variant)
    symbols = mos_profile.staged.parse_symbols(staged_run.symbols)
    phases = mos_profile.cold.resolve_phase_spans(staged_run.program, symbols)
    boundaries = mos_profile.cold.execution_boundary_sequence(phases)
    log_path = staged_run.directory / "emulator.log"
    process: subprocess.Popen[bytes] | None = None
    profiler: mos_profile.cold.ColdLoadCycleProfiler | None = None
    corpus_before: dict[str, object] | None = None
    corpus_after: dict[str, object] | None = None
    deadline = time.monotonic() + timeout
    with (
        tempfile.TemporaryDirectory(prefix=f"combo-diag-{variant.name}-sd-") as sd_name,
        tempfile.TemporaryDirectory(prefix=f"combo-diag-{variant.name}-run-") as cwd_name,
    ):
        sd_root = Path(sd_name)
        mos_profile.staged.stage_fixture(sd_root, staged_run.program)
        corpus_before = mos_profile.builder.validate_runtime_corpus(sd_root / "survey")
        mos_profile.write_exact_autoexec(sd_root / "autoexec.txt")
        command = mos_profile.emulator_command(
            sd_root, vdp, staged_run.mos, variant.mos_sha256, boundaries
        )
        (staged_run.directory / "command.json").write_text(
            json.dumps(
                {
                    "argv": command,
                    "mode": "diagnostic-five-call-spans",
                    "variant": variant.name,
                    "role": variant.role,
                    "program": artifact(staged_run.program),
                    "symbols": artifact(staged_run.symbols),
                    "mos": artifact(staged_run.mos),
                    "mos_map": artifact(staged_run.mos_map),
                    "phases": [phase.as_dict() for phase in phases],
                    "breakpoints": list(boundaries),
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
                profiler = mos_profile.cold.ColdLoadCycleProfiler(
                    process, phases, EXPECTED_RECORDS
                )
                mos_profile.staged.wait_for_log(
                    log_path,
                    process,
                    deadline,
                    lambda value: (
                        mos_profile.staged.COLD_RENDER_MARKER in value
                        and profiler.complete
                    ),
                    f"{variant.name} combined diagnostic cold fill",
                    service=profiler.service,
                )
                profiler.require_complete()
                mos_profile.shutdown(process, log_path, deadline)
                corpus_after = mos_profile.builder.validate_runtime_corpus(
                    sd_root / "survey"
                )
                if corpus_after != corpus_before:
                    raise CombinedProfileError(
                        f"{variant.name} staged corpus changed during diagnostic run"
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
    phase_cycles = mos_profile.cold.parse_phase_cycles(
        contents, phases, EXPECTED_RECORDS
    )
    five_phase_cycles = [
        sum(phase_cycles[name][order] for name in mos_profile.cold.PHASE_NAMES)
        for order in range(EXPECTED_RECORDS)
    ]
    bound = mos_profile.cold.validate_record_bindings(
        mos_profile.regular_capture.initial_records(), publications, phase_cycles
    )
    return {
        "mode": "diagnostic-five-call-spans",
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
        "runtime_corpus": {
            "before": mos_profile.corpus_witness(corpus_before),
            "after": mos_profile.corpus_witness(corpus_after),
            "unchanged": True,
        },
        "cold_endpoint": endpoint,
        "publication_semantics": mos_profile.publication_semantics(publications),
        "render_sequences": render_evidence["qualified_prefix"],
        "render_evidence": render_evidence,
        "live": profiler.require_complete(),
        "phases": {
            name: {
                "cycles": phase_cycles[name],
                "summary": mos_profile.summarize_distribution(
                    phase_cycles[name]
                ).as_dict(),
                "completion_equivalent": False,
            }
            for name in mos_profile.cold.PHASE_NAMES
        },
        "measured_five_phase_guest_cycles_total": {
            "cycles": five_phase_cycles,
            "summary": mos_profile.summarize_distribution(
                five_phase_cycles
            ).as_dict(),
            "completion_equivalent": False,
        },
        "records": bound,
        "emulator_exit_status": process.returncode,
    }


def assert_semantic_equivalence(
    control: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    mos_profile.assert_semantic_equivalence(control, candidate)


def paired_metric(
    control: Mapping[str, object],
    candidate: Mapping[str, object],
    metric: str,
    boundary: str,
) -> dict[str, object]:
    return mos_profile.paired_metric(control, candidate, metric, boundary)


def diagnostic_comparison(
    control: Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    result = mos_profile.diagnostic_comparison(control, candidate)
    left = control.get("measured_five_phase_guest_cycles_total")
    right = candidate.get("measured_five_phase_guest_cycles_total")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise CombinedProfileError("diagnostic five-phase totals are missing")
    left_summary = left.get("summary")
    right_summary = right.get("summary")
    before = left_summary.get("total") if isinstance(left_summary, dict) else None
    after = right_summary.get("total") if isinstance(right_summary, dict) else None
    if (
        not isinstance(before, int)
        or not isinstance(after, int)
        or before <= 0
    ):
        raise CombinedProfileError("diagnostic five-phase totals are invalid")
    result["measured_five_phase_guest_cycles_total"] = {
        "control_cycles": before,
        "candidate_cycles": after,
        "delta_cycles": after - before,
        "candidate_vs_control_percent": (after - before) * 100.0 / before,
        "completion_equivalent": False,
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    if args.timeout <= 0:
        raise CombinedProfileError("--timeout must be positive")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise CombinedProfileError(f"refusing to replace existing output: {output}")
    inputs = validate_inputs(args.crc_build, args.mos_build)
    initial_identity = dict(inputs.identity)
    canonical_corpus = mos_profile.builder.validate_runtime_corpus()
    vdp = mos_profile.staged.require_file(args.vdp_module, "diagnostic VDP module")
    mos_profile.survey.require_diagnostic_vdp(vdp)
    emulator_sha256 = sha256(mos_profile.input_trace.FAB_BINARY)
    vdp_sha256 = sha256(vdp)
    script_sha256 = sha256(Path(__file__))
    output.mkdir(parents=True)

    normative_control = run_normative(
        inputs.control, vdp=vdp, output=output, timeout=args.timeout
    )
    normative_candidate = run_normative(
        inputs.candidate, vdp=vdp, output=output, timeout=args.timeout
    )
    assert_semantic_equivalence(normative_control, normative_candidate)

    diagnostic_control = run_diagnostic(
        inputs.control, vdp=vdp, output=output, timeout=args.timeout
    )
    diagnostic_candidate = run_diagnostic(
        inputs.candidate, vdp=vdp, output=output, timeout=args.timeout
    )
    assert_semantic_equivalence(diagnostic_control, diagnostic_candidate)
    for normative, diagnostic in (
        (normative_control, diagnostic_control),
        (normative_candidate, diagnostic_candidate),
    ):
        for name in ("cold_endpoint", "publication_semantics", "render_sequences"):
            if normative[name] != diagnostic[name]:
                raise CombinedProfileError(
                    f"normative/diagnostic {normative['variant']} {name} differs"
                )

    final_inputs = validate_inputs(args.crc_build, args.mos_build)
    if dict(final_inputs.identity) != initial_identity:
        raise CombinedProfileError("qualified component identities changed during run")
    if mos_profile.builder.validate_runtime_corpus() != canonical_corpus:
        raise CombinedProfileError("canonical runtime corpus changed during run")
    if sha256(mos_profile.input_trace.FAB_BINARY) != emulator_sha256:
        raise CombinedProfileError("emulator identity changed during run")
    if sha256(vdp) != vdp_sha256:
        raise CombinedProfileError("VDP identity changed during run")
    if sha256(Path(__file__)) != script_sha256:
        raise CombinedProfileError("combined profile script changed during run")

    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "third_code_patch_created": False,
            "accepted_files_modified": False,
            "crc_sibling_builder_modified": False,
            "mos_sibling_builder_modified": False,
            "fresh_process_per_run": True,
            "normative_pair_count": 1,
            "diagnostic_pair_count": 1,
            "records_per_run": EXPECTED_RECORDS,
            "normative_breakpoints_per_record": 3,
            "no_normative_breakpoint_after_upload_before_submit": True,
            "publication_must_precede_matching_submit_marker": True,
            "all_227_runtime_files_exact_before_and_after_every_run": True,
            "run_local_program_symbols_mos_map_autoexec_exact_pre_and_post": True,
            "candidate_shifted_symbols_and_submit_sites_resolved_independently": True,
            "diagnostic_call_spans_are_not_completion_equivalent": True,
        },
        "identity": {
            **initial_identity,
            "profile_script": artifact(Path(__file__)),
            "emulator": artifact(mos_profile.input_trace.FAB_BINARY),
            "vdp": artifact(vdp),
            "runtime_corpus": mos_profile.corpus_witness(canonical_corpus),
        },
        "component_matrix": {
            "control": {
                "application": ACCEPTED_PROGRAM_SHA256,
                "symbols": ACCEPTED_SYMBOLS_SHA256,
                "mos": PINNED_MOS_SHA256,
            },
            "candidate": {
                "application": CRC_PROGRAM_SHA256,
                "symbols": CRC_SYMBOLS_SHA256,
                "mos": PATCHED_MOS_SHA256,
            },
            "no_cross_built_or_new_binary": True,
            "static_composition": inputs.composition,
        },
        "semantic_equivalence": {
            "all_four_runs_exact": True,
            "publications_each_run": EXPECTED_RECORDS,
            "publication_order_shapes_and_manifest_files_exact": True,
            "cold_endpoint_exact": True,
            "render_prefix_0_through_226_exact": True,
            "shutdown_tails_recorded_bounded_and_scene_stable": True,
        },
        "normative_comparison": {
            metric: {
                "loop_records_1_through_226": paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_loop_226",
                ),
                "all_records_including_startup_0": paired_metric(
                    normative_control,
                    normative_candidate,
                    metric,
                    "summary_all_227",
                ),
                "cumulative_end_to_end": True,
                "interpretation": (
                    "guest cycles through the matching submit call after the nth "
                    "successful VDP publication; includes combined CRC and MOS effects"
                ),
            }
            for metric in (
                "upload_to_publication_complete_submit",
                "read_to_publication_complete_submit",
            )
        },
        "diagnostic_comparison": diagnostic_comparison(
            diagnostic_control, diagnostic_candidate
        ),
        "diagnostic_interpretation": {
            "completion_equivalent": False,
            "validate_container_attributes_crc_algorithm_work": True,
            "upload_and_command_spans_expose_uart_work": True,
            "not_an_additive_component_decomposition": True,
            "reason": (
                "the MOS-wide THRE change alters every UART0 TX caller and raw "
                "call endpoints can leave different queued transmitter state"
            ),
        },
        "runs": [
            normative_control,
            normative_candidate,
            diagnostic_control,
            diagnostic_candidate,
        ],
        "limitations": {
            "single_emulator_pair_does_not_establish_repeatability": True,
            "exact_image_emulator_evidence_only": True,
            "hardware_uart_cts_fifo_timing_qualification_open": True,
            "thre_return_does_not_imply_transmitter_idle": True,
            "mos_patch_affects_every_uart0_serial_tx_caller": True,
            "must_not_install_or_distribute_patched_mos_blob": True,
            "normal_mos_source_rebuild_required_for_promotion": True,
            "crc_and_mos_components_remain_separately_owned": True,
        },
    }
    report_path = output / REPORT_NAME
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Combined CRC-register + MOS-THRE profile passed: {report_path}")
    for metric, comparison in report["normative_comparison"].items():
        loop = comparison["loop_records_1_through_226"]
        print(
            f"{metric}: control={loop['control_cycles']} "
            f"candidate={loop['candidate_cycles']} "
            f"percent={loop['candidate_vs_control_percent']} "
            "publication_complete=True"
        )
    print("four_runs=4 records_each=227 combined_components_only=True")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        CombinedProfileError,
        crc_profile.CrcSiblingProfileError,
        mos_profile.MosUartThreProfileError,
        mos_profile.builder.MosUartThreBuildError,
    ) as error:
        raise SystemExit(f"combined CRC+MOS profile failed: {error}") from error
