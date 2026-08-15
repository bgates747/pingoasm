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
EXPERIMENT = ROOT / "experiments/agondev-regular-policy"
BUILDER_PATH = ROOT / "scripts/build_agondev_regular_policy.py"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_agondev_regular_policy", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()


class AgonDevRegularPolicyTests(unittest.TestCase):
    def run_builder(
        self, output: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
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

    def test_tracked_experiment_is_source_only_and_isolated(self) -> None:
        expected = {
            "PROVENANCE.json",
            "include/regular_policy.h",
            "linker.ld",
            "src/selector.c",
        }
        actual = {
            path.relative_to(EXPERIMENT).as_posix()
            for path in EXPERIMENT.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        self.assertEqual(actual, expected)
        for path in EXPERIMENT.rglob("*"):
            self.assertFalse(path.is_symlink(), path)
        for forbidden in (
            "CMakeLists.txt",
            "CMakePresets.json",
            "Makefile",
            "obj",
            "bin",
            builder.MODULE_FILENAME,
        ):
            self.assertFalse((EXPERIMENT / forbidden).exists())

    def test_descriptor_and_entry_contracts_are_explicit(self) -> None:
        header = (EXPERIMENT / "include/regular_policy.h").read_text(
            encoding="utf-8"
        )
        source = (EXPERIMENT / "src/selector.c").read_text(encoding="utf-8")
        linker = (EXPERIMENT / "linker.ld").read_text(encoding="utf-8")
        for contract in (
            "FSIM_POLICY_DESCRIPTOR_RETIRING_OFFSET = 0",
            "FSIM_POLICY_DESCRIPTOR_ENTERING_OFFSET = 1",
            "FSIM_POLICY_DESCRIPTOR_SOURCE_INDEX_OFFSET = 2",
            "FSIM_POLICY_DESCRIPTOR_BYTES = 3",
            "FSIM_POLICY_MAX_DESCRIPTORS = 38",
            "FSIM_POLICY_MAX_SIDE = 14",
            "FSIM_POLICY_INVALID = 0xfe",
            "FSIM_POLICY_NO_SELECTION = 0xff",
            "sizeof(int) == 3",
            "sizeof(void *) == 3",
        ):
            self.assertIn(contract, header)
        self.assertIn('section(".text.entry")', source)
        self.assertIn("source_index >= FSIM_POLICY_MAX_DESCRIPTORS", source)
        self.assertIn("source_index <= previous_source", source)
        self.assertIn("return FSIM_POLICY_INVALID", source)
        self.assertIn("score > selected_score", source)
        self.assertIn("entering < selected_entering", source)
        self.assertIn("retiring > selected_retiring", source)
        self.assertIn("source_index < selected_source", source)
        for contract in (
            'ENTRY(_fsim_regular_policy_select)',
            "ORIGIN = 0x070000",
            "LENGTH = 0x010000",
            "LONG(0x00070020)",
            "BYTE(38)",
            "BYTE(14)",
            "BYTE(0xff)",
            "BYTE(0xfe)",
            "_fsim_regular_policy_select == 0x070020",
            "SIZEOF(.forbidden) == 0",
            "__fsim_regular_policy_image_end < 0x080000",
        ):
            self.assertIn(contract, linker)

    def test_policy_source_has_no_runtime_or_numeric_dependency(self) -> None:
        source = (EXPERIMENT / "src/selector.c").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^#include\s+(.+)$", source, re.MULTILINE), [
            '"regular_policy.h"'
        ])
        self.assertNotRegex(source, re.compile(r"\b(?:float|double|int32_t)\b"))
        for token in ("putch(", "mos_", "vdp_", "malloc(", "printf("):
            self.assertNotIn(token, source.lower())
        self.assertIn("-ffreestanding", builder.COMPILER_FLAGS)
        self.assertIn("-fno-builtin", builder.COMPILER_FLAGS)

    def test_frame_helper_contract_uses_archive_not_vendored_source(self) -> None:
        provenance = json.loads(
            (EXPERIMENT / "PROVENANCE.json").read_text(encoding="utf-8")
        )
        toolchain = provenance["toolchain"]
        self.assertNotIn("mirrored_sources", toolchain)
        self.assertEqual(
            toolchain["frame_helper"],
            {
                "archive": "release/lib/libagon.a",
                "member": "frameset.o",
                "symbol": "__frameset",
            },
        )
        self.assertFalse((EXPERIMENT / "src/frameset.src").exists())
        self.assertNotIn(
            EXPERIMENT / "src/frameset.src", builder.TRACKED_INPUTS
        )

    def test_local_agondev_input_has_explicit_unknown_license_status(self) -> None:
        provenance = json.loads(
            (EXPERIMENT / "PROVENANCE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provenance["licensing"], builder.LICENSING_CONTRACT)
        self.assertEqual(
            provenance["licensing"]["distribution"],
            "local-build-input-only-not-redistributed",
        )
        self.assertEqual(provenance["licensing"]["present"], [])

    @unittest.skipUnless(
        (
            builder.DEFAULT_AGONDEV_ROOT
            / builder.FRAME_HELPER_ARCHIVE
        ).is_file()
        and (
            builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-nm"
        ).is_file(),
        "pinned AgonDev frame-helper archive is unavailable",
    )
    def test_frame_helper_comes_from_exact_pinned_agondev_archive(self) -> None:
        provenance = json.loads(
            (EXPERIMENT / "PROVENANCE.json").read_text(encoding="utf-8")
        )
        toolchain = provenance["toolchain"]
        archive = builder.DEFAULT_AGONDEV_ROOT / builder.FRAME_HELPER_ARCHIVE
        self.assertEqual(
            builder.sha256_file(archive),
            toolchain["files"][builder.FRAME_HELPER_ARCHIVE.as_posix()],
        )
        nm = builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-nm"
        archive_nm = builder.run((nm, "-A", "--defined-only", archive))
        self.assertEqual(
            builder.archive_symbol_members(archive_nm, archive, "__frameset"),
            ["frameset.o"],
        )

    def test_reference_selector_matches_accepted_lexicographic_order(self) -> None:
        none = builder.NO_SELECTION
        invalid = builder.INVALID
        vectors = (
            ([], 4, none),
            ([(14, 5, 0), (3, 2, 1)], 2, 1),
            ([(5, 4, 0), (4, 2, 1)], 4, 1),
            ([(6, 4, 0), (4, 2, 1)], 4, 1),
            ([(3, 2, 0), (4, 2, 1)], 2, 1),
            ([(4, 2, 3), (4, 2, 7)], 2, 3),
            ([(4, 2, 7), (4, 2, 3)], 2, invalid),
            ([(4, 2, 3), (4, 2, 3)], 2, invalid),
            ([(15, 0, 0), (4, 2, 1)], 2, invalid),
            ([(4, 15, 0), (4, 2, 1)], 15, invalid),
            ([(4, 2, 38), (4, 2, 1)], 2, invalid),
        )
        for descriptors, free_slots, expected in vectors:
            with self.subTest(descriptors=descriptors, free_slots=free_slots):
                self.assertEqual(
                    builder.select_reference(descriptors, free_slots), expected
                )

        # Exhaust every legal two-record count pair.  The independent key is
        # the accepted shrink/enter/retire/source order, not the implementation
        # score expression.
        for free_slots in range(builder.MAX_SIDE + 1):
            for retiring_a in range(builder.MAX_SIDE + 1):
                for entering_a in range(builder.MAX_SIDE + 1):
                    for retiring_b in range(builder.MAX_SIDE + 1):
                        for entering_b in range(builder.MAX_SIDE + 1):
                            descriptors = (
                                (retiring_a, entering_a, 0),
                                (retiring_b, entering_b, 1),
                            )
                            feasible = [
                                descriptor
                                for descriptor in descriptors
                                if descriptor[1] <= free_slots
                            ]
                            if not feasible:
                                expected = none
                            else:
                                expected = max(
                                    feasible,
                                    key=lambda item: (
                                        item[0] - item[1],
                                        -item[1],
                                        item[0],
                                        -item[2],
                                    ),
                                )[2]
                            self.assertEqual(
                                builder.select_reference(descriptors, free_slots),
                                expected,
                            )

    def test_reference_selector_enforces_descriptor_count_bound(self) -> None:
        descriptors = [(4, 2, index) for index in range(builder.MAX_DESCRIPTORS)]
        self.assertEqual(builder.select_reference(descriptors, 2), 0)
        self.assertEqual(
            builder.select_reference(descriptors + [(4, 2, 0)], 2),
            builder.INVALID,
        )
        self.assertEqual(builder.select_reference(descriptors, -1), builder.INVALID)
        self.assertEqual(
            builder.select_reference(descriptors, 0x100), builder.INVALID
        )

    def test_header_encoding_is_exact_and_little_endian(self) -> None:
        header = builder.expected_header(0x0108)
        self.assertEqual(len(header), builder.HEADER_BYTES)
        self.assertEqual(header[:8], b"FSIMCPOL")
        self.assertEqual(header[8:16], bytes((1, 1, 32, 3, 38, 14, 255, 254)))
        self.assertEqual(header[16:20], bytes((0x20, 0x00, 0x07, 0x00)))
        self.assertEqual(header[20:24], bytes((0x08, 0x01, 0x00, 0x00)))
        self.assertEqual(header[24:28], bytes((0x00, 0x00, 0x07, 0x00)))
        self.assertEqual(header[28:32], bytes((0x00, 0x00, 0x08, 0x00)))

    @unittest.skipUnless(
        (ROOT / ".venv/bin/python").is_file()
        and (builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-clang").is_file()
        and (
            builder.DEFAULT_AGONDEV_ROOT / builder.FRAME_HELPER_ARCHIVE
        ).is_file(),
        "pinned FSIM Python/AgonDev toolchain is unavailable",
    )
    def test_deterministic_build_and_receipt_revalidation(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="fsim-agondev-regular-policy-test-"
        ) as temporary:
            output = Path(temporary) / "output"
            completed = self.run_builder(output)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("Qualified fixed AgonDev regular-policy module", completed.stdout)

            receipt = json.loads((output / builder.BUILD_RECEIPT).read_text())
            self.assertEqual(receipt["status"], "qualified")
            self.assertEqual(receipt["module"]["filename"], "CPOLICY.BIN")
            self.assertEqual(receipt["module"]["load_address"], 0x070000)
            self.assertEqual(receipt["module"]["entry_address"], 0x070020)
            self.assertEqual(receipt["module"]["image_bytes"], 301)
            self.assertEqual(
                receipt["module"]["sha256"],
                "8c73781f71e9b335408659047047df6fb760f43bea0e67fc0580b7da32b78c71",
            )
            self.assertRegex(receipt["module"]["crc32"], r"^[0-9a-f]{8}$")
            self.assertLess(
                receipt["module"]["load_address"]
                + receipt["module"]["image_bytes"],
                receipt["module"]["limit_exclusive"],
            )
            verification = receipt["verification"]
            self.assertTrue(verification["deterministic_rebuild"])
            self.assertTrue(verification["elf_binary_matches_raw"])
            self.assertEqual(verification["selector_entry"], 0x070020)
            self.assertEqual(
                verification["selector_undefined_symbols"], ["__frameset"]
            )
            self.assertEqual(verification["frame_helper_exports"], ["__frameset"])
            self.assertEqual(
                verification["frame_helper_archive"], "toolchain/libagon.a"
            )
            self.assertEqual(verification["frame_helper_member"], "frameset.o")
            self.assertEqual(verification["final_undefined_symbols"], [])
            self.assertEqual(verification["forbidden_runtime_symbols"], [])
            self.assertEqual(verification["allocated_elf_sections"], {".policy": "AX"})
            self.assertEqual(verification["header"]["invalid"], 0xFE)
            self.assertEqual(verification["image_crc32"], receipt["module"]["crc32"])
            self.assertNotIn(
                "project/obj/frameset.o", verification["outputs"]
            )
            self.assertFalse((output / "project/src/frameset.src").exists())
            self.assertFalse((output / "project/obj/frameset.o").exists())

            module = output / f"project/bin/{builder.MODULE_FILENAME}"
            self.assertEqual(
                module.read_bytes()[: builder.HEADER_BYTES],
                builder.expected_header(module.stat().st_size),
            )
            generated_include = (output / builder.IMPORT_FILENAME).read_text()
            self.assertIn("fsim_regular_policy_load_address: equ 070000h", generated_include)
            self.assertIn("fsim_regular_policy_entry_address: equ 070020h", generated_include)
            self.assertIn(
                f"fsim_regular_policy_image_bytes: equ {module.stat().st_size}",
                generated_include,
            )
            self.assertIn(receipt["module"]["sha256"], generated_include)
            self.assertIn(receipt["module"]["crc32"], generated_include.lower())
            self.assertIn("fsim_regular_policy_invalid: equ 0FEh", generated_include)

            verified = self.run_builder(output, "--verify-only")
            self.assertEqual(verified.returncode, 0, verified.stdout)
            self.assertIn("Verified fixed AgonDev regular-policy module", verified.stdout)

            link_map = output / f"project/bin/{builder.MAP_FILENAME}"
            link_map.write_text(
                link_map.read_text(encoding="utf-8").replace(
                    "toolchain/libagon.a(frameset.o)",
                    "toolchain/libagon.a(frameset0.o)",
                    1,
                ),
                encoding="utf-8",
            )
            rejected = self.run_builder(output, "--verify-only")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
            self.assertIn(
                "Link extracted unexpected frame-helper archive members",
                rejected.stdout,
            )

    def test_stage_only_uses_exact_tracked_sources(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="fsim-agondev-regular-policy-stage-"
        ) as temporary:
            output = Path(temporary) / "output"
            retired_source = output / "project/src/frameset.src"
            retired_object = output / "project/obj/frameset.o"
            retired_source.parent.mkdir(parents=True)
            retired_object.parent.mkdir(parents=True)
            retired_source.write_text("retired", encoding="utf-8")
            retired_object.write_bytes(b"retired")
            builder.stage_project(output, builder.DEFAULT_AGONDEV_ROOT)
            builder.verify_staged_files(output, builder.DEFAULT_AGONDEV_ROOT)
            self.assertEqual(
                (output / "project/src/selector.c").read_bytes(),
                (EXPERIMENT / "src/selector.c").read_bytes(),
            )
            staged_archive = output / "project/toolchain/libagon.a"
            pinned_archive = (
                builder.DEFAULT_AGONDEV_ROOT / builder.FRAME_HELPER_ARCHIVE
            )
            self.assertEqual(staged_archive.read_bytes(), pinned_archive.read_bytes())
            self.assertFalse(retired_source.exists())
            self.assertFalse(retired_object.exists())
            self.assertFalse((output / "project/bin").exists())

            staged_archive.write_bytes(staged_archive.read_bytes() + b"tampered")
            with self.assertRaisesRegex(
                builder.RegularPolicyBuildError,
                "Staged input differs from pinned source",
            ):
                builder.verify_staged_files(output, builder.DEFAULT_AGONDEV_ROOT)


if __name__ == "__main__":
    unittest.main()
