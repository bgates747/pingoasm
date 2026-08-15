#!/usr/bin/env python3
"""Build the isolated regular-LOD sibling with one AgonDev policy seam."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence
import zlib


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = ROOT / "fixtures/terrain-manager-survey/src"
ACCEPTED_SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-survey.asm"
SOURCE = SOURCE_DIRECTORY / "terrain-manager-regular-lod-c-policy-survey.asm"
PROVIDER = SOURCE_DIRECTORY / "terrain-manager-regular-lod-provider.inc"
CLIENT = SOURCE_DIRECTORY / "terrain-manager-regular-lod-policy-client.inc"
FIXTURE = ROOT / "fixtures/terrain-manager-regular-lod-c-policy-survey"
DEFAULT_ARTIFACT_OUTPUT = FIXTURE / "tgt"
DEFAULT_RUNTIME_OUTPUT = ROOT / "build/p3dm/bay-area-regular-n1-hierarchy"
DEFAULT_MODULE_OUTPUT = ROOT / "build/experiments/agondev-regular-policy"
MODULE_BUILDER_PATH = ROOT / "scripts/build_agondev_regular_policy.py"
ACCEPTED_BUILDER_PATH = ROOT / "scripts/build_regular_lod_manager_survey.py"

PROGRAM_STEM = "terrain-manager-regular-lod-c-policy-survey"
PROGRAM_NAME = "P3DRGLC.BIN"
MODULE_NAME = "CPOLICY.BIN"
MANIFEST_NAME = "MANAGERC.json"
BUILD_RECEIPT = "BUILD.json"
BUILD_SCHEMA = "pingo-terrain-regular-lod-c-policy-survey-build-v1"
RUNTIME_SCHEMA = "pingo-terrain-regular-lod-c-policy-survey-runtime-v1"

FIXTURE_LOAD_ADDRESS = 0x040000
FIXTURE_LIMIT_EXCLUSIVE = 0x070000
MODULE_LOAD_ADDRESS = 0x070000
MODULE_ENTRY_ADDRESS = 0x070020
MODULE_LIMIT_EXCLUSIVE = 0x080000
LAUNCHER_LOAD_ADDRESS = 0x0B0000
ACCEPTED_PROGRAM_SHA256 = (
    "27f09db1eb0b0eec702aad5c17f35e68922f154a6c3391370d07a76027cc57bf"
)
HISTORICAL_MODE_PROGRAM_SHA256 = {
    "asm-only": "ca85793ca3687e1ac8657d1dae5e44ab0e7d1ecbffa4425632030aec6d06d836",
    "dual-strict": "fa463e862f1bb0602f7e67ff8855ac20aa5c2974dc87408007a1914fd700cc07",
}
FIXTURE_STUB = bytes((0xC3, 0x45, 0x00, 0x04))
MOS_ADL_HEADER = b"MOS\x00\x01"

MODE_PROFILES = {
    "asm-only": {
        "value": 0,
        "include": "terrain-manager-regular-lod-policy-mode-asm-only.inc",
        "display": "ASM_ONLY",
        "authority": "accepted assembly selector",
        "module_required": True,
        "source_dependencies": (),
    },
    "dual-strict": {
        "value": 1,
        "include": "terrain-manager-regular-lod-policy-mode-dual-strict.inc",
        "display": "DUAL_STRICT",
        "authority": "assembly oracle; C mismatch aborts before staging",
        "module_required": True,
        "source_dependencies": (),
    },
    "c-guarded": {
        "value": 2,
        "include": "terrain-manager-regular-lod-policy-mode-c-guarded.inc",
        "display": "C_GUARDED",
        "authority": "revalidated C result; assembly fault fallback",
        "module_required": True,
        "source_dependencies": (),
    },
}
DEFAULT_MODE = "c-guarded"


class CPolicyFixtureBuildError(RuntimeError):
    """A source, module, memory-map, or installation contract failed."""


def checked_descriptor_cache_bytes(group_count: int) -> int:
    """Return the fixed cache usage or reject a count that could overrun it."""

    if not 0 <= group_count <= module_builder.MAX_DESCRIPTORS:
        raise CPolicyFixtureBuildError(
            f"Descriptor count exceeds fixed cache: {group_count}"
        )
    return group_count * module_builder.DESCRIPTOR_BYTES


def import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CPolicyFixtureBuildError(f"Cannot import builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module_builder = import_script("build_agondev_regular_policy", MODULE_BUILDER_PATH)
accepted_builder = import_script(
    "build_regular_lod_manager_survey", ACCEPTED_BUILDER_PATH
)


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-mode", choices=tuple(MODE_PROFILES), default=DEFAULT_MODE)
    parser.add_argument(
        "--artifact-output", type=Path, default=DEFAULT_ARTIFACT_OUTPUT
    )
    parser.add_argument("--runtime-output", type=Path, default=DEFAULT_RUNTIME_OUTPUT)
    parser.add_argument("--module-output", type=Path, default=DEFAULT_MODULE_OUTPUT)
    parser.add_argument(
        "--skip-module-build",
        action="store_true",
        help="verify and consume an already-qualified fixed module",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="build target artifacts and receipt without installing runtime files",
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


def receipt_path(path: Path) -> str:
    """Use repository-relative names for reproducible tracked receipts."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CPolicyFixtureBuildError(f"Refusing to overwrite symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def atomic_json(path: Path, document: dict[str, object]) -> None:
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
        raise CPolicyFixtureBuildError(
            f"Command failed ({completed.returncode}): {' '.join(rendered)}\n"
            f"{completed.stdout}"
        )
    return completed.stdout


def canonicalize_sibling_source(text: str) -> str:
    """Map the tracked sibling's only permitted profile differences to control."""

    text = text.replace(
        "; Experimental Marina regular-hierarchy sibling with an AgonDev C policy seam.",
        "; Marina regular-hierarchy survey: regional client of the universal manager.",
        1,
    )
    profile = (
        "terrain_manager_regular_policy_client: equ 1\n"
        "terrain_manager_regular_policy_mode: equ 2\n"
        '    include "../../../build/experiments/agondev-regular-policy/'
        'regular-policy-import.inc"\n'
        '    include "terrain-manager-regular-lod-policy-mode-c-guarded.inc"'
    )
    control = (
        "terrain_manager_regular_policy_client: equ 0\n"
        "terrain_manager_regular_policy_mode: equ 0\n"
        "    MACRO REGULAR_POLICY_BEGIN_TRANSITION\n"
        "        .align 1\n"
        "    ENDMACRO\n"
        "    MACRO REGULAR_POLICY_SELECT_DISPATCH\n"
        "        .align 1\n"
        "    ENDMACRO"
    )
    if text.count(profile) != 1:
        raise CPolicyFixtureBuildError("Sibling policy preamble changed")
    text = text.replace(profile, control, 1)
    text = text.replace(
        'title:\n    db "Marina hierarchy C-policy C_GUARDED:',
        'title:\n    db "Marina hierarchy:',
        1,
    )
    return text


def validate_source_copy() -> None:
    accepted = ACCEPTED_SOURCE.read_text(encoding="ascii")
    sibling = SOURCE.read_text(encoding="ascii")
    if canonicalize_sibling_source(sibling).rstrip("\n") != accepted.rstrip("\n"):
        raise CPolicyFixtureBuildError(
            "Sibling source differs from the accepted fixture outside its exact "
            "profile preamble/title"
        )


def profile_source(mode: str) -> str:
    profile = MODE_PROFILES[mode]
    text = SOURCE.read_text(encoding="ascii")
    text = text.replace(
        "terrain_manager_regular_policy_mode: equ 2",
        f"terrain_manager_regular_policy_mode: equ {profile['value']}",
        1,
    )
    text = text.replace(
        'include "terrain-manager-regular-lod-policy-mode-c-guarded.inc"',
        f'include "{profile["include"]}"',
        1,
    )
    text = text.replace("C-policy C_GUARDED:", f"C-policy {profile['display']}:", 1)
    return text


def stage_source_mirror(directory: Path, mode: str | None) -> Path:
    mirror_root = directory / "fsim"
    fixture_mirror = mirror_root / "fixtures"
    source_mirror = fixture_mirror / "terrain-manager-survey/src"
    source_mirror.mkdir(parents=True)

    for name in ("build", "runtime"):
        (mirror_root / name).symlink_to(ROOT / name, target_is_directory=True)
    for fixture in (ROOT / "fixtures").iterdir():
        if fixture.name == "terrain-manager-survey":
            continue
        (fixture_mirror / fixture.name).symlink_to(
            fixture, target_is_directory=fixture.is_dir()
        )
    for dependency in SOURCE_DIRECTORY.iterdir():
        if dependency == SOURCE:
            continue
        (source_mirror / dependency.name).symlink_to(
            dependency, target_is_directory=dependency.is_dir()
        )
    generated = source_mirror / "RLC.ASM"
    if mode is None:
        source_text = ACCEPTED_SOURCE.read_text(encoding="ascii")
    else:
        source_text = profile_source(mode)
    generated.write_text(source_text, encoding="ascii")
    return generated


def rebuild_accepted_control() -> str:
    """Assemble the accepted assembly-only control in isolation."""

    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise CPolicyFixtureBuildError("ez80asm is not available on PATH")
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="rlc-control-") as temporary:
        source = stage_source_mirror(Path(temporary), None)
        generated_program = source.with_suffix(".BIN")
        run(
            (
                assembler,
                source.name,
                generated_program.name,
                "-c",
            ),
            cwd=source.parent,
        )
        if not generated_program.is_file():
            raise CPolicyFixtureBuildError(
                f"ez80asm omitted control artifact: {generated_program}"
            )
        rebuilt_sha256 = sha256_file(generated_program)
    if rebuilt_sha256 != ACCEPTED_PROGRAM_SHA256:
        raise CPolicyFixtureBuildError(
            "Accepted assembly-only control changed: "
            f"{rebuilt_sha256} != {ACCEPTED_PROGRAM_SHA256}"
        )
    return rebuilt_sha256


def require_module(module_output: Path, *, build: bool) -> tuple[dict, Path, Path]:
    command = [sys.executable, str(MODULE_BUILDER_PATH), "--output", str(module_output)]
    if not build:
        command.append("--verify-only")
    run(command, cwd=ROOT)
    receipt_path = module_output / module_builder.BUILD_RECEIPT
    import_path = module_output / module_builder.IMPORT_FILENAME
    image_path = module_output / f"project/bin/{MODULE_NAME}"
    for path in (receipt_path, import_path, image_path):
        if not path.is_file() or path.is_symlink():
            raise CPolicyFixtureBuildError(f"Qualified module output is absent: {path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    module = receipt.get("module")
    if not isinstance(module, dict) or receipt.get("status") != "qualified":
        raise CPolicyFixtureBuildError("Fixed-module receipt is not qualified")
    image = image_path.read_bytes()
    expected = module_builder.expected_header(len(image))
    if image[: module_builder.HEADER_BYTES] != expected:
        raise CPolicyFixtureBuildError("Runtime module header differs from generated ABI")
    expected_include = module_builder.render_import_include(
        image_bytes=len(image),
        image_sha256=sha256_bytes(image),
        image_crc32=zlib.crc32(image) & 0xFFFFFFFF,
    )
    if import_path.read_text(encoding="utf-8") != expected_include:
        raise CPolicyFixtureBuildError("Generated module import include is stale")
    witness = (
        module.get("filename"),
        module.get("load_address"),
        module.get("entry_address"),
        module.get("limit_exclusive"),
        module.get("image_bytes"),
        module.get("sha256"),
        module.get("crc32"),
    )
    expected_witness = (
        MODULE_NAME,
        MODULE_LOAD_ADDRESS,
        MODULE_ENTRY_ADDRESS,
        MODULE_LIMIT_EXCLUSIVE,
        len(image),
        sha256_bytes(image),
        f"{zlib.crc32(image) & 0xFFFFFFFF:08x}",
    )
    if witness != expected_witness:
        raise CPolicyFixtureBuildError(
            f"Fixed-module receipt/image mismatch: {witness} != {expected_witness}"
        )
    return receipt, image_path, import_path


def assemble(mode: str, artifact_output: Path) -> tuple[Path, Path, Path, str]:
    assembler = shutil.which("ez80asm")
    if assembler is None:
        raise CPolicyFixtureBuildError("ez80asm is not available on PATH")
    artifact_output.mkdir(parents=True, exist_ok=True)
    program = artifact_output / f"{PROGRAM_STEM}.bin"
    listing = artifact_output / f"{PROGRAM_STEM}.lst"
    symbols = artifact_output / f"{PROGRAM_STEM}.symbols"
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="rlc-build-") as temporary:
        source = stage_source_mirror(Path(temporary), mode)
        audit = run(
            (
                sys.executable,
                ROOT / "scripts/audit_adl_width.py",
                "--follow-includes",
                "--show-review",
                "--fail-review",
                source,
            ),
            cwd=source.parent,
        )
        generated_program = source.with_suffix(".BIN")
        generated_listing = source.with_suffix(".lst")
        generated_symbols = source.with_suffix(".symbols")
        run(
            (
                assembler,
                "-l",
                "-s",
                source.name,
                generated_program.name,
                "-c",
            ),
            cwd=source.parent,
        )
        for generated, destination in (
            (generated_program, program),
            (generated_listing, listing),
            (generated_symbols, symbols),
        ):
            if not generated.is_file():
                raise CPolicyFixtureBuildError(
                    f"ez80asm omitted requested artifact: {generated}"
                )
            atomic_bytes(destination, generated.read_bytes())
    return program, listing, symbols, audit.strip()


def parse_symbols(path: Path) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z_@][A-Za-z0-9_@.]*) \$([0-9A-Fa-f]+)", line)
        if match is None:
            continue
        parsed.setdefault(match.group(1), int(match.group(2), 16))
    return parsed


def validate_memory_map(
    program: Path, symbols_path: Path, module: dict, resource_paths: Sequence[Path]
) -> dict[str, object]:
    payload = program.read_bytes()
    if payload[:4] != FIXTURE_STUB or payload[0x40:0x45] != MOS_ADL_HEADER:
        raise CPolicyFixtureBuildError("Sibling lost the common fixture entry/header")
    symbols = parse_symbols(symbols_path)
    required = {
        "filedata",
        "p3dm_file_buffer",
        "terrain_manager_initialize",
        "regular_transition_select_feasible_group",
        "regular_transition_select_feasible_group_asm",
        "regular_policy_initialize",
        "regular_policy_expected_header",
        "regular_policy_descriptors",
        "regular_policy_all_descriptors",
    }
    missing = required - set(symbols)
    if missing:
        raise CPolicyFixtureBuildError(f"Sibling symbol export is incomplete: {sorted(missing)}")
    descriptor_cache_bytes = checked_descriptor_cache_bytes(
        module_builder.MAX_DESCRIPTORS
    )
    descriptor_gaps = (
        symbols["regular_policy_descriptors"]
        - symbols["regular_policy_all_descriptors"],
        symbols["terrain_manager_initialize"]
        - symbols["regular_policy_descriptors"],
    )
    if descriptor_gaps != (descriptor_cache_bytes, descriptor_cache_bytes):
        raise CPolicyFixtureBuildError(
            "Fixed descriptor arrays do not occupy their exact reserved windows: "
            f"{descriptor_gaps} != "
            f"({descriptor_cache_bytes}, {descriptor_cache_bytes})"
        )
    program_end = FIXTURE_LOAD_ADDRESS + len(payload)
    filedata = symbols["filedata"]
    if program_end != filedata:
        raise CPolicyFixtureBuildError(
            f"Sibling filedata/program end mismatch: 0x{filedata:06x} != "
            f"0x{program_end:06x}"
        )
    resources = [
        {
            "path": receipt_path(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in resource_paths
    ]
    maximum_resource = max(item["bytes"] for item in resources)
    staging_end = filedata + int(maximum_resource)
    module_load = int(module["load_address"])
    module_end = module_load + int(module["image_bytes"])
    module_limit = int(module["limit_exclusive"])
    if not (
        program_end < FIXTURE_LIMIT_EXCLUSIVE
        and staging_end < module_load
        and module_load == FIXTURE_LIMIT_EXCLUSIVE
        and module_end < module_limit
        and module_limit < LAUNCHER_LOAD_ADDRESS
    ):
        raise CPolicyFixtureBuildError(
            "Sibling/module memory windows collide: "
            f"program_end=0x{program_end:06x}, staging_end=0x{staging_end:06x}, "
            f"module=[0x{module_load:06x},0x{module_end:06x}), "
            f"limit=0x{module_limit:06x}, launcher=0x{LAUNCHER_LOAD_ADDRESS:06x}"
        )
    p3dm_start = symbols["p3dm_file_buffer"]
    p3dm_end = p3dm_start + 16_384
    if p3dm_end > program_end or p3dm_end >= module_load:
        raise CPolicyFixtureBuildError("P3DM validation buffer escapes fixture window")
    return {
        "fixture_load_address": FIXTURE_LOAD_ADDRESS,
        "fixture_program_end": program_end,
        "fixture_filedata": filedata,
        "resource_staging_maximum_bytes": maximum_resource,
        "resource_staging_end": staging_end,
        "p3dm_file_buffer": [p3dm_start, p3dm_end],
        "fixture_limit_exclusive": FIXTURE_LIMIT_EXCLUSIVE,
        "module_load_address": module_load,
        "module_entry_address": int(module["entry_address"]),
        "module_image_end": module_end,
        "module_limit_exclusive": module_limit,
        "launcher_load_address": LAUNCHER_LOAD_ADDRESS,
        "descriptor_array_bytes": descriptor_cache_bytes,
        "descriptor_array_gaps": list(descriptor_gaps),
        "resources": resources,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = arguments(argv)
    mode = args.policy_mode
    artifact_output = args.artifact_output.expanduser().resolve()
    runtime_output = args.runtime_output.expanduser().resolve()
    module_output = args.module_output.expanduser().resolve()
    if module_output != DEFAULT_MODULE_OUTPUT.resolve():
        raise CPolicyFixtureBuildError(
            "--module-output is pinned to the generated include imported by the "
            f"tracked sibling source: {DEFAULT_MODULE_OUTPUT.resolve()}"
        )
    validate_source_copy()
    rebuilt_control_sha256 = rebuild_accepted_control()

    # Reuse the accepted builder's complete corpus and presentation gates.
    hierarchy, selected = accepted_builder.require_hierarchy(DEFAULT_RUNTIME_OUTPUT)
    accepted_builder.require_fine_corpus(accepted_builder.DEFAULT_FINE_CORPUS)
    _, aggregates = accepted_builder.initial_runtime_records(
        DEFAULT_RUNTIME_OUTPUT, accepted_builder.DEFAULT_FINE_CORPUS, selected
    )

    module_receipt, module_image, module_import = require_module(
        module_output, build=not args.skip_module_build
    )
    program, listing, symbols, audit = assemble(mode, artifact_output)
    historical_hash = HISTORICAL_MODE_PROGRAM_SHA256.get(mode)
    if historical_hash is not None and sha256_file(program) != historical_hash:
        raise CPolicyFixtureBuildError(
            f"Historical {mode} binary changed: "
            f"{sha256_file(program)} != {historical_hash}"
        )
    resource_paths = tuple(DEFAULT_RUNTIME_OUTPUT / name for name in accepted_builder.RESOURCE_NAMES)
    if not all(path.is_file() for path in resource_paths):
        raise CPolicyFixtureBuildError("Canonical regular-LOD resources are incomplete")
    memory = validate_memory_map(
        program, symbols, module_receipt["module"], resource_paths
    )
    profile = MODE_PROFILES[mode]
    mode_include = SOURCE_DIRECTORY / str(profile["include"])
    if not mode_include.is_file() or mode_include.is_symlink():
        raise CPolicyFixtureBuildError(f"Policy mode include is absent: {mode_include}")
    mode_dependencies = []
    for name in profile["source_dependencies"]:
        dependency = SOURCE_DIRECTORY / str(name)
        if not dependency.is_file() or dependency.is_symlink():
            raise CPolicyFixtureBuildError(
                f"Policy mode dependency is absent: {dependency}"
            )
        mode_dependencies.append(
            {
                "path": str(dependency.relative_to(ROOT)),
                "sha256": sha256_file(dependency),
            }
        )
    profiled_source = profile_source(mode).encode("ascii")
    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in (program, listing, symbols)
    }
    receipt: dict[str, object] = {
        "schema": BUILD_SCHEMA,
        "status": "statically-qualified",
        "policy": {
            "mode": profile["display"],
            "mode_value": profile["value"],
            "authority": profile["authority"],
            "selector_seam": "regular_transition_select_feasible_group",
            "fallback": "accepted assembly selector",
            "edge_filter_cache": "once per transition, then pending-only packing",
            "module_required": profile["module_required"],
            "descriptor_capacity": module_builder.MAX_DESCRIPTORS,
            "descriptor_cache_bytes": checked_descriptor_cache_bytes(
                module_builder.MAX_DESCRIPTORS
            ),
        },
        "assembly_control": {
            "kind": "accepted assembly-only control",
            "program": "RLC.BIN",
            "sha256": rebuilt_control_sha256,
            "source": str(ACCEPTED_SOURCE.relative_to(ROOT)),
            "installed_runtime_program": False,
        },
        "source": {
            "path": str(SOURCE.relative_to(ROOT)),
            "sha256": sha256_file(SOURCE),
            "provider": str(PROVIDER.relative_to(ROOT)),
            "provider_sha256": sha256_file(PROVIDER),
            "client": str(CLIENT.relative_to(ROOT)),
            "client_sha256": sha256_file(CLIENT),
            "profiled_sha256": sha256_bytes(profiled_source),
            "mode_include": str(mode_include.relative_to(ROOT)),
            "mode_include_sha256": sha256_file(mode_include),
            "mode_dependencies": mode_dependencies,
            "controlled_copy_difference": True,
        },
        "module": {
            **module_receipt["module"],
            "build_receipt": receipt_path(
                module_output / module_builder.BUILD_RECEIPT
            ),
            "build_receipt_sha256": sha256_file(
                module_output / module_builder.BUILD_RECEIPT
            ),
            "import_include": receipt_path(module_import),
            "import_include_sha256": sha256_file(module_import),
        },
        "memory_map": memory,
        "initial_view": aggregates,
        "artifacts": artifacts,
        "adl_width_audit": audit,
        "human_gates": [
            "interactive emulator presentation",
            "physical hardware execution and timing",
        ],
    }
    atomic_json(artifact_output / BUILD_RECEIPT, receipt)

    if not args.no_install:
        runtime_output.mkdir(parents=True, exist_ok=True)
        installed_program = runtime_output / PROGRAM_NAME
        atomic_bytes(installed_program, program.read_bytes())
        installed_module = runtime_output / MODULE_NAME
        removed_stale_module = False
        if profile["module_required"]:
            atomic_bytes(installed_module, module_image.read_bytes())
        elif os.path.lexists(installed_module):
            if installed_module.is_symlink() or not installed_module.is_file():
                raise CPolicyFixtureBuildError(
                    f"Refusing to remove non-regular stale module: {installed_module}"
                )
            installed_module.unlink()
            removed_stale_module = True
        runtime = {
            "schema": RUNTIME_SCHEMA,
            "program": {
                "filename": PROGRAM_NAME,
                "bytes": installed_program.stat().st_size,
                "sha256": sha256_file(installed_program),
            },
            "module": {
                "filename": MODULE_NAME,
                "bytes": module_image.stat().st_size,
                "sha256": sha256_file(module_image),
                "load_address": MODULE_LOAD_ADDRESS,
                "entry_address": MODULE_ENTRY_ADDRESS,
                "runtime_required": profile["module_required"],
                "installed_by_build": profile["module_required"],
                "removed_stale_module": removed_stale_module,
            },
            "policy": receipt["policy"],
            "memory_map": memory,
            "fixture_build": {
                "path": receipt_path(artifact_output / BUILD_RECEIPT),
                "sha256": sha256_file(artifact_output / BUILD_RECEIPT),
            },
            "accepted_manager_manifest": {
                "path": receipt_path(
                    DEFAULT_RUNTIME_OUTPUT / accepted_builder.RUNTIME_MANIFEST_NAME
                ),
                "sha256": sha256_file(
                    DEFAULT_RUNTIME_OUTPUT / accepted_builder.RUNTIME_MANIFEST_NAME
                ),
                "hierarchy_schema": hierarchy.get("schema"),
            },
            "launcher_entry": None,
        }
        atomic_json(runtime_output / MANIFEST_NAME, runtime)

    print(
        "REGULAR_LOD_C_POLICY",
        f"mode={profile['display']}",
        f"module_required={int(profile['module_required'])}",
        f"binary_bytes={program.stat().st_size}",
        f"binary_sha256={sha256_file(program)}",
        f"module_sha256={sha256_file(module_image)}",
        f"filedata=0x{memory['fixture_filedata']:06x}",
        f"artifact_output={artifact_output}",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CPolicyFixtureBuildError as error:
        raise SystemExit(str(error)) from error
