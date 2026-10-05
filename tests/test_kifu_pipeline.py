#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.kifu.csa import parse_csa, parse_csa_games
from tools.kifu.build_dataset import build_dataset, game_fingerprint, split_for

SAMPLE = """V2.2
N+Black
N-White
PI
+
+7776FU
-3334FU
%TORYO
"""

SAMPLE2 = """V2.2
N+Black2
N-White2
PI
+
+2726FU
-8384FU
%TORYO
"""


class KifuPipelineTests(unittest.TestCase):
    def test_csa_to_usi_and_result(self):
        game = parse_csa(SAMPLE, "sample.csa")
        self.assertEqual(game.moves_usi, ["7g7f", "3c3d"])
        self.assertEqual(game.winner, "white")
        self.assertEqual(game.start_sfen, "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1")

    def test_multi_record_file(self):
        games = parse_csa_games(SAMPLE + "\n/\n" + SAMPLE2, "multi.csa")
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0].source_record, 1)
        self.assertEqual(games[1].source_record, 2)
        self.assertEqual(games[1].moves_usi, ["2g2f", "8c8d"])

    def test_all_remaining_pieces_hand(self):
        text = """V2.2
P1 *  *  *  * -OU *  *  *  * 
P2 *  *  *  *  *  *  *  *  * 
P3 *  *  *  *  *  *  *  *  * 
P4 *  *  *  *  *  *  *  *  * 
P5 *  *  *  *  *  *  *  *  * 
P6 *  *  *  *  *  *  *  *  * 
P7 *  *  *  *  *  *  *  *  * 
P8 *  *  *  *  *  *  *  *  * 
P9 *  *  *  * +OU *  *  *  * 
P+00AL
+
%CHUDAN
"""
        game = parse_csa(text)
        self.assertIn("18P", game.start_sfen)
        self.assertIn("4L", game.start_sfen)
        self.assertEqual(game.winner, None)

    def test_fingerprint_and_split_are_deterministic(self):
        game = parse_csa(SAMPLE)
        fp = game_fingerprint(game)
        self.assertEqual(fp, game_fingerprint(game))
        self.assertEqual(split_for(fp), split_for(fp))
        self.assertIn(split_for(fp), {"train", "validation", "test"})

    def test_dataset_deduplicates_whole_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "a.csa").write_text(SAMPLE, encoding="utf-8")
            (tmp / "b.csa").write_text(SAMPLE, encoding="utf-8")
            output = tmp / "games.jsonl"
            manifest = tmp / "manifest.json"
            summary = build_dataset([tmp], output, manifest)
            self.assertEqual(summary["records_seen"], 2)
            self.assertEqual(summary["games_written"], 1)
            self.assertEqual(summary["duplicates_removed"], 1)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["moves_usi"], ["7g7f", "3c3d"])


if __name__ == "__main__":
    unittest.main()
