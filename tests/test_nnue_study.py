#!/usr/bin/env python3
"""Low-cost deterministic research-control tests: no 50-minute searches."""
import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from tools.research import nnue_deep_study


def case():
    board = shogi.Board()
    return {
        "case_id": "t1", "start_sfen": board.sfen(), "history_moves": [],
        "actual_move": "7g7f", "analysis_position_command": "position sfen " + board.sfen(),
        "source": {"game_id": "selfplay-game-1"},
    }


class FakeAnalyzer:
    requests = []
    def __init__(self, *_, **__):
        pass
    def search(self, start, history, ms):
        self.requests.append((tuple(history), ms))
        selected = "7g7f" if ms == 50 else "2g2f"
        return {"bestmove": selected, "status": "recorded", "kind": "cp",
                "bound": "exact", "pv_head_matches": True, "depth": 4,
                "value_stm": 100, "requested_ms": ms,
                "position_command": "position sfen " + start}
    def close(self):
        pass


class StudyControl(unittest.TestCase):
    def setUp(self):
        FakeAnalyzer.requests.clear()

    def test_loss_signal_selects_sharp_played_move_but_not_training_label(self):
        rows = [{"move": "7g7f", "search": {
            "score_status": "recorded", "score_cp_stm": 0}}
            for _ in range(24)]
        # Before ply 11 the mover likes the position; the other side then
        # suddenly likes it even more. Actor loss signal = 240+270.
        rows[10]["search"]["score_cp_stm"] = 240
        rows[11]["search"]["score_cp_stm"] = 270
        g = types.SimpleNamespace(row={"game_id": "g", "moves": rows},
                                  moves=rows, outcome_status="verified_win_loss")
        def fake_case(game, ply):
            return {"source": {"game_id": "g"}, "position_key": str(ply),
                    "case_id": f"c-{ply}", "actual_move": "7g7f"}
        with patch.object(nnue_deep_study, "make_case", fake_case):
            chosen = nnue_deep_study.choose([g], 1, 4, {"g"})
        self.assertEqual(chosen[0]["case_id"], "c-11")
        self.assertEqual(chosen[0]["triage"]["reason"], "suspected_loss")
        self.assertEqual(chosen[0]["triage"]["observed_actor_drop_cp"], 510)
        # The same score is not an exact cp teacher and is never copied there.
        self.assertNotIn("cp_black", chosen[0])

    def test_disagreement_uses_long_analysis_and_equal_child_budget(self):
        with patch.object(nnue_deep_study, "Analyzer", FakeAnalyzer):
            result = nnue_deep_study.analyze(
                "unused", "unused", case(), 50, 600000, 3000000, 600000, 163)
        self.assertEqual(result["status"], "studied_and_compared")
        self.assertEqual(result["root_deep"]["requested_ms"], 3000000)
        self.assertEqual(FakeAnalyzer.requests, [
            ((), 50), ((), 600000), ((), 3000000),
            (("7g7f",), 600000), (("2g2f",), 600000)])
        self.assertEqual(result["research_budget_requested_ms"],
                         50 + 600000 + 3000000 + 2*600000)

    def test_matching_fast_and_medium_skips_long_budget(self):
        class Stable(FakeAnalyzer):
            def search(self, start, history, ms):
                result = super().search(start, history, ms)
                result["bestmove"] = "7g7f"
                return result
        with patch.object(nnue_deep_study, "Analyzer", Stable):
            result = nnue_deep_study.analyze(
                "unused", "unused", case(), 50, 600000, 3000000, 600000, 163)
        self.assertEqual(FakeAnalyzer.requests, [((), 50), ((), 600000)])
        self.assertEqual(result["status"], "studied")
        self.assertEqual(result["research_budget_requested_ms"], 600050)

    def test_checkpoint_recovers_completed_case_and_rejects_changed_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            eng, know = directory / "engine", directory / "adopted-knowledge"
            eng.write_bytes(b"fixture engine")
            know.write_bytes(b"fixture knowledge")
            c = case()
            class Game:
                row = {"game_id": "selfplay-game-1", "moves": [1]*12}
                outcome_status = "verified_win_loss"
                archive_sha256 = "a"*64
            with patch.object(nnue_deep_study, "load_archive", return_value=[Game()]), \
                 patch.object(nnue_deep_study, "choose", return_value=[c]), \
                 patch.object(nnue_deep_study, "analyze", return_value={
                     "case": c, "status": "studied", "root_deep": {},
                     "research_budget_requested_ms": 200}):
                out = directory / "resume.json"
                first = nnue_deep_study.execute(
                    [directory], eng, know, out,
                    max_cases=1, medium_ms=500, long_ms=1000,
                    branch_ms=500)
                second = nnue_deep_study.execute(
                    [directory], eng, know, out,
                    max_cases=1, medium_ms=500, long_ms=1000,
                    branch_ms=500)
                self.assertEqual(first["case_ids"], second["case_ids"])
                self.assertEqual(len(second["results"]), 1)
                with self.assertRaisesRegex(ValueError, "changed"):
                    nnue_deep_study.execute([directory], eng, know, out,
                                            max_cases=1, medium_ms=600,
                                            long_ms=1000, branch_ms=500)


if __name__ == "__main__":
    unittest.main()
