#!/usr/bin/env python3
"""Historical multi-run NN training: select models by held-out source run.

Historical outcomes are labels for predicting winners, never certified
best-move labels. All input positions must have verified KUMOJI-only origin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from network import PositionNet, encode_sfen
from train import calibrate_cp, load_samples, measure


CONFIGS = ((4, 2), (8, 3), (16, 4))
SEED = 20261011


def assign_groups(rows):
    groups = sorted({r.get("source_group") for r in rows})
    if None in groups or len(groups) < 3:
        raise ValueError("at least three independent source runs are required")
    order = sorted(groups, key=lambda g: hashlib.sha256(
        f"{SEED}:{g}".encode()).digest())
    n_hold = max(1, int(len(order) * .15))
    # All source runs are assigned as an indivisible unit, avoiding cross-run contamination.
    assign = {g: "train" for g in order[:len(order) - 2*n_hold]}
    assign.update({g: "val" for g in order[len(order) - 2*n_hold:-n_hold]})
    assign.update({g: "test" for g in order[-n_hold:]})
    return assign


def run(source: Path, destination: Path):
    rows = load_samples(source)
    group = assign_groups(rows)
    split = {name: [r for r in rows if group[r["source_group"]] == name]
             for name in ("train", "val", "test")}
    # Group isolation is necessary but insufficient: the same opening positions
    # recur in many matches. Exclude exact board/turn/hand duplicates from holdouts.
    seen = {r["sfen"].rsplit(" ", 1)[0] for r in split["train"]}
    removed = {}
    for name in ("val", "test"):
        original = split[name]
        split[name] = [r for r in original if r["sfen"].rsplit(" ", 1)[0] not in seen]
        removed[name] = len(original) - len(split[name])
        seen.update(r["sfen"].rsplit(" ", 1)[0] for r in split[name])
        if not split[name]:
            raise ValueError(name + " is empty after opening-position removal")
    training, validation = split["train"], split["val"]
    if not training:
        raise ValueError("training set is empty")
    data = np.stack([encode_sfen(r["sfen"]) for r in training])
    target = np.array([r["target_black"] for r in training], dtype=np.float32)
    temperature = calibrate_cp(training)
    if temperature is None:
        raise ValueError("missing static evaluation on historical samples")
    # Baseline static evaluation and NN are compared on the same target and rows.
    candidates = []
    winner = None
    for hidden, epochs in CONFIGS:
        model = PositionNet(hidden=hidden, seed=SEED)
        model.fit(data, target, epochs=epochs, seed=SEED, batch_size=256)
        validation_metrics = measure(validation, model, temperature)
        score = validation_metrics["neural_brier"]
        entry = {"hidden": hidden, "epochs": epochs,
                 "validation_brier": score}
        candidates.append(entry)
        if winner is None or score < winner[0]:
            winner = score, model, entry
    destination.mkdir(parents=True, exist_ok=True)
    chosen = winner[1]
    chosen.save(destination / "historical-position-net-v1.npz")
    metrics = {name: measure(split[name], chosen, temperature)
               for name in ("train", "val", "test")}
    report = {
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_run_counts": {name: len({r["source_group"] for r in split[name]})
                              for name in split},
        "game_counts": {name: len({r["game_id"] for r in split[name]})
                        for name in split},
        "positions": {name: len(split[name]) for name in split},
        "removed_exact_duplicate_holdout_positions": removed,
        "static_score_temperature_fitted_on_training": temperature,
        "candidates": candidates,
        "chosen_model": winner[2],
        "metrics": metrics,
        "basis": "Source-run holdout, with any exact overlapping positions removed",
        "constraints": (
            "Old KUMOJI-only selfplay. Source runs have different engine versions and "
            "time controls. Outcome targets are only empirical game results. "
            "No independent recent prospective holdout has been performed. "
            "Network is research-only; not used in playing engine."
        )
    }
    (destination / "historical-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.input, a.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
