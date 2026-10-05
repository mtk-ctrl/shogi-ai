#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))

spec = importlib.util.spec_from_file_location("external_match", BENCHMARKS / "external_match.py")
external_match = importlib.util.module_from_spec(spec)
sys.modules["external_match"] = external_match
spec.loader.exec_module(external_match)

levels_spec = importlib.util.spec_from_file_location("external_levels", BENCHMARKS / "external_levels.py")
external_levels = importlib.util.module_from_spec(levels_spec)
sys.modules["external_levels"] = external_levels
levels_spec.loader.exec_module(external_levels)


class ExternalMatchTest(unittest.TestCase):
    def test_parse_option_name(self):
        self.assertEqual(
            external_match.parse_option_name("option name USI_OwnBook type check default true"),
            "USI_OwnBook",
        )
        self.assertEqual(
            external_match.parse_option_name("option name Eval Dir type string default eval"),
            "Eval Dir",
        )
        self.assertIsNone(external_match.parse_option_name("id name dummy"))

    def test_go_command_validation(self):
        self.assertEqual(external_match.validate_go_command("go movetime 50"), "go movetime 50")
        with self.assertRaises(ValueError):
            external_match.validate_go_command("position startpos")
        with self.assertRaises(ValueError):
            external_match.validate_go_command("go nodes 10\nquit")

    def test_external_output_cannot_enter_selfplay_results(self):
        forbidden = ROOT / "benchmarks" / "results" / "external.json"
        with self.assertRaises(ValueError):
            external_match.validate_output_path(forbidden)

        allowed = ROOT / "benchmarks" / "external-results" / "external.json"
        self.assertEqual(external_match.validate_output_path(allowed), allowed.resolve())

    def test_options_must_be_json_object(self):
        self.assertEqual(
            external_match.parse_json_object('{"Threads":1,"USI_OwnBook":false}', "opponent-options"),
            {"Threads": 1, "USI_OwnBook": False},
        )
        with self.assertRaises(ValueError):
            external_match.parse_json_object("[]", "opponent-options")

    def test_external_level_scale_is_monotonic_and_pinned(self):
        self.assertEqual(external_levels.nodes_for_level(1), 10)
        self.assertEqual(external_levels.nodes_for_level(100), 1_000_000)
        values = [external_levels.nodes_for_level(level) for level in range(1, 101)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(external_levels.nearest_level_for_nodes(100), 21)
        self.assertEqual(external_levels.nearest_level_for_nodes(1_000), 41)
        self.assertEqual(external_levels.nearest_level_for_nodes(10_000), 60)

    def test_external_level_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            external_levels.nodes_for_level(0)
        with self.assertRaises(ValueError):
            external_levels.nodes_for_level(101)
        with self.assertRaises(ValueError):
            external_levels.nearest_level_for_nodes(0)


if __name__ == "__main__":
    unittest.main()
