import copy
import json
from pathlib import Path
import tempfile
import unittest

import shogi

from tools.research.postgame_candidates import accepted_record, build


def case():
    return {
        "route": "stable_research_move_candidate",
        "research_move": "2g2f",
        "root_short": {"bestmove": "2g2f"},
        "root_deep": {"bestmove": "2g2f", "kind": "cp", "value_stm": 10},
        "followup": {
            "requested_depth": 3,
            "actual": {"depth": 3, "kind": "cp", "bound": "exact"},
            "research": {"depth": 3, "kind": "cp", "bound": "exact"},
            "comparison": {"status": "comparable", "improvement_cp": 151},
        },
        "case": {
            "case_id": "a" * 64,
            "start_sfen": shogi.STARTING_SFEN,
            "history_moves": [],
            "position_key": " ".join(shogi.Board().sfen().split()[:3]),
            "actual_move": "7g7f",
            "source": {"run_id": 1, "game_id": "g", "ply": 1},
            "outcome": {"terminal_reward_stm": -1},
        },
    }


class CandidateTest(unittest.TestCase):
    def test_strict_stable_gate_and_full_history_line(self):
        line, evidence = accepted_record(case(), "g1")
        self.assertIn("\tresearch_decision\t", line)
        self.assertTrue(line.endswith("\t-"))
        self.assertEqual(evidence["confirmed_improvement_cp"], 151)
        for mutation in ("short", "improvement", "bound", "depth", "route"):
            row = copy.deepcopy(case())
            if mutation == "short": row["root_short"]["bestmove"] = "7g7f"
            elif mutation == "improvement": row["followup"]["comparison"]["improvement_cp"] = 149
            elif mutation == "bound": row["followup"]["actual"]["bound"] = "lower"
            elif mutation == "depth": row["followup"]["actual"]["depth"] = 2
            else: row["route"] = "hold"
            with self.assertRaises(ValueError):
                accepted_record(row, "g1")

    def test_build_keeps_parent_unchanged_and_records_no_eval_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diagnosis = root / "diagnosis.json"
            diagnosis.write_text(json.dumps([case()]))
            key = case()["case"]["position_key"]
            # The production gate requires exactly 163 unique parent positions.
            rows = [f"key{i} b -\t7g7f\tbase\t1" for i in range(163)]
            base = root / "base.tsv"
            base.write_text("# position-knowledge-v1-active\n" + "\n".join(rows) + "\n")
            out, manifest = root / "candidate.tsv", root / "manifest.json"
            report = build(diagnosis, base, out, manifest, "g1")
            self.assertEqual(report["candidate_positions"], 1)
            self.assertEqual(report["combined_positions"], 164)
            self.assertFalse(report["evaluation_candidate"]["created"])
            self.assertEqual(base.read_text().count("\n"), 164)
            self.assertIn(key, out.read_text())


if __name__ == "__main__":
    unittest.main()
