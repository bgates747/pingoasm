#!/usr/bin/env python3
"""Stage, build, and statically qualify the FSIM AgonDev ABI probe."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT = ROOT / "experiments/agondev-interop"
DEFAULT_OUTPUT = ROOT / "build/experiments/agondev-interop"
DEFAULT_AGONDEV_ROOT = ROOT.parents[3] / "agondev"
DEFAULT_ABI_REFERENCE_ROOT = ROOT.parents[2] / "mos-agondev"
PROVENANCE = EXPERIMENT / "PROVENANCE.json"
BUILD_RECEIPT = "BUILD.json"
LOCAL_BUILD_RECEIPT = "LOCAL-BUILD.json"
BUILD_SCHEMA = "pingo-fsim-agondev-interop-build-v1"
LOCAL_BUILD_SCHEMA = "pingo-fsim-agondev-interop-local-build-v1"
PINNED_OBJCOPY_SHA256 = (
    "2a6a03bbd8c1f1a528a98013e58fb7cb88463c5931b70a6c922c52fefe49d86c"
)
PINNED_POLICY_EXTERNAL_UNDEFINED = frozenset(
    {"__frameset", "__frameset0", "_putch"}
)
AUTHORITATIVE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "load_address",
        "load_capacity",
        "toolchain",
        "abi_reference",
        "inputs",
        "verification",
        "semantic_sha256",
    }
)

TRACKED_INPUTS = (
    Path(__file__).resolve(),
    EXPERIMENT / "AgonDev.mk.in",
    EXPERIMENT / "CMakeLists.txt.in",
    EXPERIMENT / "CMakePresets.json.in",
    EXPERIMENT / "PROVENANCE.json",
    EXPERIMENT / "README.md",
    EXPERIMENT / "include/interop.h",
    EXPERIMENT / "src/bridge.asm",
    EXPERIMENT / "src/main.c",
)


class InteropBuildError(RuntimeError):
    """A pinned build or ABI contract failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: Iterable[object], *, cwd: Path | None = None) -> str:
    rendered_command = tuple(str(part) for part in command)
    completed = subprocess.run(
        rendered_command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        rendered = " ".join(rendered_command)
        raise InteropBuildError(
            f"Command failed ({completed.returncode}): {rendered}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def load_provenance() -> dict[str, object]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def validate_toolchain(agondev_root: Path) -> dict[str, object]:
    agondev_root = agondev_root.resolve()
    provenance = load_provenance()
    contract = provenance["toolchain"]
    if not isinstance(contract, dict):
        raise InteropBuildError("Toolchain provenance has the wrong shape")

    if not (agondev_root / ".git").is_dir():
        raise InteropBuildError(f"AgonDev checkout is absent: {agondev_root}")
    commit = run(("git", "rev-parse", "HEAD"), cwd=agondev_root).strip()
    if commit != contract["git_commit"]:
        raise InteropBuildError(
            f"AgonDev commit changed: expected {contract['git_commit']}, got {commit}"
        )
    dirty = run(("git", "status", "--porcelain"), cwd=agondev_root).strip()
    if dirty:
        raise InteropBuildError("AgonDev checkout must remain a clean read-only input")

    observed_files: dict[str, dict[str, object]] = {}
    configured_files = contract["files"]
    if not isinstance(configured_files, dict):
        raise InteropBuildError("Toolchain file provenance has the wrong shape")
    files = dict(configured_files)
    objcopy_relative = "release/bin/ez80-none-elf-objcopy"
    configured_objcopy = files.get(objcopy_relative)
    if (
        configured_objcopy is not None
        and configured_objcopy != PINNED_OBJCOPY_SHA256
    ):
        raise InteropBuildError("Pinned objcopy provenance conflicts with the builder")
    files[objcopy_relative] = PINNED_OBJCOPY_SHA256
    for relative, expected_hash in sorted(files.items()):
        path = agondev_root / relative
        if not path.is_file():
            raise InteropBuildError(f"Pinned AgonDev input is absent: {path}")
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise InteropBuildError(
                f"AgonDev input hash changed for {relative}: {observed_hash}"
            )
        observed_files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": observed_hash,
        }

    compiler = agondev_root / "release/bin/ez80-none-elf-clang"
    return {
        "git_commit": commit,
        "compiler_version": run((compiler, "--version")).splitlines()[:4],
        "files": observed_files,
    }


def validate_abi_reference(reference_root: Path) -> dict[str, object]:
    reference_root = reference_root.resolve()
    provenance = load_provenance()
    contract = provenance.get("abi_reference")
    if not isinstance(contract, dict):
        raise InteropBuildError("ABI-reference provenance has the wrong shape")
    if not (reference_root / ".git").exists():
        raise InteropBuildError(f"ABI-reference checkout is absent: {reference_root}")

    commit = run(("git", "rev-parse", "HEAD"), cwd=reference_root).strip()
    if commit != contract.get("git_commit"):
        raise InteropBuildError(
            "ABI-reference commit changed: "
            f"expected {contract.get('git_commit')}, got {commit}"
        )

    configured_files = contract.get("files")
    if not isinstance(configured_files, dict):
        raise InteropBuildError("ABI-reference file provenance has the wrong shape")
    observed_files: dict[str, dict[str, object]] = {}
    for relative, expected_hash in sorted(configured_files.items()):
        path = reference_root / relative
        if not path.is_file() or path.is_symlink():
            raise InteropBuildError(f"Pinned ABI-reference input is absent: {path}")
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise InteropBuildError(
                f"ABI-reference input hash changed for {relative}: {observed_hash}"
            )
        observed_files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": observed_hash,
        }
    return {"git_commit": commit, "files": observed_files}


def render_template(template: Path, replacements: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for token, value in replacements.items():
        text = text.replace(f"@{token}@", value)
    unresolved = sorted(set(re.findall(r"@[A-Z][A-Z0-9_]*@", text)))
    if unresolved:
        raise InteropBuildError(
            f"Unresolved template tokens in {template}: {', '.join(unresolved)}"
        )
    return text


def materialize(template: Path, target: Path, replacements: dict[str, str]) -> None:
    text = render_template(template, replacements)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)


def staging_replacements(output_root: Path, agondev_root: Path) -> dict[str, str]:
    return {
        "AGONDEV_ROOT": str(agondev_root.resolve()),
        "BUILD_SCRIPT": str((ROOT / "scripts/build_agondev_interop.py").resolve()),
        "FSIM_ROOT": str(ROOT.resolve()),
        "OUTPUT_ROOT": str(output_root.resolve()),
        "PYTHON": str(ROOT / ".venv/bin/python"),
    }


def makefile_replacements(agondev_root: Path) -> dict[str, str]:
    return {
        "AGONDEV_MAKEFILE": str(
            agondev_root.resolve() / "release/config/makefile.inc"
        )
    }


def stage_project(output_root: Path, agondev_root: Path) -> Path:
    output_root = output_root.resolve()
    project = output_root / "project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    (project / "include").mkdir(parents=True, exist_ok=True)

    shutil.copyfile(EXPERIMENT / "src/main.c", project / "src/main.c")
    shutil.copyfile(EXPERIMENT / "src/bridge.asm", project / "src/bridge.asm")
    shutil.copyfile(
        EXPERIMENT / "include/interop.h", project / "include/interop.h"
    )
    materialize(
        EXPERIMENT / "AgonDev.mk.in",
        project / "Makefile",
        makefile_replacements(agondev_root),
    )

    cmake_source = output_root / "cmake-source"
    replacements = staging_replacements(output_root, agondev_root)
    materialize(
        EXPERIMENT / "CMakeLists.txt.in",
        cmake_source / "CMakeLists.txt",
        replacements,
    )
    materialize(
        EXPERIMENT / "CMakePresets.json.in",
        cmake_source / "CMakePresets.json",
        replacements,
    )
    return project


def expected_staged_files(
    output_root: Path, agondev_root: Path
) -> dict[Path, bytes]:
    output_root = output_root.resolve()
    project = output_root / "project"
    cmake_source = output_root / "cmake-source"
    cmake_replacements = staging_replacements(output_root, agondev_root)
    return {
        project / "src/main.c": (EXPERIMENT / "src/main.c").read_bytes(),
        project / "src/bridge.asm": (EXPERIMENT / "src/bridge.asm").read_bytes(),
        project / "include/interop.h": (
            EXPERIMENT / "include/interop.h"
        ).read_bytes(),
        project / "Makefile": render_template(
            EXPERIMENT / "AgonDev.mk.in", makefile_replacements(agondev_root)
        ).encode(),
        cmake_source / "CMakeLists.txt": render_template(
            EXPERIMENT / "CMakeLists.txt.in", cmake_replacements
        ).encode(),
        cmake_source / "CMakePresets.json": render_template(
            EXPERIMENT / "CMakePresets.json.in", cmake_replacements
        ).encode(),
    }


def verify_staged_files(output_root: Path, agondev_root: Path) -> None:
    expected = expected_staged_files(output_root, agondev_root)
    for path, wanted in expected.items():
        if path.is_symlink() or not path.is_file():
            raise InteropBuildError(f"Expected staged input is absent: {path}")
        if path.read_bytes() != wanted:
            raise InteropBuildError(f"Staged input differs from tracked source: {path}")

    output_root = output_root.resolve()
    inventory_contracts = {
        output_root / "project/src": {"main.c", "bridge.asm"},
        output_root / "project/include": {"interop.h"},
        output_root / "cmake-source": {"CMakeLists.txt", "CMakePresets.json"},
    }
    for directory, wanted_names in inventory_contracts.items():
        if not directory.is_dir() or directory.is_symlink():
            raise InteropBuildError(f"Staged input directory is absent: {directory}")
        actual_names = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        if actual_names != wanted_names:
            raise InteropBuildError(
                f"Staged input inventory changed in {directory}: "
                f"expected {sorted(wanted_names)}, got {sorted(actual_names)}"
            )


def build_project(project: Path) -> str:
    return run(("make", "--no-print-directory", "all"), cwd=project)


def require_pattern(text: str, pattern: str, description: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise InteropBuildError(f"Missing {description}: /{pattern}/")


def verify_outputs(
    output_root: Path, agondev_root: Path, *, deterministic_rebuild: bool
) -> dict[str, object]:
    project = output_root.resolve() / "project"
    toolbin = agondev_root.resolve() / "release/bin"
    main_object = project / "obj/main.o"
    bridge_object = project / "obj/bridge.o"
    inspection = project / "inspect/main.s"
    elf = project / "bin/fsim-agondev-interop.elf"
    binary = project / "bin/fsim-agondev-interop.bin"
    noname = project / "bin/fsim-agondev-interop.noname.bin"
    link_map = project / "bin/fsim-agondev-interop.map"

    outputs = (main_object, bridge_object, inspection, elf, binary, noname, link_map)
    for path in outputs:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise InteropBuildError(f"Expected build output is absent or empty: {path}")

    binary_bytes = binary.read_bytes()
    if binary_bytes[:4] != bytes((0xC3, 0x45, 0x00, 0x04)):
        raise InteropBuildError("AgonDev MOS entry jump changed")
    if binary_bytes[0x40:0x45] != b"MOS\x00\x01":
        raise InteropBuildError("AgonDev MOS application header changed")
    if len(binary_bytes) >= 0x070000:
        raise InteropBuildError("Interop probe exceeds the FSIM fixture load window")

    nm = toolbin / "ez80-none-elf-nm"
    objdump = toolbin / "ez80-none-elf-objdump"
    objcopy = toolbin / "ez80-none-elf-objcopy"
    readelf = toolbin / "ez80-none-elf-readelf"
    main_nm = run((nm, "--undefined-only", main_object))
    bridge_nm = run((nm, bridge_object))
    final_undefined = run((nm, "--undefined-only", elf)).strip()
    bridge_disassembly = run((objdump, "-dr", bridge_object))
    elf_header = run((readelf, "-h", elf))
    inspection_text = inspection.read_text(encoding="utf-8")

    for symbol in (
        "_asm_stamp_state",
        "_asm_policy_round_trip",
        "_asm_return_u16",
        "_asm_return_u24",
        "_putch",
    ):
        require_pattern(main_nm, rf"\bU\s+{re.escape(symbol)}\b", f"C reference {symbol}")
    for symbol in (
        "_asm_stamp_state",
        "_asm_policy_round_trip",
        "_asm_return_u16",
        "_asm_return_u24",
    ):
        require_pattern(bridge_nm, rf"\bT\s+{re.escape(symbol)}\b", f"assembly export {symbol}")
    require_pattern(
        bridge_nm,
        r"\bU\s+_interop_choose_action\b",
        "assembly-to-C callback reference",
    )
    require_pattern(
        bridge_disassembly,
        r"r_imm24\s+_interop_choose_action",
        "assembly callback relocation",
    )
    for symbol in (
        "_asm_stamp_state",
        "_asm_policy_round_trip",
        "_asm_return_u16",
        "_asm_return_u24",
    ):
        require_pattern(
            inspection_text,
            rf"\bcall\s+{re.escape(symbol)}\b",
            f"compiled C call to {symbol}",
        )
    require_pattern(elf_header, r"Machine:\s+Zilog Z80", "eZ80 ELF machine")
    require_pattern(elf_header, r"Entry point address:\s+0x40045", "AgonDev CRT entry")
    require_pattern(elf_header, r"Flags:\s+0x84", "eZ80 ADL ELF flags")
    if final_undefined:
        raise InteropBuildError(f"Final inspection ELF has unresolved symbols:\n{final_undefined}")

    with tempfile.TemporaryDirectory(prefix="agondev-interop-elf-image-") as temporary:
        extracted = Path(temporary) / "inspection.bin"
        run((objcopy, "-O", "binary", elf, extracted))
        if extracted.read_bytes() != noname.read_bytes():
            raise InteropBuildError(
                "Inspection ELF load image differs from the linked noname binary"
            )

    undefined_symbols = {
        line.split()[-1] for line in main_nm.splitlines() if line.strip()
    }
    bridge_exports = {
        match.group(1)
        for match in re.finditer(
            r"^[0-9a-fA-F]+\s+T\s+(\S+)$", bridge_nm, flags=re.MULTILINE
        )
    }
    external_undefined = undefined_symbols - bridge_exports
    if external_undefined != PINNED_POLICY_EXTERNAL_UNDEFINED:
        raise InteropBuildError(
            "Policy object's external undefined-symbol contract changed: "
            f"expected {sorted(PINNED_POLICY_EXTERNAL_UNDEFINED)}, "
            f"got {sorted(external_undefined)}"
        )
    forbidden_fragments = (
        "div",
        "fix",
        "float",
        "fadd",
        "fmul",
        "fsub",
        "mul",
        "rem",
    )
    forbidden = sorted(
        symbol
        for symbol in external_undefined
        if any(fragment in symbol.lower() for fragment in forbidden_fragments)
    )
    if forbidden:
        raise InteropBuildError(
            "Policy object selected forbidden arithmetic helpers: "
            + ", ".join(forbidden)
        )

    result: dict[str, object] = {
        "entry_jump_hex": binary_bytes[:4].hex(),
        "mos_header_hex": binary_bytes[0x40:0x45].hex(),
        "undefined_policy_symbols": sorted(undefined_symbols),
        "external_policy_symbols": sorted(external_undefined),
        "forbidden_arithmetic_helpers": forbidden,
        "deterministic_rebuild": deterministic_rebuild,
        "elf_binary_matches_noname": True,
        "outputs": {},
    }
    output_receipts = result["outputs"]
    assert isinstance(output_receipts, dict)
    for path in outputs:
        relative = path.relative_to(project).as_posix()
        output_receipts[relative] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return result


def tracked_input_receipts() -> dict[str, dict[str, object]]:
    inputs: dict[str, dict[str, object]] = {}
    for path in TRACKED_INPUTS:
        relative = path.relative_to(ROOT).as_posix()
        inputs[relative] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return inputs


def add_semantic_hash(receipt: dict[str, object]) -> dict[str, object]:
    if "semantic_sha256" in receipt:
        raise InteropBuildError("Receipt already contains a semantic hash")
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["semantic_sha256"] = hashlib.sha256(canonical).hexdigest()
    return receipt


def build_receipt(
    toolchain: dict[str, object],
    abi_reference: dict[str, object],
    verification: dict[str, object],
    *,
    qualified: bool,
) -> dict[str, object]:
    deterministic = verification.get("deterministic_rebuild") is True
    if qualified and not deterministic:
        raise InteropBuildError(
            "Authoritative qualification requires an independent deterministic rebuild"
        )
    receipt: dict[str, object] = {
        "schema": BUILD_SCHEMA if qualified else LOCAL_BUILD_SCHEMA,
        "status": "qualified" if qualified else "unqualified-local-build",
        "load_address": 0x040000,
        "load_capacity": 0x070000,
        "toolchain": toolchain,
        "abi_reference": abi_reference,
        "inputs": tracked_input_receipts(),
        "verification": verification,
    }
    return add_semantic_hash(receipt)


def write_receipt(
    output_root: Path, receipt: dict[str, object], *, filename: str
) -> Path:
    if filename not in {BUILD_RECEIPT, LOCAL_BUILD_RECEIPT}:
        raise InteropBuildError(f"Unexpected receipt filename: {filename}")
    path = output_root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def invalidate_generated_receipts(output_root: Path) -> None:
    for filename in (BUILD_RECEIPT, LOCAL_BUILD_RECEIPT):
        path = output_root / filename
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise InteropBuildError(f"Refusing to replace non-file receipt: {path}")
        path.unlink()


def load_json_object(path: Path) -> tuple[bytes, dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise InteropBuildError(f"Authoritative build receipt is absent: {path}")
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InteropBuildError(f"Build receipt is malformed: {path}") from error
    if not isinstance(parsed, dict):
        raise InteropBuildError(f"Build receipt has the wrong shape: {path}")
    return raw, parsed


def verify_semantic_hash(receipt: dict[str, object]) -> None:
    recorded = receipt.get("semantic_sha256")
    if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
        raise InteropBuildError("Build receipt semantic hash is absent or malformed")
    payload = dict(receipt)
    del payload["semantic_sha256"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    observed = hashlib.sha256(canonical).hexdigest()
    if observed != recorded:
        raise InteropBuildError(
            f"Build receipt semantic hash changed: expected {recorded}, got {observed}"
        )


def verify_authoritative_receipt(
    output_root: Path,
    agondev_root: Path,
    toolchain: dict[str, object],
    abi_reference: dict[str, object],
) -> Path:
    output_root = output_root.resolve()
    path = output_root / BUILD_RECEIPT
    original_bytes, receipt = load_json_object(path)
    verify_semantic_hash(receipt)

    if set(receipt) != AUTHORITATIVE_RECEIPT_KEYS:
        raise InteropBuildError(
            "BUILD.json authoritative schema keys changed: "
            f"expected {sorted(AUTHORITATIVE_RECEIPT_KEYS)}, "
            f"got {sorted(receipt)}"
        )
    if receipt.get("schema") != BUILD_SCHEMA or receipt.get("status") != "qualified":
        raise InteropBuildError("BUILD.json is not an authoritative qualified receipt")
    if receipt.get("load_address") != 0x040000 or receipt.get("load_capacity") != 0x070000:
        raise InteropBuildError("Build receipt load contract changed")
    if receipt.get("toolchain") != toolchain:
        raise InteropBuildError("Build receipt toolchain evidence changed")
    if receipt.get("abi_reference") != abi_reference:
        raise InteropBuildError("Build receipt ABI-reference evidence changed")
    if receipt.get("inputs") != tracked_input_receipts():
        raise InteropBuildError("Build receipt no longer matches tracked inputs")

    verify_staged_files(output_root, agondev_root)
    verification = verify_outputs(
        output_root, agondev_root, deterministic_rebuild=True
    )
    if receipt.get("verification") != verification:
        raise InteropBuildError("Build receipt no longer matches verified outputs")

    if path.read_bytes() != original_bytes:
        raise InteropBuildError("Verify-only unexpectedly modified BUILD.json")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agondev-root",
        type=Path,
        default=DEFAULT_AGONDEV_ROOT,
        help="read-only AgonDev checkout",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="ignored build output root",
    )
    parser.add_argument(
        "--abi-reference-root",
        type=Path,
        default=DEFAULT_ABI_REFERENCE_ROOT,
        help="read-only mos-agondev ABI-reference checkout",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="materialize Make and CMake wrappers without compiling",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify an existing staged build without compiling",
    )
    parser.add_argument(
        "--skip-determinism",
        action="store_true",
        help="skip the independent second-directory binary comparison",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    agondev_root = args.agondev_root.resolve()
    abi_reference_root = args.abi_reference_root.resolve()
    output_root = args.output.resolve()
    toolchain = validate_toolchain(agondev_root)
    abi_reference = validate_abi_reference(abi_reference_root)

    if args.stage_only and args.verify_only:
        raise InteropBuildError("--stage-only and --verify-only are exclusive")
    if args.verify_only and args.skip_determinism:
        raise InteropBuildError("--verify-only cannot weaken deterministic evidence")
    if args.stage_only and args.skip_determinism:
        raise InteropBuildError("--skip-determinism does not apply to --stage-only")
    if args.verify_only:
        receipt_path = verify_authoritative_receipt(
            output_root, agondev_root, toolchain, abi_reference
        )
        print(f"Verified authoritative AgonDev interop receipt: {receipt_path}")
        return 0

    invalidate_generated_receipts(output_root)
    if args.stage_only:
        project = stage_project(output_root, agondev_root)
        print(f"Staged AgonDev interop project: {project}")
        return 0

    deterministic = False
    project = stage_project(output_root, agondev_root)
    print(build_project(project), end="")
    verify_staged_files(output_root, agondev_root)
    if not args.skip_determinism:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="agondev-interop-determinism-", dir=output_root.parent
        ) as temporary:
            second_root = Path(temporary)
            second_project = stage_project(second_root, agondev_root)
            build_project(second_project)
            verify_staged_files(second_root, agondev_root)
            for relative in (
                "bin/fsim-agondev-interop.bin",
                "bin/fsim-agondev-interop.elf",
            ):
                first = output_root / "project" / relative
                second = second_root / "project" / relative
                if sha256_file(first) != sha256_file(second):
                    raise InteropBuildError(
                        f"Independent rebuild changed {relative}"
                    )
            deterministic = True

    verification = verify_outputs(
        output_root, agondev_root, deterministic_rebuild=deterministic
    )
    qualified = deterministic
    receipt = build_receipt(
        toolchain, abi_reference, verification, qualified=qualified
    )
    filename = BUILD_RECEIPT if qualified else LOCAL_BUILD_RECEIPT
    receipt_path = write_receipt(output_root, receipt, filename=filename)
    program = output_root / "project/bin/fsim-agondev-interop.bin"
    if qualified:
        print(f"Qualified AgonDev interop probe: {program}")
        print(f"Authoritative build receipt: {receipt_path}")
    else:
        print(f"Unqualified local AgonDev interop build: {program}")
        print(f"Local build manifest: {receipt_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InteropBuildError as error:
        raise SystemExit(str(error)) from error
