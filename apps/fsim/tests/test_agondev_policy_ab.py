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


class AgonDevPolicyABTests(unittest.TestCase):
    def test_group_wire_layout_and_bounded_contract_are_pinned(self) -> None:
        header = (EXPERIMENT / "include/interop.h").read_text(encoding="utf-8")
        bridge = (EXPERIMENT / "src/bridge.asm").read_text(encoding="utf-8")
        for contract in (
            "INTEROP_GROUP_RETIRING_OFFSET = 0",
            "INTEROP_GROUP_ENTERING_OFFSET = 1",
            "INTEROP_GROUP_PROCESSED_OFFSET = 2",
            "INTEROP_GROUP_BYTES = 3",
            "INTEROP_GROUP_MAX_COUNT = 8",
            "INTEROP_GROUP_MAX_SIDE = 14",
            "INTEROP_GROUP_NONE = 0xff",
            "sizeof(interop_group_record) == INTEROP_GROUP_BYTES",
        ):
            self.assertIn(contract, header)
        for contract in (
            ".equ interop_group_retiring_offset, 0",
            ".equ interop_group_entering_offset, 1",
            ".equ interop_group_processed_offset, 2",
            ".equ interop_group_bytes, 3",
        ):
            self.assertIn(contract, bridge)

    def test_target_vectors_cover_policy_order_and_corrupt_callback(self) -> None:
        source = (EXPERIMENT / "src/main.c").read_text(encoding="utf-8")
        for case in (
            "policy_ab_none",
            "policy_ab_processed",
            "policy_ab_infeasible",
            "policy_ab_score",
            "policy_ab_enter_tie",
            "policy_ab_retiring",
            "policy_ab_source_tie",
        ):
            self.assertIn(case, source)
        self.assertIn("asm_policy_round_trip(NULL)", source)
        self.assertIn("state.cookie_le[2] = 0", source)
        self.assertIn("c_selected != asm_selected", source)

    @unittest.skipUnless(
        (builder.DEFAULT_AGONDEV_ROOT / "release/bin/ez80-none-elf-clang").is_file(),
        "canonical AgonDev checkout is unavailable",
    )
    def test_built_selectors_have_the_real_abi_and_no_new_helpers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fsim-agondev-policy-ab-") as temporary:
            output = Path(temporary) / "output"
            completed = subprocess.run(
                (
                    str(ROOT / ".venv/bin/python"),
                    str(BUILDER_PATH),
                    "--output",
                    str(output),
                ),
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)

            project = output / "project"
            receipt = json.loads((output / "BUILD.json").read_text(encoding="utf-8"))
            inspection = (project / "inspect/main.s").read_text(encoding="utf-8")
            toolbin = builder.DEFAULT_AGONDEV_ROOT / "release/bin"
            bridge_disassembly = subprocess.run(
                (str(toolbin / "ez80-none-elf-objdump"), "-dr", str(project / "obj/bridge.o")),
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            main_symbols = subprocess.run(
                (str(toolbin / "ez80-none-elf-nm"), str(project / "obj/main.o")),
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            bridge_symbols = subprocess.run(
                (str(toolbin / "ez80-none-elf-nm"), str(project / "obj/bridge.o")),
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout

        self.assertRegex(main_symbols, r"(?m)^\s*[0-9a-f]+\s+T\s+_interop_select_feasible_group$")
        self.assertRegex(main_symbols, r"(?m)^\s+U\s+_asm_select_feasible_group$")
        self.assertRegex(bridge_symbols, r"(?m)^\s*[0-9a-f]+\s+T\s+_asm_select_feasible_group$")

        asm_selector = re.search(
            r"<_asm_select_feasible_group>:(.*?)(?=\n[0-9a-f]+ <_asm_return_u16>)",
            bridge_disassembly,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(asm_selector, bridge_disassembly)
        asm_body = asm_selector.group(1)
        self.assertIn("ld iy,(ix+6)", asm_body)
        self.assertIn("ld a,(ix+9)", asm_body)
        self.assertIn("ld a,(ix+12)", asm_body)
        self.assertNotRegex(asm_body, r"\bcall\b")

        c_selector = re.search(
            r"_interop_select_feasible_group:(.*?)\.size\s+_interop_select_feasible_group",
            inspection,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(c_selector, inspection)
        selector_calls = set(re.findall(r"\bcall\s+([^\s]+)", c_selector.group(1)))
        self.assertLessEqual(selector_calls, {"__frameset", "__frameset0"})
        self.assertIn("call\t_interop_select_feasible_group", inspection)
        self.assertIn("call\t_asm_select_feasible_group", inspection)

        expected_undefined = {
            "__frameset",
            "__frameset0",
            "_asm_policy_round_trip",
            "_asm_return_u16",
            "_asm_return_u24",
            "_asm_select_feasible_group",
            "_asm_stamp_state",
            "_putch",
        }
        self.assertEqual(
            set(receipt["verification"]["undefined_policy_symbols"]),
            expected_undefined,
        )
        self.assertEqual(receipt["verification"]["forbidden_arithmetic_helpers"], [])


if __name__ == "__main__":
    unittest.main()
