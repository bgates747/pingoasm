from __future__ import annotations

from argparse import Namespace
from contextlib import redirect_stdout
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_SOURCE = ROOT / "moslets/fsim/src/fsim.asm"
LAUNCHER_BINARY = ROOT / "moslets/fsim/tgt/fsim.bin"
BUILD_SCRIPT = ROOT / "scripts/build_fsim_launcher.py"
SETUP_SCRIPT = ROOT / "scripts/setup_emulator.py"
FIXTURE_ENTRY = 0x040000


@dataclass(frozen=True)
class Appliance:
    source: str
    directory: str
    binary: str

    @property
    def source_path(self) -> Path:
        return ROOT / self.source

    @property
    def binary_path(self) -> Path:
        return ROOT / self.directory / self.binary


APPLIANCES = (
    Appliance(
        "fixtures/berkeley-flight/src/berkeley-flight.asm",
        "fixtures/berkeley-flight/tgt",
        "berkeley-flight.bin",
    ),
    Appliance(
        "fixtures/berkeley-flight-triangular/src/berkeley-flight.asm",
        "fixtures/berkeley-flight-triangular/tgt",
        "berkeley-flight-triangular.bin",
    ),
    Appliance(
        "fixtures/berkeley-flight-triangular-dither/src/berkeley-flight-triangular-dither.asm",
        "fixtures/berkeley-flight-triangular-dither/tgt",
        "berkeley-flight-triangular-dither.bin",
    ),
    Appliance(
        "fixtures/berkeley-flight-fdm/src/berkeley-flight-fdm.asm",
        "fixtures/berkeley-flight-fdm/tgt",
        "berkeley-flight-fdm.bin",
    ),
    Appliance(
        "fixtures/koak-flight-streamed/src/koak-flight-streamed.asm",
        "build/p3dm/bay-area-koak-proof",
        "P3DFSIM.BIN",
    ),
    Appliance(
        "fixtures/koak-flight-family-lod/src/koak-flight-family-lod.asm",
        "build/p3dm/bay-area-koak-family-proof",
        "P3DLOD.BIN",
    ),
    Appliance(
        "fixtures/p3dm-loader-probe/src/p3dm-loader-probe.asm",
        "fixtures/p3dm-loader-probe/tgt",
        "p3dm-loader-probe.bin",
    ),
    Appliance(
        "fixtures/nested-agnb-loader-probe/src/nested-agnb-loader-probe.asm",
        "fixtures/nested-agnb-loader-probe/tgt",
        "nested-agnb-loader-probe.bin",
    ),
    Appliance(
        "fixtures/campanile-p3dm-probe/src/campanile-p3dm-probe.asm",
        "fixtures/campanile-p3dm-probe/tgt",
        "CAMPTEST.BIN",
    ),
    Appliance(
        "fixtures/terrain-manager-survey/src/terrain-manager-survey.asm",
        "build/p3dm/bay-area-hex-full-l0",
        "P3DHXMG.BIN",
    ),
    Appliance(
        "fixtures/terrain-manager-survey/src/terrain-manager-natural-survey.asm",
        "build/p3dm/bay-area-natural-full-l0",
        "P3DNAT.BIN",
    ),
    Appliance(
        "fixtures/terrain-manager-survey/src/terrain-manager-distance-survey.asm",
        "build/p3dm/bay-area-distance-lod-control",
        "P3DDST.BIN",
    ),
    Appliance(
        "fixtures/terrain-manager-survey/src/terrain-manager-regular-lod-survey.asm",
        "build/p3dm/bay-area-regular-n1-hierarchy",
        "P3DRGL.BIN",
    ),
)


def normalized_assembly(path: Path) -> str:
    source = path.read_text(encoding="utf-8").lower()
    return re.sub(r"\s+", " ", source)


def load_setup_module():
    spec = spec_from_file_location("pingo_terrain_setup_emulator_test", SETUP_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureEntryContractTests(unittest.TestCase):
    def test_thirteen_appliances_have_one_common_mos_entry(self) -> None:
        self.assertEqual(len(APPLIANCES), 13)
        for appliance in APPLIANCES:
            with self.subTest(source=appliance.source):
                source = normalized_assembly(appliance.source_path)
                self.assertRegex(source, r"\.assume\s+adl\s*=\s*1")
                self.assertRegex(source, r"\.org\s+0?40000h\b")
                self.assertRegex(source, r"\.org\s+0?40000h\s+jp\s+start\b")
                self.assertRegex(
                    source,
                    r"\.align\s+64\s+\.db\s+\"mos\"\s*,\s*0\s*,\s*1",
                )
                self.assertRegex(
                    source,
                    r"\bstart\s*:\s*"
                    r"push af\s+push bc\s+push de\s+push ix\s+push iy\s+"
                    r"call main\s+"
                    r"pop iy\s+pop ix\s+pop de\s+pop bc\s+pop af\s+"
                    r"ld hl\s*,\s*0\s+ret\b",
                    "manual RUN and launcher CALL must share a returning entry",
                )

    def test_all_binaries_encode_an_adl_mos_program_at_040000(self) -> None:
        for appliance in APPLIANCES:
            with self.subTest(binary=str(appliance.binary_path.relative_to(ROOT))):
                payload = appliance.binary_path.read_bytes()
                self.assertGreater(len(payload), 69)
                self.assertEqual(payload[0], 0xC3, "entry must be an absolute JP")
                jump_target = int.from_bytes(payload[1:4], "little")
                self.assertGreaterEqual(jump_target, FIXTURE_ENTRY + 69)
                self.assertLess(jump_target, FIXTURE_ENTRY + len(payload))
                self.assertEqual(payload[64:69], b"MOS\0\1")


class FsimLauncherSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
        self.normalized = re.sub(r"\s+", " ", self.source.lower())

    def test_launcher_is_an_adl_moslet_with_a_fixed_fixture_call_address(self) -> None:
        self.assertRegex(self.normalized, r"\.org\s+0?b0000h\b")
        self.assertRegex(
            self.normalized,
            r"\.align\s+64\s+\.?db\s+\"mos\"\s*,\s*0\s*,\s*1",
        )
        self.assertRegex(
            self.normalized,
            r"fixture_entry(?:_address)?\s*:\s*equ\s+0?40000h\b",
        )
        self.assertRegex(
            self.normalized,
            r"\bcall\s+(?:fixture_entry(?:_address)?|0?40000h)\b",
        )

    def test_launcher_uses_config_and_preserves_the_callers_directory(self) -> None:
        self.assertIn('/mos/fsim.cfg', self.source.lower())
        self.assertRegex(self.normalized, r"ffs_getcwd\s*:\s*equ\s+0?9eh\b")
        self.assertRegex(self.normalized, r"mos_cd\s*:\s*equ\s+0?3h\b")
        self.assertRegex(self.normalized, r"mos_load\s*:\s*equ\s+0?1h\b")
        self.assertRegex(self.normalized, r"\bcall\s+save_(?:current_)?directory\b")
        self.assertRegex(
            self.normalized,
            r"\bcall\s+restore_(?:(?:original|current)_)?directory\b",
        )
        self.assertRegex(
            self.normalized,
            r"\bcall\s+(?:load_(?:root_)?config|read_config_root)\b",
        )
        self.assertRegex(
            self.normalized,
            r"\bcall\s+(?:build_(?:fixture_)?path|build_fixture_directory)\b",
        )

        save_call = re.search(r"\bcall\s+save_(?:current_)?directory\b", self.normalized)
        config_call = re.search(
            r"\bcall\s+(?:load_(?:root_)?config|read_config_root)\b",
            self.normalized,
        )
        self.assertIsNotNone(save_call)
        self.assertIsNotNone(config_call)
        assert save_call is not None and config_call is not None
        self.assertLess(save_call.start(), config_call.start())

    def test_menu_preserves_number_keys_and_named_shortcuts(self) -> None:
        for number in range(1, 10):
            self.assertRegex(self.source, rf'(?m)^\s*db\s+"{number}(?:[.)]|\s) ')
        self.assertRegex(self.source, r'(?m)^\s*db\s+"0(?:[.)]|\s) ')
        self.assertRegex(self.source, r'(?m)^\s*db\s+"N(?:[.)]|\s) ')
        self.assertRegex(self.source, r'(?m)^\s*db\s+"D(?:[.)]|\s) ')
        self.assertRegex(self.source, r'(?m)^\s*db\s+"R(?:[.)]|\s) ')
        self.assertRegex(self.normalized, r"\bcp\s+(?:1bh|27)\b")
        self.assertRegex(self.normalized, r"\bsub\s+['\"]1['\"]")
        self.assertRegex(
            self.normalized,
            r"\bcp\s+['\"]0['\"]\s+jr\s+nz\s*,\s*@regular_fixture\s+"
            r"ld\s+a\s*,\s*9",
        )
        self.assertRegex(
            self.normalized,
            r"@regular_fixture\s*:\s*cp\s+['\"]r['\"]\s+"
            r"jr\s+z\s*,\s*@select_regular\s+cp\s+['\"]r['\"]\s+"
            r"jr\s+nz\s*,\s*@distance_fixture\s+"
            r"@select_regular\s*:\s*ld\s+a\s*,\s*12",
        )
        self.assertRegex(
            self.normalized,
            r"@distance_fixture\s*:\s*cp\s+['\"]d['\"]\s+"
            r"jr\s+z\s*,\s*@select_distance\s+cp\s+['\"]d['\"]\s+"
            r"jr\s+nz\s*,\s*@natural_fixture\s+"
            r"@select_distance\s*:\s*ld\s+a\s*,\s*11",
        )
        self.assertRegex(
            self.normalized,
            r"@natural_fixture\s*:\s*cp\s+['\"]n['\"]\s+"
            r"jr\s+z\s*,\s*@select_natural\s+cp\s+['\"]n['\"]\s+"
            r"jr\s+nz\s*,\s*@numbered_fixture\s+"
            r"@select_natural\s*:\s*ld\s+a\s*,\s*10",
        )
        self.assertRegex(self.normalized, r"\bcp\s+['\"]9['\"]\s*\+\s*1\b")
        self.assertNotRegex(
            self.normalized,
            r"\bcp\s+['\"]0['\"]\s*\+\s*fixture_count\s*\+\s*1",
            "the old contiguous range would admit ':' while rejecting key 0",
        )

        # Every appliance must be named by the launch table, not inferred from
        # a shared working directory or a mutable MOS command line.
        for appliance in APPLIANCES:
            with self.subTest(directory=appliance.directory):
                self.assertIn(appliance.directory, self.source)
                self.assertIn(appliance.binary, self.source)

    def test_config_reader_is_bounded_and_terminates_on_cr_or_lf(self) -> None:
        self.assertRegex(
            self.normalized,
            r"(?:path_buffer_(?:size|bytes)|config_root_max)\s*:\s*equ\s+\d+",
        )
        self.assertRegex(self.normalized, r"\bcp\s+(?:0?dh|13)\b")
        self.assertRegex(self.normalized, r"\bcp\s+(?:0?ah|10)\b")
        self.assertTrue(
            re.search(r"\bld\s+\(hl\)\s*,\s*0\b", self.normalized)
            or re.search(r"\bxor\s+a\s+ld\s+\(hl\)\s*,\s*a\b", self.normalized),
            "the bounded config read must receive an explicit NUL terminator",
        )
        self.assertRegex(
            self.normalized,
            r"\b(?:jr|jp)\s+(?:z|nc|c)\s*,\s*[@a-z_]\w+",
        )

        root_max_match = re.search(
            r"\bconfig_root_max\s*:\s*equ\s+(\d+)", self.normalized
        )
        path_bytes_match = re.search(
            r"\bpath_buffer_(?:size|bytes)\s*:\s*equ\s+(\d+)",
            self.normalized,
        )
        self.assertIsNotNone(root_max_match)
        self.assertIsNotNone(path_bytes_match)
        assert root_max_match is not None and path_bytes_match is not None
        root_max = int(root_max_match.group(1))
        path_bytes = int(path_bytes_match.group(1))
        longest_relative_directory = max(
            len(appliance.directory.encode("ascii")) for appliance in APPLIANCES
        )
        self.assertLessEqual(
            root_max + 1 + longest_relative_directory + 1,
            path_bytes,
            "configured root plus slash, directory and NUL must fit path_buffer",
        )

    def test_loaded_program_is_validated_before_the_indirect_call(self) -> None:
        self.assertRegex(
            self.normalized,
            r"entry_signature\s*:\s*(?:\.?db)\s+0?c3h\s*,\s*0?45h\s*,"
            r"\s*0?00h\s*,\s*0?04h",
        )
        self.assertRegex(
            self.normalized,
            r"header_signature\s*:\s*(?:\.?db)\s+\"mos\"\s*,\s*0\s*,\s*1",
        )
        launcher = self.normalized.split("run_selected_fixture:", 1)[1].split(
            "validate_fixture_entry:", 1
        )[0]
        load_at = launcher.index("moscall mos_load")
        validate_at = launcher.index("call validate_fixture_entry")
        invoke_at = launcher.index("call fixture_entry")
        self.assertLess(load_at, validate_at)
        self.assertLess(validate_at, invoke_at)

        capacity_match = re.search(
            r"fixture_load_capacity\s*:\s*equ\s+0?([0-9a-f]+)h",
            self.normalized,
        )
        self.assertIsNotNone(capacity_match)
        assert capacity_match is not None
        self.assertLessEqual(
            FIXTURE_ENTRY + int(capacity_match.group(1), 16),
            0x0B0000,
            "fixture load window must not overlap the resident MOSlet",
        )

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_launcher_assembles_to_an_isolated_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            copied_source = scratch / LAUNCHER_SOURCE.name
            shutil.copy2(LAUNCHER_SOURCE, copied_source)
            output = scratch / "fsim.bin"
            completed = subprocess.run(
                ["ez80asm", copied_source.name, output.name],
                cwd=scratch,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            payload = output.read_bytes()
            self.assertLess(len(payload), 32 * 1024)
            self.assertEqual(payload[0], 0xC3)
            self.assertEqual(payload[64:69], b"MOS\0\1")


class FsimBuildAndSetupTests(unittest.TestCase):
    def test_builder_and_checked_in_launcher_agree(self) -> None:
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ez80asm", source)
        self.assertIn("fsim.asm", source)
        self.assertIn("fsim.bin", source)
        self.assertTrue(LAUNCHER_BINARY.is_file())
        payload = LAUNCHER_BINARY.read_bytes()
        self.assertLess(len(payload), 32 * 1024)
        self.assertEqual(payload[64:69], b"MOS\0\1")

    def test_setup_helpers_refuse_to_replace_real_paths(self) -> None:
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_bytes(b"target")
            occupied = root / "occupied"
            occupied.write_bytes(b"mine")
            with self.assertRaises(SystemExit):
                setup.replace_symlink(occupied, target)
            self.assertEqual(occupied.read_bytes(), b"mine")

            occupied_directory = root / "occupied-directory"
            occupied_directory.mkdir()
            with self.assertRaises(SystemExit):
                setup.replace_directory_link(occupied_directory, root)
            self.assertTrue(occupied_directory.is_dir())
            self.assertFalse(occupied_directory.is_symlink())

    def test_autoexec_migrates_known_presets_and_preserves_custom_edits(self) -> None:
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as directory:
            autoexec = Path(directory) / "autoexec.txt"
            for legacy in setup.LEGACY_GENERATED_AUTOEXECS:
                with self.subTest(legacy=legacy):
                    autoexec.write_bytes(legacy)
                    setup.provision_autoexec(autoexec)
                    self.assertEqual(autoexec.read_bytes(), setup.DEFAULT_AUTOEXEC)

            custom = b"SET KEYBOARD 1\r\nREM author-owned\r\n"
            autoexec.write_bytes(custom)
            setup.provision_autoexec(autoexec)
            self.assertEqual(autoexec.read_bytes(), custom)

    def test_setup_installs_fsim_and_keyboard_only_autoexec(self) -> None:
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            profile = project / "emulator"
            sdcard = profile / "sdcard"
            fab = root / "fab"
            firmware = fab / "firmware"
            fixture_root = project / "fixtures"
            build_root = project / "build"
            launcher = project / "moslets/fsim/tgt/fsim.bin"
            executable = fab / "fab-agon-emulator"
            vdp = root / "vdp_combined.so"

            firmware.mkdir(parents=True)
            (fab / "sdcard/mos").mkdir(parents=True)
            fixture_root.mkdir(parents=True)
            build_root.mkdir(parents=True)
            launcher.parent.mkdir(parents=True)
            executable.write_bytes(b"emulator")
            (firmware / "mos_console8.bin").write_bytes(b"mos")
            (firmware / "mos_console8.map").write_bytes(b"map")
            launcher.write_bytes(b"launcher")
            vdp.write_bytes(b"vdp")

            with (
                patch.object(setup, "PROJECT_ROOT", project),
                patch.object(setup, "PROFILE", profile),
                patch.object(setup, "SDCARD", sdcard),
                patch.object(setup, "FAB_ROOT", fab),
                patch.object(setup, "FSIM_PROGRAM", launcher),
                patch.object(setup, "emulator_executable", return_value=executable),
                patch.object(setup, "parse_arguments", return_value=Namespace(vdp_module=vdp)),
                redirect_stdout(StringIO()),
            ):
                setup.main()

            self.assertEqual(
                (sdcard / "autoexec.txt").read_bytes(), b"SET KEYBOARD 1\r\n"
            )
            installed = sdcard / "mos/fsim.bin"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), launcher.resolve())
            self.assertEqual(
                (sdcard / "mos/fsim.cfg").read_bytes(),
                b"/mystuff/pingoasm/apps/fsim\r\n",
            )


if __name__ == "__main__":
    unittest.main()
