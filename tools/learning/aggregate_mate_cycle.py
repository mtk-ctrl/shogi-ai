#!/usr/bin/env python3
"""Aggregate fixed-A/B mate-learning game shards without changing the engine."""
import argparse
import hashlib
import json
from pathlib import Path


def aggregate(directory: Path, expected: int) -> dict:
    files = sorted(directory.glob("match-*.json"))
    if len(files) != expected:
        raise ValueError(f"Expected {expected} shards, got {len(files)}")
    records = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    reference = records[0]
    keys = ("go_command", "max_plies", "options_a", "options_b")
    for i, record in enumerate(records):
        if any(record.get(k) != reference.get(k) for k in keys):
            raise ValueError(f"Mismatched match settings in shard {i}")
        if record.get("sha256_a") != reference.get("sha256_a") or record.get("sha256_b") != reference.get("sha256_b"):
            raise ValueError(f"Engine binary mismatch in shard {i}")
        ka = record.get("position_knowledge", {}).get("A", {})
        kb = record.get("position_knowledge", {}).get("B", {})
        if not ka.get("available") or not kb.get("available") or ka.get("sha256") != kb.get("sha256"):
            raise ValueError(f"Missing or asymmetric adopted position knowledge in shard {i}")
        if record["illegal_games"]:
            raise ValueError(f"Illegal move in shard {i}")
        if not record.get("details"):
            raise ValueError(f"Missing game detail in shard {i}")
    wins_a = sum(x["wins_a"] for x in records)
    wins_b = sum(x["wins_b"] for x in records)
    draws = sum(x["draws"] for x in records)
    games = wins_a + wins_b + draws
    if games <= 0:
        raise ValueError("No games")
    score = (wins_a + draws / 2) / games
    # Bernoulli-equivalent normal approximation. For scored games 0/0.5/1,
    # compute the sample variance, not p(1-p), and label as approximate.
    values = ([1.0] * wins_a + [0.5] * draws + [0.0] * wins_b)
    variance = sum((x - score)**2 for x in values) / (games - 1) if games > 1 else 0.0
    err = 1.96 * (variance / games) ** 0.5
    return {
        "status": "candidate_unadopted",
        "games": games,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "draws": draws,
        "score_a": score,
        "score_95pct_approx": [max(0, score - err), min(1, score + err)],
        "illegal_games": 0,
        "candidate_sha256": reference["sha256_a"],
        "baseline_sha256": reference["sha256_b"],
        "knowledge_sha256": reference["position_knowledge"]["A"]["sha256"],
        "go_command": reference["go_command"],
        "options_a": reference["options_a"],
        "options_b": reference["options_b"],
        "timing_ms": {
            side: {
                "mean_of_shard_means": sum(r["timing_ms"][side]["mean"] for r in records)/len(records),
                "max_observed": max(r["timing_ms"][side]["max"] for r in records),
            } for side in ("A", "B")
        },
        "note": "Do not adopt automatically. Validate game trajectories, training data and tactics."
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = aggregate(args.input_dir, args.expected_shards)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
