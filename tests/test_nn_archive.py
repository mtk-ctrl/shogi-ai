#!/usr/bin/env python3
"""Verify real archive adapter, provenance checks, and an offline evaluation reader."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nn"))
from import_release import convert_archive
from prepare import convert
from score_samples import score_samples


class ArchiveResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_archive(self):
        game_moves = []
        for i in range(5):
            b = shogi.Board()
            moves = []
            for j in range(18):
                options = list(b.legal_moves)
                choice = options[(i + j) % len(options)]
                moves.append(choice.usi())
                b.push(choice)
            game_moves.append(moves)
        identity = "a" * 64
        source_id = "b" * 64
        games = []
        for i, moves in enumerate(game_moves):
            games.append({"source_id": source_id, "a_black": i % 2 == 0,
                          "winner": "A" if i % 2 else "B", "reason": "resign",
                          "plies": len(moves),
                          "moves": [{"move": m, "search": {}} for m in moves]})
        archive = self.root / "games.gz"
        with gzip.open(archive, "wt", encoding="utf-8") as f:
            for row in games:
                f.write(json.dumps(row) + "\n")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "sources": [{"source_id": source_id, "metadata": {
                "sha256_a": identity, "sha256_b": identity}}]}))
        return archive, manifest

    def test_archive_and_holdout(self):
        archive, manifest = self.make_archive()
        imported = self.root / "imported"
        result = convert_archive(archive, manifest, imported)
        self.assertEqual(result["games"], 5)
        sample = self.root / "samples.jsonl"
        counts = convert(list(imported.glob("*.json")), sample, stride=5)
        self.assertEqual(counts["games"], 5)
        self.assertEqual(counts["positions"], 20)
        lines = [json.loads(line) for line in sample.read_text().splitlines()]
        self.assertTrue(all(r["source"] == "kumoji_selfplay" for r in lines))
        self.assertEqual(lines[0]["ply"], 1)
        assert counts["positions"] == len(lines)
        bad = json.loads(manifest.read_text())
        bad["archive_sha256"] = "0" * 64
        manifest.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            convert_archive(archive, manifest, imported)

    def test_score_samples_reads_current_eval(self):
        engine = self.root / "mock-kumoji"
        engine.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "for line in sys.stdin:\n"
            " if line.strip() == 'usi':\n"
            "  print('id name KUMOJI test'); print('usiok', flush=True)\n"
            " elif line.strip() == 'eval':\n"
            "  print('info string evaluation material 0 safety 0 total 120', flush=True)\n"
            " elif line.strip() == 'quit':\n"
            "  break\n")
        engine.chmod(0o755)
        inp, out = self.root / "input.jsonl", self.root / "scored.jsonl"
        inp.write_text(json.dumps({"sfen": shogi.Board().sfen(),
                                   "game_id": "test", "source": "kumoji_selfplay",
                                   "target_black": 1.0}) + "\n")
        self.assertEqual(score_samples(inp, out, engine), 1)
        self.assertEqual(json.loads(out.read_text())["static_cp_black"], 120)


if __name__ == "__main__":
    unittest.main()
