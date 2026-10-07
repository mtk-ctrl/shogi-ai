#!/usr/bin/env python3
"""B/C vs high-level YaneuraOu Material benchmark.

Profiles:
- B: Material1x Safety10x ThreatOFF Influence0.316x
- C: Material10x Safety31.6x Threat0.03x Influence0.03x

Opponent levels: 60/70/80/90/100.
Each profile plays 100 games per level = 1,000 total games.

Scheduling:
- 100 blocks x 10 games
- greedily balanced over 20 GitHub runners
- exactly 5 blocks / 50 games per runner
- 4 local subprocesses per runner
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.eval_v2_bc_robustness import PROFILES, LABELS, OPPONENT_OPTIONS
from benchmarks.external_levels import nodes_for_level

LEVELS = (60, 70, 80, 90, 100)
LEVEL_NODES = {level: nodes_for_level(level) for level in LEVELS}
GAMES_PER_MATCHUP = 100
BLOCK_GAMES = 10
BLOCKS_PER_MATCHUP = GAMES_PER_MATCHUP // BLOCK_GAMES
SHARDS = 20
BLOCKS_PER_SHARD = 5


def all_blocks():
    blocks = []
    gid = 0
    for profile in "BC":
        for level in LEVELS:
            for block_index in range(BLOCKS_PER_MATCHUP):
                blocks.append({
                    "global_id": gid,
                    "profile": profile,
                    "level": level,
                    "block_index": block_index,
                    "estimated_cost": LEVEL_NODES[level] + 50000,
                })
                gid += 1
    assert len(blocks) == 100
    return blocks


def assignment():
    """Greedy load balance while keeping exactly five 10-game blocks per shard."""
    shards = [{"cost": 0, "blocks": []} for _ in range(SHARDS)]
    blocks = sorted(
        all_blocks(),
        key=lambda b: (b["estimated_cost"], b["profile"], b["level"], b["block_index"]),
        reverse=True,
    )
    for block in blocks:
        candidates = [
            (s["cost"], len(s["blocks"]), idx)
            for idx, s in enumerate(shards)
            if len(s["blocks"]) < BLOCKS_PER_SHARD
        ]
        _, _, idx = min(candidates)
        shards[idx]["blocks"].append(block)
        shards[idx]["cost"] += block["estimated_cost"]
    assert all(len(s["blocks"]) == BLOCKS_PER_SHARD for s in shards)
    return shards


def shard_blocks(shard: int):
    rows = assignment()[shard]["blocks"]
    assert len(rows) == BLOCKS_PER_SHARD
    return rows


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def execute(engine: str, opponent: str, block: dict, outdir: Path):
    p = block["profile"]
    level = block["level"]
    bi = block["block_index"]
    out = outdir / f"{p}-L{level}-b{bi:02d}.json"
    seed = 2026300000 + (0 if p == "B" else 500000) + level * 1000 + bi * 20
    run([
        sys.executable, "benchmarks/external_match.py",
        "--self-engine", engine,
        "--opponent-engine", opponent,
        "--self-options", json.dumps(PROFILES[p], separators=(",", ":")),
        "--opponent-options", json.dumps(OPPONENT_OPTIONS, separators=(",", ":")),
        "--self-go", "go movetime 200",
        "--opponent-go", f"go nodes {LEVEL_NODES[level]}",
        "--games", str(BLOCK_GAMES),
        "--max-plies", "300",
        "--seed", str(seed),
        "--output", str(out),
    ])
    return str(out)


def ci(score: float, n: int):
    se = math.sqrt(max(score * (1 - score), 1e-12) / n)
    return [max(0.0, score - 1.96 * se), min(1.0, score + 1.96 * se)]


def elo(score: float):
    if not 0 < score < 1:
        return None
    return 400 * math.log10(score / (1 - score))


def cmd_shard(args):
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = shard_blocks(args.shard)
    manifest = {
        "shard": args.shard,
        "games": len(rows) * BLOCK_GAMES,
        "estimated_cost": assignment()[args.shard]["cost"],
        "blocks": rows,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(execute, args.engine, args.opponent, block, out) for block in rows]
        for fut in concurrent.futures.as_completed(futs):
            print("completed", fut.result(), flush=True)


def cmd_analyze(args):
    root = Path(args.root)
    external = {}
    illegal = 0
    for profile in "BC":
        for level in LEVELS:
            files = list(root.rglob(f"{profile}-L{level}-b*.json"))
            if len(files) != BLOCKS_PER_MATCHUP:
                raise SystemExit(
                    f"expected {BLOCKS_PER_MATCHUP} blocks for {profile} L{level}, got {len(files)}"
                )
            ds = [json.loads(f.read_text()) for f in files]
            n = sum(x["games"] for x in ds)
            w = sum(x["wins_self"] for x in ds)
            d = sum(x["draws"] for x in ds)
            l = sum(x["losses_self"] for x in ds)
            ill = sum(x.get("illegal_games", 0) for x in ds)
            illegal += ill
            s = (w + 0.5 * d) / n
            external[f"{profile}-L{level}"] = {
                "profile": profile,
                "label": LABELS[profile],
                "level": level,
                "nodes_per_move": LEVEL_NODES[level],
                "games": n,
                "wins_self": w,
                "draws": d,
                "losses_self": l,
                "score_self": s,
                "score_self_ci95_normal": ci(s, n),
                "elo_vs_opponent_estimate": elo(s),
                "illegal_games": ill,
            }
    if illegal:
        raise SystemExit(f"illegal games detected: {illegal}")

    robustness = {}
    for profile in "BC":
        scores = [external[f"{profile}-L{level}"]["score_self"] for level in LEVELS]
        robustness[profile] = {
            "mean_score": sum(scores) / len(scores),
            "minimum_score": min(scores),
            "scores_by_level": {
                str(level): external[f"{profile}-L{level}"]["score_self"]
                for level in LEVELS
            },
        }

    payload = {
        "stage": "eval_v2_bc_yaneuraou_high_levels",
        "scheduling": {
            "runner_shards": SHARDS,
            "games_per_shard": BLOCKS_PER_SHARD * BLOCK_GAMES,
            "local_parallel": 4,
        },
        "total_games": 1000,
        "official_time": {
            "go": "go movetime 200",
            "AdaptiveLongThink": True,
            "max_ms": 1000,
            "max_uses_per_game": 10,
        },
        "levels": LEVEL_NODES,
        "external": external,
        "robustness": robustness,
        "profiles": {
            p: {"label": LABELS[p], "options": PROFILES[p]} for p in "BC"
        },
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# Evaluation-v2 B/C vs YaneuraOu Material high levels",
        "",
        "- B/C x L60/L70/L80/L90/L100 x 100 games = 1,000 games",
        "- 20 runner shards x 50 games; 4 local lanes/runner",
        "",
    ]
    for level in LEVELS:
        lines.append(f"## Level {level} ({LEVEL_NODES[level]} nodes/move)")
        for profile in "BC":
            r = external[f"{profile}-L{level}"]
            lo, hi = r["score_self_ci95_normal"]
            lines.append(
                f"- {profile}: {r['wins_self']}-{r['draws']}-{r['losses_self']}; "
                f"score={r['score_self']:.1%}; CI≈{lo:.1%}–{hi:.1%}"
            )
        lines.append("")
    lines.append("## Robustness")
    for profile in "BC":
        r = robustness[profile]
        lines.append(
            f"- {profile}: mean={r['mean_score']:.1%}; minimum={r['minimum_score']:.1%}"
        )
    Path(args.summary).write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shard")
    s.add_argument("--engine", required=True)
    s.add_argument("--opponent", required=True)
    s.add_argument("--shard", type=int, choices=range(SHARDS), required=True)
    s.add_argument("--output-dir", required=True)

    a = sub.add_parser("analyze")
    a.add_argument("--root", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--summary", required=True)

    args = p.parse_args()
    if args.cmd == "shard":
        cmd_shard(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
