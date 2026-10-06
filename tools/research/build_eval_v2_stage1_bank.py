#!/usr/bin/env python3
"""Build a phase-balanced benchmark-only position bank from Evaluation-v2 stage-1 games.

The source run explored all 3,125 OA configurations.  This script deliberately
samples positions across that wide parameter population instead of reusing the
historical opening book or experience cache.  The resulting prefixes are
benchmark contexts only; they are not training labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

GAME_RE = re.compile(r"cfg-(\d{4})/game-(\d{3})\.json$")
PHASES = (("early", 24), ("middle", 64), ("late", 104))


def load_games(root: Path) -> dict[int, list[dict]]:
    by_cfg: dict[int, list[dict]] = {}
    for path in root.rglob("game-*.json"):
        match = re.search(r"cfg-(\d{4})[/\\]game-(\d{3})\.json$", str(path))
        if not match:
            continue
        cfg = int(match.group(1))
        game = int(match.group(2))
        data = json.loads(path.read_text(encoding="utf-8"))
        moves = data.get("moves")
        plies = data.get("plies")
        if not isinstance(moves, list) or not isinstance(plies, int):
            continue
        by_cfg.setdefault(cfg, []).append({"game": game, "plies": plies, "moves": moves})
    return by_cfg


def stable_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_bank(by_cfg: dict[int, list[dict]], per_phase: int, min_remaining: int,
               source_run_id: int) -> list[dict]:
    used_cfg: set[int] = set()
    used_prefix: set[str] = set()
    rows: list[dict] = []
    for phase, target in PHASES:
        candidates = []
        for cfg, games in by_cfg.items():
            if cfg in used_cfg:
                continue
            eligible = [g for g in games if g["plies"] >= target + min_remaining]
            if not eligible:
                continue
            eligible.sort(key=lambda g: stable_key(f"{phase}:{cfg}:{g['game']}"))
            game = eligible[0]
            prefix = game["moves"][:target]
            prefix_text = " ".join(prefix)
            if prefix_text in used_prefix:
                continue
            candidates.append((stable_key(f"{phase}:{cfg}:{game['game']}:{prefix_text}"),
                               cfg, game, prefix, prefix_text))
        candidates.sort(key=lambda x: x[0])
        if len(candidates) < per_phase:
            raise SystemExit(f"not enough {phase} positions: {len(candidates)} < {per_phase}")
        for _, cfg, game, prefix, prefix_text in candidates[:per_phase]:
            used_cfg.add(cfg)
            used_prefix.add(prefix_text)
            rid = stable_key(
                f"eval-v2-stage1:{source_run_id}:{cfg}:{game['game']}:{target}:{prefix_text}"
            )[:20]
            rows.append({
                "id": rid,
                "moves": prefix,
                "ply": target,
                "phase": phase,
                "tags": [phase, "evaluation-v2-stage1-diverse"],
                "source": {
                    "run_id": source_run_id,
                    "config": cfg,
                    "game": game["game"],
                    "selection": "uniform-wide-v2-stage1",
                },
                "learning_eligible": False,
                "benchmark_position_only": True,
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-phase", type=int, default=100)
    parser.add_argument("--min-remaining", type=int, default=20)
    parser.add_argument("--source-run-id", type=int, default=37466626100)
    args = parser.parse_args()
    if args.per_phase < 1 or args.min_remaining < 1:
        raise SystemExit("per-phase and min-remaining must be positive")
    by_cfg = load_games(args.input)
    if len(by_cfg) != 3125:
        raise SystemExit(f"stage-1 configs incomplete: {len(by_cfg)}/3125")
    rows = build_bank(by_cfg, args.per_phase, args.min_remaining, args.source_run_id)
    counts = {phase: sum(r["phase"] == phase for r in rows) for phase, _ in PHASES}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8",
    )
    print(json.dumps({
        "configs": len(by_cfg),
        "positions": len(rows),
        "phase_counts": counts,
        "unique_source_configs": len({r["source"]["config"] for r in rows}),
        "source_run_id": args.source_run_id,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
