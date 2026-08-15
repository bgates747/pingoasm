import tempfile
from pathlib import Path
import unittest

from pingo_terrain.adl_width import audit_paths, include_closure
from pingo_terrain.paths import PROJECT_ROOT


class ADLWidthAuditTests(unittest.TestCase):
    def audit(self, source: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.asm"
            path.write_text(source, encoding="utf-8")
            return audit_paths([path])

    def test_unsuffixed_adl_store_overruns_dw(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "patch:\n"
            "    ld (@field),hl\n"
            "    ret\n"
            "@field: dw 0\n"
            "@opcode: db 14\n"
        )
        self.assertEqual(len(result.hazards), 1)
        self.assertEqual(result.hazards[0].classification, "word-overrun")

    def test_unsuffixed_adl_load_overreads_dw(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "read:\n"
            "    ld bc,(@count)\n"
            "    ret\n"
            "@count: dw 0\n"
        )
        self.assertEqual(len(result.hazards), 1)
        self.assertEqual(result.hazards[0].direction, "load")

    def test_dl_is_intentional_24_bit_storage(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "read:\n"
            "    ld hl,(pointer)\n"
            "    ret\n"
            "pointer: dl 0\n"
        )
        self.assertFalse(result.hazards)
        self.assertEqual(result.accesses[0].classification, "24-bit-storage")

    def test_dw24_alias_is_intentional_24_bit_storage(self) -> None:
        result = self.audit(
            ".assume adl=1\nread:\n    ld hl,(pointer)\npointer: dw24 0\n"
        )
        self.assertFalse(result.hazards)
        self.assertEqual(result.accesses[0].classification, "24-bit-storage")

    def test_block_pointer_storage_is_large_enough(self) -> None:
        result = self.audit(
            ".assume adl=1\nread:\n    ld hl,(pointer)\npointer: blkp 1,0\n"
        )
        self.assertFalse(result.hazards)
        self.assertEqual(result.accesses[0].classification, "reserved-storage")

    def test_short_data_suffix_does_not_overrun(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "patch:\n"
            "    ld.sis (@field),hl\n"
            "    ret\n"
            "@field: dw 0\n"
        )
        self.assertFalse(result.hazards)
        self.assertEqual(result.accesses[0].classification, "explicit-16-bit")

    def test_register_indirect_access_remains_visible_for_review(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "write:\n"
            "    ld (ix+2),de\n"
        )
        self.assertFalse(result.hazards)
        self.assertEqual(len(result.review_items), 1)

    def test_annotated_indirect_24_bit_contract_is_reviewed(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "read:\n"
            "    ld hl,(ix+2) ; ADL24 OK: structure field is exactly 3 bytes\n"
        )
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    def test_annotation_only_waives_a_deliberate_packed_access(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "patch:\n"
            "    ld (@field),hl ; ADL24 OK: packed word plus explicit byte\n"
            "    ret\n"
            "@field: dw 0\n"
            "@byte: db 0\n"
        )
        self.assertFalse(result.hazards)
        self.assertTrue(result.accesses[0].annotated)

    def test_empty_annotation_does_not_waive_access(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "patch:\n"
            "    ld (@field),hl ; ADL24 OK:\n"
            "    ret\n"
            "@field: dw 0\n"
            "@byte: db 0\n"
        )
        self.assertEqual(len(result.hazards), 1)

    def test_unique_global_storage_resolves_across_include_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            use = root / "use.asm"
            definition = root / "state.inc"
            use.write_text(
                ".assume adl=1\nstart:\n    ld hl,(pointer)\n",
                encoding="utf-8",
            )
            definition.write_text("pointer: dl 0\n", encoding="utf-8")
            result = audit_paths([use, definition])
        self.assertFalse(result.hazards)
        self.assertEqual(result.accesses[0].classification, "24-bit-storage")

    def test_approved_dither_fixture_has_no_unreviewed_width_access(self) -> None:
        source = (
            PROJECT_ROOT
            / "fixtures/berkeley-flight-triangular-dither/src"
        )
        paths = include_closure(
            [source / "berkeley-flight-triangular-dither.asm"]
        )
        result = audit_paths(paths)
        self.assertFalse(result.hazards)
        self.assertFalse(result.review_items)

    def test_include_closure_is_recursive_and_comment_aware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "entry.asm"
            first = root / "first.inc"
            second = root / "sub/second.inc"
            second.parent.mkdir()
            entry.write_text(
                'include "first.inc"\n; include "missing.inc"\n',
                encoding="utf-8",
            )
            first.write_text('include "sub/second.inc"\n', encoding="utf-8")
            second.write_text("value: dl 0\n", encoding="utf-8")
            closure = include_closure([entry])
        self.assertEqual(
            {path.name for path in closure}, {"entry.asm", "first.inc", "second.inc"}
        )

    def test_mlt_product_cannot_feed_long_address_add_with_stale_upper_byte(self) -> None:
        result = self.audit(
            ".assume adl=1\n"
            "lookup:\n"
            "    ld e,a\n"
            "    ld d,17\n"
            "    mlt de\n"
            "    ld hl,table\n"
            "    add hl,de\n"
            "table: db 0\n"
        )
        self.assertEqual(len(result.hazards), 1)
        self.assertEqual(result.hazards[0].classification, "upper-byte-address")
        self.assertEqual(result.hazards[0].register, "de")

    def test_mlt_address_offset_accepts_explicit_upper_zero_or_short_add(self) -> None:
        for source in (
            (
                ".assume adl=1\nlookup:\n    ld de,0\n    ld e,a\n"
                "    ld d,17\n    mlt de\n    ld hl,table\n    add hl,de\n"
                "table: db 0\n"
            ),
            (
                ".assume adl=1\nlookup:\n    ld e,a\n    ld d,17\n"
                "    mlt de\n    ld hl,table\n    add.s hl,de\n"
                "table: db 0\n"
            ),
            (
                ".assume adl=1\nlookup:\n    ld e,a\n    ld d,17\n"
                "    mlt de\n    inc.s de\n    ld hl,table\n    add hl,de\n"
                "table: db 0\n"
            ),
        ):
            with self.subTest(source=source):
                self.assertFalse(self.audit(source).hazards)


if __name__ == "__main__":
    unittest.main()
