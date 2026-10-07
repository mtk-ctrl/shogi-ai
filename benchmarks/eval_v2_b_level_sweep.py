#!/usr/bin/env python3
"""Find the current KUMOJI strength band on the YaneuraOu Material 1..100 scale.

Default sweep for the adopted Evaluation-v2 B profile:
levels 48..57, 100 games per level.

Scheduling is optimized for GitHub-hosted 4-vCPU runners:
- 10-game color-balanced blocks
- 100 total blocks / 20 runners = 5 blocks (50 games) per runner
- four blocks run concurrently inside each runner
- greedy assignment balances higher-node levels across runners
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

BLOCK_GAMES = 10
SHARDS = 20
LOCAL_PARALLEL = 4


def build_blocks(level_start: int, level_end: int, games_per_level: int):
    if level_start < 1 or level_end > 100 or level_start > level_end:
        raise ValueError("levels must satisfy 1 <= start <= end <= 100")
    if games_per_level < BLOCK_GAMES or games_per_level % BLOCK_GAMES:
        raise ValueError(f"games-per-level must be a positive multiple of {BLOCK_GAMES}")
    blocks = []
    gid = 0
    for level in range(level_start, level_end + 1):
        nodes = nodes_for_level(level)
        for block_index in range(games_per_level // BLOCK_GAMES):
            blocks.append({
                "global_id": gid,
                "level": level,
                "nodes": nodes,
                "block_index": block_index,
                # Self side is timed and usually dominates at low levels; opponent
                # node cost becomes increasingly important toward the top end.
                "estimated_cost": 50000 + nodes,
            })
            gid += 1
    return blocks


def assign_blocks(level_start: int, level_end: int, games_per_level: int):
    blocks = build_blocks(level_start, level_end, games_per_level)
    if len(blocks) < SHARDS:
        raise ValueError("sweep must contain at least 20 blocks to fill all runners")
    shards = [{"cost": 0, "blocks": []} for _ in range(SHARDS)]
    # Largest-first bin packing reduces the long tail from the stronger levels.
    for block in sorted(blocks, key=lambda b: (b["estimated_cost"], b["global_id"]), reverse=True):
        idx = min(range(SHARDS), key=lambda i: (shards[i]["cost"], len(shards[i]["blocks"]), i))
        shards[idx]["blocks"].append(block)
        shards[idx]["cost"] += block["estimated_cost"]
    return shards


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def run_block(engine: str, opponent: str, block: dict, outdir: Path):
    level = block["level"]
    bi = block["block_index"]
    out = outdir / f"L{level}-b{bi:02d}.json"
    seed = 2026400000 + level * 10000 + bi * 20
    run([
        sys.executable, "benchmarks/external_match.py",
        "--self-engine", engine,
        "--opponent-engine", opponent,
        "--self-options", json.dumps(PROFILES["B"], separators=(",", ":")),
        "--opponent-options", json.dumps(OPPONENT_OPTIONS, separators=(",", ":")),
        "--self-go", "go movetime 200",
        "--opponent-go", f"go nodes {block['nodes']}",
        "--games", str(BLOCK_GAMES),
        "--max-plies", "300",
        "--seed", str(seed),
        "--output", str(out),
    ])
    return str(out)


def ci95(score: float, n: int):
    se = math.sqrt(max(score * (1.0 - score), 1e-12) / n)
    return [max(0.0, score - 1.96 * se), min(1.0, score + 1.96 * se)]


def elo(score: float):
    if not 0.0 < score < 1.0:
        return None
    return 400.0 * math.log10(score / (1.0 - score))


def cmd_shard(args):
    assignments = assign_blocks(args.level_start, args.level_end, args.games_per_level)
    rows = assignments[args.shard]
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "shard": args.shard,
        "games": len(rows) * BLOCK_GAMES,
        "estimated_cost": assignments[args.shard]["cost"] if isinstance(assignments[args.shard], dict) else None,
        "blocks": rows,
    }
    # assignments currently stores dicts; normalize for manifest and execution.
    if isinstance(assignments[args.shard], dict):
        rows = assignments[args.shard]["blocks"]
        manifest = {
            "shard": args.shard,
            "games": len(rows) * BLOCK_GAMES,
            "estimated_cost": assignments[args.shard]["cost"],
            "blocks": rows,
        }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=LOCAL_PARALLEL) as pool:
        futs = [pool.submit(run_block, args.engine, args.opponent, row, out) for row in rows]
        for fut in concurrent.futures.as_completed(futs):
            print("completed", fut.result(), flush=True)


def cmd_analyze(args):
    root = Path(args.root)
    results = {}
    illegal = 0
    for level in range(args.level_start, args.level_end + 1):
        files = list(root.rglob(f"L{level}-b*.json"))
        expected = args.games_per_level // BLOCK_GAMES
        if len(files) != expected:
            raise SystemExit(f"L{level}: expected {expected} blocks, got {len(files)}")
        ds = [json.loads(p.read_text()) for p in files]
        n = sum(d["games"] for d in ds)
        w = sum(d["wins_self"] for d in ds)
        dr = sum(d["draws"] for d in ds)
        l = sum(d["losses_self"] for d in ds)
        ill = sum(d.get("illegal_games", 0) for d in ds)
        illegal += ill
        score = (w + 0.5 * dr) / n
        results[level] = {
            "level": level,
            "nodes_per_move": nodes_for_level(level),
            "games": n,
            "wins_self": w,
            "draws": dr,
            "losses_self": l,
            "score_self": score,
            "score_self_ci95_normal": ci95(score, n),
            "elo_vs_opponent_estimate": elo(score),
            "illegal_games": ill,
        }
    if illegal:
        raise SystemExit(f"illegal games detected: {illegal}")

    closest = min(results.values(), key=lambda r: (abs(r["score_self"] - 0.5), r["level"]))
    equal_zone = [r["level"] for r in results.values() if 0.45 <= r["score_self"] < 0.55]
    clear = [r["level"] for r in results.values() if r["score_self"] >= 0.55]
    payload = {
        "stage": "yaneuraou_material_level_sweep",
        "profile": "B",
        "profile_label": LABELS["B"],
        "levels": [args.level_start, args.level_end],
        "games_per_level": args.games_per_level,
        "total_games": args.games_per_level * (args.level_end - args.level_start + 1),
        "official_time": {
            "go": "go movetime 200",
            "AdaptiveLongThink": True,
            "max_ms": 1000,
            "max_uses_per_game": 10,
        },
        "results": {str(k): v for k, v in results.items()},
        "closest_to_50": closest,
        "equal_zone_levels": equal_zone,
        "highest_clear_level_in_sweep": max(clear) if clear else None,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# KUMOJI vs YaneuraOu Material level sweep",
        "",
        f"- profile: B ({LABELS['B']})",
        f"- levels: {args.level_start}..{args.level_end}",
        f"- {args.games_per_level} games/level",
        f"- total: {payload['total_games']} games",
        "",
        "| Level | nodes/move | W-D-L | score | 95% CI |",
        "|---:|---:|---:|---:|---:|",
    ]
    for level, r in results.items():
        lo, hi = r["score_self_ci95_normal"]
        lines.append(
            f"| {level} | {r['nodes_per_move']} | {r['wins_self']}-{r['draws']}-{r['losses_self']} | "
            f"{r['score_self']:.1%} | {lo:.1%}–{hi:.1%} |"
        )
    lines += [
        "",
        f"- closest to 50%: Level {closest['level']} ({closest['score_self']:.1%})",
        f"- equal zone (45–55%): {equal_zone or 'none'}",
        f"- highest clear level in this sweep (>=55%): {payload['highest_clear_level_in_sweep']}",
    ]
    Path(args.summary).write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--engine", required=True)
    s.add_argument("--opponent", required=True)
    s.add_argument("--shard", type=int, choices=range(SHARDS), required=True)
    s.add_argument("--level-start", type=int, default=48)
    s.add_argument("--level-end", type=int, default=57)
    s.add_argument("--games-per-level", type=int, default=100)
    s.add_argument("--output-dir", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--root", required=True)
    a.add_argument("--level-start", type=int, default=48)
    a.add_argument("--level-end", type=int, default=57)
    a.add_argument("--games-per-level", type=int, default=100)
    a.add_argument("--output", required=True)
    a.add_argument("--summary", required=True)
    args = p.parse_args()
    if args.cmd == "shard":
        cmd_shard(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
