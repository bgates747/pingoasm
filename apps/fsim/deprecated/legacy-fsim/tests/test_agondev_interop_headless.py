from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
QUALIFIER_PATH = ROOT / "scripts/qualify_agondev_interop_headless.py"


def load_qualifier():
    spec = importlib.util.spec_from_file_location(
        "qualify_agondev_interop_headless", QUALIFIER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qualifier = load_qualifier()


def transcript(*, fail: bool = False, returned: bool = True) -> bytes:
    status = b"FAIL" if fail else b"PASS"
    tail = b"/ *" if returned else b""
    return (
        b"Tom's Fake VDP\r\nAgon Platform MOS\r\n"
        b"/ *fsim-agondev-interop.bin\r\n"
        b"FSIM AGONDEV INTEROP "
        + status
        + b"\r\n"
        + tail
    )


class AgonDevHeadlessTests(unittest.TestCase):
    def test_transcript_proves_pass_and_post_return_prompt(self) -> None:
        evidence = qualifier.validate_transcript(transcript())
        self.assertEqual(evidence["command_echo_count"], 1)
        self.assertEqual(evidence["pass_count"], 1)
        self.assertEqual(evidence["prompt_count"], 2)
        self.assertLess(
            evidence["offsets"]["pass"], evidence["offsets"]["post_return_prompt"]
        )

    def test_transcript_rejects_failure_or_missing_return(self) -> None:
        for payload in (transcript(fail=True), transcript(returned=False)):
            with self.subTest(payload=payload):
                with self.assertRaises(qualifier.HeadlessQualificationError):
                    qualifier.validate_transcript(payload)

    def test_transcript_rejects_duplicates_errors_and_post_prompt_noise(self) -> None:
        cases = (
            transcript() + b"FSIM AGONDEV INTEROP PASS\n",
            transcript() + b"Invalid command\n",
            transcript() + b"RUN AGAIN",
            transcript().replace(b"/ *fsim", b"/ */ *fsim"),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(qualifier.HeadlessQualificationError):
                    qualifier.validate_transcript(payload)

    def test_build_binding_rejects_program_and_semantic_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-headless-binding-") as temporary:
            root = Path(temporary)
            program = root / "probe.bin"
            program.write_bytes(b"probe")
            receipt = {
                "schema": "pingo-fsim-agondev-interop-build-v1",
                "status": "qualified",
                "inputs": {},
                "verification": {
                    "deterministic_rebuild": True,
                    "entry_jump_hex": "c3450004",
                    "mos_header_hex": "4d4f530001",
                    "outputs": {
                        "bin/fsim-agondev-interop.bin": {
                            "bytes": 5,
                            "sha256": qualifier.sha256_file(program),
                        }
                    },
                },
            }
            receipt["semantic_sha256"] = qualifier.canonical_semantic_hash(receipt)
            receipt_path = root / "BUILD.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            qualifier.validate_build_binding(receipt_path, program)

            program.write_bytes(b"other")
            with self.assertRaises(qualifier.HeadlessQualificationError):
                qualifier.validate_build_binding(receipt_path, program)
            program.write_bytes(b"probe")
            document = json.loads(receipt_path.read_text(encoding="utf-8"))
            document["verification"]["entry_jump_hex"] = "00000000"
            receipt_path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(qualifier.HeadlessQualificationError):
                qualifier.validate_build_binding(receipt_path, program)

    def test_hostfs_snapshot_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-headless-hostfs-") as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_bytes(b"x")
            (root / "link").symlink_to(target)
            with self.assertRaises(qualifier.HeadlessQualificationError):
                qualifier.hostfs_snapshot(root)


if __name__ == "__main__":
    unittest.main()
