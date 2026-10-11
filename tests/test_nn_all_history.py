#!/usr/bin/env python3
"""Offline tests for historical archive labels, de-duplication, and split isolation."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nn"))
from collect_history import extract_games, verify_archive_payload
from train_history import assign_groups


class AllHistoryTests(unittest.TestCase):
    def archive(self):
        board = shogi.Board()
        moves = []
        for i in range(30):
            legal = list(board.legal_moves)
            token = legal[(i * 5) % len(legal)].usi()
            moves.append({"move": token})
            board.push_usi(token)
        hash_a = "a" * 64
        hash_b = "b" * 64
        metadata = {"sources": [
            {"source_id": "good", "metadata": {
                "sha256_a": hash_a, "sha256_b": hash_a}},
            {"source_id": "different", "metadata": {
                "sha256_a": hash_a, "sha256_b": hash_b}},
        ]}
        records = [
            {"source_id": "good", "a_black": True, "winner": "A",
             "reason": "resign", "plies": len(moves), "moves": moves},
            {"source_id": "different", "a_black": False, "winner": "A",
             "reason": "resign", "plies": len(moves), "moves": moves},
            {"source_id": "good", "a_black": True, "winner": "A",
             "reason": "resign", "plies": len(moves), "moves": moves},
        ]
        payload = ("\n".join(json.dumps(g) for g in records) + "\n").encode()
        compressed = gzip.compress(payload, mtime=0)
        metadata["archive_sha256"] = hashlib.sha256(compressed).hexdigest()
        return compressed, json.dumps(metadata).encode()

    def test_integrity_and_eligibility(self):
        payload, manifest = self.archive()
        sources = verify_archive_payload(payload, manifest, label="fixture")
        counters, seen, output = Counter(), set(), io.StringIO()
        extract_games(payload, sources, group="run-1", counters=counters,
                      seen_games=seen, output=output)
        result = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(counters["archive_games_seen"], 3)
        self.assertEqual(counters["excluded_different_binary_versions"], 1)
        self.assertEqual(counters["duplicate_games"], 1)
        self.assertEqual(counters["labelled_games"], 1)
        self.assertEqual(len(result), 6)
        self.assertTrue(all(x["source_group"] == "run-1" for x in result))
        with self.assertRaises(ValueError):
            verify_archive_payload(payload + b"x", manifest, label="tamper")

    def test_split_by_run_not_by_game(self):
        rows = [{"source_group": f"run-{i}", "game_id": f"game-{i}-{j}"}
                for i in range(12) for j in range(3)]
        partitions = assign_groups(rows)
        self.assertEqual(set(partitions.values()), {"train", "val", "test"})
        for i in range(12):
            self.assertIn(f"run-{i}", partitions)


if __name__ == "__main__":
    unittest.main()
