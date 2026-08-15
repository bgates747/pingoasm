#!/usr/bin/env python3
"""Run the qualified AgonDev interop MOSlet in an isolated headless Agon."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT = ROOT / "experiments/agondev-interop"
BUILD_ROOT = ROOT / "build/experiments/agondev-interop"
DEFAULT_PROGRAM = BUILD_ROOT / "project/bin/fsim-agondev-interop.bin"
DEFAULT_BUILD_RECEIPT = BUILD_ROOT / "BUILD.json"
DEFAULT_OUTPUT = BUILD_ROOT / "headless"
DEFAULT_CLI = ROOT.parents[3] / "fab-agon-emulator/target/release/agon-cli-emulator"
DEFAULT_MOS = ROOT.parents[2] / "mos-agondev/emulator/firmware/mos_platform.bin"
PROGRAM_NAME = "fsim-agondev-interop.bin"
STDIN = (PROGRAM_NAME + "\n").encode("ascii")
MAX_OUTPUT_BYTES = 1024 * 1024


class HeadlessQualificationError(RuntimeError):
    """A target-execution contract failed."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_semantic_hash(document: dict[str, object]) -> str:
    payload = dict(document)
    payload.pop("semantic_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(canonical)


def load_runtime_contract() -> dict[str, object]:
    document = json.loads(
        (EXPERIMENT / "PROVENANCE.json").read_text(encoding="utf-8")
    )
    runtime = document.get("headless_runtime")
    if not isinstance(runtime, dict):
        raise HeadlessQualificationError("headless runtime provenance is absent")
    return runtime


def require_regular_file(path: Path, label: str, *, executable: bool = False) -> Path:
    resolved = path.expanduser().resolve()
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        raise HeadlessQualificationError(f"{label} is unavailable: {resolved}") from error
    if not stat.S_ISREG(mode):
        raise HeadlessQualificationError(f"{label} is not a regular file: {resolved}")
    if executable and not os.access(resolved, os.X_OK):
        raise HeadlessQualificationError(f"{label} is not executable: {resolved}")
    return resolved


def validate_input_pin(
    path: Path, contract: dict[str, object], label: str
) -> dict[str, object]:
    observed_size = path.stat().st_size
    observed_hash = sha256_file(path)
    expected_size = contract.get("bytes")
    expected_hash = contract.get("sha256")
    if expected_size is not None and observed_size != expected_size:
        raise HeadlessQualificationError(
            f"{label} size changed: expected {expected_size}, got {observed_size}"
        )
    if observed_hash != expected_hash:
        raise HeadlessQualificationError(
            f"{label} hash changed: expected {expected_hash}, got {observed_hash}"
        )
    return {"path": str(path), "bytes": observed_size, "sha256": observed_hash}


def validate_build_binding(
    receipt_path: Path, program_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    receipt_path = require_regular_file(receipt_path, "build receipt")
    program_path = require_regular_file(program_path, "interop program")
    document = json.loads(receipt_path.read_text(encoding="utf-8"))
    if document.get("schema") != "pingo-fsim-agondev-interop-build-v1":
        raise HeadlessQualificationError("build receipt is not authoritative schema v1")
    if document.get("status") != "qualified":
        raise HeadlessQualificationError("build receipt is not qualified")
    expected_semantic = document.get("semantic_sha256")
    observed_semantic = canonical_semantic_hash(document)
    if expected_semantic != observed_semantic:
        raise HeadlessQualificationError("build receipt semantic hash is invalid")
    verification = document.get("verification")
    if not isinstance(verification, dict):
        raise HeadlessQualificationError("build receipt verification is malformed")
    if verification.get("deterministic_rebuild") is not True:
        raise HeadlessQualificationError("program lacks deterministic rebuild evidence")
    if verification.get("entry_jump_hex") != "c3450004":
        raise HeadlessQualificationError("program entry jump contract changed")
    if verification.get("mos_header_hex") != "4d4f530001":
        raise HeadlessQualificationError("program MOS header contract changed")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict):
        raise HeadlessQualificationError("build receipt inputs are malformed")
    for relative, contract in inputs.items():
        if not isinstance(relative, str) or not isinstance(contract, dict):
            raise HeadlessQualificationError("build receipt input entry is malformed")
        tracked = require_regular_file(ROOT / relative, f"tracked input {relative}")
        if (
            tracked.stat().st_size != contract.get("bytes")
            or sha256_file(tracked) != contract.get("sha256")
        ):
            raise HeadlessQualificationError(
                f"tracked input no longer matches the build receipt: {relative}"
            )
    outputs = verification.get("outputs")
    if not isinstance(outputs, dict):
        raise HeadlessQualificationError("build receipt outputs are malformed")
    program_contract = outputs.get("bin/fsim-agondev-interop.bin")
    if not isinstance(program_contract, dict):
        raise HeadlessQualificationError("program is absent from the build receipt")
    observed_program = {
        "path": str(program_path),
        "bytes": program_path.stat().st_size,
        "sha256": sha256_file(program_path),
    }
    for field in ("bytes", "sha256"):
        if observed_program[field] != program_contract.get(field):
            raise HeadlessQualificationError(
                f"program {field} does not match the build receipt"
            )
    build = {
        "receipt": {
            "path": str(receipt_path),
            "bytes": receipt_path.stat().st_size,
            "sha256": sha256_file(receipt_path),
            "schema": document["schema"],
            "semantic_sha256": expected_semantic,
        },
        "program_receipt_key": "bin/fsim-agondev-interop.bin",
        "deterministic_rebuild": True,
    }
    return build, observed_program


def hostfs_snapshot(root: Path) -> dict[str, object]:
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root.is_symlink():
        raise HeadlessQualificationError("temporary hostfs root is not a plain directory")
    entries: dict[str, object] = {}
    for path in sorted(root.iterdir()):
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise HeadlessQualificationError(
                f"temporary hostfs acquired a non-regular entry: {path.name}"
            )
        entries[path.name] = {
            "kind": "file",
            "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            "bytes": info.st_size,
            "sha256": sha256_file(path),
        }
    return {
        "root_mode": f"{stat.S_IMODE(root_info.st_mode):04o}",
        "entries": entries,
    }


def normalize_output(output: bytes) -> bytes:
    return output.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def validate_transcript(output: bytes) -> dict[str, object]:
    if not output:
        raise HeadlessQualificationError("emulator produced no output")
    if len(output) > MAX_OUTPUT_BYTES:
        raise HeadlessQualificationError("emulator output exceeded the 1 MiB bound")
    normalized = normalize_output(output)
    command = b"/ *" + STDIN
    passed = b"FSIM AGONDEV INTEROP PASS\n"
    failed = b"FSIM AGONDEV INTEROP FAIL"
    prompt = b"/ *"
    forbidden = (
        b"Invalid command",
        b"Could not find file",
        b"No SD card present",
    )
    if normalized.count(command) != 1:
        raise HeadlessQualificationError("expected exactly one MOS command echo")
    if normalized.count(passed) != 1:
        raise HeadlessQualificationError("expected exactly one interop PASS marker")
    if failed in normalized:
        raise HeadlessQualificationError("interop program emitted a FAIL marker")
    if normalized.count(prompt) != 2:
        raise HeadlessQualificationError("expected initial and returned MOS prompts")
    for marker in forbidden:
        if marker in normalized:
            raise HeadlessQualificationError(
                f"MOS reported a command/hostfs error: {marker.decode('ascii')}"
            )
    command_offset = normalized.find(command)
    pass_offset = normalized.find(passed)
    returned_prompt = normalized.find(prompt, pass_offset + len(passed))
    if not (0 <= command_offset < pass_offset < returned_prompt):
        raise HeadlessQualificationError("command, PASS, and returned prompt are unordered")
    tail = normalized[returned_prompt + len(prompt) :]
    if tail.strip(b"\x00\t\n\v\f "):
        raise HeadlessQualificationError("non-whitespace output followed returned MOS prompt")
    return {
        "normalized_bytes": len(normalized),
        "normalized_sha256": sha256_bytes(normalized),
        "normalization": "CRLF and CR to LF",
        "command_echo_count": 1,
        "pass_count": 1,
        "fail_count": 0,
        "prompt_count": 2,
        "offsets": {
            "command_echo": command_offset,
            "pass": pass_offset,
            "post_return_prompt": returned_prompt,
        },
        "post_prompt_tail_hex": tail.hex(),
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--build-receipt", type=Path, default=DEFAULT_BUILD_RECEIPT)
    parser.add_argument("--cli", type=Path, default=DEFAULT_CLI)
    parser.add_argument("--mos", type=Path, default=DEFAULT_MOS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--show-output", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        raise HeadlessQualificationError("timeout must be positive")
    build, program = validate_build_binding(args.build_receipt, args.program)
    runtime = load_runtime_contract()
    emulator_contract = runtime.get("emulator")
    mos_contract = runtime.get("mos")
    if not isinstance(emulator_contract, dict) or not isinstance(mos_contract, dict):
        raise HeadlessQualificationError("headless runtime provenance is malformed")
    cli = require_regular_file(args.cli, "Fab CLI emulator", executable=True)
    mos = require_regular_file(args.mos, "reference MOS")
    emulator = validate_input_pin(cli, emulator_contract, "Fab CLI emulator")
    mos_input = validate_input_pin(mos, mos_contract, "reference MOS")

    argv_template = [
        str(cli),
        "--mos",
        str(mos),
        "--sdcard",
        "<temporary-read-only-hostfs>",
        "--unlimited-cpu",
        "--zero",
    ]
    output = b""
    before: dict[str, object]
    after: dict[str, object]
    returncode: int
    with tempfile.TemporaryDirectory(prefix="fsim-agondev-headless-") as temporary:
        hostfs = Path(temporary) / "sd"
        hostfs.mkdir(mode=0o755)
        target = hostfs / PROGRAM_NAME
        target.write_bytes(Path(args.program).resolve().read_bytes())
        target.chmod(0o444)
        hostfs.chmod(0o555)
        before = hostfs_snapshot(hostfs)
        argv = list(argv_template)
        argv[4] = str(hostfs)
        try:
            completed = subprocess.run(
                argv,
                input=STDIN,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=args.timeout,
            )
            output = completed.stdout
            returncode = completed.returncode
            after = hostfs_snapshot(hostfs)
        except subprocess.TimeoutExpired as error:
            raise HeadlessQualificationError("headless emulator timed out") from error
        finally:
            hostfs.chmod(0o755)
            if target.exists() and not target.is_symlink():
                target.chmod(0o644)

    if returncode != 0:
        raise HeadlessQualificationError(f"headless emulator exited {returncode}")
    if before != after:
        raise HeadlessQualificationError("headless emulator changed its read-only hostfs")
    transcript_contract = validate_transcript(output)
    if sha256_file(cli) != emulator["sha256"] or sha256_file(mos) != mos_input["sha256"]:
        raise HeadlessQualificationError("headless runtime input changed during execution")
    if sha256_file(Path(args.program).resolve()) != program["sha256"]:
        raise HeadlessQualificationError("interop program changed during execution")

    output_root = args.output.resolve()
    transcript_path = output_root / "transcript.bin"
    atomic_write(transcript_path, output)
    transcript_contract.update(
        {
            "artifact": transcript_path.name,
            "bytes": len(output),
            "sha256": sha256_bytes(output),
        }
    )
    report: dict[str, object] = {
        "schema": "pingo-fsim-agondev-interop-headless-v1",
        "qualified": True,
        "build": build,
        "inputs": {
            "program": program,
            "qualifier": {
                "path": str(Path(__file__).resolve()),
                "bytes": Path(__file__).resolve().stat().st_size,
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "emulator": emulator,
            "mos": {**mos_input, "role": "stock-platform-reference"},
        },
        "invocation": {
            "argv": argv_template,
            "stdin_ascii": STDIN.decode("ascii"),
            "stdin_hex": STDIN.hex(),
            "timeout_seconds": args.timeout,
            "stderr": "merged-into-stdout",
        },
        "hostfs": {
            "temporary": True,
            "before": before,
            "after": after,
            "unchanged": True,
        },
        "process": {
            "returncode": returncode,
            "timed_out": False,
            "output_bytes": len(output),
        },
        "transcript": transcript_contract,
        "assertions": {
            "build_bound": True,
            "input_pins": True,
            "hostfs_unchanged": True,
            "command_executed": True,
            "probe_passed": True,
            "returned_to_mos": True,
        },
    }
    report["semantic_sha256"] = canonical_semantic_hash(report)
    report_path = output_root / "HEADLESS.json"
    atomic_write(
        report_path,
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    if args.show_output:
        print(normalize_output(output).decode("latin-1"), end="")
    print(f"Qualified headless interop target: {report_path}")
    print(f"Transcript: {transcript_path} ({sha256_bytes(output)})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HeadlessQualificationError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
