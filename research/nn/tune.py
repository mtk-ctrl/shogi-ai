#!/usr/bin/env python3
"""Validation-only model selection for the isolated KUMOJI neural evaluator.

The held-out test partition is not evaluated until the winning configuration
has been selected. This is an exploratory training study, not a chess strength claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from network import PositionNet, encode_sfen
from train import load_samples, partition, calibrate_cp, measure


CANDIDATES = [(4, 2), (8, 3), (16, 5), (32, 6), (32, 15)]


def run(input_path: Path, output_dir: Path, seed: int = 20261011):
    rows = load_samples(input_path)
    assignment = partition(rows, seed)
    splits = {s: [r for r in rows if assignment[r["game_id"]] == s]
              for s in ("train", "val", "test")}
    already_seen = {r["sfen"].rsplit(" ", 1)[0] for r in splits["train"]}
    excluded = {}
    for name in ("val", "test"):
        original = splits[name]
        splits[name] = [r for r in original
                        if r["sfen"].rsplit(" ", 1)[0] not in already_seen]
        excluded[name] = len(original) - len(splits[name])
        already_seen.update(r["sfen"].rsplit(" ", 1)[0] for r in splits[name])
        if len(splits[name]) < 1:
            raise ValueError(name + " has no unseen positions")
    train, validation, test = (splits[s] for s in ("train", "val", "test"))
    x = np.stack([encode_sfen(r["sfen"]) for r in train])
    y = np.asarray([r["target_black"] for r in train], dtype=np.float32)
    temperature = calibrate_cp(train)
    candidates = []
    best = None
    for hidden, epochs in CANDIDATES:
        model = PositionNet(hidden=hidden, seed=seed)
        model.fit(x, y, epochs=epochs, seed=seed)
        result = measure(validation, model, temperature)
        candidate = {"hidden": hidden, "epochs": epochs,
                     "validation_brier": result["neural_brier"]}
        candidates.append(candidate)
        # Strictly select using validation, never test outcome or test performance.
        if best is None or candidate["validation_brier"] < best[0]:
            best = (candidate["validation_brier"], model, candidate)
    model = best[1]
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save(output_dir / "position-net-v1.npz")
    measurements = {name: measure(splits[name], model, temperature)
                    for name in ("train", "val", "test")}
    report = {
        "purpose": "OFFLINE research, never used by active KUMOJI to choose moves",
        "selection_criterion": "lowest validation Brier; test held out until selection",
        "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "candidate_profiles": candidates,
        "chosen_profile": best[2],
        "holdout_duplicate_positions_removed": excluded,
        "static_cp_calibration_temperature": temperature,
        "metrics": measurements,
        "independent_games": {s: len({r["game_id"] for r in splits[s]})
                              for s in splits},
        "limitations": (
            "Historical self-play, same board positions filtered but games share "
            "opening patterns. Test used in earlier experiment, so this follow-up "
            "does not constitute an untouched confirmatory test. Predictions are "
            "empirical game outcomes, not proof of move quality."
        ),
    }
    (output_dir / "tuning-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.input, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
