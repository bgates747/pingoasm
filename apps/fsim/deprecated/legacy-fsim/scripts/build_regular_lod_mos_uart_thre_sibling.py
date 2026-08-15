#!/usr/bin/env python3
"""Build a one-byte Console8 MOS sibling using UART0 THRE readiness.

This is a binary experiment for a future source-level MOS change.  It never
edits the external Fab checkout: the exact pinned ``mos_console8.bin`` is read
as an immutable input, its proven UART0 TX ``AND 40h`` immediate is changed to
``AND 20h`` in memory, and a separately named ignored sibling is emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

import build_regular_lod_crc_register_sibling as crc_builder


ROOT = Path(__file__).resolve().parent.parent
FAB_ROOT = Path.home() / "Agon/mystuff/fab-agon-emulator"
PINNED_MOS = FAB_ROOT / "firmware/mos_console8.bin"
PINNED_MAP = FAB_ROOT / "firmware/mos_console8.map"
DEFAULT_OUTPUT = ROOT / "build/evidence/regular-lod-mos-uart-thre-sibling-build-v3"
DEFAULT_CRC_BUILD = crc_builder.DEFAULT_OUTPUT
CONTROL_MOS_NAME = "mos_console8_uart_temt_control.bin"
CANDIDATE_MOS_NAME = "mos_console8_uart_thre_candidate.bin"
REPORT_NAME = "BUILD.json"
SCHEMA = "pingo-terrain-regular-lod-mos-uart-thre-sibling-build-v1"

PINNED_MOS_BYTES = 81_072
PINNED_MOS_SHA256 = (
    "5fbacb749ee037f0428aeac39817b5a6d465adc020f92d4020bb7dcb046d39fe"
)
PINNED_MAP_BYTES = 153_448
PINNED_MAP_SHA256 = (
    "2d3fb36ec90a073d4e0f5f665f75bd788338275906ffc07309c83e969d0368b0"
)
PATCHED_MOS_SHA256 = (
    "c8c347a7c04af35d6be51e0c85c5b50e689d923da39992d42880f4e88eba968c"
)

ACCEPTED_SOURCE = ROOT / "fixtures/terrain-manager-survey/src/terrain-manager-regular-lod-survey.asm"
ACCEPTED_LOADER = ROOT / "fixtures/p3dm-loader-probe/src/p3dm-loader.inc"
REGULAR_TARGET = ROOT / "fixtures/terrain-manager-regular-lod-survey/tgt"
ACCEPTED_RUNTIME_INCLUDE = REGULAR_TARGET / "regular-lod-runtime.inc"
ACCEPTED_TRANSITION_INCLUDE = REGULAR_TARGET / "regular-lod-transitions.inc"
MANAGER_MANIFEST = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy/MANAGER.json"
WORLD_MANIFEST = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy/WORLD.json"
RUNTIME_FIXTURE = MANAGER_MANIFEST.parent
REFERENCE_SERIAL_SOURCE = Path.home() / "Agon/agon-mos/src/serial.asm"
REFERENCE_SERIAL_SOURCE_BYTES = 8_054
REFERENCE_SERIAL_SOURCE_SHA256 = (
    "53905f372f388256968f61d5304d510069f463b2967931224c81a73fa8575b47"
)
ACCEPTED_INPUT_SPECS = {
    "source": (
        ACCEPTED_SOURCE,
        17_765,
        "760a657db1b16b88c6c8921821f59bfc5ca6a14e56896409db4a6065b351d1fe",
    ),
    "loader": (
        ACCEPTED_LOADER,
        30_250,
        "15215e21d0bb3a3277fa31e9a73d9beae341b3495e2a0a281fc200131472ddc3",
    ),
    "runtime_include": (
        ACCEPTED_RUNTIME_INCLUDE,
        427_712,
        "22607a410cb2c3ef3506d30d542a7eb7a14160bec8c73bd68a6abb33f204aff4",
    ),
    "transition_include": (
        ACCEPTED_TRANSITION_INCLUDE,
        109_831,
        "aa6a3d152370f59fc2cefceacc46766bfc3425cb012be927beb5a758788de749",
    ),
    "world_manifest": (
        WORLD_MANIFEST,
        69_293_127,
        "382e7c7e9ec46ddb4d57bd51db706e441a37e52b7538d2af1b384fa9a053c04e",
    ),
}
CRC1_CONTROL_ARTIFACTS = {
    "legacy_control_program": (
        "bin",
        142_763,
        crc_builder.ACCEPTED_PROGRAM_SHA256,
    ),
    "legacy_control_listing": (
        "lst",
        2_304_719,
        "4951950b4f80c56a96c46246c56e1f314e5eae070600ddc9fce0111073439696",
    ),
    "legacy_control_symbols": (
        "symbols",
        66_112,
        "b1a9d5e35560df89c556f276b0910c6abf687416f0292d99882d891b46b07262",
    ),
}

RST18_VECTOR_OFFSET = 0x0018
RST18_TARGET = 0x001422
RST18_UART_CALL_OFFSET = 0x00142F
UART0_CTS_OFFSET = 0x001044
UART0_TX_OFFSET = 0x001056
UART0_TX_MASK_OFFSET = 0x001060
UART0_TX_THR_OFFSET = 0x00106D
UART0_PUTCH_OFFSET = 0x0010CA
TEMT_MASK = 0x40
THRE_MASK = 0x20
P3DM_DATA_OFFSET = 100
EXPECTED_RECORDS = 227
EXPECTED_CONTAINER_BYTES = 787_192
EXPECTED_DATA_BYTES = 764_288
EXPECTED_MAXIMUM_RECORD_BYTES = 4_568
EXPECTED_MANAGER_SCHEMA = "pingo-terrain-regular-lod-manager-survey-v2"
EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256 = (
    "1cf09313ba0b2983a4a8c9f09fb01bfb0c3e9d854bb7520d988043ccaace141d"
)

RST18_VECTOR = bytes.fromhex("5bc3221400")
RST18_COUNTED_LOOP = bytes.fromhex(
    "5fed6eb7c4f4070078b1280d7ecdca1000230b78b120f55bc9"
)
UART0_CTS_WAIT = bytes.fromhex("ed38a2ed640820f8c9")
UART0_PUTCH = bytes.fromhex(
    "f53a2dc30bed64012828ed6402c4441000f1cd56100030fac9"
)
UART0_TX_TEMT = bytes.fromhex(
    "c5f501004000ed38c5e64020090b78b120f4f1c1b7c9f1ed39c0c137c9"
)
UART0_TX_THRE = bytes.fromhex(
    "c5f501004000ed38c5e62020090b78b120f4f1c1b7c9f1ed39c0c137c9"
)


class MosUartThreBuildError(RuntimeError):
    """An immutable input, opcode, diff, or determinism gate failed."""


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--crc-build",
        type=Path,
        default=DEFAULT_CRC_BUILD,
        help="CRC-register build containing the private historical CRC1 trio",
    )
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
    if not resolved.is_file():
        raise MosUartThreBuildError(f"missing artifact: {resolved}")
    if key is None:
        try:
            key = str(resolved.relative_to(ROOT))
        except ValueError:
            key = resolved.name
    return {"key": key, "bytes": resolved.stat().st_size, "sha256": sha256_file(resolved)}


def require_file(path: Path, size: int, digest: str, description: str) -> bytes:
    if not path.is_file():
        raise MosUartThreBuildError(f"missing {description}: {path}")
    payload = path.read_bytes()
    actual = sha256_bytes(payload)
    if len(payload) != size or actual != digest:
        raise MosUartThreBuildError(
            f"{description} identity changed: bytes={len(payload)} sha256={actual}"
        )
    return payload


def require_accepted_inputs() -> None:
    for name, (path, size, digest) in ACCEPTED_INPUT_SPECS.items():
        if not path.is_file():
            raise MosUartThreBuildError(f"missing accepted {name}: {path}")
        actual = sha256_file(path)
        if path.stat().st_size != size or actual != digest:
            raise MosUartThreBuildError(
                f"accepted {name} changed: bytes={path.stat().st_size} sha256={actual}"
            )


def validate_crc1_control_build(
    build: Path,
) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    """Bind the private policy-1 trio without consulting canonical ``tgt``."""

    build = build.expanduser().resolve()
    receipt_path = build / "BUILD.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MosUartThreBuildError("CRC1 control BUILD receipt is unreadable") from error
    if not isinstance(receipt, dict) or (
        receipt.get("schema") != crc_builder.SCHEMA
        or receipt.get("qualified") is not True
    ):
        raise MosUartThreBuildError("CRC1 control BUILD receipt is not qualified")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise MosUartThreBuildError("CRC1 control BUILD receipt omits artifacts")
    paths: list[Path] = []
    for name, (suffix, size, digest) in CRC1_CONTROL_ARTIFACTS.items():
        path = build / f"{crc_builder.CONTROL_PROGRAM_STEM}.{suffix}"
        entry = artifacts.get(name)
        expected = {
            "key": f"artifacts/{path.name}",
            "bytes": size,
            "sha256": digest,
        }
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(entry, Mapping)
            or dict(entry) != expected
            or path.stat().st_size != size
            or sha256_file(path) != digest
        ):
            raise MosUartThreBuildError(
                f"private CRC1 control artifact identity changed: {name}"
            )
        paths.append(path)
    patch = receipt.get("source_patch")
    if not isinstance(patch, Mapping) or (
        patch.get("temporary_control_crc_policy") != "legacy-memory-bitwise"
        or patch.get("temporary_control_program_sha256")
        != crc_builder.ACCEPTED_PROGRAM_SHA256
        or patch.get("temporary_control_program_exact") is not True
        or patch.get("accepted_files_modified") is not False
    ):
        raise MosUartThreBuildError("private CRC1 source/control binding changed")
    return paths[0], paths[1], paths[2], receipt_path, receipt


def _manifest_uint(record: Mapping[str, object], name: str, order: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MosUartThreBuildError(
            f"manifest record {order} has invalid {name}: {value!r}"
        )
    return value


def validate_runtime_corpus(
    root: Path | None = None,
    *,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    """Bind every initial-view container byte, including staged symlink views."""

    manifest_path = MANAGER_MANIFEST if manifest_path is None else manifest_path
    root = RUNTIME_FIXTURE if root is None else root
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MosUartThreBuildError("manager manifest is absent or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MosUartThreBuildError("manager manifest is unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != EXPECTED_MANAGER_SCHEMA:
        raise MosUartThreBuildError("manager manifest schema changed")
    records = manifest.get("initial_view", {}).get("records", ())
    if not isinstance(records, list) or len(records) != EXPECTED_RECORDS:
        raise MosUartThreBuildError("manager manifest does not contain 227 records")
    coverage = []
    total_container = 0
    total_data = 0
    maximum = 0
    for order, record in enumerate(records):
        if not isinstance(record, dict) or record.get("order") != order:
            raise MosUartThreBuildError(f"manifest record order changed at {order}")
        relative = record.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise MosUartThreBuildError(f"manifest record {order} has unsafe path")
        path = root / relative
        if not path.is_file():
            raise MosUartThreBuildError(f"runtime record is missing: {relative}")
        payload = path.read_bytes()
        file_bytes = _manifest_uint(record, "bytes", order)
        data_bytes = _manifest_uint(record, "data_bytes", order)
        expected_sha256 = record.get("sha256")
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise MosUartThreBuildError(f"record checksum is invalid: {relative}")
        if len(payload) != file_bytes or sha256_bytes(payload) != expected_sha256:
            raise MosUartThreBuildError(f"runtime record identity changed: {relative}")
        if len(payload) < P3DM_DATA_OFFSET or int.from_bytes(
            payload[96:100], "little"
        ) != data_bytes:
            raise MosUartThreBuildError(f"runtime record DATA size changed: {relative}")
        padded_data_bytes = (data_bytes + 3) & ~3
        if P3DM_DATA_OFFSET + padded_data_bytes != file_bytes:
            raise MosUartThreBuildError(
                f"runtime record DATA extent changed: {relative}"
            )
        total_container += file_bytes
        total_data += data_bytes
        maximum = max(maximum, file_bytes)
        coverage.append(
            {
                "order": order,
                "path": relative,
                "file_bytes": file_bytes,
                "file_sha256": expected_sha256,
                "data_bytes": data_bytes,
            }
        )
    aggregates = {
        "records": len(coverage),
        "container_bytes": total_container,
        "data_bytes": total_data,
        "maximum_record_bytes": maximum,
    }
    expected = {
        "records": EXPECTED_RECORDS,
        "container_bytes": EXPECTED_CONTAINER_BYTES,
        "data_bytes": EXPECTED_DATA_BYTES,
        "maximum_record_bytes": EXPECTED_MAXIMUM_RECORD_BYTES,
    }
    if aggregates != expected:
        raise MosUartThreBuildError(
            f"runtime corpus aggregates changed: {aggregates} != {expected}"
        )
    digest = sha256_bytes(
        json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode()
    )
    if digest != EXPECTED_CORPUS_COVERAGE_DIGEST_SHA256:
        raise MosUartThreBuildError(
            f"runtime corpus coverage digest changed: {digest}"
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
        "all_manifest_order_path_size_sha256_and_data_extents_exact": True,
        "records": coverage,
    }


def validate_reference_source_context() -> dict[str, object]:
    payload = require_file(
        REFERENCE_SERIAL_SOURCE,
        REFERENCE_SERIAL_SOURCE_BYTES,
        REFERENCE_SERIAL_SOURCE_SHA256,
        "local reference agon-mos serial source",
    )
    text = payload.decode("utf-8")
    start = text.find("UART0_serial_TX:")
    end = text.find("UART0_serial_TX2:")
    if start < 0 or end <= start:
        raise MosUartThreBuildError("reference UART0 TX source body changed")
    body = text[start:end]
    if body.count("UART_LSR_ETH") != 1 or "UART_LSR_ETX" in body:
        raise MosUartThreBuildError("reference UART0 TX readiness symbol changed")
    return {
        "source": artifact(REFERENCE_SERIAL_SOURCE),
        "observed_uart0_tx_readiness_symbol": "UART_LSR_ETH",
        "observed_uart0_tx_readiness_value": THRE_MASK,
        "provenance_for_pinned_binary": False,
    }


def readiness_truth_table() -> list[dict[str, object]]:
    rows = []
    for holding_empty, transmitter_idle in (
        (False, False),
        (True, False),
        (True, True),
    ):
        lsr = (THRE_MASK if holding_empty else 0) | (
            TEMT_MASK if holding_empty and transmitter_idle else 0
        )
        control_ready = bool(lsr & TEMT_MASK)
        candidate_ready = bool(lsr & THRE_MASK)
        if control_ready and not candidate_ready:
            raise MosUartThreBuildError("TEMT readiness does not imply THRE readiness")
        rows.append(
            {
                "holding_register_empty": holding_empty,
                "transmitter_idle": transmitter_idle,
                "lsr": lsr,
                "temt_control_ready": control_ready,
                "thre_candidate_ready": candidate_ready,
            }
        )
    return rows


def parse_map(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    pattern = re.compile(r"^([^\s]+)\s+[CD]:([0-9A-Fa-f]{6})\b")
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = pattern.match(line)
        if match:
            symbols.setdefault(match.group(1), int(match.group(2), 16))
    return symbols


def exact_window(image: bytes, offset: int, expected: bytes, name: str) -> bytes:
    actual = image[offset : offset + len(expected)]
    if actual != expected:
        raise MosUartThreBuildError(
            f"{name} changed at 0x{offset:06x}: {actual.hex()} != {expected.hex()}"
        )
    return actual


def validate_pinned_contract() -> tuple[bytes, dict[str, object]]:
    image = require_file(
        PINNED_MOS, PINNED_MOS_BYTES, PINNED_MOS_SHA256, "pinned Console8 MOS"
    )
    require_file(
        PINNED_MAP, PINNED_MAP_BYTES, PINNED_MAP_SHA256, "pinned Console8 map"
    )
    symbols = parse_map(PINNED_MAP)
    expected_symbols = {
        "UART0_serial_PUTCH": UART0_PUTCH_OFFSET,
        "UART0_serial_TX": UART0_TX_OFFSET,
    }
    for name, expected in expected_symbols.items():
        if symbols.get(name) != expected:
            raise MosUartThreBuildError(
                f"pinned map {name} changed: {symbols.get(name)!r} != 0x{expected:06x}"
            )
    exact_window(image, RST18_VECTOR_OFFSET, RST18_VECTOR, "RST18 vector")
    exact_window(image, RST18_TARGET, RST18_COUNTED_LOOP, "RST18 counted loop")
    exact_window(image, UART0_CTS_OFFSET, UART0_CTS_WAIT, "UART0 CTS wait")
    exact_window(image, UART0_PUTCH_OFFSET, UART0_PUTCH, "UART0 PUTCH")
    exact_window(image, UART0_TX_OFFSET, UART0_TX_TEMT, "UART0 TX")
    if image.count(UART0_TX_TEMT) != 1:
        raise MosUartThreBuildError("UART0 TX opcode window is not unique in pinned MOS")
    if image[RST18_UART_CALL_OFFSET : RST18_UART_CALL_OFFSET + 4] != bytes.fromhex(
        "cdca1000"
    ):
        raise MosUartThreBuildError("RST18 no longer calls pinned UART0 PUTCH")
    if image[UART0_TX_THR_OFFSET : UART0_TX_THR_OFFSET + 3] != bytes.fromhex(
        "ed39c0"
    ):
        raise MosUartThreBuildError("UART0 TX no longer writes UART0 THR")
    return image, {
        "map_symbols": expected_symbols,
        "rst18_vector_offset": RST18_VECTOR_OFFSET,
        "rst18_target": RST18_TARGET,
        "rst18_counted_uart_call_offset": RST18_UART_CALL_OFFSET,
        "uart0_cts_offset": UART0_CTS_OFFSET,
        "uart0_putch_offset": UART0_PUTCH_OFFSET,
        "uart0_tx_offset": UART0_TX_OFFSET,
        "uart0_tx_mask_offset": UART0_TX_MASK_OFFSET,
        "uart0_tx_thr_offset": UART0_TX_THR_OFFSET,
        "original_uart0_tx_window_hex": UART0_TX_TEMT.hex(),
    }


def patch_image(original: bytes) -> tuple[bytes, dict[str, object]]:
    if (
        len(original) != PINNED_MOS_BYTES
        or sha256_bytes(original) != PINNED_MOS_SHA256
    ):
        raise MosUartThreBuildError(
            "patch input is not the exact pinned Console8 MOS"
        )
    if original[UART0_TX_MASK_OFFSET] != TEMT_MASK:
        raise MosUartThreBuildError("pinned UART0 readiness immediate is not TEMT 0x40")
    changed = bytearray(original)
    changed[UART0_TX_MASK_OFFSET] = THRE_MASK
    candidate = bytes(changed)
    differences = [
        index for index, (before, after) in enumerate(zip(original, candidate))
        if before != after
    ]
    if differences != [UART0_TX_MASK_OFFSET] or len(candidate) != len(original):
        raise MosUartThreBuildError(f"MOS sibling diff changed: {differences}")
    exact_window(candidate, UART0_TX_OFFSET, UART0_TX_THRE, "patched UART0 TX")
    if candidate.count(UART0_TX_THRE) != 1 or candidate.count(UART0_TX_TEMT) != 0:
        raise MosUartThreBuildError("patched UART0 TX opcode topology changed")
    reversed_image = bytearray(candidate)
    reversed_image[UART0_TX_MASK_OFFSET] = TEMT_MASK
    if bytes(reversed_image) != original:
        raise MosUartThreBuildError("one-byte reverse patch did not restore pinned MOS")
    digest = sha256_bytes(candidate)
    if digest != PATCHED_MOS_SHA256:
        raise MosUartThreBuildError(
            f"patched MOS hash changed: {digest} != {PATCHED_MOS_SHA256}"
        )
    return candidate, {
        "changed_byte_count": 1,
        "changed_offsets": differences,
        "offset": UART0_TX_MASK_OFFSET,
        "before": TEMT_MASK,
        "after": THRE_MASK,
        "before_semantics": "TEMT: holding register empty and transmitter idle",
        "after_semantics": "THRE: transmit holding register empty",
        "unique_exact_window": True,
        "reverse_patch_exact": True,
        "all_other_bytes_exact": True,
        "patched_uart0_tx_window_hex": UART0_TX_THRE.hex(),
    }


def atomic_json(path: Path, document: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    output = args.output.expanduser().resolve()
    crc_build = args.crc_build.expanduser().resolve()
    if output.exists():
        raise MosUartThreBuildError(f"refusing to replace existing output: {output}")
    (
        crc1_program,
        crc1_listing,
        crc1_symbols,
        crc1_receipt_path,
        crc1_receipt,
    ) = validate_crc1_control_build(crc_build)
    require_accepted_inputs()
    runtime_corpus = validate_runtime_corpus()
    original, pinned_contract = validate_pinned_contract()
    reference_context = validate_reference_source_context()
    readiness = readiness_truth_table()
    first, patch = patch_image(original)
    second, second_patch = patch_image(bytes(original))
    if first != second or patch != second_patch:
        raise MosUartThreBuildError("independent in-memory MOS sibling builds differ")
    output.mkdir(parents=True)
    control_mos = output / CONTROL_MOS_NAME
    candidate_mos = output / CANDIDATE_MOS_NAME
    control_mos.write_bytes(original)
    candidate_mos.write_bytes(first)
    private_controls = []
    for source in (crc1_program, crc1_listing, crc1_symbols):
        destination = output / source.name
        destination.write_bytes(source.read_bytes())
        private_controls.append(destination)
    if control_mos.read_bytes() != original or candidate_mos.read_bytes() != first:
        raise MosUartThreBuildError("written MOS pair differs from deterministic bytes")
    final_crc1 = validate_crc1_control_build(crc_build)
    if final_crc1[:4] != (
        crc1_program,
        crc1_listing,
        crc1_symbols,
        crc1_receipt_path,
    ) or final_crc1[4] != crc1_receipt:
        raise MosUartThreBuildError("private CRC1 build changed during MOS build")
    for destination, (name, (_suffix, size, digest)) in zip(
        private_controls, CRC1_CONTROL_ARTIFACTS.items()
    ):
        if destination.stat().st_size != size or sha256_file(destination) != digest:
            raise MosUartThreBuildError(
                f"copied private CRC1 artifact changed: {name}"
            )
    # Recheck the immutable external inputs after producing the sibling.
    require_accepted_inputs()
    if validate_runtime_corpus() != runtime_corpus:
        raise MosUartThreBuildError("runtime corpus changed during MOS build")
    validate_pinned_contract()
    validate_reference_source_context()
    report = {
        "schema": SCHEMA,
        "qualified": True,
        "scope": {
            "external_fab_checkout_modified": False,
            "pinned_mos_modified": False,
            "pinned_map_modified": False,
            "accepted_application_modified": False,
            "accepted_artifacts_modified": False,
            "docs_modified": False,
            "output_is_ignored_evidence": True,
        },
        "inputs": {
            "pinned_mos": artifact(PINNED_MOS),
            "pinned_map": artifact(PINNED_MAP),
            "crc1_build_receipt": artifact(
                crc1_receipt_path, key="inputs/crc1-build/BUILD.json"
            ),
        },
        "artifacts": {
            "control_mos": artifact(
                control_mos, key=f"artifacts/{control_mos.name}"
            ),
            "patched_mos": artifact(
                candidate_mos, key=f"artifacts/{candidate_mos.name}"
            ),
            **{
                name: artifact(path, key=f"artifacts/{path.name}")
                for name, path in zip(CRC1_CONTROL_ARTIFACTS, private_controls)
            },
        },
        "accepted_inputs": {
            name: artifact(path)
            for name, (path, _size, _digest) in ACCEPTED_INPUT_SPECS.items()
        },
        "runtime_corpus": runtime_corpus,
        "pinned_contract": pinned_contract,
        "patch": patch,
        "readiness_truth_table": readiness,
        "determinism": {
            "independent_in_memory_builds": 2,
            "byte_exact": True,
            "patched_mos_sha256": PATCHED_MOS_SHA256,
            "private_crc1_artifacts_copied_byte_exact": True,
        },
        "historical_crc1_control": {
            "source": "private ignored CRC-register sibling build artifacts",
            "canonical_target_consulted": False,
            "program_sha256": crc_builder.ACCEPTED_PROGRAM_SHA256,
            "crc_policy": "legacy-memory-bitwise",
            "build_source_patch": crc1_receipt["source_patch"],
        },
        "source_level_change_recipe": {
            "symbol": "UART0_serial_TX",
            "operation": (
                "bring the older pinned Console8 binary's UART0 TX readiness "
                "behavior from TEMT 0x40 to source-level THRE 0x20"
            ),
            "binary_proof_only": True,
            "external_source_tree_was_not_modified": True,
            "reference_source_context": (
                "the current local agon-mos serial.asm already names UART_LSR_ETH; "
                "this does not establish it as the source provenance of the older "
                "pinned binary, whose CTS implementation also differs"
            ),
        },
        "reference_source_context": reference_context,
        "limitations": {
            "binary_proof_for_future_source_level_mos_change": True,
            "not_a_source_level_mos_build": True,
            "must_not_install_or_distribute_patched_blob": True,
            "emulator_and_physical_qualification_are_separate": True,
            "hardware_timing_not_claimed": True,
            "uart_block_return_no_longer_implies_transmitter_idle": True,
            "patch_affects_every_uart0_serial_tx_caller": True,
            "original_map_is_unchanged_layout_annotation_not_candidate_rebuild": True,
        },
    }
    receipt = output / REPORT_NAME
    atomic_json(receipt, report)
    print(f"Regular-LOD MOS UART-THRE sibling build passed: {receipt}")
    print(
        f"mos_bytes={len(first)} mos_sha256={sha256_bytes(first)} "
        f"changed_offset=0x{UART0_TX_MASK_OFFSET:06x} 0x40->0x20"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MosUartThreBuildError as error:
        raise SystemExit(f"regular-LOD MOS UART-THRE build failed: {error}") from error
