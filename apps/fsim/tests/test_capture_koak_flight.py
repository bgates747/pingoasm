from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/capture_koak_flight.py"
SPEC = importlib.util.spec_from_file_location("capture_koak_flight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class CaptureKOAKFlightTests(unittest.TestCase):
    def test_sequences_require_first_and_later_unique_frames(self):
        self.assertEqual(capture.parse_sequences("30,0"), (0, 30))
        for invalid in ("0", "1,2", "0,0", "0,-1", "x,1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(argparse.ArgumentTypeError):
                    capture.parse_sequences(invalid)

    def test_stream_evidence_requires_complete_direct_mapped_scene(self):
        lines = []
        for mesh_id in (*range(1, 26), 101, 102):
            lines.append(
                "PINGO_STREAM mesh_replace=ok stage=29696 "
                f"mid={mesh_id} bytes=100 v=3 i=3 u=1 t=3 us=50"
            )
            lines.append(
                f"PINGO_STREAM object_active=ok oid={mesh_id} active=1"
            )
        lines.append("PINGO_STREAM object_active=ok oid=201 active=0")
        evidence = capture.parse_stream_evidence("\n".join(lines))
        self.assertEqual(evidence["missing_mesh_ids"], [])
        self.assertEqual(evidence["unexpected_mesh_ids"], [])
        self.assertEqual(evidence["inactive_expected_object_ids"], [])
        self.assertEqual(evidence["unexpected_active_object_ids"], [])
        self.assertFalse(evidence["aircraft_object_active"])
        self.assertEqual(evidence["mesh_replace_count"], 27)

    def test_frame_analysis_correlates_color_and_depth(self):
        pixels = capture.WIDTH * capture.HEIGHT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "frame.rgba2"
            depth = root / "frame.z32le"
            raw.write_bytes(bytes([0, 1]) + bytes(pixels - 2))
            depth.write_bytes(
                b"\0\0\0\0" + (7).to_bytes(4, "little") + bytes((pixels - 2) * 4)
            )
            evidence = capture.analyze_frame(raw, depth)
        self.assertEqual(evidence["nonzero_color_pixels"], 1)
        self.assertEqual(evidence["populated_depth_pixels"], 1)
        self.assertEqual(evidence["minimum_nonzero_depth_u32"], 7)
        self.assertEqual(evidence["maximum_nonzero_depth_u32"], 7)

    def test_known_protocol_and_scene_failures_are_rejected(self):
        for marker in capture.FATAL_LOG_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, capture.find_log_failures(marker))
        failure = "PINGO_DUMP seq=30 bmid=257 status=failed"
        self.assertIn(failure, capture.find_log_failures(failure))

    def test_vdp_must_contain_stream_scene_and_dump_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / "vdp_combined.so"
            module.write_bytes(b"\0".join(capture.REQUIRED_VDP_DIAGNOSTIC_MARKERS))
            capture.require_diagnostic_vdp(module)
            module.write_bytes(capture.REQUIRED_VDP_DIAGNOSTIC_MARKERS[0])
            with self.assertRaises(SystemExit):
                capture.require_diagnostic_vdp(module)


if __name__ == "__main__":
    unittest.main()
