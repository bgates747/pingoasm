#!/usr/bin/env python3
"""Build and statically qualify the fixed-address AgonDev regular-LOD policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Iterable, Sequence
import zlib


ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT = ROOT / "experiments/agondev-regular-policy"
DEFAULT_OUTPUT = ROOT / "build/experiments/agondev-regular-policy"
DEFAULT_AGONDEV_ROOT = ROOT.parents[4] / "agondev"
PROVENANCE = EXPERIMENT / "PROVENANCE.json"
FRAME_HELPER_ARCHIVE = Path("release/lib/libagon.a")
FRAME_HELPER_MEMBER = "frameset.o"
FRAME_HELPER_SYMBOL = "__frameset"
STAGED_FRAME_HELPER_ARCHIVE = Path("toolchain/libagon.a")

MODULE_FILENAME = "CPOLICY.BIN"
ELF_FILENAME = "fsim-agondev-regular-policy.elf"
MAP_FILENAME = "fsim-agondev-regular-policy.map"
IMPORT_FILENAME = "regular-policy-import.inc"
BUILD_RECEIPT = "BUILD.json"
BUILD_SCHEMA = "pingo-fsim-agondev-regular-policy-build-v1"

LOAD_ADDRESS = 0x070000
ENTRY_ADDRESS = 0x070020
LIMIT_EXCLUSIVE = 0x080000
HEADER_BYTES = 32
SIGNATURE = b"FSIMCPOL"
FORMAT_VERSION = 1
ABI_VERSION = 1
DESCRIPTOR_BYTES = 3
MAX_DESCRIPTORS = 38
MAX_SIDE = 14
NO_SELECTION = 0xFF
INVALID = 0xFE
LICENSING_CONTRACT = {
    "status": "unknown-no-root-license-or-notice",
    "distribution": "local-build-input-only-not-redistributed",
    "checkout_root_names_checked": [
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "COPYING",
        "COPYING.txt",
        "NOTICE",
        "NOTICE.txt",
    ],
    "present": [],
}

TRACKED_INPUTS = (
    Path(__file__).resolve(),
    PROVENANCE,
    EXPERIMENT / "linker.ld",
    EXPERIMENT / "include/regular_policy.h",
    EXPERIMENT / "src/selector.c",
)

AUTHORITATIVE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "module",
        "toolchain",
        "inputs",
        "verification",
        "semantic_sha256",
    }
)

COMPILER_FLAGS = (
    "-mllvm",
    "-z80-gas-style",
    "-mllvm",
    "-z80-print-zero-offset",
    "-nostdinc",
    "-target",
    "ez80-none-elf",
    "-Oz",
    "-Wa,-march=ez80+full",
    "-ffreestanding",
    "-fno-builtin",
    "-fno-common",
    "-fno-ident",
    "-fno-threadsafe-statics",
    "-std=gnu17",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Iinclude",
)


class RegularPolicyBuildError(RuntimeError):
    """A pinned source, link-layout, or module-ABI contract failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: Iterable[object], *, cwd: Path | None = None) -> str:
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
        raise RegularPolicyBuildError(
            f"Command failed ({completed.returncode}): {' '.join(rendered)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def archive_symbol_members(
    nm_output: str, archive: Path, symbol: str
) -> list[str]:
    pattern = re.compile(
        rf"^{re.escape(str(archive))}:([^:\s]+):[0-9a-fA-F]+\s+T\s+"
        rf"{re.escape(symbol)}$",
        flags=re.MULTILINE,
    )
    return pattern.findall(nm_output)


def load_provenance() -> dict[str, object]:
    loaded = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RegularPolicyBuildError("Provenance root must be an object")
    return loaded


def validate_toolchain(agondev_root: Path) -> dict[str, object]:
    agondev_root = agondev_root.resolve()
    provenance = load_provenance()
    contract = provenance.get("toolchain")
    if not isinstance(contract, dict):
        raise RegularPolicyBuildError("Toolchain provenance has the wrong shape")
    if provenance.get("licensing") != LICENSING_CONTRACT:
        raise RegularPolicyBuildError("AgonDev licensing review contract changed")
    if not (agondev_root / ".git").is_dir():
        raise RegularPolicyBuildError(f"AgonDev checkout is absent: {agondev_root}")

    commit = run(("git", "rev-parse", "HEAD"), cwd=agondev_root).strip()
    if commit != contract.get("git_commit"):
        raise RegularPolicyBuildError(
            "AgonDev commit changed: "
            f"expected {contract.get('git_commit')}, got {commit}"
        )
    if run(("git", "status", "--porcelain"), cwd=agondev_root).strip():
        raise RegularPolicyBuildError(
            "AgonDev checkout must remain a clean read-only input"
        )
    present_root_notices = [
        name
        for name in LICENSING_CONTRACT["checkout_root_names_checked"]
        if (agondev_root / str(name)).exists()
    ]
    if present_root_notices != LICENSING_CONTRACT["present"]:
        raise RegularPolicyBuildError(
            "AgonDev checkout root licensing files changed: "
            f"{present_root_notices!r}"
        )

    configured_files = contract.get("files")
    if not isinstance(configured_files, dict):
        raise RegularPolicyBuildError("Toolchain file provenance has the wrong shape")
    observed_files: dict[str, dict[str, object]] = {}
    for relative, expected_hash in sorted(configured_files.items()):
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RegularPolicyBuildError("Invalid pinned toolchain file record")
        path = agondev_root / relative
        if not path.is_file() or path.is_symlink():
            raise RegularPolicyBuildError(f"Pinned AgonDev tool is absent: {path}")
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise RegularPolicyBuildError(
                f"AgonDev input hash changed for {relative}: {observed_hash}"
            )
        observed_files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": observed_hash,
        }

    expected_frame_helper = {
        "archive": FRAME_HELPER_ARCHIVE.as_posix(),
        "member": FRAME_HELPER_MEMBER,
        "symbol": FRAME_HELPER_SYMBOL,
    }
    frame_helper = contract.get("frame_helper")
    if frame_helper != expected_frame_helper or "mirrored_sources" in contract:
        raise RegularPolicyBuildError("Frame-helper provenance contract changed")
    archive_relative = FRAME_HELPER_ARCHIVE.as_posix()
    if archive_relative not in configured_files:
        raise RegularPolicyBuildError(
            "Frame-helper archive is absent from pinned toolchain files"
        )
    archive = agondev_root / FRAME_HELPER_ARCHIVE
    nm = agondev_root / "release/bin/ez80-none-elf-nm"
    archive_nm = run((nm, "-A", "--defined-only", archive))
    helper_members = archive_symbol_members(
        archive_nm, archive, FRAME_HELPER_SYMBOL
    )
    if helper_members != [FRAME_HELPER_MEMBER]:
        raise RegularPolicyBuildError(
            "Pinned frame-helper resolution changed: expected "
            f"{FRAME_HELPER_MEMBER}({FRAME_HELPER_SYMBOL}), got {helper_members}"
        )

    compiler = agondev_root / "release/bin/ez80-none-elf-clang"
    return {
        "git_commit": commit,
        "compiler_version": run((compiler, "--version")).splitlines()[:4],
        "files": observed_files,
        "frame_helper": {
            "archive": archive_relative,
            "member": FRAME_HELPER_MEMBER,
            "symbol": FRAME_HELPER_SYMBOL,
        },
        "licensing": LICENSING_CONTRACT,
    }


def stage_project(output_root: Path, agondev_root: Path) -> Path:
    project = output_root.resolve() / "project"
    staged = {
        project / "linker.ld": EXPERIMENT / "linker.ld",
        project / "include/regular_policy.h": (
            EXPERIMENT / "include/regular_policy.h"
        ),
        project / "src/selector.c": EXPERIMENT / "src/selector.c",
        project / STAGED_FRAME_HELPER_ARCHIVE: (
            agondev_root.resolve() / FRAME_HELPER_ARCHIVE
        ),
    }
    for retired in (project / "src/frameset.src", project / "obj/frameset.o"):
        if retired.is_symlink() or (retired.exists() and not retired.is_file()):
            raise RegularPolicyBuildError(
                f"Refusing to remove unexpected retired helper path: {retired}"
            )
        if retired.exists():
            retired.unlink()
    for destination, source in staged.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise RegularPolicyBuildError(
                f"Refusing to overwrite staged symlink: {destination}"
            )
        shutil.copyfile(source, destination)
    verify_staged_files(output_root, agondev_root)
    return project


def verify_staged_files(output_root: Path, agondev_root: Path) -> None:
    project = output_root.resolve() / "project"
    expected = {
        project / "linker.ld": EXPERIMENT / "linker.ld",
        project / "include/regular_policy.h": (
            EXPERIMENT / "include/regular_policy.h"
        ),
        project / "src/selector.c": EXPERIMENT / "src/selector.c",
        project / STAGED_FRAME_HELPER_ARCHIVE: (
            agondev_root.resolve() / FRAME_HELPER_ARCHIVE
        ),
    }
    for staged, source in expected.items():
        if not staged.is_file() or staged.is_symlink():
            raise RegularPolicyBuildError(f"Staged input is absent: {staged}")
        if staged.read_bytes() != source.read_bytes():
            raise RegularPolicyBuildError(
                f"Staged input differs from pinned source: {staged}"
            )
    for retired in (project / "src/frameset.src", project / "obj/frameset.o"):
        if retired.exists() or retired.is_symlink():
            raise RegularPolicyBuildError(
                f"Retired vendored frame helper remains staged: {retired}"
            )


def build_project(project: Path, agondev_root: Path) -> None:
    toolbin = agondev_root.resolve() / "release/bin"
    compiler = toolbin / "ez80-none-elf-clang"
    linker = toolbin / "ez80-none-elf-ld"
    objcopy = toolbin / "ez80-none-elf-objcopy"

    for directory in (project / "obj", project / "inspect", project / "bin"):
        directory.mkdir(parents=True, exist_ok=True)

    run(
        (
            compiler,
            *COMPILER_FLAGS,
            "src/selector.c",
            "-c",
            "-o",
            "obj/selector.o",
        ),
        cwd=project,
    )
    run(
        (
            compiler,
            *COMPILER_FLAGS,
            "src/selector.c",
            "-S",
            "-o",
            "inspect/selector.s",
        ),
        cwd=project,
    )
    run(
        (
            linker,
            f"-Map=bin/{MAP_FILENAME}",
            "-T",
            "linker.ld",
            "-o",
            f"bin/{ELF_FILENAME}",
            "obj/selector.o",
            STAGED_FRAME_HELPER_ARCHIVE,
        ),
        cwd=project,
    )
    run(
        (
            objcopy,
            "-O",
            "binary",
            f"bin/{ELF_FILENAME}",
            f"bin/{MODULE_FILENAME}",
        ),
        cwd=project,
    )


def symbol_set(nm_output: str, *, type_letter: str | None = None) -> set[str]:
    symbols: set[str] = set()
    for line in nm_output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if type_letter is None:
            symbols.add(fields[-1])
        elif len(fields) >= 2 and fields[-2] == type_letter:
            symbols.add(fields[-1])
    return symbols


def parse_named_symbol(nm_output: str, name: str) -> tuple[int, int]:
    pattern = re.compile(
        rf"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Tt]\s+{re.escape(name)}$",
        flags=re.MULTILINE,
    )
    match = pattern.search(nm_output)
    if match is None:
        raise RegularPolicyBuildError(f"Missing sized text symbol: {name}")
    return int(match.group(1), 16), int(match.group(2), 16)


def expected_header(image_bytes: int) -> bytes:
    return b"".join(
        (
            SIGNATURE,
            bytes(
                (
                    FORMAT_VERSION,
                    ABI_VERSION,
                    HEADER_BYTES,
                    DESCRIPTOR_BYTES,
                    MAX_DESCRIPTORS,
                    MAX_SIDE,
                    NO_SELECTION,
                    INVALID,
                )
            ),
            struct.pack(
                "<IIII",
                ENTRY_ADDRESS,
                image_bytes,
                LOAD_ADDRESS,
                LIMIT_EXCLUSIVE,
            ),
        )
    )


def decode_header(image: bytes) -> dict[str, object]:
    if len(image) < HEADER_BYTES:
        raise RegularPolicyBuildError("Policy image is shorter than its header")
    entry, image_bytes, load, limit = struct.unpack_from("<IIII", image, 16)
    return {
        "signature_ascii": image[:8].decode("ascii", errors="strict"),
        "format_version": image[8],
        "abi_version": image[9],
        "header_bytes": image[10],
        "descriptor_bytes": image[11],
        "maximum_descriptors": image[12],
        "maximum_side": image[13],
        "no_selection": image[14],
        "invalid": image[15],
        "entry_address": entry,
        "image_bytes": image_bytes,
        "load_address": load,
        "limit_exclusive": limit,
    }


def render_import_include(
    *, image_bytes: int, image_sha256: str, image_crc32: int
) -> str:
    signature_lines = "\n".join(
        f"fsim_regular_policy_signature_{index}: equ 0{value:02X}h"
        for index, value in enumerate(SIGNATURE)
    )
    return f"""; Generated by scripts/build_agondev_regular_policy.py; do not edit.
; Module file: {MODULE_FILENAME}
; Module SHA-256: {image_sha256}
; Module CRC-32/ISO-HDLC: {image_crc32:08x}
; Entry ABI: caller-cleaned 3-byte slots (descriptor pointer, count, free slots);
; result is returned in A.  Descriptor source indices are unique and strictly
; increasing in the range 0..37.

fsim_regular_policy_load_address: equ 070000h
fsim_regular_policy_entry_address: equ 070020h
fsim_regular_policy_limit_exclusive: equ 080000h
fsim_regular_policy_image_bytes: equ {image_bytes}
fsim_regular_policy_header_bytes: equ 32
fsim_regular_policy_format_version: equ 1
fsim_regular_policy_abi_version: equ 1
fsim_regular_policy_descriptor_bytes: equ 3
fsim_regular_policy_max_descriptors: equ 38
fsim_regular_policy_max_side: equ 14
fsim_regular_policy_invalid: equ 0FEh
fsim_regular_policy_no_selection: equ 0FFh
fsim_regular_policy_crc32_0: equ 0{image_crc32 & 0xff:02X}h
fsim_regular_policy_crc32_1: equ 0{(image_crc32 >> 8) & 0xff:02X}h
fsim_regular_policy_crc32_2: equ 0{(image_crc32 >> 16) & 0xff:02X}h
fsim_regular_policy_crc32_3: equ 0{(image_crc32 >> 24) & 0xff:02X}h

fsim_regular_policy_header_signature_offset: equ 0
fsim_regular_policy_header_format_offset: equ 8
fsim_regular_policy_header_abi_offset: equ 9
fsim_regular_policy_header_size_offset: equ 10
fsim_regular_policy_header_descriptor_size_offset: equ 11
fsim_regular_policy_header_max_descriptors_offset: equ 12
fsim_regular_policy_header_max_side_offset: equ 13
fsim_regular_policy_header_no_selection_offset: equ 14
fsim_regular_policy_header_invalid_offset: equ 15
fsim_regular_policy_header_entry_offset: equ 16
fsim_regular_policy_header_image_bytes_offset: equ 20
fsim_regular_policy_header_load_offset: equ 24
fsim_regular_policy_header_limit_offset: equ 28

fsim_regular_policy_descriptor_retiring_offset: equ 0
fsim_regular_policy_descriptor_entering_offset: equ 1
fsim_regular_policy_descriptor_source_index_offset: equ 2

{signature_lines}
"""


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RegularPolicyBuildError(f"Refusing to overwrite symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def verify_outputs(
    output_root: Path,
    agondev_root: Path,
    *,
    deterministic_rebuild: bool,
    write_import: bool,
) -> dict[str, object]:
    project = output_root.resolve() / "project"
    verify_staged_files(output_root, agondev_root)
    toolbin = agondev_root.resolve() / "release/bin"
    selector_object = project / "obj/selector.o"
    frame_archive = project / STAGED_FRAME_HELPER_ARCHIVE
    inspection = project / "inspect/selector.s"
    elf = project / f"bin/{ELF_FILENAME}"
    image = project / f"bin/{MODULE_FILENAME}"
    link_map = project / f"bin/{MAP_FILENAME}"
    import_include = output_root.resolve() / IMPORT_FILENAME
    outputs = (selector_object, inspection, elf, image, link_map)
    for path in outputs:
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise RegularPolicyBuildError(
                f"Expected build output is absent or empty: {path}"
            )

    image_data = image.read_bytes()
    if image_data[:HEADER_BYTES] != expected_header(len(image_data)):
        raise RegularPolicyBuildError("Fixed module header or image-size field changed")
    if LOAD_ADDRESS + len(image_data) >= LIMIT_EXCLUSIVE:
        raise RegularPolicyBuildError("Policy image reaches or exceeds 0x080000")
    header = decode_header(image_data)

    nm = toolbin / "ez80-none-elf-nm"
    objcopy = toolbin / "ez80-none-elf-objcopy"
    objdump = toolbin / "ez80-none-elf-objdump"
    readelf = toolbin / "ez80-none-elf-readelf"

    selector_undefined_text = run((nm, "--undefined-only", selector_object))
    selector_undefined = symbol_set(selector_undefined_text)
    if selector_undefined != {"__frameset"}:
        raise RegularPolicyBuildError(
            "Selector undefined-symbol contract changed: "
            f"expected ['__frameset'], got {sorted(selector_undefined)}"
        )
    frame_nm = run((nm, "-A", "--defined-only", frame_archive))
    frame_members = archive_symbol_members(
        frame_nm, frame_archive, FRAME_HELPER_SYMBOL
    )
    if frame_members != [FRAME_HELPER_MEMBER]:
        raise RegularPolicyBuildError(
            "Staged frame-helper archive resolution changed: "
            f"expected [{FRAME_HELPER_MEMBER}], got {frame_members}"
        )
    frame_exports = {FRAME_HELPER_SYMBOL}
    final_undefined = run((nm, "--undefined-only", elf)).strip()
    if final_undefined:
        raise RegularPolicyBuildError(
            f"Fixed policy ELF has unresolved symbols:\n{final_undefined}"
        )

    sized_symbols = run((nm, "-S", "-n", elf))
    selector_address, selector_bytes = parse_named_symbol(
        sized_symbols, "_fsim_regular_policy_select"
    )
    if selector_address != ENTRY_ADDRESS:
        raise RegularPolicyBuildError(
            f"Selector entry moved to 0x{selector_address:06x}"
        )
    symbols = symbol_set(run((nm, elf)))
    required_symbols = {
        "__frameset",
        "__fsim_regular_policy_header_end",
        "__fsim_regular_policy_image_end",
        "__fsim_regular_policy_image_start",
        "_fsim_regular_policy_select",
    }
    if not required_symbols.issubset(symbols):
        raise RegularPolicyBuildError(
            f"Fixed module symbols changed: missing {sorted(required_symbols - symbols)}"
        )
    forbidden_symbols = sorted(
        symbol
        for symbol in symbols
        if any(
            fragment in symbol.lower()
            for fragment in (
                "mos_",
                "vdp_",
                "printf",
                "malloc",
                "div",
                "rem",
                "mul",
                "float",
                "fix",
                "unwind",
            )
        )
    )
    if forbidden_symbols:
        raise RegularPolicyBuildError(
            "Policy module acquired forbidden runtime symbols: "
            + ", ".join(forbidden_symbols)
        )

    selector_disassembly = run((objdump, "-dr", selector_object))
    if len(re.findall(r"r_imm24\s+__frameset\b", selector_disassembly)) != 1:
        raise RegularPolicyBuildError(
            "Selector must have exactly one call relocation to local __frameset"
        )
    inspection_text = inspection.read_text(encoding="utf-8")
    if inspection_text.count("call\t__frameset") != 1:
        raise RegularPolicyBuildError(
            "Compiler inspection no longer has exactly one __frameset call"
        )
    if "__frameset0" in inspection_text:
        raise RegularPolicyBuildError("Selector unexpectedly acquired __frameset0")

    elf_header = run((readelf, "-h", elf))
    for pattern, description in (
        (r"Machine:\s+Zilog Z80", "eZ80 ELF machine"),
        (r"Entry point address:\s+0x70020", "fixed ELF entry"),
        (r"Flags:\s+0x84", "eZ80 ADL flags"),
    ):
        if re.search(pattern, elf_header) is None:
            raise RegularPolicyBuildError(f"Missing {description}: /{pattern}/")
    section_table = run((readelf, "-W", "-S", elf))
    alloc_sections = re.findall(
        r"\[\s*\d+\]\s+(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+([A-Z]+)",
        section_table,
    )
    observed_alloc = {name: flags for name, flags in alloc_sections if "A" in flags}
    if observed_alloc != {".policy": "AX"}:
        raise RegularPolicyBuildError(
            f"Unexpected allocated ELF sections: {observed_alloc}"
        )
    map_text = link_map.read_text(encoding="utf-8")
    loaded_inputs = set(
        re.findall(r"^LOAD\s+(\S+)\s*$", map_text, flags=re.MULTILINE)
    )
    expected_loaded_inputs = {
        "obj/selector.o",
        STAGED_FRAME_HELPER_ARCHIVE.as_posix(),
    }
    if loaded_inputs != expected_loaded_inputs:
        raise RegularPolicyBuildError(
            f"Link acquired unexpected input objects: {sorted(loaded_inputs)}"
        )
    archive_label = re.escape(STAGED_FRAME_HELPER_ARCHIVE.as_posix())
    included_members = re.findall(
        rf"^{archive_label}\(([^)]+)\)\s*$",
        map_text,
        flags=re.MULTILINE,
    )
    if included_members != [FRAME_HELPER_MEMBER]:
        raise RegularPolicyBuildError(
            "Link extracted unexpected frame-helper archive members: "
            f"{included_members}"
        )
    inclusion_contract = re.compile(
        rf"^{archive_label}\({re.escape(FRAME_HELPER_MEMBER)}\)\s*$\n"
        rf"\s+obj/selector\.o \({re.escape(FRAME_HELPER_SYMBOL)}\)\s*$",
        flags=re.MULTILINE,
    )
    if len(inclusion_contract.findall(map_text)) != 1:
        raise RegularPolicyBuildError(
            "Link map does not prove frameset.o satisfied selector __frameset"
        )
    if re.search(r"\.forbidden\s+0x[0-9a-fA-F]+\s+0x[1-9a-fA-F]", map_text):
        raise RegularPolicyBuildError("Link map contains a nonempty forbidden section")

    with tempfile.TemporaryDirectory(prefix="fsim-policy-elf-image-") as temporary:
        extracted = Path(temporary) / MODULE_FILENAME
        run((objcopy, "-O", "binary", elf, extracted))
        if extracted.read_bytes() != image_data:
            raise RegularPolicyBuildError(
                "ELF load image differs from the distributed raw module"
            )

    image_hash = sha256_file(image)
    image_crc32 = zlib.crc32(image_data) & 0xFFFFFFFF
    import_text = render_import_include(
        image_bytes=len(image_data),
        image_sha256=image_hash,
        image_crc32=image_crc32,
    )
    if write_import:
        atomic_write_text(import_include, import_text)
    elif not import_include.is_file() or import_include.is_symlink():
        raise RegularPolicyBuildError("Generated ez80asm import include is absent")
    elif import_include.read_text(encoding="utf-8") != import_text:
        raise RegularPolicyBuildError("Generated ez80asm import include changed")
    if import_include.read_text(encoding="utf-8") != import_text:
        raise RegularPolicyBuildError("Generated ez80asm import include is not exact")

    output_receipts: dict[str, dict[str, object]] = {}
    for path in (*outputs, import_include):
        try:
            relative = path.relative_to(output_root.resolve()).as_posix()
        except ValueError as error:
            raise RegularPolicyBuildError(f"Output escaped build root: {path}") from error
        output_receipts[relative] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    return {
        "deterministic_rebuild": deterministic_rebuild,
        "header": header,
        "image_crc32": f"{image_crc32:08x}",
        "selector_entry": selector_address,
        "selector_bytes": selector_bytes,
        "selector_undefined_symbols": sorted(selector_undefined),
        "frame_helper_exports": sorted(frame_exports),
        "frame_helper_archive": STAGED_FRAME_HELPER_ARCHIVE.as_posix(),
        "frame_helper_member": FRAME_HELPER_MEMBER,
        "final_undefined_symbols": [],
        "forbidden_runtime_symbols": forbidden_symbols,
        "allocated_elf_sections": observed_alloc,
        "elf_binary_matches_raw": True,
        "outputs": output_receipts,
    }


def tracked_input_receipts() -> dict[str, dict[str, object]]:
    receipts: dict[str, dict[str, object]] = {}
    for path in TRACKED_INPUTS:
        if not path.is_file() or path.is_symlink():
            raise RegularPolicyBuildError(f"Tracked build input is absent: {path}")
        receipts[path.relative_to(ROOT).as_posix()] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return receipts


def add_semantic_hash(receipt: dict[str, object]) -> dict[str, object]:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["semantic_sha256"] = hashlib.sha256(canonical).hexdigest()
    return receipt


def build_receipt(
    toolchain: dict[str, object], verification: dict[str, object]
) -> dict[str, object]:
    if verification.get("deterministic_rebuild") is not True:
        raise RegularPolicyBuildError(
            "Authoritative module receipt requires an independent rebuild"
        )
    outputs = verification.get("outputs")
    if not isinstance(outputs, dict):
        raise RegularPolicyBuildError("Verification output receipts are absent")
    raw = outputs.get(f"project/bin/{MODULE_FILENAME}")
    if not isinstance(raw, dict):
        raise RegularPolicyBuildError("Raw module receipt is absent")
    receipt: dict[str, object] = {
        "schema": BUILD_SCHEMA,
        "status": "qualified",
        "module": {
            "filename": MODULE_FILENAME,
            "load_address": LOAD_ADDRESS,
            "entry_address": ENTRY_ADDRESS,
            "limit_exclusive": LIMIT_EXCLUSIVE,
            "header_bytes": HEADER_BYTES,
            "image_bytes": raw["bytes"],
            "sha256": raw["sha256"],
            "crc32": verification["image_crc32"],
        },
        "toolchain": toolchain,
        "inputs": tracked_input_receipts(),
        "verification": verification,
    }
    return add_semantic_hash(receipt)


def write_receipt(output_root: Path, receipt: dict[str, object]) -> Path:
    path = output_root.resolve() / BUILD_RECEIPT
    atomic_write_text(path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return path


def verify_semantic_hash(receipt: dict[str, object]) -> None:
    claimed = receipt.get("semantic_sha256")
    if not isinstance(claimed, str):
        raise RegularPolicyBuildError("BUILD.json semantic hash is absent")
    unhashed = dict(receipt)
    del unhashed["semantic_sha256"]
    canonical = json.dumps(unhashed, sort_keys=True, separators=(",", ":")).encode()
    observed = hashlib.sha256(canonical).hexdigest()
    if observed != claimed:
        raise RegularPolicyBuildError(
            f"BUILD.json semantic hash changed: expected {claimed}, got {observed}"
        )


def verify_authoritative_receipt(
    output_root: Path,
    agondev_root: Path,
    toolchain: dict[str, object],
) -> Path:
    path = output_root.resolve() / BUILD_RECEIPT
    if not path.is_file() or path.is_symlink():
        raise RegularPolicyBuildError(f"Authoritative receipt is absent: {path}")
    original = path.read_bytes()
    loaded = json.loads(original)
    if not isinstance(loaded, dict):
        raise RegularPolicyBuildError("BUILD.json root must be an object")
    receipt: dict[str, object] = loaded
    verify_semantic_hash(receipt)
    if set(receipt) != AUTHORITATIVE_RECEIPT_KEYS:
        raise RegularPolicyBuildError("BUILD.json authoritative keys changed")
    if receipt.get("schema") != BUILD_SCHEMA or receipt.get("status") != "qualified":
        raise RegularPolicyBuildError("BUILD.json is not a qualified module receipt")
    if receipt.get("toolchain") != toolchain:
        raise RegularPolicyBuildError("BUILD.json toolchain evidence changed")
    if receipt.get("inputs") != tracked_input_receipts():
        raise RegularPolicyBuildError("BUILD.json no longer matches tracked inputs")
    verify_staged_files(output_root, agondev_root)
    verification = verify_outputs(
        output_root,
        agondev_root,
        deterministic_rebuild=True,
        write_import=False,
    )
    if receipt.get("verification") != verification:
        raise RegularPolicyBuildError("BUILD.json no longer matches verified outputs")
    rebuilt_receipt = build_receipt(toolchain, verification)
    if receipt != rebuilt_receipt:
        raise RegularPolicyBuildError("BUILD.json module metadata changed")
    if path.read_bytes() != original:
        raise RegularPolicyBuildError("Receipt verification unexpectedly rewrote BUILD.json")
    return path


def select_reference(
    descriptors: Sequence[tuple[int, int, int]], free_slots: int
) -> int:
    """Host mirror of the module's bounded selector, used by focused tests."""
    if len(descriptors) > MAX_DESCRIPTORS or not 0 <= free_slots <= 0xFF:
        return INVALID
    selected: tuple[int, int, int] | None = None
    previous_source: int | None = None
    for retiring, entering, source_index in descriptors:
        if not (
            0 <= retiring <= MAX_SIDE
            and 0 <= entering <= MAX_SIDE
            and 0 <= source_index < MAX_DESCRIPTORS
        ):
            return INVALID
        if previous_source is not None and source_index <= previous_source:
            return INVALID
        previous_source = source_index
        if entering > free_slots:
            continue
        candidate = (retiring, entering, source_index)
        if selected is None:
            selected = candidate
            continue
        selected_retiring, selected_entering, selected_source = selected
        candidate_key = (
            retiring - entering,
            -entering,
            retiring,
            -source_index,
        )
        selected_key = (
            selected_retiring - selected_entering,
            -selected_entering,
            selected_retiring,
            -selected_source,
        )
        if candidate_key > selected_key:
            selected = candidate
    return NO_SELECTION if selected is None else selected[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agondev-root",
        type=Path,
        default=DEFAULT_AGONDEV_ROOT,
        help="read-only pinned AgonDev checkout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="ignored build output root",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="materialize exact pinned module inputs without compiling",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify an existing build and authoritative receipt",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stage_only and args.verify_only:
        raise RegularPolicyBuildError("--stage-only and --verify-only are exclusive")
    output_root = args.output.resolve()
    agondev_root = args.agondev_root.resolve()
    toolchain = validate_toolchain(agondev_root)

    if args.verify_only:
        receipt = verify_authoritative_receipt(
            output_root, agondev_root, toolchain
        )
        print(f"Verified fixed AgonDev regular-policy module: {receipt}")
        return 0

    receipt_path = output_root / BUILD_RECEIPT
    if receipt_path.exists() and not receipt_path.is_symlink():
        receipt_path.unlink()
    project = stage_project(output_root, agondev_root)
    if args.stage_only:
        print(f"Staged fixed AgonDev regular-policy module: {project}")
        return 0

    build_project(project, agondev_root)
    verify_staged_files(output_root, agondev_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="agondev-regular-policy-determinism-", dir=output_root.parent
    ) as temporary:
        second_root = Path(temporary)
        second_project = stage_project(second_root, agondev_root)
        build_project(second_project, agondev_root)
        second_verification = verify_outputs(
            second_root,
            agondev_root,
            deterministic_rebuild=True,
            write_import=True,
        )
        first_verification = verify_outputs(
            output_root,
            agondev_root,
            deterministic_rebuild=True,
            write_import=True,
        )
        first_outputs = first_verification["outputs"]
        second_outputs = second_verification["outputs"]
        assert isinstance(first_outputs, dict) and isinstance(second_outputs, dict)
        for relative in (
            f"project/bin/{MODULE_FILENAME}",
            f"project/bin/{ELF_FILENAME}",
            IMPORT_FILENAME,
        ):
            first_record = first_outputs.get(relative)
            second_record = second_outputs.get(relative)
            if not isinstance(first_record, dict) or not isinstance(
                second_record, dict
            ):
                raise RegularPolicyBuildError(
                    f"Determinism output record is absent: {relative}"
                )
            if first_record.get("sha256") != second_record.get("sha256"):
                raise RegularPolicyBuildError(
                    f"Independent rebuild changed {relative}"
                )

    receipt = build_receipt(toolchain, first_verification)
    receipt_path = write_receipt(output_root, receipt)
    module = output_root / f"project/bin/{MODULE_FILENAME}"
    import_include = output_root / IMPORT_FILENAME
    print(f"Qualified fixed AgonDev regular-policy module: {module}")
    print(f"Generated ez80asm import contract: {import_include}")
    print(f"Authoritative build receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegularPolicyBuildError as error:
        raise SystemExit(str(error)) from error
