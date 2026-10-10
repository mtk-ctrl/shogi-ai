#!/usr/bin/env python3
"""Regression for the research-only mate-learning pipeline."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mate_learning", ROOT / "tools/learning/mate_learning.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def test_training():
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp)
        samples = tmp / "samples.jsonl"
        # Synthetic observations for algorithmic regression only, not chess
        # strength or real classifier performance.
        with samples.open("w", encoding="utf-8") as out:
            for label in (0, 1):
                for i in range(16):
                    values = [15.0 + i, float(label), float(label * 4 + i % 3),
                              float(label * 5), float(label + (i % 2)),
                              float(8 - 3 * label), float(label * 4), float(1 - label)]
                    row = {"schema": module.SCHEMA, "sfen": f"synthetic-{label}-{i}",
                           "horizon": 7, "source_ply": 3 if label else 11,
                           "features": values, "label": label}
                    out.write(json.dumps(row) + "\n")
        model = tmp / "model.txt"
        report = tmp / "report.json"
        subprocess.run([sys.executable, str(ROOT / "tools/learning/mate_learning.py"),
                        "train", "--samples", str(samples), "--model", str(model),
                        "--report", str(report)], check=True, capture_output=True, text=True)
        text = model.read_text(encoding="ascii").splitlines()
        require(text[0] == "KUMOJI_MATE_GATE_V1", "model header")
        require(len(text) == 6, "model row count")
        require(all(len(text[i].split()) == 9 for i in (1, 2, 3)), "model 8 features")
        data = json.loads(report.read_text(encoding="utf-8"))
        require(data["train_samples"] == 24 and data["holdout_samples"] == 8, "split")
        require(data["holdout"]["accuracy"] >= 0.75, "model actually trains")


def test_unproven_not_negative():
    with tempfile.TemporaryDirectory() as temp:
        file = Path(temp) / "samples.jsonl"
        file.write_text(json.dumps({"schema": module.SCHEMA, "sfen": "bad",
                       "horizon": 7, "features": [0] * 8, "label": None}) + "\n")
        try:
            module.parse_samples(file)
            raise AssertionError("unknown label accepted")
        except ValueError:
            pass


def test_engine_protocol(exe):
    eng = module.Engine(exe)
    try:
        eng.send("position sfen 4k4/9/9/9/9/9/9/9/4K4 b - 1")
        eng.send("learning_features")
        response = eng.until("info string learning_features ", 5)
        require(response.startswith(module.FEATURE_TAG), "feature protocol")
        require(len(response[len(module.FEATURE_TAG):].split()) == 8, "feature count")
        features, label, status = eng.observe("4k4/9/9/9/9/9/9/9/4K4 b - 1", 2000)
        require(label == 0 and status == "no_mate_within_7", "verified bounded non-mate")
        # A known exactly-five-ply real-game fixture.
        mate = "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105"
        _, label, status = eng.observe(mate, 2000)
        require(label == 1 and status == "proven_mate", "verified bounded mate")
    finally:
        eng.close()


if __name__ == "__main__":
    test_training()
    test_unproven_not_negative()
    if len(sys.argv) > 1:
        test_engine_protocol(sys.argv[1])
    print("PASS mate-learning train, unknown-label filter and engine protocol")
