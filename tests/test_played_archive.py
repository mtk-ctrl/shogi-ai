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


if __name__ == "__main__":
    unittest.main()
