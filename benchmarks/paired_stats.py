#!/usr/bin/env python3
"""Paired-opening statistics for arena shard results.

Every opening is played twice with the colours swapped (arena --opening-plies).
The unit of analysis is the PAIR: A's score over the two games of one opening.
Opening luck then cancels inside a pair, so the interval is narrower than the
plain per-game interval whenever the openings matter.
"""
import json
import math
import sys
from pathlib import Path


def game_points(game):
    if game["winner"] == "A":
        return 1.0
    if game["winner"] == "B":
        return 0.0
    return 0.5


def paired_summary(shards):
    """`shards`: list of arena result dicts. None when the run was not paired."""
    pairs = {}
    for shard in shards:
        for game in shard.get("details", []):
            pair = game.get("opening_pair")
            if pair is None:
                continue
            pairs.setdefault(pair, []).append(game_points(game))
    if not pairs:
        return None
    complete = {k: v for k, v in pairs.items() if len(v) == 2}
    n = len(complete)
    if n < 2:
        return {"pairs": n, "note": "fewer than two complete pairs"}
    pair_scores = [sum(v) / 2 for v in complete.values()]
    mean = sum(pair_scores) / n
    variance = sum((x - mean) ** 2 for x in pair_scores) / (n - 1)
    se = math.sqrt(variance / n)
    games = [p for v in complete.values() for p in v]
    gm = sum(games) / len(games)
    gse = math.sqrt(max(gm * (1 - gm), 0) / len(games))
    return {
        "pairs": n,
        "incomplete_pairs": len(pairs) - n,
        "pair_score_a": mean,
        "pair_se": se,
        "pair_95pct": [max(0.0, mean - 1.96 * se), min(1.0, mean + 1.96 * se)],
        "per_game_se_for_comparison": gse,
        "pairs_a_swept": sum(1 for x in pair_scores if x == 1.0),
        "pairs_split": sum(1 for x in pair_scores if x == 0.5),
        "pairs_b_swept": sum(1 for x in pair_scores if x == 0.0),
        "variance_ratio_vs_per_game": (se / gse) ** 2 if gse else None,
    }


def main(paths):
    shards = [json.loads(Path(p).read_text()) for p in paths]
    print(json.dumps(paired_summary(shards), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
