from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/qualify_regular_lod_crc_production_errors.py"


def load_qualifier():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    specification = importlib.util.spec_from_file_location(
        "qualify_regular_lod_crc_production_errors", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


qualifier = load_qualifier()


class ProductionCrcErrorQualifierTests(unittest.TestCase):
    def test_exact_tool_identity_gate_rejects_one_byte_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "tool.bin"
            payload = b"qualified-tool"
            tool.write_bytes(payload)
            qualifier.require_content_identity(
                tool,
                expected_bytes=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                description="test tool",
            )
            tool.write_bytes(payload[:-1] + bytes((payload[-1] ^ 1,)))
            with self.assertRaisesRegex(
                qualifier.ProductionCrcError, "identity changed"
            ):
                qualifier.require_content_identity(
                    tool,
                    expected_bytes=len(payload),
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                    description="test tool",
                )

    def test_cli_requires_explicit_program_symbols_and_output(self) -> None:
        arguments = qualifier.arguments(
            [
                "--program",
                "runtime.bin",
                "--symbols",
                "runtime.symbols",
                "--output",
                "evidence",
            ]
        )
        self.assertEqual(arguments.program, Path("runtime.bin"))
        self.assertEqual(arguments.symbols, Path("runtime.symbols"))
        self.assertEqual(arguments.output, Path("evidence"))
        self.assertEqual(arguments.timeout, 120.0)

    def test_negative_result_gate_requires_both_exact_fresh_witnesses(self) -> None:
        runs = [
            {
                "kind": "crc-data",
                "fresh_process": True,
                "guest_executed": True,
                "guest_error": 9,
                "mesh_publications_before_rejection": 0,
                "cold_endpoint_reached": False,
                "emulator_exit_status": 0,
                "first_breakpoint": 0x123456,
                "return_error_address": 0x123456,
                "crc_entry_address": 0x111111,
            },
            {
                "kind": "index-valid-crc",
                "fresh_process": True,
                "guest_executed": True,
                "guest_error": 10,
                "mesh_publications_before_rejection": 0,
                "cold_endpoint_reached": False,
                "emulator_exit_status": 0,
                "first_breakpoint": 0x123456,
                "return_error_address": 0x123456,
                "crc_entry_address": 0x111111,
            },
        ]
        self.assertEqual(
            list(qualifier.validate_negative_results(runs)),
            list(qualifier.NEGATIVE_KINDS),
        )
        damaged = [dict(item) for item in runs]
        damaged[1]["first_breakpoint"] = damaged[1]["crc_entry_address"]
        with self.assertRaisesRegex(qualifier.ProductionCrcError, "incomplete"):
            qualifier.validate_negative_results(damaged)

    def test_main_launches_exactly_two_runs_and_writes_small_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "P3DRGL.BIN"
            symbols = root / "P3DRGL.symbols"
            vdp = root / "vdp.so"
            for path in (program, symbols, vdp):
                path.write_bytes(path.name.encode("ascii"))
            output = root / "evidence"
            identity = {"program": {"sha256": "production"}}
            inputs = qualifier.ValidatedInputs(program, symbols, vdp, identity)

            calls: list[str] = []

            def fake_run_negative(**kwargs):
                kind = kwargs["kind"]
                calls.append(kind)
                return {
                    "kind": kind,
                    "fresh_process": True,
                    "guest_executed": True,
                    "guest_error": qualifier.EXPECTED_ERRORS[kind],
                    "mesh_publications_before_rejection": 0,
                    "cold_endpoint_reached": False,
                    "emulator_exit_status": 0,
                    "first_breakpoint": 0x123456,
                    "return_error_address": 0x123456,
                    "crc_entry_address": 0x111111,
                }

            with (
                mock.patch.object(
                    qualifier, "validate_inputs", side_effect=[inputs, inputs]
                ),
                mock.patch.object(
                    qualifier.crc_profile,
                    "run_negative",
                    side_effect=fake_run_negative,
                ) as runner,
            ):
                status = qualifier.main(
                    [
                        "--program",
                        str(program),
                        "--symbols",
                        str(symbols),
                        "--vdp-module",
                        str(vdp),
                        "--output",
                        str(output),
                        "--timeout",
                        "17",
                    ]
                )

            self.assertEqual(status, 0)
            self.assertEqual(calls, list(qualifier.NEGATIVE_KINDS))
            self.assertEqual(runner.call_count, 2)
            for call in runner.call_args_list:
                self.assertEqual(call.kwargs["program"], program)
                self.assertEqual(call.kwargs["symbols_path"], symbols)
                self.assertEqual(call.kwargs["vdp"], vdp)
                self.assertEqual(call.kwargs["output"], output)
                self.assertEqual(call.kwargs["timeout"], 17.0)

            report = json.loads(
                output.joinpath(qualifier.REPORT_NAME).read_text(encoding="utf-8")
            )
            self.assertTrue(report["qualified"])
            self.assertEqual(report["scope"]["process_count"], 2)
            self.assertTrue(report["scope"]["stock_mos"])
            self.assertEqual(report["identity"], identity)
            self.assertEqual(
                set(report["negative_qualification"]),
                {
                    "crc_data_guest_error_9_no_publication",
                    "invalid_index_valid_crc_guest_error_10_before_crc",
                },
            )


if __name__ == "__main__":
    unittest.main()
