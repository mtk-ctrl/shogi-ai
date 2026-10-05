#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/book"))

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

importer = load_module("import_arena_games", ROOT / "tools/book/import_arena_games.py")
builder = load_module("build_opening_book", ROOT / "tools/book/build_opening_book.py")

class OpeningBookPipelineTest(unittest.TestCase):
    def test_import_deduplicates_and_skips_bad_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = {"winner": "A", "a_black": True, "reason": "checkmate",
                    "moves": ["7g7f", "3c3d", "2g2f"]}
            (root / "a.json").write_text(json.dumps({"details": [
                game,
                {"winner": None, "a_black": True, "reason": "move_limit", "moves": ["7g7f"]},
                {"winner": "B", "a_black": True, "reason": "illegal_move:x", "illegal_by": "A", "moves": ["7g7f"]},
            ]}), encoding="utf-8")
            (root / "b.json").write_text(json.dumps({"details": [game]}), encoding="utf-8")
            games, stats = importer.collect(root)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0][1], "black")
            self.assertEqual(stats["duplicates"], 1)
            self.assertEqual(stats["skipped_nondecisive"], 1)
            self.assertEqual(stats["skipped_illegal"], 1)

    def test_builder_keeps_supported_early_alternatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "samples.tsv"
            rows = []
            for i, outcome in enumerate([1, 1, 1, 1, -1, -1], 1):
                rows.append(f"g{i}\tbook\t1\t100\tsfen\t7g7f\t{outcome}")
            for i, outcome in enumerate([1, 1, -1, -1], 7):
                rows.append(f"g{i}\tbook\t1\t100\tsfen\t2g2f\t{outcome}")
            for i in range(3):
                rows.append(f"x{i}\tbook\t2\t200\tsfen\t3c3d\t1")
            rows.append("late\tbook\t21\t300\tsfen\t8h2b+\t1")
            source.write_text("\n".join(rows) + "\n", encoding="utf-8")
            args = SimpleNamespace(input=source, max_ply=20, min_position_samples=8,
                min_move_samples=3, max_moves=3, max_score_gap=0.12)
            entries, report = builder.build(args)
            self.assertEqual(report["positions_kept"], 1)
            self.assertEqual({row[1] for row in entries}, {"7g7f", "2g2f"})
            self.assertTrue(all(row[7] > 0 for row in entries))

    def test_builder_accumulates_prior_book_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "samples.tsv"
            source.write_text(
                "new1\tbook\t1\t100\tsfen\t7g7f\t1\n"
                "new2\tbook\t1\t100\tsfen\t7g7f\t1\n",
                encoding="utf-8")
            prior = root / "prior.tsv"
            prior.write_text(
                "# shogi-ai opening book v1: key move samples wins draws losses score_milli weight\n"
                "100\t7g7f\t8\t5\t0\t3\t600\t1000\n",
                encoding="utf-8")
            args = SimpleNamespace(input=source, prior_book=prior, max_ply=20, min_position_samples=8,
                min_move_samples=3, max_moves=3, max_score_gap=0.12)
            entries, report = builder.build(args)
            self.assertEqual(report["prior_book_entries"], 1)
            self.assertEqual(report["prior_book_samples"], 8)
            self.assertEqual(len(entries), 1)
            row = entries[0]
            self.assertEqual(row[0:6], (100, "7g7f", 10, 7, 0, 3))

if __name__ == "__main__":
    unittest.main()
