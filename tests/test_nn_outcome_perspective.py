"""Regression guard: KUMOJI value targets are explicitly Black-perspective.
The rule-layer kifu exporter independently uses side-to-move targets.
Do not apply the FUKAJI v0 fix to target_black: that would invert White rows.
"""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"research"/"nn"))
import shogi
from prepare import convert
from train import load_samples
import json, tempfile

class OutcomePerspectiveTests(unittest.TestCase):
    def test_black_target_does_not_flip_when_turn_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            matches=[]
            # Three unique, valid opening fragments; a result field is a synthetic
            # conversion fixture, not a verified game outcome or evidence of strength.
            for moves in (["7g7f","3c3d"],["2g2f","8c8d"],["7g7f","8c8d"]):
                matches.append({"moves":moves,"winner":"A","reason":"resign","a_black":True})
            path=root/"match.json"
            path.write_text(json.dumps({"learning_origin":"kumoji_selfplay","sha256_a":"a"*64,"sha256_b":"a"*64,"details":matches}))
            samples=root/"samples.jsonl"
            convert([path],samples)
            rows=load_samples(samples)
            self.assertTrue(any(r["sfen"].split()[1]=="w" for r in rows))
            self.assertTrue(all(r["target_black"]==1.0 for r in rows))
            self.assertTrue(all(r["source"]=="kumoji_selfplay" for r in rows))
if __name__=="__main__": unittest.main()
