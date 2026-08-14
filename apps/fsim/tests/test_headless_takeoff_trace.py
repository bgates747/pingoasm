from __future__ import annotations

import argparse
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

INPUT_SPEC = importlib.util.spec_from_file_location(
    "trace_koak_input", SCRIPTS / "trace_koak_input.py"
)
assert INPUT_SPEC is not None and INPUT_SPEC.loader is not None
input_trace = importlib.util.module_from_spec(INPUT_SPEC)
INPUT_SPEC.loader.exec_module(input_trace)
sys.modules["trace_koak_input"] = input_trace

TAKEOFF_SPEC = importlib.util.spec_from_file_location(
    "trace_koak_takeoff", SCRIPTS / "trace_koak_takeoff.py"
)
assert TAKEOFF_SPEC is not None and TAKEOFF_SPEC.loader is not None
trace = importlib.util.module_from_spec(TAKEOFF_SPEC)
TAKEOFF_SPEC.loader.exec_module(trace)


def store_signed(data: bytearray, offset: int, value: int, width: int) -> None:
    data[offset : offset + width] = value.to_bytes(
        width, "little", signed=True
    )


def store_vector(data: bytearray, offset: int, values: tuple[int, int, int]) -> None:
    for axis, value in enumerate(values):
        store_signed(data, offset + axis * 2, value, 2)


def synthetic_snapshot() -> tuple[dict[int, int], dict[str, int]]:
    symbols = {
        "flight_state": 0x102030,
        "object_state": 0x203040,
        "streaming_coarse_x": 0x304050,
    }
    flight = bytearray(trace.STATE_LENGTH)
    ground_q8 = 44 * 256
    positions = (
        3088 * 256 + 300 * 4096,
        ground_q8 + 10 * 4096,
        2181 * 256 - 40 * 4096,
    )
    for axis, value in enumerate(positions):
        store_signed(flight, axis * 3, value, 3)
    store_signed(flight, 9, ground_q8, 3)
    for offset, values in (
        (12, (120, 34, 4567)),
        (18, (-1, 2, -3)),
        (24, (4, -5, 6)),
        (30, (-7, 8, -9)),
        (36, (10, -11, 12)),
        (42, (-13, 14, -15)),
    ):
        store_vector(flight, offset, values)
    store_signed(flight, 66, 4001, 2)
    store_signed(flight, 68, 37, 2)
    store_signed(flight, 70, 28, 2)
    flight[72:77] = bytes((255, 0xFE, 3, 0xFC, 0))

    object_data = bytearray(trace.OBJECT_LENGTH)
    store_vector(object_data, 10, (-2739, 203, -84))
    store_vector(object_data, 16, (-15616, -1920, -16384))
    store_vector(object_data, 52, (0, 1, -2))

    memory: dict[int, int] = {}
    for address, data in (
        (symbols["flight_state"], flight),
        (symbols["object_state"], object_data),
        (symbols["streaming_coarse_x"], bytes((94, 146))),
    ):
        memory.update(
            (address + offset, value) for offset, value in enumerate(data)
        )
    return memory, symbols


def arguments(counter_vblanks: int = 0) -> argparse.Namespace:
    return argparse.Namespace(
        pitch_delay_vblanks=380,
        pull_vblanks=8,
        counter_vblanks=counter_vblanks,
    )


def qualifying_records(counter_vblanks: int = 0):
    records = [
        {
            "host_vblank": 100,
            "action": "down",
            "scancode": input_trace.SET2_CODES["V"],
            "source": "fifo-tap",
        },
        {
            "host_vblank": 100,
            "action": "down",
            "scancode": input_trace.SET2_CODES["W"],
            "source": "fifo",
        },
        {
            "host_vblank": 104,
            "action": "up",
            "scancode": input_trace.SET2_CODES["V"],
            "source": "tap-release",
        },
        {
            "host_vblank": 480,
            "action": "down",
            "scancode": input_trace.SET2_CODES["DOWN"],
            "source": "tapafter-make",
        },
        {
            "host_vblank": 488,
            "action": "up",
            "scancode": input_trace.SET2_CODES["DOWN"],
            "source": "tapafter-release",
        },
        {
            "host_vblank": 900,
            "action": "up",
            "scancode": input_trace.SET2_CODES["W"],
            "source": "fifo",
        },
    ]
    if counter_vblanks:
        records.extend(
            (
                {
                    "host_vblank": 488,
                    "action": "down",
                    "scancode": input_trace.SET2_CODES["UP"],
                    "source": "tapafter-make",
                },
                {
                    "host_vblank": 488 + counter_vblanks,
                    "action": "up",
                    "scancode": input_trace.SET2_CODES["UP"],
                    "source": "tapafter-release",
                },
            )
        )
    return records


class HeadlessTakeoffTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        memory, symbols = synthetic_snapshot()
        self.state = trace.decode_state(memory, symbols)

    def test_debugger_memory_parser_strips_ansi_and_latest_byte_wins(self) -> None:
        contents = (
            "\x1b[31m>> 102030: 01 fe 7f \x1b[0m\n"
            "unrelated debugger text\n"
            "102031: aa bb \n"
        )
        self.assertEqual(
            trace.parse_memory(contents),
            {0x102030: 0x01, 0x102031: 0xAA, 0x102032: 0xBB},
        )
        with self.assertRaisesRegex(SystemExit, "omitted address 0x102033"):
            trace.read_span(trace.parse_memory(contents), 0x102030, 4)

    def test_snapshot_decode_preserves_fixed_width_signs_and_units(self) -> None:
        self.assertEqual(self.state["position_q8"], [2019328, 52224, 394496])
        self.assertEqual(self.state["velocity_q8"], [120, 34, 4567])
        self.assertEqual(self.state["force_q8"], [-1, 2, -3])
        self.assertEqual(self.state["acceleration_q8"], [4, -5, 6])
        self.assertEqual(self.state["angular_acceleration"], [-7, 8, -9])
        self.assertEqual(self.state["body_velocity_q8"], [10, -11, 12])
        self.assertEqual(self.state["local_force_q8"], [-13, 14, -15])
        self.assertEqual(self.state["controls"], {"pitch": -2, "roll": 3, "yaw": -4})
        self.assertEqual(self.state["coarse_cell"], [94, 146])
        self.assertEqual(self.state["displacement_m"], [300.0, -40.0])
        self.assertAlmostEqual(self.state["height_agl_m"], 10.0)
        self.assertAlmostEqual(self.state["horizontal_distance_m"], 302.654919)
        self.assertEqual(self.state["object_world_position_counts"], [-2739, 203, -84])
        self.assertEqual(self.state["object_local_angular_velocity"], [0, 1, -2])
        self.assertEqual(self.state["object_pingo_rotation_degrees"][-1], -180.0)

    def test_atomic_command_batch_has_one_common_fifo_write(self) -> None:
        commands = ("tap 0x002a 4", "down 0x001d", "tapafter 0xe072 380 8")
        payload = b"tap 0x002a 4\ndown 0x001d\ntapafter 0xe072 380 8\n"
        with mock.patch.object(trace.os, "write", return_value=len(payload)) as write:
            trace.write_command_batch(17, list(commands))
        write.assert_called_once_with(17, payload)

        with mock.patch.object(trace.os, "write", return_value=1):
            with self.assertRaisesRegex(SystemExit, "Short input FIFO write"):
                trace.write_command_batch(17, ["down 0x001d"])
        for commands in ([], ["down 0x001d\nup 0x001d"], ["x" * 513]):
            with self.subTest(commands=commands):
                with self.assertRaises(SystemExit):
                    trace.write_command_batch(17, commands)

    def test_takeoff_validation_accepts_exact_schedule_and_counter_pulse(self) -> None:
        self.assertEqual(
            trace.validate_takeoff(self.state, qualifying_records(), arguments()),
            {
                "view_to_power": 0,
                "v_hold": 4,
                "pitch_delay": 380,
                "pull_hold": 8,
            },
        )
        self.assertEqual(
            trace.validate_takeoff(
                self.state, qualifying_records(3), arguments(3)
            ),
            {
                "view_to_power": 0,
                "v_hold": 4,
                "pitch_delay": 380,
                "pull_hold": 8,
                "counter_start": 388,
                "counter_hold": 3,
            },
        )

    def test_takeoff_validation_rejects_timing_source_and_state_failures(self) -> None:
        bad_timing = copy.deepcopy(qualifying_records())
        bad_timing[3]["host_vblank"] = 481
        with self.assertRaisesRegex(SystemExit, "Input timing changed"):
            trace.validate_takeoff(self.state, bad_timing, arguments())

        bad_source = copy.deepcopy(qualifying_records())
        bad_source[3]["source"] = "fifo"
        with self.assertRaisesRegex(SystemExit, "down_down came from fifo"):
            trace.validate_takeoff(self.state, bad_source, arguments())

        for field, value, message in (
            ("arithmetic_failure", True, "arithmetic failure"),
            ("on_ground", True, "remained on runway"),
            ("airspeed_q8", 3199, "takeoff speed"),
            ("height_agl_m", 0.0, "did not climb"),
            ("horizontal_distance_m", 249.9, "takeoff distance"),
        ):
            with self.subTest(field=field):
                bad_state = dict(self.state)
                bad_state[field] = value
                with self.assertRaisesRegex(SystemExit, message):
                    trace.validate_takeoff(
                        bad_state, qualifying_records(), arguments()
                    )

    def test_takeoff_validation_rejects_duplicate_control_events(self) -> None:
        records = qualifying_records()
        records.append(copy.deepcopy(records[0]))
        with self.assertRaisesRegex(SystemExit, "found 2"):
            trace.validate_takeoff(self.state, records, arguments())


if __name__ == "__main__":
    unittest.main()
