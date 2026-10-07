import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("played_archive", ROOT / "tools/records/archive_played_moves.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PlayedArchiveTest(unittest.TestCase):
    def source(self, directory):
        path = Path(directory) / "source.json"
        data = {"games": 1, "sha256_a": "engine-hash", "options_a": {"OpeningBook": False},
                "details": [{"plies": 2, "moves": ["7g7f", "3c3d"], "winner": "A",
                             "move_records": [
                                 {"ply": 1, "move": "7g7f", "search": {"depth": 3, "score_cp_stm": 120,
                                  "score_black_cp": 120, "pv": ["7g7f", "8c8d"], "candidates": ["2g2f"]}},
                                 {"ply": 2, "move": "3c3d", "search": {"depth": 0}}]}]}
        path.write_text(json.dumps(data))
        return path

    def test_round_trip_and_missing_score(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            result = module.archive([source], Path(directory) / "out")
            with gzip.open(Path(directory) / "out/played-games.jsonl.gz", "rt") as stream:
                game = json.loads(stream.readline())
            self.assertEqual([r["move"] for r in game["moves"]], ["7g7f", "3c3d"])
            self.assertEqual(game["moves"][0]["search"]["score_cp_stm"], 120)
            self.assertNotIn("pv", game["moves"][0]["search"])
            self.assertNotIn("candidates", game["moves"][0]["search"])
            self.assertIsNone(game["moves"][1]["search"]["score_cp_stm"])
            self.assertEqual(result["missing_score_plies"], 1)
            self.assertEqual(result["sources"][0]["metadata"]["sha256_a"], "engine-hash")
            second = module.archive([source], Path(directory) / "other")
            self.assertEqual(result["archive_sha256"], second["archive_sha256"])

    def test_reject_mismatched_or_duplicate_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            with self.assertRaises(ValueError):
                module.archive([source, source], Path(directory) / "out")
            data = json.loads(source.read_text())
            data["details"][0]["move_records"][0]["move"] = "2g2f"
            source.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                module.archive([source], Path(directory) / "out")
            self.assertFalse((Path(directory) / "out/played-games.jsonl.gz").exists())

    def test_legacy_mixed_scores_are_preserved_and_separate_from_missing(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            data = json.loads(source.read_text())
            data["details"][0]["move_records"][0]["search"].update(score_mate_stm=3, score_black_mate=3)
            data["details"][0]["move_records"][1]["search"].update(score_cp_stm=None, score_mate_stm=None)
            source.write_text(json.dumps(data))
            result = module.archive([source], Path(directory) / "out")
            with gzip.open(Path(directory) / "out/played-games.jsonl.gz", "rt") as stream:
                game = json.loads(stream.readline())
            mixed = game["moves"][0]["search"]
            self.assertEqual(mixed["score_status"], "ambiguous")
            self.assertEqual(mixed["score_cp_stm"], 120)
            self.assertEqual(mixed["score_mate_stm"], 3)
            self.assertEqual(game["moves"][1]["search"]["score_status"], "not_recorded")
            self.assertEqual(result["ambiguous_score_plies"], 1)
            self.assertEqual(result["missing_score_plies"], 1)
            self.assertEqual(result["scored_plies"], 0)
        self.assertEqual(module.clean_search({"score_cp_stm": 0})["score_status"], "recorded")


if __name__ == "__main__":
    unittest.main()
