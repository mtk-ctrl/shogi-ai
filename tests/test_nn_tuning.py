#!/usr/bin/env python3
"""Synthetic, reproducible smoke test of NN validation-only selection."""
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nn"))
from tune import run


class TuningTests(unittest.TestCase):
    def test_selects_validation_model_and_writes_report(self):
        rng = random.Random(20261011)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "examples.jsonl"
            with source.open("w") as f:
                for game in range(15):
                    board = shogi.Board()
                    outcome = float(game % 2)
                    for ply in range(30):
                        f.write(json.dumps({
                            "game_id": f"synthetic-{game}",
                            "source": "kumoji_selfplay",
                            "sfen": board.sfen(),
                            "ply": ply + 1,
                            "target_black": outcome,
                            "static_cp_black": ((game % 3) - 1) * 100,
                        }) + "\n")
                        legal = list(board.legal_moves)
                        board.push(legal[rng.randrange(len(legal))])
            out = Path(folder) / "out"
            report = run(source, out, seed=20261011)
            self.assertEqual(report["chosen_profile"]["validation_brier"],
                             min(c["validation_brier"] for c in report["candidate_profiles"]))
            self.assertTrue((out / "position-net-v1.npz").is_file())
            self.assertTrue((out / "tuning-report.json").is_file())
            self.assertGreater(report["metrics"]["test"]["positions"], 0)


if __name__ == "__main__":
    unittest.main()
