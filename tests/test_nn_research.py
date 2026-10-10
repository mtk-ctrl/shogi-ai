#!/usr/bin/env python3
"""Independent, tiny end-to-end neural research test; no change to playing engine."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

import numpy as np
import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nn"))
from network import INPUT_SIZE, PositionNet, encode_sfen
from mark_selfplay import mark
from prepare import convert
from train import load_samples, partition, run


class NeuralResearchTests(unittest.TestCase):
    def test_sfen_features_and_validation(self):
        board = shogi.Board()
        x = encode_sfen(board.sfen())
        self.assertEqual(x.shape, (INPUT_SIZE,))
        self.assertEqual(x.dtype, np.float32)
        self.assertEqual(x[-1], 1)
        self.assertEqual(float(x[:-1].sum()), 40)
        board.push(next(iter(board.legal_moves)))
        self.assertEqual(encode_sfen(board.sfen())[-1], -1)
        self.assertRaises(ValueError, encode_sfen, "not sfen")
        self.assertRaises(ValueError, encode_sfen, "9/9/9/9/9/9/9/9 b - 1")
        self.assertRaises(ValueError, encode_sfen, "9/9/9/9/9/9/9/9/9 b X 1")

    def sample_match(self, sha):
        rng = random.Random(20261011)
        details = []
        for game in range(12):
            board = shogi.Board()
            moves, observations = [], []
            for ply in range(25):
                legal = list(board.legal_moves)
                if not legal:
                    break
                m = legal[rng.randrange(len(legal))]
                usi = m.usi()
                moves.append(usi)
                observations.append({
                    "move": usi,
                    "search": {"phase_static_cp_black": (game % 2) * 120 - 60}
                })
                board.push(m)
            details.append({
                "moves": moves, "move_records": observations,
                "winner": "A" if game % 3 else "B",
                "reason": "resign", "a_black": game % 2 == 0
            })
        return {"sha256_a": sha, "sha256_b": sha, "details": details}

    def test_training_end_to_end_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            engine = base / "engine"
            engine.write_bytes(b"fixture binary; not a KUMOJI release")
            sha = hashlib.sha256(engine.read_bytes()).hexdigest()
            raw = base / "raw.json"
            raw.write_text(json.dumps(self.sample_match(sha)), encoding="utf-8")
            tagged = base / "tagged.json"
            mark(raw, engine, tagged)
            samples = base / "samples.jsonl"
            counts = convert([tagged], samples)
            self.assertEqual(counts["games"], 12)
            rows = load_samples(samples)
            self.assertEqual(counts["positions"], len(rows))
            splits = partition(rows, 9)
            self.assertEqual(set(splits.values()), {"train", "val", "test"})
            output = base / "out"
            result = run(samples, output, epochs=3, hidden=8, seed=9)
            self.assertEqual(result["split_results"]["train"]["positions"] > 0, True)
            self.assertTrue((output / "disagreements.csv").exists())
            m = PositionNet.load(output / "position-net-v1.npz")
            p = m.predict(np.stack([encode_sfen(rows[0]["sfen"])]))
            self.assertTrue(0 <= float(p[0]) <= 1)
            self.assertTrue(np.isfinite(p).all())
            polluted = base / "external.jsonl"
            polluted.write_text(json.dumps(dict(rows[0], source="external_ai")) + "\n")
            with self.assertRaises(ValueError):
                load_samples(polluted)
            corrupted = base / "corrupted.json"
            candidate = self.sample_match("f" * 64)
            candidate["learning_origin"] = "external_ai"
            corrupted.write_text(json.dumps(candidate))
            with self.assertRaises(ValueError):
                convert([corrupted], base / "unsafe.jsonl")
            with self.assertRaises(ValueError):
                mark(raw, base / "missing_binary", tagged)

    def test_same_position_prediction_after_serialization(self):
        model = PositionNet(hidden=4, seed=8)
        x = encode_sfen(shogi.Board().sfen())[None, :]
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "model.npz"
            original = model.predict(x)
            model.save(file)
            self.assertTrue(np.array_equal(original, PositionNet.load(file).predict(x)))


if __name__ == "__main__":
    unittest.main()
