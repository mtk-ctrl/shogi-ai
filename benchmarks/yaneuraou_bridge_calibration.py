#!/usr/bin/env python3
"""Calibrate YaneuraOu edition strength on the shared 1..100 node scale.

For a fixed KPPT level, search for the MATERIAL level that scores closest to
50% in direct engine-vs-engine games.  This creates an edition bridge without
changing the meaning of the shared level number itself.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.external_levels import nodes_for_level

YANE_OPTIONS = {"Threads": 1, "USI_Hash": 16, "USI_OwnBook": False}
KPPT_OPTIONS = {**YANE_OPTIONS, "EvalDir": "eval"}


def run_match(material_engine: str, kppt_engine: str, kppt_level: int,
              material_level: int, games: int, seed: int, output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "benchmarks/external_match.py",
        "--self-engine", kppt_engine,
        "--opponent-engine", material_engine,
        "--self-options", json.dumps(KPPT_OPTIONS, separators=(",", ":")),
        "--opponent-options", json.dumps(YANE_OPTIONS, separators=(",", ":")),
        "--self-go", f"go nodes {nodes_for_level(kppt_level)}",
        "--opponent-go", f"go nodes {nodes_for_level(material_level)}",
        "--games", str(games),
        "--max-plies", "300",
        "--seed", str(seed),
        "--output", str(output),
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    data = json.loads(output.read_text())
    if data.get("illegal_games", 0):
        raise RuntimeError(f"illegal games in {output}")
    return data


def ci95(score: float, n: int) -> list[float]:
    se = math.sqrt(max(score * (1.0 - score), 1e-12) / n)
    return [max(0.0, score - 1.96 * se), min(1.0, score + 1.96 * se)]


def compact(level: int, data: dict, phase: str) -> dict:
    return {
        "phase": phase,
        "material_level": level,
        "material_nodes": nodes_for_level(level),
        "games": data["games"],
        "kppt_wins": data["wins_self"],
        "draws": data["draws"],
        "kppt_losses": data["losses_self"],
        "kppt_score": data["score_self"],
        "elapsed_seconds": data["elapsed_seconds"],
    }


def calibrate(args) -> dict:
    if not 1 <= args.kppt_level <= 100:
        raise ValueError("kppt-level must be 1..100")
    if not 1 <= args.material_low <= args.material_high <= 100:
        raise ValueError("material bracket must be inside 1..100")
    if args.probe_games < 10 or args.probe_games % 2:
        raise ValueError("probe-games must be an even number >= 10")
    if args.final_games < 20 or args.final_games % 2:
        raise ValueError("final-games must be an even number >= 20")

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    tested: dict[int, dict] = {}

    lo, hi = args.material_low, args.material_high
    step = 0
    while lo <= hi and step < args.max_probes:
        mid = (lo + hi) // 2
        path = outdir / f"probe-k{args.kppt_level:03d}-m{mid:03d}.json"
        data = run_match(
            args.material_engine, args.kppt_engine, args.kppt_level, mid,
            args.probe_games,
            args.seed + args.kppt_level * 10000 + step * 200,
            path,
        )
        row = compact(mid, data, "probe")
        tested[mid] = row
        score = row["kppt_score"]
        print(f"KPPT L{args.kppt_level} vs MATERIAL L{mid}: {score:.1%}", flush=True)

        if 0.40 <= score <= 0.60:
            break
        if score > 0.50:
            lo = mid + 1
        else:
            hi = mid - 1
        step += 1

    best = min(tested.values(), key=lambda r: (abs(r["kppt_score"] - 0.5), r["material_level"]))
    final_levels = [best["material_level"]]

    final_rows: list[dict] = []
    first_level = final_levels[0]
    path = outdir / f"final-k{args.kppt_level:03d}-m{first_level:03d}.json"
    data = run_match(
        args.material_engine, args.kppt_engine, args.kppt_level, first_level,
        args.final_games,
        args.seed + args.kppt_level * 10000 + 7000,
        path,
    )
    first = compact(first_level, data, "final")
    final_rows.append(first)

    # If the first confirmation is clearly off 50%, confirm the adjacent level
    # in the direction that should restore balance.
    if first["kppt_score"] > 0.55 and first_level < args.material_high:
        neighbor = first_level + 1
    elif first["kppt_score"] < 0.45 and first_level > args.material_low:
        neighbor = first_level - 1
    else:
        neighbor = None

    if neighbor is not None:
        path = outdir / f"final-k{args.kppt_level:03d}-m{neighbor:03d}.json"
        data = run_match(
            args.material_engine, args.kppt_engine, args.kppt_level, neighbor,
            args.final_games,
            args.seed + args.kppt_level * 10000 + 8000,
            path,
        )
        final_rows.append(compact(neighbor, data, "final"))

    chosen = min(final_rows, key=lambda r: (abs(r["kppt_score"] - 0.5), r["material_level"]))
    lo95, hi95 = ci95(chosen["kppt_score"], chosen["games"])
    return {
        "kind": "yaneuraou_edition_bridge",
        "shared_scale": "nodes_per_move_1_to_100",
        "source_edition": "KPPT_Apery_WCSC26",
        "source_level": args.kppt_level,
        "source_nodes": nodes_for_level(args.kppt_level),
        "target_edition": "MATERIAL",
        "search_bracket": [args.material_low, args.material_high],
        "probe_games": args.probe_games,
        "final_games": args.final_games,
        "probes": [tested[k] for k in sorted(tested)],
        "finals": final_rows,
        "equivalent_material_level": chosen["material_level"],
        "equivalent_material_nodes": chosen["material_nodes"],
        "kppt_score_at_equivalent": chosen["kppt_score"],
        "kppt_score_ci95_normal": [lo95, hi95],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--material-engine", required=True)
    p.add_argument("--kppt-engine", required=True)
    p.add_argument("--kppt-level", type=int, required=True)
    p.add_argument("--material-low", type=int, default=1)
    p.add_argument("--material-high", type=int, default=100)
    p.add_argument("--probe-games", type=int, default=20)
    p.add_argument("--final-games", type=int, default=100)
    p.add_argument("--max-probes", type=int, default=7)
    p.add_argument("--seed", type=int, default=20261007)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--summary", required=True)
    args = p.parse_args()

    result = calibrate(args)
    summary = Path(args.summary)
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
