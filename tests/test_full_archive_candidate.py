"""Conservative full-archive reuse: only replay-validated completed old studies become hints."""
import importlib.util
from pathlib import Path
import unittest
import shogi

FILE=Path(__file__).resolve().parents[1]/"research/long-study/full-match-20261031/build_full_candidate.py"
spec=importlib.util.spec_from_file_location("full_study_candidate",FILE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ArchiveCandidateTests(unittest.TestCase):
    def sample(self):
        board=shogi.Board()
        board.push_usi("7g7f")
        return dict(record=dict(completed=True,research_ms_requested=3000000,
             elapsed_seconds=3001.0,sfen=" ".join(board.sfen().split()[:3]),
             history_moves=["7g7f"],bestmove="7c7d",
             final=dict(depth=8,nodes=12000,score_type="cp",score_value=42)))

    def test_legal_old_study_accepted_as_hint_source(self):
        parsed, reason=module.extract_legacy(self.sample())
        self.assertIsNone(reason)
        self.assertEqual(parsed["move"],"7c7d")
        self.assertEqual(parsed["depth"],8)

    def test_fabricated_unreplayable_position_rejected(self):
        case=self.sample()
        case["record"]["sfen"]="9/9/9/9/9/9/9/9/9 b -"
        parsed,reason=module.extract_legacy(case)
        self.assertIsNone(parsed)
        self.assertEqual(reason,"position_history_mismatch")

    def test_short_or_incomplete_study_not_automatically_used(self):
        case=self.sample()
        case["record"]["research_ms_requested"]=60000
        parsed,reason=module.extract_legacy(case)
        self.assertIsNone(parsed)
        self.assertEqual(reason,"not_50_minute_study")
        case=self.sample()
        case["record"]["completed"]=False
        parsed,reason=module.extract_legacy(case)
        self.assertIsNone(parsed)
        self.assertEqual(reason,"unconfirmed_completion")

    def test_nested_nn_disagreement_old_record(self):
        case=self.sample()
        old=case["record"]
        nested=dict(record=dict(selection=dict(sfen=old["sfen"],history_moves=old["history_moves"]),
                                research=old))
        parsed,reason=module.extract_legacy(nested)
        self.assertIsNone(reason)
        self.assertEqual(parsed["position"],old["sfen"])

if __name__=="__main__":unittest.main()
