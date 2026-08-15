from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_regular_lod_runtime as benchmark  # noqa: E402
from pingo_terrain.regular_lod_profile import (  # noqa: E402
    ProfileEvidenceError,
    parse_render_records,
)


def render_line(
    *,
    ti: int = 10,
    tu: int = 4,
    pc: int = 10,
    render_us: int = 100,
    cmd: int = 112,
) -> str:
    return (
        f"PINGO_RENDER seq=7 bmid=257 render_us={render_us} d=4 w=320 h=240 "
        f"fmt=2 far=65535 cmd={cmd} pre=3 "
        "clr=5 xf=20 ts=30 ras=40 out=2 ob=9 obt=8 ofr=7 "
        f"ti={ti} tz=1 tfr=2 tc=3 tu={tu} "
        "tg=10 tp=1 tf=2 td=3 to=0 tr=4 pt=20 "
        f"pc={pc} pz=1 pd=2 pu=3 ps=4"
    )


class RegularLodBenchmarkTests(unittest.TestCase):
    def test_render_conservation_contract_accepts_exact_diagnostics(self) -> None:
        record = parse_render_records(render_line())[0]

        benchmark.validate_render(record)

        derived = benchmark.summarize_derived([record])
        self.assertEqual(
            derived["renderer_unattributed_us"]["samples"], [5]
        )
        self.assertEqual(
            derived["command_unattributed_us"]["samples"], [7]
        )

    def test_render_conservation_contract_rejects_counter_drift(self) -> None:
        for line in (render_line(ti=11), render_line(pc=11)):
            with self.subTest(line=line):
                record = parse_render_records(line)[0]
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.validate_render(record)

    def test_render_contract_rejects_impossible_or_negative_times(self) -> None:
        for line in (
            render_line(render_us=94),
            render_line(cmd=104),
        ):
            with self.subTest(line=line):
                record = parse_render_records(line)[0]
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.validate_render(record)
        with self.assertRaises(ProfileEvidenceError):
            parse_render_records(render_line(render_us=-1))

    def test_handoff_end_uses_radius_make_event(self) -> None:
        contents = (
            "prefix\n"
            "FAB_INPUT frame=10 action=down scancode=0x0025 source=fifo-tap\n"
            "suffix\n"
        )
        self.assertEqual(
            benchmark._handoff_end(contents, {"radius_input": {"radius": 4}}),
            contents.index("FAB_INPUT"),
        )
        self.assertEqual(
            benchmark._handoff_end(contents, {"radius_input": None}),
            len(contents),
        )
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark._handoff_end(
                contents.replace("action=down", "action=up"),
                {"radius_input": {"radius": 4}},
            )

    def test_fixed_scope_constants_pin_three_process_windows(self) -> None:
        self.assertEqual(
            (
                benchmark.COLD_SEQUENCE,
                benchmark.STEADY_FIRST,
                benchmark.STEADY_LAST,
                benchmark.STEADY_FRAMES,
            ),
            (226, 227, 526, 300),
        )
        self.assertEqual(benchmark.EXPECTED_CROSSING_GROUPS, (29, 21, 17, 17))

    def test_cross_run_identity_requires_exact_shared_artifacts(self) -> None:
        common = {
            name: {"sha256": f"{index:064x}"}
            for index, name in enumerate(
                ("program", "vdp", "emulator", "mos"), 1
            )
        }
        trace_only = {
            "symbols": {"sha256": "a" * 64},
            "proxy": {"sha256": "b" * 64},
        }
        stationary = {"identity": dict(common)}
        handoff = {"identity": {**common, **trace_only}}
        selector = {"identity": {**common, **trace_only}}

        observed = benchmark.validate_cross_run_identity(
            stationary, handoff, selector
        )

        self.assertEqual(observed["program"], common["program"]["sha256"])
        selector["identity"]["program"] = {"sha256": "f" * 64}
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.validate_cross_run_identity(
                stationary, handoff, selector
            )


if __name__ == "__main__":
    unittest.main()
