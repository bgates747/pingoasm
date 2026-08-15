from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "scripts/build_regular_lod_c_policy_survey.py"
ACCEPTED_SOURCE = (
    ROOT / "fixtures/terrain-manager-survey/src/terrain-manager-regular-lod-survey.asm"
)
SIBLING_SOURCE = ACCEPTED_SOURCE.with_name(
    "terrain-manager-regular-lod-c-policy-survey.asm"
)
PROVIDER = ACCEPTED_SOURCE.with_name("terrain-manager-regular-lod-provider.inc")
CLIENT = ACCEPTED_SOURCE.with_name("terrain-manager-regular-lod-policy-client.inc")


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_regular_lod_c_policy_survey", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()


class RegularLodCPolicySourceTests(unittest.TestCase):
    def test_sibling_is_a_controlled_copy_and_control_binary_is_pinned(self) -> None:
        builder.validate_source_copy()
        self.assertEqual(
            builder.rebuild_accepted_control(),
            builder.ACCEPTED_PROGRAM_SHA256,
        )
        self.assertEqual(
            builder.canonicalize_sibling_source(
                SIBLING_SOURCE.read_text(encoding="ascii")
            ).rstrip("\n"),
            ACCEPTED_SOURCE.read_text(encoding="ascii").rstrip("\n"),
        )

    def test_provider_hooks_are_unconditional_macros_not_nested_conditions(self) -> None:
        provider = PROVIDER.read_text(encoding="ascii")
        self.assertIn("REGULAR_POLICY_BEGIN_TRANSITION", provider)
        self.assertIn("REGULAR_POLICY_SELECT_DISPATCH", provider)
        selector = provider.split(
            "regular_transition_select_feasible_group:", 1
        )[1].split("regular_transition_select_feasible_group_asm:", 1)[0]
        self.assertEqual(selector.strip(), "REGULAR_POLICY_SELECT_DISPATCH")
        begin = provider.split("terrain_provider_begin_transition:", 1)[1].split(
            "terrain_provider_transition_busy:", 1
        )[0]
        self.assertIn("REGULAR_POLICY_BEGIN_TRANSITION", begin)
        self.assertNotIn(".if terrain_manager_regular_policy_client", provider)

        client = CLIENT.read_text(encoding="ascii")
        self.assertNotRegex(client, r"(?m)^\s*\.(?:if|else|endif)\b")
        for mode in builder.MODE_PROFILES.values():
            mode_source = ACCEPTED_SOURCE.with_name(str(mode["include"])).read_text(
                encoding="ascii"
            )
            self.assertNotRegex(mode_source, r"(?m)^\s*\.(?:if|else|endif)\b")

    def test_module_is_loaded_before_resources_and_fails_soft(self) -> None:
        source = SIBLING_SOURCE.read_text(encoding="ascii")
        main = source.split("main:", 1)[1].split("@loop:", 1)[0]
        self.assertLess(
            main.index("call regular_policy_initialize"),
            main.index("call load_scene_resources"),
        )
        client = CLIENT.read_text(encoding="ascii")
        initialize = client.split("regular_policy_initialize:", 1)[1].split(
            "regular_policy_validate_crc32:", 1
        )[0]
        for contract in (
            "ld hl,fsim_regular_policy_load_address",
            "ld bc,fsim_regular_policy_image_bytes",
            "MOSCALL mos_load",
            "jr nc,@mos_no_carry",
            "ld de,regular_policy_expected_header",
            "ld b,fsim_regular_policy_header_bytes",
            "call regular_policy_validate_crc32",
        ):
            self.assertIn(contract, initialize)
        self.assertIn("db fsim_regular_policy_invalid", client)
        self.assertIn('db "CPOLICY.BIN",0', client)

    def test_descriptor_filter_is_cached_once_and_bounded_before_write(self) -> None:
        client = CLIENT.read_text(encoding="ascii")
        cache = client.split("regular_policy_build_all_descriptors:", 1)[1].split(
            "regular_policy_select_dual_strict:", 1
        )[0]
        self.assertIn("call regular_transition_old_slot_pointer", cache)
        self.assertIn("call regular_transition_target_owner_present", cache)
        append = cache.split("@append:", 1)[1].split("@advance:", 1)[0]
        self.assertLess(
            append.index("cp fsim_regular_policy_max_descriptors"),
            append.index("ld (hl),a"),
        )

        pack = client.split("regular_policy_pack_pending_descriptors:", 1)[1].split(
            "regular_policy_call_c:", 1
        )[0]
        self.assertIn("call regular_transition_group_is_processed", pack)
        self.assertNotIn("regular_transition_old_slot_pointer", pack)
        self.assertNotIn("regular_transition_target_owner_present", pack)
        guarded = client.split("regular_policy_select_c_guarded:", 1)[1].split(
            "regular_policy_candidate_failed_fallback:", 1
        )[0]
        self.assertNotIn("call regular_transition_select_feasible_group_asm", guarded)
        self.assertIn("call regular_policy_apply_c_result", guarded)
        self.assertEqual(builder.checked_descriptor_cache_bytes(38), 114)
        with self.assertRaises(builder.CPolicyFixtureBuildError):
            builder.checked_descriptor_cache_bytes(39)

    def test_modes_have_honest_authority_and_no_oracle_on_guarded_fast_path(self) -> None:
        asm_mode = ACCEPTED_SOURCE.with_name(
            "terrain-manager-regular-lod-policy-mode-asm-only.inc"
        ).read_text(encoding="ascii")
        dual_mode = ACCEPTED_SOURCE.with_name(
            "terrain-manager-regular-lod-policy-mode-dual-strict.inc"
        ).read_text(encoding="ascii")
        guarded_mode = ACCEPTED_SOURCE.with_name(
            "terrain-manager-regular-lod-policy-mode-c-guarded.inc"
        ).read_text(encoding="ascii")
        self.assertIn("jp regular_transition_select_feasible_group_asm", asm_mode)
        self.assertIn("jp regular_policy_select_dual_strict", dual_mode)
        self.assertIn("jp regular_policy_select_c_guarded", guarded_mode)

        client = CLIENT.read_text(encoding="ascii")
        dual = client.split("regular_policy_select_dual_strict:", 1)[1].split(
            "regular_policy_select_c_guarded:", 1
        )[0]
        self.assertLess(
            dual.index("call regular_transition_select_feasible_group_asm"),
            dual.index("call regular_policy_call_c"),
        )
        self.assertIn("ld (regular_transition_state),a", dual)
        guarded = client.split("regular_policy_select_c_guarded:", 1)[1].split(
            "regular_policy_candidate_failed_fallback:", 1
        )[0]
        self.assertNotIn("call regular_transition_select_feasible_group_asm", guarded)
        self.assertIn("REGULAR_POLICY_C_GUARDED_LATCH_CHECK", guarded)
        self.assertIn(
            "ld a,(regular_policy_qualification_failure)", guarded_mode
        )
        self.assertIn(
            "jp nz,regular_transition_select_feasible_group_asm", guarded_mode
        )
        fallback = client.split("regular_policy_candidate_failed_fallback:", 1)[1]
        self.assertIn("jp regular_transition_select_feasible_group_asm", fallback)

    def test_c_call_uses_three_caller_cleaned_adl_slots(self) -> None:
        client = CLIENT.read_text(encoding="ascii")
        call = client.split("regular_policy_call_c:", 1)[1].split(
            "regular_policy_revalidate_c_result:", 1
        )[0]
        self.assertEqual(call.count("    push hl"), 3)
        self.assertEqual(call.count("    pop hl"), 3)
        self.assertLess(call.index("ld l,a\n    push hl"), call.index("call fsim_regular_policy_entry_address"))
        self.assertIn("ld hl,regular_policy_descriptors\n    push hl", call)
        self.assertIn("ld (regular_policy_c_result),a", call)

    def test_profile_generation_changes_only_mode_include_value_and_title(self) -> None:
        for name, profile in builder.MODE_PROFILES.items():
            with self.subTest(mode=name):
                text = builder.profile_source(name)
                self.assertIn(
                    f"terrain_manager_regular_policy_mode: equ {profile['value']}",
                    text,
                )
                self.assertIn(f'include "{profile["include"]}"', text)
                self.assertIn(f"C-policy {profile['display']}:", text)

    def test_large_sibling_debug_sidecars_are_regenerated_not_tracked(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        base = "fixtures/terrain-manager-regular-lod-c-policy-survey/tgt/"
        self.assertIn(base + "*.lst", ignore)
        self.assertIn(base + "*.symbols", ignore)


@unittest.skipUnless(
    shutil.which("ez80asm")
    and (ROOT / ".venv/bin/python").is_file()
    and builder.DEFAULT_RUNTIME_OUTPUT.joinpath("WORLD.json").is_file()
    and builder.DEFAULT_MODULE_OUTPUT.joinpath("BUILD.json").is_file(),
    "qualified corpus/module/assembler inputs are unavailable",
)
class RegularLodCPolicyBuildTests(unittest.TestCase):
    def run_builder(
        self, output: Path, mode: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                str(ROOT / ".venv/bin/python"),
                "-B",
                str(BUILDER_PATH),
                "--skip-module-build",
                "--policy-mode",
                mode,
                "--artifact-output",
                str(output),
                "--no-install",
            ),
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_all_modes_build_with_disjoint_memory_and_deterministic_dual(self) -> None:
        accepted = (
            ROOT
            / "fixtures/terrain-manager-regular-lod-survey/tgt/"
            "terrain-manager-regular-lod-survey.bin"
        )
        accepted_before = hashlib.sha256(accepted.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="regular-c-policy-build-") as temporary:
            root = Path(temporary)
            receipts: dict[str, dict] = {}
            for mode in builder.MODE_PROFILES:
                completed = self.run_builder(root / mode, mode)
                self.assertEqual(completed.returncode, 0, completed.stdout)
                receipt = json.loads(
                    (root / mode / builder.BUILD_RECEIPT).read_text(encoding="utf-8")
                )
                receipts[mode] = receipt
                self.assertNotIn(str(ROOT), json.dumps(receipt, sort_keys=True))
                memory = receipt["memory_map"]
                self.assertEqual(
                    memory["fixture_program_end"], memory["fixture_filedata"]
                )
                self.assertLess(
                    memory["resource_staging_end"], memory["module_load_address"]
                )
                self.assertLess(
                    memory["module_image_end"], memory["module_limit_exclusive"]
                )
                self.assertEqual(receipt["module"]["image_bytes"], 301)
                self.assertEqual(receipt["module"]["entry_address"], 0x070020)
                self.assertNotIn("accepted_control", receipt)
                self.assertNotIn(
                    "private_historical_policy1_scratch_control", receipt
                )
                control = receipt["assembly_control"]
                self.assertEqual(control["kind"], "accepted assembly-only control")
                self.assertEqual(
                    control["program"],
                    "RLC.BIN",
                )
                self.assertFalse(control["installed_runtime_program"])
                self.assertNotIn("compile_time_override", control)
                self.assertNotIn("rebuilt_from_current_source", control)
                self.assertNotIn("unchanged", control)
                self.assertEqual(
                    control["sha256"],
                    builder.ACCEPTED_PROGRAM_SHA256,
                )
                self.assertEqual(memory["descriptor_array_bytes"], 114)
                self.assertEqual(memory["descriptor_array_gaps"], [114, 114])
                self.assertEqual(
                    receipt["human_gates"],
                    [
                        "interactive emulator presentation",
                        "physical hardware execution and timing",
                    ],
                )
                profile = builder.MODE_PROFILES[mode]
                self.assertEqual(
                    receipt["policy"]["module_required"],
                    profile["module_required"],
                )
                mode_include = builder.SOURCE_DIRECTORY / str(profile["include"])
                self.assertEqual(
                    receipt["source"]["mode_include_sha256"],
                    hashlib.sha256(mode_include.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    receipt["source"]["profiled_sha256"],
                    hashlib.sha256(
                        builder.profile_source(mode).encode("ascii")
                    ).hexdigest(),
                )
                dependencies = receipt["source"]["mode_dependencies"]
                self.assertEqual(
                    [Path(item["path"]).name for item in dependencies],
                    list(profile["source_dependencies"]),
                )
                for item in dependencies:
                    dependency = ROOT / item["path"]
                    self.assertEqual(
                        item["sha256"],
                        hashlib.sha256(dependency.read_bytes()).hexdigest(),
                    )
                if mode in builder.HISTORICAL_MODE_PROGRAM_SHA256:
                    self.assertEqual(
                        receipt["artifacts"][
                            "terrain-manager-regular-lod-c-policy-survey.bin"
                        ]["sha256"],
                        builder.HISTORICAL_MODE_PROGRAM_SHA256[mode],
                    )

            second = self.run_builder(root / "dual-second", "dual-strict")
            self.assertEqual(second.returncode, 0, second.stdout)
            second_receipt = json.loads(
                (root / "dual-second" / builder.BUILD_RECEIPT).read_text()
            )
            self.assertEqual(
                receipts["dual-strict"]["artifacts"], second_receipt["artifacts"]
            )
            self.assertEqual(
                {receipt["policy"]["mode"] for receipt in receipts.values()},
                {"ASM_ONLY", "DUAL_STRICT", "C_GUARDED"},
            )
        self.assertEqual(
            hashlib.sha256(accepted.read_bytes()).hexdigest(), accepted_before
        )

    def test_nondefault_module_output_is_rejected_before_assembly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="regular-c-policy-module-") as temporary:
            root = Path(temporary)
            completed = subprocess.run(
                (
                    str(ROOT / ".venv/bin/python"),
                    "-B",
                    str(BUILDER_PATH),
                    "--skip-module-build",
                    "--module-output",
                    str(root / "alternate-module"),
                    "--artifact-output",
                    str(root / "artifact"),
                    "--no-install",
                ),
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--module-output is pinned", completed.stdout)


if __name__ == "__main__":
    unittest.main()
