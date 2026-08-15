from __future__ import annotations

import unittest

from pingo_terrain.regular_lod_profile import (
    ProfileEvidenceError,
    parse_mesh_replace_records,
    parse_regular_lod_profile,
    parse_render_records,
    parse_selector_cycle_pairs,
    summarize_distribution,
    summarize_render_window,
)


def render_line(sequence: int, render_us: int, *, bitmap_id: int = 257) -> str:
    return (
        f"PINGO_RENDER seq={sequence} bmid={bitmap_id} "
        f"render_us={render_us} clr={render_us // 10} "
        f"xf={render_us // 2} status=ok"
    )


class RegularLodProfileTests(unittest.TestCase):
    def test_parses_embedded_render_and_mesh_diagnostics(self) -> None:
        contents = "\n".join(
            (
                "unrelated emulator output",
                "ESP32 DBGSerial: noise " + render_line(226, 1290),
                "prefix PINGO_STREAM mesh_replace=ok stage=29696 mid=47 "
                "bytes=3310 v=121 i=630 u=16 t=630 us=44",
            )
        )

        profile = parse_regular_lod_profile(contents)

        self.assertEqual(len(profile.renders), 1)
        render = profile.renders[0]
        self.assertEqual((render.line_number, render.sequence), (2, 226))
        self.assertEqual(render.render_us, 1290)
        self.assertEqual(render.value("status"), "ok")
        self.assertEqual(len(profile.mesh_replacements), 1)
        mesh = profile.mesh_replacements[0]
        self.assertEqual(
            (
                mesh.stage_buffer_id,
                mesh.mesh_id,
                mesh.data_bytes,
                mesh.vertices,
                mesh.position_indices,
                mesh.texture_coordinates,
                mesh.texture_indices,
                mesh.publication_us,
            ),
            (29696, 47, 3310, 121, 630, 16, 630, 44),
        )
        self.assertEqual(profile.selector_pairs, ())

    def test_marked_diagnostics_fail_closed_when_malformed(self) -> None:
        malformed_renders = (
            "PINGO_RENDER seq=1 bmid=257",
            "PINGO_RENDER seq=1 bmid=257 render_us=abc",
            "PINGO_RENDER seq=1 seq=2 bmid=257 render_us=3",
            "PINGO_RENDER seq=1 bmid=257 render_us=3 trailing-garbage",
        )
        for contents in malformed_renders:
            with self.subTest(contents=contents):
                with self.assertRaises(ProfileEvidenceError):
                    parse_render_records(contents)

        malformed_meshes = (
            "PINGO_STREAM mesh_replace=failed stage=29696 mid=1 bytes=10 "
            "v=1 i=3 u=1 t=3 us=2",
            "PINGO_STREAM mesh_replace=ok stage=29696 mid=1 bytes=10 "
            "v=1 i=3 u=1 t=3",
            "PINGO_STREAM mesh_replace=ok stage=29696 mid=-1 bytes=10 "
            "v=1 i=3 u=1 t=3 us=2",
        )
        for contents in malformed_meshes:
            with self.subTest(contents=contents):
                with self.assertRaises(ProfileEvidenceError):
                    parse_mesh_replace_records(contents)

    def test_distribution_uses_nearest_rank_p95(self) -> None:
        summary = summarize_distribution((40, 10, 30, 20))

        self.assertEqual(summary.count, 4)
        self.assertEqual(summary.total, 100)
        self.assertEqual((summary.minimum, summary.maximum), (10, 40))
        self.assertEqual(summary.mean, 25.0)
        self.assertEqual(summary.median, 25.0)
        self.assertEqual(summary.p95, 40.0)
        self.assertEqual(summarize_distribution((7,)).p95, 7.0)
        with self.assertRaises(ProfileEvidenceError):
            summarize_distribution(())
        with self.assertRaises(TypeError):
            summarize_distribution((1, True))

    def test_render_window_is_exact_contiguous_and_deterministic(self) -> None:
        records = parse_render_records(
            "\n".join(
                (
                    render_line(9, 900),
                    render_line(10, 1000),
                    render_line(11, 1100),
                    render_line(12, 1200),
                    render_line(13, 1300),
                )
            )
        )

        window = summarize_render_window(
            records,
            first_sequence=10,
            last_sequence=12,
            metric_names=("render_us", "clr", "xf"),
        )

        self.assertEqual(
            (
                window.bitmap_id,
                window.first_sequence,
                window.last_sequence,
                window.frame_count,
            ),
            (257, 10, 12, 3),
        )
        self.assertEqual(window.metric("render_us").total, 3300)
        self.assertEqual(window.metric("render_us").median, 1100.0)
        self.assertEqual(window.metric("render_us").p95, 1200.0)
        self.assertEqual(
            tuple(name for name, _summary in window.metrics),
            ("render_us", "clr", "xf"),
        )

        auto = summarize_render_window(
            records, first_sequence=10, last_sequence=12
        )
        self.assertEqual(
            tuple(name for name, _summary in auto.metrics),
            ("clr", "render_us", "xf"),
        )

    def test_render_window_rejects_gaps_duplicates_and_mixed_bitmaps(self) -> None:
        gap = parse_render_records(
            "\n".join((render_line(10, 1), render_line(12, 2)))
        )
        with self.assertRaisesRegex(ProfileEvidenceError, "not exact and contiguous"):
            summarize_render_window(gap, first_sequence=10, last_sequence=12)

        duplicate = parse_render_records(
            "\n".join((render_line(10, 1), render_line(10, 2)))
        )
        with self.assertRaisesRegex(ProfileEvidenceError, "not exact and contiguous"):
            summarize_render_window(duplicate)

        mixed = parse_render_records(
            "\n".join(
                (render_line(10, 1), render_line(10, 2, bitmap_id=258))
            )
        )
        with self.assertRaisesRegex(ProfileEvidenceError, "multiple bitmap IDs"):
            summarize_render_window(mixed)

    def test_selector_full_state_lines_pair_call_with_post_call(self) -> None:
        contents = "\n".join(
            (
                "* 000100: NOP Cycles since last break: 999",
                "* 05fd96: CALL.L $05f9ac AF:0000 "
                "Cycles since last break: 120 Cycles per instruction: 2.0",
                "* 05fd9a: OR A, A AF:0100 "
                "Cycles since last break: 37 Cycles per instruction: 1.4",
                "* 05FD96: CALL.L $05f9ac AF:0000 "
                "Cycles since last break: 41",
                "* 05FD9A: OR A, A AF:0100 Cycles since last break: 52",
            )
        )

        pairs = parse_selector_cycle_pairs(contents)

        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0].entry.line_number, 2)
        self.assertEqual(pairs[0].entry.cycles_since_last_break, 120)
        self.assertEqual(pairs[0].selector_cycles, 37)
        self.assertEqual(pairs[1].selector_cycles, 52)
        self.assertEqual(
            summarize_distribution(pair.selector_cycles for pair in pairs).total,
            89,
        )

    def test_selector_accepts_fab_following_cycle_detail_line(self) -> None:
        contents = "\n".join(
            (
                "* 05fd96: CALL.L $05f9ac AF:0000",
                "* 05fd96: CALL.L $05f9ac AF:0000",
                "                              Cycles since last break: 400",
                "* 05fd9a: OR A, A AF:0100",
                "* 05fd9a: OR A, A AF:0100",
                "                              Cycles since last break: 73",
            )
        )

        pair = parse_selector_cycle_pairs(contents)[0]

        self.assertEqual(pair.entry.line_number, 2)
        self.assertEqual(pair.entry.cycles_line_number, 3)
        self.assertEqual(pair.post_call.line_number, 5)
        self.assertEqual(pair.post_call.cycles_line_number, 6)
        self.assertEqual(pair.selector_cycles, 73)

    def test_selector_parser_fails_closed_on_incomplete_or_wrong_order(self) -> None:
        cases = {
            "missing state cycles": "* 05fd96: CALL\n* 000100: NOP",
            "post-call first": (
                "* 05fd9a: OR A, A Cycles since last break: 3"
            ),
            "nested entry": (
                "* 05fd96: CALL Cycles since last break: 2\n"
                "* 05fd96: CALL Cycles since last break: 4"
            ),
            "missing post-call": (
                "* 05fd96: CALL Cycles since last break: 2"
            ),
            "malformed cycles": (
                "* 05fd96: CALL Cycles since last break: nope"
            ),
        }
        for description, contents in cases.items():
            with self.subTest(description=description):
                with self.assertRaises(ProfileEvidenceError):
                    parse_selector_cycle_pairs(contents)


if __name__ == "__main__":
    unittest.main()
