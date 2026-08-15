from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT = ROOT / "experiments/agondev-interop"
BUILDER_PATH = ROOT / "scripts/build_agondev_interop.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_agondev_interop", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()


class AgonDevInteropTests(unittest.TestCase):
    def run_builder(self, output: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                str(ROOT / ".venv/bin/python"),
                str(BUILDER_PATH),
                "--output",
                str(output),
                *arguments,
            ),
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_tracked_experiment_has_no_discoverable_cmake_or_outputs(self) -> None:
        self.assertFalse((EXPERIMENT / "CMakeLists.txt").exists())
        self.assertFalse((EXPERIMENT / "CMakePresets.json").exists())
        self.assertFalse((EXPERIMENT / "Makefile").exists())
        self.assertFalse((EXPERIMENT / "obj").exists())
        self.assertFalse((EXPERIMENT / "bin").exists())
        self.assertTrue((EXPERIMENT / "CMakeLists.txt.in").is_file())
        self.assertTrue((EXPERIMENT / "CMakePresets.json.in").is_file())
        for path in EXPERIMENT.rglob("*"):
            self.assertFalse(path.is_symlink(), path)

    def test_durable_contract_and_todo_share_one_queue(self) -> None:
        todo = (ROOT / "docs/todo.md").read_text(encoding="utf-8")
        design = (ROOT / "docs/agondev-interop-experiment.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**E1 — AgonDev C/assembly interoperability experiment:**", todo)
        self.assertIn("not a second task list", design)
        self.assertIn("Assembly continues to own", design)
        self.assertIn("fixed-point", design)

    def test_shared_state_and_stack_slot_contracts_are_explicit(self) -> None:
        header = (EXPERIMENT / "include/interop.h").read_text(encoding="utf-8")
        bridge = (EXPERIMENT / "src/bridge.asm").read_text(encoding="utf-8")
        for assertion in (
            "sizeof(int) == 3",
            "sizeof(uint24_t) == 3",
            "sizeof(void *) == 3",
            "sizeof(size_t) == 3",
            "INTEROP_ASM_STAMP_OFFSET = 10",
            "INTEROP_STATE_BYTES = 12",
        ):
            self.assertIn(assertion, header)
        self.assertIn(".equ interop_asm_stamp_offset, 10", bridge)
        self.assertGreaterEqual(bridge.count("ld hl,(ix+6)"), 2)
        self.assertIn("ld a,(ix+9)", bridge)
        self.assertIn("call _interop_choose_action", bridge)
        self.assertRegex(bridge, re.compile(r"call _interop_choose_action\n\s+pop hl"))
        self.assertIn("ld hl,0x00beef", bridge)
        self.assertIn("ld hl,0xabcdef", bridge)

    def test_policy_source_defers_numerics_to_assembly(self) -> None:
        source = (EXPERIMENT / "src/main.c").read_text(encoding="utf-8")
        self.assertNotRegex(source, re.compile(r"\b(?:float|double)\b"))
        for operator in ("*=", "/=", "%="):
            self.assertNotIn(operator, source)
        make_template = (EXPERIMENT / "AgonDev.mk.in").read_text(encoding="utf-8")
        self.assertIn("-ffreestanding", make_template)
        self.assertIn("-fno-builtin", make_template)

    @unittest.skipUnless(shutil.which("cmake"), "cmake is unavailable")
    def test_generated_default_cmake_configure_is_inert(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-cmake-") as temporary:
            output = Path(temporary) / "output"
            builder.stage_project(output, Path(temporary) / "missing-agondev")
            source = output / "cmake-source"
            build = output / "cmake-test"
            completed = subprocess.run(
                ("cmake", "-S", str(source), "-B", str(build)),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("ordinary configure is inert", completed.stdout)
            cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
            self.assertIn("FSIM_ENABLE_AGONDEV_INTEROP:BOOL=OFF", cache)

    @unittest.skipUnless(shutil.which("cmake"), "cmake is unavailable")
    def test_generated_explicit_cmake_configure_and_build_use_pinned_toolchain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-cmake-") as temporary:
            output = Path(temporary) / "output"
            builder.stage_project(output, builder.DEFAULT_AGONDEV_ROOT)
            source = output / "cmake-source"
            cmake_text = (source / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn(str(ROOT / ".venv/bin/python"), cmake_text)
            completed = subprocess.run(
                (
                    "cmake",
                    "-S",
                    str(source),
                    "-B",
                    str(output / "cmake-explicit"),
                    "-DFSIM_ENABLE_AGONDEV_INTEROP=ON",
                    f"-DAGONDEV_ROOT={builder.DEFAULT_AGONDEV_ROOT}",
                ),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            built = subprocess.run(
                ("cmake", "--build", str(output / "cmake-explicit"),
                 "--target", "agondev-interop"),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(built.returncode, 0, built.stdout)
            self.assertIn("Qualified AgonDev interop probe", built.stdout)
            receipt = json.loads((output / builder.BUILD_RECEIPT).read_text())
            self.assertEqual(receipt["status"], "qualified")

    def test_staged_sources_and_generated_build_files_are_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-stage-") as temporary:
            output = Path(temporary) / "output"
            builder.stage_project(output, builder.DEFAULT_AGONDEV_ROOT)
            builder.verify_staged_files(output, builder.DEFAULT_AGONDEV_ROOT)
            for path in builder.expected_staged_files(
                output, builder.DEFAULT_AGONDEV_ROOT
            ):
                original = path.read_bytes()
                path.write_bytes(original + b"\nAUDIT-TAMPER\n")
                with self.assertRaisesRegex(
                    builder.InteropBuildError, "Staged input differs"
                ):
                    builder.verify_staged_files(
                        output, builder.DEFAULT_AGONDEV_ROOT
                    )
                path.write_bytes(original)
            builder.verify_staged_files(output, builder.DEFAULT_AGONDEV_ROOT)

    @unittest.skipUnless(
        (builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-clang").is_file(),
        "canonical AgonDev checkout is unavailable",
    )
    def test_skip_determinism_mints_only_unqualified_local_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-build-") as temporary:
            output = Path(temporary) / "output"
            completed = self.run_builder(output, "--skip-determinism")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertNotIn("Qualified AgonDev", completed.stdout)
            self.assertIn("Unqualified local", completed.stdout)
            self.assertFalse((output / builder.BUILD_RECEIPT).exists())
            receipt = json.loads(
                (output / builder.LOCAL_BUILD_RECEIPT).read_text(encoding="utf-8")
            )
        self.assertEqual(receipt["schema"], builder.LOCAL_BUILD_SCHEMA)
        self.assertEqual(receipt["status"], "unqualified-local-build")
        verification = receipt["verification"]
        self.assertFalse(verification["deterministic_rebuild"])
        self.assertEqual(verification["entry_jump_hex"], "c3450004")
        self.assertEqual(verification["mos_header_hex"], "4d4f530001")
        self.assertEqual(verification["forbidden_arithmetic_helpers"], [])
        self.assertTrue(verification["elf_binary_matches_noname"])
        self.assertIn("bin/fsim-agondev-interop.bin", verification["outputs"])

    @unittest.skipUnless(
        (builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-clang").is_file(),
        "canonical AgonDev checkout is unavailable",
    )
    def test_deterministic_receipt_verify_only_is_byte_preserving(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-build-") as temporary:
            output = Path(temporary) / "output"
            built = self.run_builder(output)
            self.assertEqual(built.returncode, 0, built.stdout)
            receipt_path = output / builder.BUILD_RECEIPT
            original = receipt_path.read_bytes()
            receipt = json.loads(original)
            self.assertEqual(receipt["schema"], builder.BUILD_SCHEMA)
            self.assertEqual(receipt["status"], "qualified")
            self.assertTrue(receipt["verification"]["deterministic_rebuild"])
            self.assertTrue(receipt["verification"]["elf_binary_matches_noname"])
            self.assertEqual(
                set(receipt["verification"]["external_policy_symbols"]),
                {"__frameset", "__frameset0", "_putch"},
            )
            self.assertEqual(
                builder.PINNED_POLICY_EXTERNAL_UNDEFINED,
                {"__frameset", "__frameset0", "_putch"},
            )
            self.assertEqual(
                receipt["abi_reference"]["git_commit"],
                builder.load_provenance()["abi_reference"]["git_commit"],
            )
            self.assertEqual(
                receipt["toolchain"]["files"][
                    "release/bin/ez80-none-elf-objcopy"
                ]["sha256"],
                builder.PINNED_OBJCOPY_SHA256,
            )

            verified = self.run_builder(output, "--verify-only")
            self.assertEqual(verified.returncode, 0, verified.stdout)
            self.assertIn("Verified authoritative", verified.stdout)
            self.assertEqual(receipt_path.read_bytes(), original)
            self.assertFalse((output / builder.LOCAL_BUILD_RECEIPT).exists())

    @unittest.skipUnless(
        (builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-clang").is_file(),
        "canonical AgonDev checkout is unavailable",
    )
    def test_verify_only_rejects_staged_output_and_receipt_downgrades(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-build-") as temporary:
            output = Path(temporary) / "output"
            built = self.run_builder(output)
            self.assertEqual(built.returncode, 0, built.stdout)
            receipt_path = output / builder.BUILD_RECEIPT
            authoritative = receipt_path.read_bytes()

            staged_main = output / "project/src/main.c"
            staged_main.write_bytes(staged_main.read_bytes() + b"\n/* stale */\n")
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("Staged input differs", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), authoritative)
            staged_main.write_bytes((EXPERIMENT / "src/main.c").read_bytes())

            binary = output / "project/bin/fsim-agondev-interop.bin"
            binary_bytes = binary.read_bytes()
            binary.write_bytes(binary_bytes[:-1] + bytes((binary_bytes[-1] ^ 1,)))
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("no longer matches verified outputs", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), authoritative)
            binary.write_bytes(binary_bytes)

            noname = output / "project/bin/fsim-agondev-interop.noname.bin"
            noname_bytes = noname.read_bytes()
            noname.write_bytes(noname_bytes[:-1] + bytes((noname_bytes[-1] ^ 1,)))
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("ELF load image differs", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), authoritative)
            noname.write_bytes(noname_bytes)

            semantic_tamper = json.loads(authoritative)
            semantic_tamper["semantic_sha256"] = "0" * 64
            receipt_path.write_text(
                json.dumps(semantic_tamper, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            semantic_tamper_bytes = receipt_path.read_bytes()
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("semantic hash changed", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), semantic_tamper_bytes)

            input_tamper = json.loads(authoritative)
            first_input = min(input_tamper["inputs"])
            input_tamper["inputs"][first_input]["sha256"] = "0" * 64
            del input_tamper["semantic_sha256"]
            builder.add_semantic_hash(input_tamper)
            receipt_path.write_text(
                json.dumps(input_tamper, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            input_tamper_bytes = receipt_path.read_bytes()
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("no longer matches tracked inputs", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), input_tamper_bytes)

            downgraded = json.loads(authoritative)
            downgraded["verification"]["deterministic_rebuild"] = False
            del downgraded["semantic_sha256"]
            builder.add_semantic_hash(downgraded)
            receipt_path.write_text(
                json.dumps(downgraded, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            downgraded_bytes = receipt_path.read_bytes()
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn("no longer matches verified outputs", rejected.stdout)
            self.assertEqual(receipt_path.read_bytes(), downgraded_bytes)


if __name__ == "__main__":
    unittest.main()
