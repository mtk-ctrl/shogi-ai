"""Holdout membership and canonical SFEN anti-leakage unit tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from tools.research.nnue_split import allocate_roots, position_identity
from tools.research.train_nnue import split_groups


def move_sfen(move, ply=None):
    board = shogi.Board()
    if move:
        board.push_usi(move)
    sfen = board.sfen()
    if ply is not None:
        sfen = " ".join(sfen.split()[:3]) + f" {ply}"
    return sfen


def sample(root, sfen):
    return {"root": root, "sfen": sfen, "target": .1, "weight": 1,
            "features": [1]}


class SplitTest(unittest.TestCase):
    def test_same_position_different_ply_counter_is_same_network_input(self):
        s = move_sfen("7g7f")
        self.assertEqual(position_identity(s), position_identity(move_sfen("7g7f", 99)))
        self.assertNotEqual(position_identity(s), position_identity(move_sfen("2g2f", 99)))

    def test_deterministic_original_game_split_and_same_position_filtered(self):
        roots = [f"independent-game-{i:03d}" for i in range(20)]
        p = allocate_roots(roots, 101)
        assert not p["train"] & p["test"] and not p["train"] & p["validation"]
        self.assertEqual(p, allocate_roots(reversed(roots), 101))
        t, v, x = sorted(p["train"]), sorted(p["validation"]), sorted(p["test"])
        samples = [sample(root, move_sfen("7g7f", k + 2))
                   for k, root in enumerate(t)]
        samples += [sample(v[0], move_sfen("7g7f", 777))]
        samples += [sample(v[1], move_sfen("2g2f", 7))]
        samples += [sample(x[0], move_sfen("2g2f", 999))]
        samples += [sample(x[1], move_sfen("2h3h", 9))]
        training, validation, testing = split_groups(samples, 101)
        self.assertEqual(len(training), len(t))
        self.assertEqual([a["root"] for a in validation], [v[1]])
        self.assertEqual([a["root"] for a in testing], [x[1]])
        self.assertTrue(all(a["root"] in p["train"] for a in training))

    def test_empty_holdout_fails_instead_of_silently_leaking(self):
        rows = [sample(f"g{i}", move_sfen("7g7f", i + 4)) for i in range(12)]
        with self.assertRaisesRegex(ValueError, "leakage-free"):
            split_groups(rows, 101)


if __name__ == "__main__":
    unittest.main()
