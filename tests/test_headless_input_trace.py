from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/trace_koak_input.py"
SPEC = importlib.util.spec_from_file_location("trace_koak_input", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
trace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trace)


class HeadlessInputTraceTests(unittest.TestCase):
    def test_fab_input_records_retain_vblank_make_break_and_extended_code(self):
        contents = "\n".join(
            (
                "FAB_INPUT frame=100 action=down scancode=0x002a "
                "source=fifo-tap",
                "FAB_INPUT frame=104 action=up scancode=0x002a "
                "source=tap-release",
                "FAB_INPUT frame=108 action=down scancode=0xe075 "
                "source=fifo",
            )
        )
        self.assertEqual(
            trace.input_records(contents),
            [
                {
                    "host_vblank": 100,
                    "action": "down",
                    "scancode": 0x002A,
                    "source": "fifo-tap",
                },
                {
                    "host_vblank": 104,
                    "action": "up",
                    "scancode": 0x002A,
                    "source": "tap-release",
                },
                {
                    "host_vblank": 108,
                    "action": "down",
                    "scancode": 0xE075,
                    "source": "fifo",
                },
            ],
        )

    def test_control_set_uses_fab_ps2_set2_codes(self):
        self.assertEqual(
            trace.SET2_CODES,
            {
                "W": 0x001D,
                "S": 0x001B,
                "A": 0x001C,
                "D": 0x0023,
                "V": 0x002A,
                "UP": 0xE075,
                "DOWN": 0xE072,
                "LEFT": 0xE06B,
                "RIGHT": 0xE074,
                "ESCAPE": 0x0076,
            },
        )

    def test_proxy_build_exports_the_complete_current_fab_vdp_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vdp_input_trace_proxy.so"
            exports = trace.build_proxy(trace.PROXY_SOURCE, output)
            self.assertTrue(output.is_file())
            self.assertTrue(trace.REQUIRED_PROXY_EXPORTS.issubset(exports))

    def test_tapafter_emits_exact_delayed_make_and_break_vblanks(self):
        fake_source = r"""
#include <stddef.h>
#include <stdint.h>

static uint16_t event_codes[8];
static uint8_t event_down[8];
static size_t event_count;

void vdp_setup(void) {}
void signal_vblank(void) {}
void sendPS2KbEventToFabgl(uint16_t code, uint8_t down) {
    if (event_count < 8) {
        event_codes[event_count] = code;
        event_down[event_count] = down;
        ++event_count;
    }
}
size_t fake_event_count(void) { return event_count; }
uint16_t fake_event_code(size_t index) { return event_codes[index]; }
uint8_t fake_event_down(size_t index) { return event_down[index]; }
"""
        child = r"""
import ctypes
import json
import os

fifo = os.environ["TEST_INPUT_FIFO"]
control = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
fake = ctypes.CDLL(os.environ["FAB_INPUT_REAL_VDP"])
proxy = ctypes.CDLL(os.environ["TEST_INPUT_PROXY"])
fake.fake_event_count.restype = ctypes.c_size_t
fake.fake_event_code.argtypes = [ctypes.c_size_t]
fake.fake_event_code.restype = ctypes.c_uint16
fake.fake_event_down.argtypes = [ctypes.c_size_t]
fake.fake_event_down.restype = ctypes.c_uint8
proxy.vdp_setup()
os.write(control, b"tapafter 0xe072 3 2\n")
events = []
seen = 0
for frame in range(1, 7):
    proxy.signal_vblank()
    count = fake.fake_event_count()
    while seen < count:
        events.append([
            frame,
            fake.fake_event_code(seen),
            fake.fake_event_down(seen),
        ])
        seen += 1
print(json.dumps(events))
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proxy = root / "vdp_input_trace_proxy.so"
            trace.build_proxy(trace.PROXY_SOURCE, proxy)
            source = root / "fake_vdp.c"
            source.write_text(fake_source, encoding="ascii")
            real_vdp = root / "fake_vdp.so"
            subprocess.run(
                [
                    "cc",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-fPIC",
                    "-shared",
                    str(source),
                    "-o",
                    str(real_vdp),
                ],
                check=True,
            )
            fifo = root / "input.fifo"
            os.mkfifo(fifo)
            environment = os.environ.copy()
            environment.update(
                {
                    "FAB_INPUT_REAL_VDP": str(real_vdp),
                    "FAB_INPUT_FIFO": str(fifo),
                    "TEST_INPUT_FIFO": str(fifo),
                    "TEST_INPUT_PROXY": str(proxy),
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", child],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
        self.assertEqual(
            json.loads(result.stdout),
            [[4, 0xE072, 1], [6, 0xE072, 0]],
        )
        self.assertIn(
            "FAB_INPUT frame=4 action=down scancode=0xe072 "
            "source=tapafter-make",
            result.stderr,
        )
        self.assertIn(
            "FAB_INPUT frame=6 action=up scancode=0xe072 "
            "source=tapafter-release",
            result.stderr,
        )

    def test_fatal_proxy_and_runtime_markers_are_rejected(self):
        for marker in trace.FATAL_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, trace.find_failures(marker))


if __name__ == "__main__":
    unittest.main()
