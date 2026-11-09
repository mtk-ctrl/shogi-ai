"""Paired-opening matches: shared openings, swapped colours, pair statistics."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "scripts"))
import arena
import paired_stats
from dispatch_match_request import validate, dispatch_command


class Fake:
    def __init__(self, label):
        self.label = label
        self.last_search = {}
        self.seen = []

    def configure_game(self, seed):
        pass

    def bestmove(self, moves):
        self.seen.append(list(moves))
        return "resign"


def play(index, offset=0, plies=6, seed=2026):
    a, b = Fake("A"), Fake("B")
    result = arena.play_game(a, b, index, 400, 10 ** 6 * (offset + 1), offset, plies, seed)
    return result, a, b


class PairedOpeningTest(unittest.TestCase):
    def test_opening_is_deterministic_and_legal(self):
        self.assertEqual(arena.make_opening(6, 7, 3), arena.make_opening(6, 7, 3))
        self.assertNotEqual(arena.make_opening(6, 7, 3), arena.make_opening(6, 7, 4))
        self.assertEqual(len(arena.make_opening(6, 7, 3)), 6)

    def test_pair_shares_opening_and_swaps_colours(self):
        first, a1, b1 = play(0)
        second, a2, b2 = play(1)
        self.assertEqual(first["opening_moves"], second["opening_moves"])
        self.assertEqual(first["opening_pair"], second["opening_pair"])
        self.assertNotEqual(first["a_black"], second["a_black"])
        # The engine to move is shown the whole opening as its game history.
        mover = a1 if first["a_black"] else b1
        self.assertEqual(mover.seen[0], first["opening_moves"])

    def test_pair_index_is_global_across_shards(self):
        # shard 2 starts at global game 20: its first two games are pair 10.
        r0, _, _ = play(0, offset=20)
        r1, _, _ = play(1, offset=20)
        self.assertEqual((r0["opening_pair"], r1["opening_pair"]), (10, 10))
        self.assertEqual(r0["opening_moves"], arena.make_opening(6, 2026, 10))
        # A shard boundary inside a pair still gives both halves the same opening.
        left, _, _ = play(0, offset=18)   # global game 18 = pair 9, first half
        right, _, _ = play(0, offset=19)  # global game 19 = pair 9, second half
        self.assertEqual(left["opening_pair"], right["opening_pair"])
        self.assertEqual(left["opening_moves"], right["opening_moves"])
        self.assertNotEqual(left["a_black"], right["a_black"])

    def test_off_by_default_keeps_the_historical_game(self):
        result, a, b = play(0, plies=0)
        self.assertIsNone(result["opening_pair"])
        self.assertEqual(result["opening_moves"], [])
        self.assertEqual((a if result["a_black"] else b).seen[0], [])

    def test_pair_statistics(self):
        def game(pair, winner):
            return {"opening_pair": pair, "winner": winner}
        shards = [
            {"details": [game(0, "A"), game(0, "A"), game(1, "A"), game(1, "B")]},
            {"details": [game(2, "B"), game(2, "B"), game(3, "A"), game(3, None), game(4, "A")]},
        ]
        s = paired_stats.paired_summary(shards)
        self.assertEqual((s["pairs"], s["incomplete_pairs"]), (4, 1))
        self.assertEqual((s["pairs_a_swept"], s["pairs_split"], s["pairs_b_swept"]), (1, 1, 1))
        scores = [1.0, 0.5, 0.0, 0.75]
        mean = sum(scores) / 4
        var = sum((x - mean) ** 2 for x in scores) / 3
        self.assertAlmostEqual(s["pair_score_a"], mean)
        self.assertAlmostEqual(s["pair_se"], math.sqrt(var / 4))
        self.assertIsNone(paired_stats.paired_summary([{"details": [{"winner": "A"}]}]))

    def test_identical_players_have_no_signal(self):
        # Every opening won by whoever is Black: colour effect only. The pair
        # score is exactly 50% with zero variance, i.e. colour bias cancels.
        details = []
        for pair in range(10):
            details += [{"opening_pair": pair, "winner": "A"}, {"opening_pair": pair, "winner": "B"}]
        s = paired_stats.paired_summary([{"details": details}])
        self.assertEqual(s["pair_score_a"], 0.5)
        self.assertEqual(s["pair_se"], 0.0)

    def test_dispatch_validates_opening_plies(self):
        base = {"ref_a": "main", "ref_b": "BASELINE_FILE", "games": "20", "shards": "2",
                "go_command": "go movetime 200", "max_plies": "300", "seed": "1",
                "options_a": "{}", "options_b": "{}"}
        self.assertNotIn("opening_plies=", " ".join(dispatch_command(validate(dict(base), issue_request=False), "o/r")))
        req = validate({**base, "opening_plies": "6"}, issue_request=False)
        self.assertIn("opening_plies=6", dispatch_command(req, "o/r"))
        for bad in ("13", "-1", "x", True):
            with self.assertRaises(ValueError):
                validate({**base, "opening_plies": bad}, issue_request=False)


if __name__ == "__main__":
    unittest.main()
