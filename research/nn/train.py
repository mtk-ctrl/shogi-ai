#!/usr/bin/env python3
"""Train a research-only position evaluator and compare it to KUMOJI static scores."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from network import PositionNet, encode_sfen, sigmoid


def load_samples(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("source") != "kumoji_selfplay":
            raise ValueError(f"line {line_no}: external or unidentified data is forbidden")
        if not isinstance(row.get("game_id"), str) or not row["game_id"]:
            raise ValueError(f"line {line_no}: game_id required")
        target = row.get("target_black")
        if type(target) not in (float, int) or not np.isfinite(target) or not 0 <= target <= 1:
            raise ValueError(f"line {line_no}: invalid result target")
        if not isinstance(row.get("sfen"), str):
            raise ValueError(f"line {line_no}: SFEN required")
        rows.append(row)
    if not rows:
        raise ValueError("empty learning dataset")
    return rows


def partition(rows: list[dict], seed: int):
    games = sorted({row["game_id"] for row in rows},
                   key=lambda game: hashlib.sha256(f"{seed}:{game}".encode()).digest())
    if len(games) < 3:
        raise ValueError("at least three games are required for independent splits")
    n_val = max(1, round(len(games) * .10))
    n_test = max(1, round(len(games) * .10))
    if n_val + n_test >= len(games):
        raise ValueError("not enough training games")
    assignments = {g: "train" for g in games[:len(games) - n_val - n_test]}
    assignments.update({g: "val" for g in games[len(games) - n_val - n_test:-n_test]})
    assignments.update({g: "test" for g in games[-n_test:]})
    return assignments


def mse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((y - p) ** 2))


def calibrate_cp(rows: list[dict]) -> float | None:
    pairs = [(r["static_cp_black"], r["target_black"]) for r in rows
             if type(r.get("static_cp_black")) is int
             and abs(r["static_cp_black"]) < 100000]
    if len(pairs) < 10:
        return None
    scores = np.array([r[0] for r in pairs], dtype=np.float32)
    outcomes = np.array([r[1] for r in pairs], dtype=np.float32)
    candidates = (100, 200, 350, 500, 700, 1000, 1500, 2200, 3300)
    return float(min(candidates, key=lambda t: mse(outcomes, sigmoid(scores / t))))


def measure(rows, model, cp_temperature, max_batch=512):
    if not rows:
        return {"positions": 0}
    targets = np.array([r["target_black"] for r in rows], dtype=np.float32)
    predicted_parts = []
    for i in range(0, len(rows), max_batch):
        x = np.stack([encode_sfen(r["sfen"]) for r in rows[i:i + max_batch]])
        predicted_parts.append(model.predict(x))
    probabilities = np.concatenate(predicted_parts)
    valid_cp = [i for i, r in enumerate(rows) if type(r.get("static_cp_black")) is int
                and abs(r["static_cp_black"]) < 100000]
    result = {"positions": len(rows), "games": len({r["game_id"] for r in rows}),
              "neural_brier": round(mse(targets, probabilities), 6),
              "neural_mean_probability": round(float(probabilities.mean()), 6),
              "baseline_static_positions": len(valid_cp)}
    if cp_temperature is not None and valid_cp:
        cp = np.array([rows[i]["static_cp_black"] for i in valid_cp], dtype=np.float32)
        prior = sigmoid(cp / cp_temperature)
        result["baseline_brier"] = round(mse(targets[valid_cp], prior), 6)
        result["neural_brier_same_positions"] = round(
            mse(targets[valid_cp], probabilities[valid_cp]), 6)
    else:
        result["baseline_brier"] = None
        result["neural_brier_same_positions"] = None
    return result


def run(input_path: Path, output_dir: Path, *, hidden=32, epochs=15, seed=20261011):
    rows = load_samples(input_path)
    parts = partition(rows, seed)
    by_split = {s: [r for r in rows if parts[r["game_id"]] == s]
                for s in ("train", "val", "test")}
    train = by_split["train"]
    x = np.stack([encode_sfen(r["sfen"]) for r in train])
    y = np.array([r["target_black"] for r in train], dtype=np.float32)
    model = PositionNet(hidden=hidden, seed=seed)
    model.fit(x, y, epochs=epochs, seed=seed)
    temperature = calibrate_cp(train)
    results = {s: measure(by_split[s], model, temperature)
               for s in ("train", "val", "test")}
    position_sets = {s: {r["sfen"].rsplit(" ", 1)[0] for r in by_split[s]}
                     for s in by_split}
    overlaps = {f"train_vs_{s}": len(position_sets["train"] & position_sets[s])
                for s in ("val", "test")}
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save(output_dir / "position-net-v1.npz")
    report = {
        "purpose": "Research ONLY; no effect on KUMOJI move selection",
        "target": "Empirical Black result (win=1, loss=0, draw=0.5), not ground truth best move",
        "evaluation": "Brier score (lower is better), holdouts split by entire game",
        "source": "same-binary self-play only",
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "model": {"type": "MLP", "hidden": hidden, "epochs": epochs, "seed": seed},
        "static_cp_temperature_fit_on_training_only": temperature,
        "split_results": results,
        "identical_position_overlap_across_splits": overlaps,
        "caution": "Adjacent positions correlate; identical positions across different games may overlap. Small samples cannot establish strength.",
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Disagreement is a research priority signal, NOT proof one evaluator is right.
    candidates = [r for r in by_split["test"]
                  if temperature is not None and type(r.get("static_cp_black")) is int]
    ranked = []
    for start in range(0, len(candidates), 512):
        batch = candidates[start:start + 512]
        probabilities = model.predict(np.stack([encode_sfen(r["sfen"]) for r in batch]))
        for row, p in zip(batch, probabilities):
            baseline = float(sigmoid(np.asarray(row["static_cp_black"] / temperature)))
            ranked.append((abs(float(p) - baseline), row, float(p), baseline))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    with (output_dir / "disagreements.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["game_id", "ply", "sfen", "target_black", "static_cp_black",
                         "neural_probability_black", "calibrated_static_probability_black",
                         "absolute_gap"])
        for gap, row, p, baseline in ranked[:100]:
            writer.writerow([row["game_id"], row.get("ply"), row["sfen"],
                             row["target_black"], row["static_cp_black"],
                             round(p, 6), round(baseline, 6), round(gap, 6)])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20261011)
    args = parser.parse_args()
    report = run(args.input, args.output_dir, hidden=args.hidden,
                 epochs=args.epochs, seed=args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
