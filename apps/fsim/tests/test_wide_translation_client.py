from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ROOT / "fixtures/_common/pingo-wide-translation.inc"
HARNESS = ROOT / "tests/pingo_wide_translation_harness.asm"


class WideTranslationClientTests(unittest.TestCase):
    def test_packet_is_command_52_with_exact_fixed_width_fields(self) -> None:
        source = INCLUDE.read_text(encoding="utf-8")
        packet = source.split("@command:", 1)[1].split("@command_end:", 1)[0]
        self.assertIn("db 049h,52", packet)
        self.assertEqual(packet.count("dw 0"), 1)
        self.assertEqual(packet.count("db 0,0,0"), 3)
        self.assertNotRegex(
            source,
            r"ld\s+\([^)]*\),\s*(?:hl|de|bc|ix|iy)\b",
        )
        self.assertEqual(
            len(re.findall(r"ld\s+a,\(ix\+[0-8]\)", source)),
            9,
        )

    def test_include_assembles_in_adl_mode(self) -> None:
        assembler = shutil.which("ez80asm")
        self.assertIsNotNone(assembler)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            tests = root / "tests"
            common = root / "fixtures/_common"
            tests.mkdir(parents=True)
            common.mkdir(parents=True)
            shutil.copy2(HARNESS, tests / HARNESS.name)
            shutil.copy2(INCLUDE, common / INCLUDE.name)
            output = root / "wide.bin"
            subprocess.run(
                [assembler, HARNESS.name, str(output)],
                cwd=tests,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
