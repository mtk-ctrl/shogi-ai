#!/usr/bin/env python3
"""Regression checks for official stage splitting and immutable study handoff."""
from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nn"))
from select_disagreements import official_maturity, PhaseProbe, norm, validate_history
from study_disagreements import read_selection, aggregate


class NNDisagreementTests(unittest.TestCase):
    def test_adopted_phase_formula(self):
        self.assertEqual(official_maturity(0, 0, 0), (0, "opening"))
        self.assertEqual(official_maturity(100, 100, 100), (95, "end"))
        self.assertEqual(official_maturity(45, 50, 45)[1], "middle")
        self.assertRaises(ValueError, official_maturity, -1, 50, 30)

    def test_probe_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            program = Path(d) / "phase"
            program.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "for line in sys.stdin:\n"
                " print('phase development 45 battle 50 invasion 45 king_threat 8 progress 49', flush=True)\n")
            program.chmod(0o755)
            probe = PhaseProbe(program)
            try:
                maturity, stage, components = probe.classify(shogi.Board().sfen())
                self.assertEqual(stage, "middle")
                self.assertEqual(components["king_threat"], 8)
                self.assertEqual(maturity, official_maturity(45, 50, 45)[0])
            finally:
                probe.close()

    def test_selection_validation_and_nonautomatic_aggregation(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            source = folder / "selection.json"
            positions = []
            rng = random.Random(50)
            for stage in ("opening", "middle", "end"):
                for i in range(10):
                    board = shogi.Board()
                    moves = []
                    for _ in range(4 + i * 2):
                        possible = list(board.legal_moves)
                        move = possible[rng.randrange(len(possible))]
                        moves.append(move.usi())
                        board.push(move)
                    positions.append({"id": stage + str(i), "stage": stage,
                                      "history_moves": moves, "sfen": norm(board.sfen()),
                                      "nn_probability_black": .8,
                                      "static_cp_black": -200})
            source.write_text(json.dumps({
                "schema": "nn-disagreement-selection-v1",
                "positions": positions
            }))
            read_selection(source)
            validate_history(positions[0])
            folder_results = folder / "research-results" / "lane0"
            folder_results.mkdir(parents=True)
            row = positions[0]
            (folder_results / "result.json").write_text(json.dumps({
                "id": row["id"], "sfen": row["sfen"],
                "history_moves": row["history_moves"],
                "completed": True, "bestmove": "7g7f",
                "final": {"score_type": "cp", "score_value": 150}
            }))
            report = aggregate(source, folder / "research-results", folder / "report")
            self.assertEqual(report["expected"], 30)
            self.assertEqual(report["received"], 1)
            self.assertEqual(report["completed"], 1)
            self.assertEqual(len(report["missing"]), 29)
            self.assertFalse(report["position_knowledge_automatically_adopted"])
            self.assertEqual(report["per_stage"]["opening"]["deep_cp_available"], 1)
            self.assertTrue((folder / "report" / "research.json.gz").is_file())
            positions[0]["history_moves"] = ["1a1b"]
            source.write_text(json.dumps({
                "schema": "nn-disagreement-selection-v1", "positions": positions
            }))
            with self.assertRaises(ValueError):
                read_selection(source)


if __name__ == "__main__":
    unittest.main()
