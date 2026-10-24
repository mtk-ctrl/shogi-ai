#!/usr/bin/env python3
"""Smoke-test NNUE training, source restrictions, and real USI inference."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import shogi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))
import train_nnue
from tools.research.nnue_cycle import verify_native


def run():
    binary = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        dataset = directory / "own.jsonl"
        model = directory / "candidate.nnue"
        report = directory / "report.json"
        rows = []
        for i, move in enumerate(shogi.Board().legal_moves):
            if i >= 14:
                break
            board = shogi.Board()
            board.push(move)
            rows.append({
                "root_game_id": f"isolated-game-{i}", "sfen": board.sfen(),
                "origin": "own_search" if i % 2 else "selfplay_result",
                "cp_black": 30 + i * 20, "outcome_black": 1 if i % 3 else -1,
                "terminal_confirmed": True, "confidence": .6,
            })
        dataset.write_text("\n".join(map(json.dumps, rows)) + "\n")
        subprocess.run([sys.executable, str(Path(train_nnue.__file__)),
                        "--data", str(dataset), "--model", str(model),
                        "--report", str(report), "--hidden", "16",
                        "--epochs", "3"], check=True, capture_output=True, text=True)
        payload = json.loads(report.read_text())
        assert payload["status"] == "trained_candidate_not_proven_stronger"
        assert payload["train_samples"] and payload["untouched_test_samples"]
        assert payload["formal_engine_adopted"] is False
        script = "\n".join([
            "usi", f"setoption name EvalNeuralFile value {model}",
            "setoption name EvalNeural value true",
            "position sfen " + rows[0]["sfen"], "eval", "go depth 1",
            "isready", "quit", "",
        ])
        output = subprocess.run([binary], input=script, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, check=True).stdout
        assert "neural_evaluation loaded width 16" in output, output
        match = re.search(r"neural_evaluation static_cp_black (-?\d+)", output)
        assert match, output
        expected = train_nnue.evaluate_quantized(
            {"features": train_nnue.sparse_features(rows[0]["sfen"])},
            model.read_bytes())
        assert int(match.group(1)) == expected, (match.group(1), expected)
        native = verify_native(binary, model, rows[0]["sfen"], expected,
                               Path("position-knowledge-v1.tsv"), 163)
        assert native["search_completed"] and native["native_cp"] == expected
        # A bad model must be visible, never silently scored by the old evaluator.
        output_bad = subprocess.run([binary], input="\n".join([
            "setoption name EvalNeuralFile value /no/such/model",
            "setoption name EvalNeural value true",
            "position startpos", "go depth 1", "quit", ""]),
            text=True, stdout=subprocess.PIPE, timeout=10, check=True).stdout
        assert "neural_evaluation error invalid_model" in output_bad
        assert "neural_evaluation error model_unavailable" in output_bad
        assert "bestmove resign" in output_bad
        # Reject external teacher provenance, even if other fields are valid.
        rows[0]["origin"] = "external_engine"
        dataset.write_text("\n".join(map(json.dumps, rows)) + "\n")
        try:
            train_nnue.read_samples(dataset)
        except ValueError as exc:
            assert "unapproved teacher" in str(exc)
        else:
            raise AssertionError("external teacher was accepted")


if __name__ == "__main__":
    run()
