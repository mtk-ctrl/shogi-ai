"""Numerical guardrails and mirrored tactical fixture definitions."""
import importlib.util
from pathlib import Path
import sys,unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/selfplay-learning-20261017'))
import followup as f
class FollowupTests(unittest.TestCase):
    def test_mirrored_fixture_roundtrip_and_legality(self):
        for _,sfen,good,bad in f.TACTICS:
            self.assertEqual(f.mirror_sfen(f.mirror_sfen(sfen)),sfen)
            for move in (good,bad):
                self.assertEqual(f.mirror_move(f.mirror_move(move)),move)
                self.assertIn(f.shogi.Move.from_usi(move),f.shogi.Board(sfen).legal_moves)
                self.assertIn(f.shogi.Move.from_usi(f.mirror_move(move)),
                              f.shogi.Board(f.mirror_sfen(sfen)).legal_moves)
    def test_original_model_exposes_turn_bias(self):
        m=f.learn.Residual.from_text((ROOT/'research/selfplay-learning-20261017/original-model.txt').read_text())
        x=np.zeros((2,12));x[:,11]=[1,-1]
        self.assertEqual(m.correction(x).tolist(),[520,-520])
    def test_invariance_rejects_a_turn_shortcut(self):
        m=f.learn.Residual(4,150);m.w1[:]=0;m.w1[0,11]=1;m.w2[0]=1
        with self.assertRaisesRegex(AssertionError,'turn leaked'):f.invariants(m)
    def test_invariance_retains_material_direction(self):
        m=f.learn.Residual(4,150);m.w1[:]=0;m.w1[0,0]=.1;m.w2[0]=.1
        self.assertTrue(f.invariants(m)['turn_invariant'])
if __name__=='__main__':unittest.main()
