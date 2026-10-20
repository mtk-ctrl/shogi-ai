"""Verify the controller and algorithm fingerprints for a frozen spiral plan."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SpiralFreezePreflight(unittest.TestCase):
    def test_controller_and_algorithm_hashes(self):
        path = ROOT / '.github/scripts/run_postgame_spiral.py'
        spec = importlib.util.spec_from_file_location('postgame_spiral_freeze', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        values = {'controller_sha256': module.code_hash(),
                  'algorithm_sha256': module.algorithm_hash()}
        self.assertEqual(64, len(values['controller_sha256']))
        self.assertEqual(64, len(values['algorithm_sha256']))
        print('SIX_HOUR_HASHES ' + json.dumps(values, sort_keys=True), flush=True)
