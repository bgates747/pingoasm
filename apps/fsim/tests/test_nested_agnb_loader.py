from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.nested_agnb import RecordIdentity, select_record
from pingo_terrain.p3dm import parse_container
from pingo_terrain.regional_lod import make_bundle, parse_bundle


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures/nested-agnb-loader-probe"
MAIN = FIXTURE / "src/nested-agnb-loader-probe.asm"
LOADER = FIXTURE / "src/nested-agnb-loader.inc"
LOOSE_RECORD = ROOT / "fixtures/p3dm-loader-probe/tgt/TRN/L0/00/0C.AGN"


def probe_records(count: int = 10, selected_index: int = 6):
    base = parse_container(LOOSE_RECORD.read_bytes())
    records = []
    for index in range(count):
        if index == selected_index:
            records.append(base)
            continue
        lod = 2 if index == 0 else 1 if index == 1 else 0
        tile_x = index + 20
        tile_y = 0
        records.append(
            replace(
                base,
                meta=replace(
                    base.meta,
                    lod=lod,
                    tile_x=tile_x,
                    tile_y=tile_y,
                    center_east_m=tile_x * 512 + 256,
                    center_north_m=256,
                ),
            )
        )
    return tuple(records)


class NestedAGNBHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = probe_records()
        self.bundle = make_bundle(self.records)
        self.expected = RecordIdentity.from_tile(self.records[6])

    def test_selects_middle_record_from_family_larger_than_staging_window(self):
        self.assertGreater(len(self.bundle), 16_384)
        result = select_record(BytesIO(self.bundle), self.expected)
        self.assertEqual(result.tile, self.records[6])
        self.assertEqual(result.record_index, 6)
        self.assertEqual(result.records_scanned, 10)
        self.assertLess(result.bytes_read, 4_096)
        self.assertLess(result.bytes_read, len(self.bundle) // 4)

        _, spans = parse_bundle(self.bundle)
        self.assertEqual(result.list_offset, spans[6].list_offset)
        self.assertEqual(result.data_offset, spans[6].data_offset)
        self.assertEqual(result.data_bytes, spans[6].data_bytes)

    def test_selected_data_crc_is_checked_by_existing_parser(self):
        _, spans = parse_bundle(self.bundle)
        corrupted = bytearray(self.bundle)
        corrupted[spans[6].data_offset] ^= 0x01
        with self.assertRaisesRegex(ValueError, "CRC"):
            select_record(BytesIO(corrupted), self.expected)

    def test_unmatched_padding_and_contradictory_list_size_are_rejected(self):
        _, spans = parse_bundle(self.bundle)
        corrupted_header_padding = bytearray(self.bundle)
        corrupted_header_padding[spans[0].list_offset + 22] = 1
        with self.assertRaisesRegex(ValueError, "BHDR.*padding"):
            select_record(BytesIO(corrupted_header_padding), self.expected)

        corrupted_padding = bytearray(self.bundle)
        first = spans[0]
        corrupted_padding[first.data_offset + first.data_bytes] = 1
        with self.assertRaisesRegex(ValueError, "padding"):
            select_record(BytesIO(corrupted_padding), self.expected)

        corrupted_size = bytearray(self.bundle)
        original = struct.unpack_from("<I", corrupted_size, first.list_offset + 4)[0]
        struct.pack_into("<I", corrupted_size, first.list_offset + 4, original + 4)
        with self.assertRaisesRegex(ValueError, "LIST size"):
            select_record(BytesIO(corrupted_size), self.expected)

    def test_missing_duplicate_and_record_limit_fail_closed(self):
        missing = replace(self.expected, tile_x=-1)
        with self.assertRaisesRegex(ValueError, "absent"):
            select_record(BytesIO(self.bundle), missing)

        _, spans = parse_bundle(self.bundle)
        duplicate = bytearray(self.bundle)
        selected_descriptor = self.bundle[
            spans[6].list_offset + 32 : spans[6].list_offset + 68
        ]
        duplicate[spans[9].list_offset + 32 : spans[9].list_offset + 68] = (
            selected_descriptor
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_record(BytesIO(duplicate), self.expected)

        seventeen = probe_records(count=17, selected_index=0)
        with self.assertRaisesRegex(ValueError, "record count"):
            select_record(
                BytesIO(make_bundle(seventeen)),
                RecordIdentity.from_tile(seventeen[0]),
            )


class NestedAGNBeZ80SourceTests(unittest.TestCase):
    def test_scan_uses_bounded_seeks_and_reuses_transactional_publication(self):
        source = LOADER.read_text(encoding="utf-8")
        self.assertIn("ffs_flseek: equ 084h", source)
        self.assertIn("agnb_record_prefix_bytes: equ 76", source)
        self.assertIn("agnb_max_records: equ 16", source)
        self.assertIn("FFSCALL ffs_flseek", source)
        self.assertGreaterEqual(
            source.count("ld bc,agnb_record_prefix_bytes"), 2
        )
        top = source.split("agnb_load_selected_component:", 1)[1].split(
            "; Open and always close", 1
        )[0]
        sequence = (
            "call agnb_read_selected_container",
            "call p3dm_validate_container",
            "call p3dm_upload_data",
            "call pingo_replace_mesh_from_buffer",
        )
        offsets = [top.index(item) for item in sequence]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreaterEqual(top.count("ret nz"), 3)

    def test_family_is_closed_before_selected_validation_and_publication(self):
        source = LOADER.read_text(encoding="utf-8")
        reader = source.split("agnb_read_selected_container:", 1)[1].split(
            "; Input HL", 1
        )[0]
        self.assertLess(
            reader.index("call agnb_scan_open_file"),
            reader.index("FFSCALL ffs_fclose"),
        )
        self.assertNotIn("pingo_replace_mesh_from_buffer", reader)

    def test_fixed_width_state_has_no_direct_adl_word_access(self):
        source = LOADER.read_text(encoding="utf-8")
        word_fields = "|".join(
            re.escape(field)
            for field in (
                "agnb_current_data_size",
                "agnb_selected_data_size",
                "p3dm_file_size",
            )
        )
        self.assertNotRegex(
            source,
            rf"ld\s+\((?:{word_fields})\),\s*(?:bc|de|hl|ix|iy)",
        )
        self.assertNotRegex(
            source,
            rf"ld\s+(?:bc|de|hl|ix|iy),\s*\((?:{word_fields})\)",
        )

    def test_include_closure_has_no_unreviewed_adl_width_access(self):
        result = audit_paths(include_closure([MAIN]))
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    @unittest.skipUnless(shutil.which("ez80asm"), "ez80asm is unavailable")
    def test_isolated_probe_assembles(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            for source in include_closure([MAIN]):
                relative = source.relative_to(ROOT)
                destination = scratch / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            copied_main = scratch / MAIN.relative_to(ROOT)
            output = scratch / "nested-agnb-loader-probe.bin"
            completed = subprocess.run(
                ["ez80asm", copied_main.name, str(output), "-c"],
                cwd=copied_main.parent,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
