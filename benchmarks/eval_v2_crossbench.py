#!/usr/bin/env python3
"""Wide Evaluation-v2 cross-benchmark.

The broad search deliberately uses three distinct evidence streams:
1) ordinary startpos games against the current v1 baseline;
2) early/middle/late benchmark positions sampled from the full stage-1 OA population;
3) games against a pinned external YaneuraOu material engine.

No opening book, experience cache, historical evaluation labels, opponent score/PV,
or opponent moves are used as teacher data.  This stage ranks directions only;
it does not automatically discard candidates.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import glob
import hashlib
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.eval_v2_overnight import BASE, FACTORS, VECTORS, rank_mod5

MULT = (0.1, math.sqrt(0.1), 1.0, math.sqrt(10.0), 10.0)
LABEL = ("0.1x", "0.316x", "1x", "3.162x", "10x")
STREAM_WEIGHTS = {"start": 0.20, "positions": 0.40, "external": 0.40}
PHASES = ("early", "middle", "late")


def atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def design_rows() -> list[dict]:
    for cols in itertools.combinations(VECTORS, 3):
        assert rank_mod5(cols) == 3, cols
    rows = []
    for idx, x in enumerate(itertools.product(range(5), repeat=5)):
        codes = [sum(v[j] * x[j] for j in range(5)) % 5 for v in VECTORS]
        opts = {"EvalV2": True, "AdaptiveLongThink": False, "EvalPositionalCap": 5000}
        relative = {}
        for name, code in zip(FACTORS, codes):
            relative[name] = LABEL[code]
            opts[name] = max(1, int(round(BASE[name] * MULT[code])))
        rows.append({"index": idx, "codes": codes, "relative": relative, "options": opts})
    assert len(rows) == 3125
    for cols in itertools.combinations(range(10), 3):
        counts = {}
        for row in rows:
            key = tuple(row["codes"][c] for c in cols)
            counts[key] = counts.get(key, 0) + 1
        assert len(counts) == 125 and set(counts.values()) == {25}
    return rows


def candidate_options(row: dict) -> dict:
    return {
        "OpeningBook": False,
        "ExperienceCache": False,
        "MateAssist": True,
        "AdaptiveLongThink": False,
        **row["options"],
    }


def v1_options() -> dict:
    return {
        "OpeningBook": False,
        "ExperienceCache": False,
        "MateAssist": True,
        "AdaptiveLongThink": False,
        "EvalV2": False,
    }


def load_bank(path: Path) -> dict[str, list[dict]]:
    groups = {phase: [] for phase in PHASES}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        phase = row.get("phase")
        if phase in groups:
            groups[phase].append(row)
    for phase in PHASES:
        groups[phase].sort(key=lambda r: r["id"])
        if len(groups[phase]) < 20:
            raise SystemExit(f"bank phase {phase} too small: {len(groups[phase])}")
    return groups


def select_positions(row: dict, bank: dict[str, list[dict]]) -> list[dict]:
    selected = []
    code_text = ",".join(map(str, row["codes"]))
    for phase in PHASES:
        group = bank[phase]
        digest = hashlib.sha256(f"{phase}:{row['index']}:{code_text}".encode("utf-8")).hexdigest()
        selected.append(group[int(digest[:16], 16) % len(group)])
    return selected


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def self_one(row: dict, engine: str, bank: dict[str, list[dict]], root: Path,
             movetime: int, seed: int) -> int:
    out = root / f"cfg-{row['index']:04d}"
    summary_path = out / "self-summary.json"
    if summary_path.exists():
        return row["index"]
    out.mkdir(parents=True, exist_ok=True)
    atomic(out / "design.json", row)
    oa = candidate_options(row)
    ob = v1_options()

    start_dir = out / "start"
    if not (start_dir / "summary.json").exists():
        run([
            sys.executable, "benchmarks/eval_v2_match.py",
            "--engine", str(Path(engine).resolve()),
            "--pairs", "1", "--lanes", "1",
            "--seed", str(seed + row["index"] * 64),
            "--max-plies", "240",
            "--go-command", f"go movetime {movetime}",
            "--output-dir", str(start_dir),
            "--options-a", json.dumps(oa, separators=(",", ":")),
            "--options-b", json.dumps(ob, separators=(",", ":")),
        ])

    positions_path = out / "positions.json"
    selected = select_positions(row, bank)
    if not positions_path.exists():
        bank_path = out / "selected-bank.jsonl"
        bank_path.write_text(
            "".join(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n" for p in selected),
            encoding="utf-8",
        )
        run([
            sys.executable, "benchmarks/position_arena.py",
            "--engine-a", str(Path(engine).resolve()),
            "--engine-b", str(Path(engine).resolve()),
            "--options-a", json.dumps(oa, separators=(",", ":")),
            "--options-b", json.dumps(ob, separators=(",", ":")),
            "--bank", str(bank_path),
            "--positions", "3",
            "--max-plies", "220",
            "--seed", str(seed + 10_000_000 + row["index"] * 64),
            "--go-command", f"go movetime {movetime}",
            "--output", str(positions_path),
        ])

    start = json.loads((start_dir / "summary.json").read_text(encoding="utf-8"))
    positions = json.loads(positions_path.read_text(encoding="utf-8"))
    phase_scores = {}
    for phase in PHASES:
        games = [g for g in positions["details"] if phase in g.get("tags", [])]
        points = sum(1.0 if g.get("winner") == "A" else 0.5 if g.get("winner") is None else 0.0
                     for g in games)
        phase_scores[phase] = points / len(games) if games else None
    atomic(summary_path, {
        "config": row["index"],
        "movetime_ms": movetime,
        "start": {
            "games": start["games"],
            "wins": start["wins_a"],
            "draws": start["draws"],
            "losses": start["wins_b"],
            "score": start["score_a"],
        },
        "positions": {
            "games": positions["games"],
            "wins": positions["wins_a"],
            "draws": positions["draws"],
            "losses": positions["wins_b"],
            "score": positions["score_a"],
            "phase_scores": phase_scores,
            "position_ids": [p["id"] for p in selected],
        },
        "illegal_games": start["illegal_games"] + positions["illegal_games"],
    })
    return row["index"]


def external_one(row: dict, engine: str, opponent: str, root: Path, movetime: int,
                 opponent_nodes: int, seed: int) -> int:
    out = root / f"cfg-{row['index']:04d}"
    result = out / "external.json"
    if result.exists():
        return row["index"]
    out.mkdir(parents=True, exist_ok=True)
    atomic(out / "design.json", row)
    run([
        sys.executable, "benchmarks/external_match.py",
        "--self-engine", str(Path(engine).resolve()),
        "--opponent-engine", str(Path(opponent).resolve()),
        "--self-options", json.dumps(candidate_options(row), separators=(",", ":")),
        "--opponent-options", json.dumps(
            {"Threads": 1, "USI_Hash": 16, "USI_OwnBook": False}, separators=(",", ":")
        ),
        "--self-go", f"go movetime {movetime}",
        "--opponent-go", f"go nodes {opponent_nodes}",
        "--games", "2",
        "--max-plies", "240",
        "--seed", str(seed + row["index"] * 64),
        "--output", str(result),
    ])
    return row["index"]


def rows_for_shard(shards: int, shard: int) -> list[dict]:
    rows = design_rows()
    return [r for pos, r in enumerate(rows) if pos % shards == shard]


def cmd_self(args) -> None:
    rows = rows_for_shard(args.shards, args.shard)
    bank = load_bank(Path(args.bank))
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    atomic(root / "stage.json", {
        "kind": "crossbench-self",
        "shard": args.shard,
        "shards": args.shards,
        "configs": len(rows),
        "movetime_ms": args.movetime,
        "multipliers": MULT,
        "labels": LABEL,
    })
    jobs = [(r, args.engine, bank, root, args.movetime, args.seed) for r in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for done, idx in enumerate(pool.map(lambda x: self_one(*x), jobs), 1):
            print(f"self shard {args.shard}: {done}/{len(rows)} cfg={idx}", flush=True)


def cmd_external(args) -> None:
    rows = rows_for_shard(args.shards, args.shard)
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    atomic(root / "stage.json", {
        "kind": "crossbench-external",
        "shard": args.shard,
        "shards": args.shards,
        "configs": len(rows),
        "movetime_ms": args.movetime,
        "opponent": "YaneuraOu YANEURAOU_ENGINE_MATERIAL",
        "opponent_level": args.opponent_level,
        "opponent_nodes": args.opponent_nodes,
        "multipliers": MULT,
        "labels": LABEL,
    })
    jobs = [(r, args.engine, args.opponent, root, args.movetime,
             args.opponent_nodes, args.seed) for r in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for done, idx in enumerate(pool.map(lambda x: external_one(*x), jobs), 1):
            print(f"external shard {args.shard}: {done}/{len(rows)} cfg={idx}", flush=True)


def collect(path: str, filename: str) -> dict[int, dict]:
    out = {}
    for fp in glob.glob(str(Path(path) / "**" / filename), recursive=True):
        p = Path(fp)
        design = p.parent / "design.json"
        if not design.exists():
            continue
        row = json.loads(design.read_text(encoding="utf-8"))
        out[row["index"]] = {"row": row, "result": json.loads(p.read_text(encoding="utf-8"))}
    return out


def main_effects(records: dict[int, dict], metric: str) -> tuple[float, dict[str, list[float]]]:
    vals = [r[metric] for r in records.values()]
    mu = sum(vals) / len(vals)
    effects = {}
    for fi, factor in enumerate(FACTORS):
        levels = []
        for level in range(5):
            group = [r[metric] for r in records.values() if r["row"]["codes"][fi] == level]
            levels.append(sum(group) / len(group))
        effects[factor] = levels
    return mu, effects


def pair_effects(records: dict[int, dict], metric: str, mu: float,
                 main: dict[str, list[float]]) -> list[dict]:
    ranked = []
    for i, j in itertools.combinations(range(10), 2):
        residuals = []
        for a in range(5):
            for b in range(5):
                group = [r[metric] for r in records.values()
                         if r["row"]["codes"][i] == a and r["row"]["codes"][j] == b]
                score = sum(group) / len(group)
                residuals.append(score - mu - (main[FACTORS[i]][a] - mu)
                                 - (main[FACTORS[j]][b] - mu))
        rms = math.sqrt(sum(x * x for x in residuals) / len(residuals))
        ranked.append({
            "pair": [FACTORS[i], FACTORS[j]],
            "rms": rms,
            "max_abs": max(abs(x) for x in residuals),
        })
    ranked.sort(key=lambda x: (x["rms"], x["max_abs"]), reverse=True)
    return ranked


def cmd_analyze(args) -> None:
    selfs = collect(args.self_root, "self-summary.json")
    externals = collect(args.external_root, "external.json")
    if len(selfs) != 3125 or len(externals) != 3125:
        raise SystemExit(f"incomplete data: self={len(selfs)}/3125 external={len(externals)}/3125")
    records = {}
    for idx in sorted(selfs):
        s = selfs[idx]
        e = externals[idx]
        if s["result"]["illegal_games"] or e["result"]["illegal_games"]:
            raise SystemExit(f"illegal game in config {idx}")
        start = float(s["result"]["start"]["score"])
        positions = float(s["result"]["positions"]["score"])
        external = float(e["result"]["score_self"])
        combined = (STREAM_WEIGHTS["start"] * start
                    + STREAM_WEIGHTS["positions"] * positions
                    + STREAM_WEIGHTS["external"] * external)
        records[idx] = {
            "row": s["row"],
            "start": start,
            "positions": positions,
            "external": external,
            "combined": combined,
            **{f"phase_{p}": float(s["result"]["positions"]["phase_scores"][p]) for p in PHASES},
        }

    metrics = ("start", "positions", "external", "combined",
               "phase_early", "phase_middle", "phase_late")
    overall = {}
    mains = {}
    for metric in metrics:
        mu, effects = main_effects(records, metric)
        overall[metric] = mu
        mains[metric] = effects
    pairs = pair_effects(records, "combined", overall["combined"], mains["combined"])

    boundaries = {}
    for factor in FACTORS:
        boundaries[factor] = {}
        for metric in ("positions", "external", "combined"):
            vals = mains[metric][factor]
            best = max(range(5), key=lambda i: vals[i])
            boundaries[factor][metric] = {
                "best_level": LABEL[best],
                "best_score": vals[best],
                "at_boundary": best in (0, 4),
            }

    top_raw = sorted(records.values(), key=lambda r: r["combined"], reverse=True)[:50]
    payload = {
        "stage": "eval_v2_crossbench_wide_100x",
        "design": {
            "configs": 3125,
            "multipliers": MULT,
            "labels": LABEL,
            "range_ratio": MULT[-1] / MULT[0],
            "strength": 3,
            "stream_weights": STREAM_WEIGHTS,
            "games_per_config": {"start_v1": 2, "phase_v1": 6, "external_yaneuraou": 2},
            "total_games": 31250,
        },
        "external_opponent": {
            "engine": "YaneuraOu",
            "edition": "YANEURAOU_ENGINE_MATERIAL",
            "level": args.opponent_level,
            "nodes": args.opponent_nodes,
            "note": "external implementation/search baseline; material edition is not treated as an evaluation-style teacher",
        },
        "overall": overall,
        "main_effects": {
            metric: {factor: {LABEL[i]: vals[i] for i in range(5)}
                     for factor, vals in effects.items()}
            for metric, effects in mains.items()
        },
        "boundary_flags": boundaries,
        "top_pair_interactions_combined": pairs[:20],
        "top_raw_configs": [
            {
                "index": r["row"]["index"],
                "relative": r["row"]["relative"],
                "start": r["start"],
                "positions": r["positions"],
                "external": r["external"],
                "combined": r["combined"],
            }
            for r in top_raw
        ],
        "selection_policy": "report only; no automatic candidate elimination in this stage",
    }
    out = Path(args.output)
    atomic(out, payload)

    lines = [
        "# Evaluation-v2 cross-benchmark broad result",
        "",
        f"- configurations: 3,125",
        f"- multiplier range: {LABEL[0]} .. {LABEL[-1]} ({MULT[-1] / MULT[0]:.0f}x)",
        "- games/config: 2 startpos vs v1 + 6 phase-bank vs v1 + 2 vs YaneuraOu = 10",
        f"- total games: 31,250",
        f"- combined weights: start {STREAM_WEIGHTS['start']:.0%}, positions {STREAM_WEIGHTS['positions']:.0%}, external {STREAM_WEIGHTS['external']:.0%}",
        "",
        "## Overall",
        f"- start vs v1: {overall['start']:.3f}",
        f"- phase-bank vs v1: {overall['positions']:.3f}",
        f"- YaneuraOu: {overall['external']:.3f}",
        f"- combined: {overall['combined']:.3f}",
        "",
        "## Boundary check",
    ]
    for factor in FACTORS:
        c = boundaries[factor]["combined"]
        mark = " **BOUNDARY**" if c["at_boundary"] else ""
        lines.append(f"- {factor}: {c['best_level']} ({c['best_score']:.3f}){mark}")
    lines += ["", "## Largest combined pair interactions"]
    for item in pairs[:10]:
        lines.append(f"- {item['pair'][0]} x {item['pair'][1]}: rms={item['rms']:.4f}, max={item['max_abs']:.4f}")
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("self")
    p.add_argument("--engine", required=True)
    p.add_argument("--bank", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--shards", type=int, default=25)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--movetime", type=int, default=100)
    p.add_argument("--seed", type=int, default=2026100700)

    p = sub.add_parser("external")
    p.add_argument("--engine", required=True)
    p.add_argument("--opponent", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--shards", type=int, default=25)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--movetime", type=int, default=100)
    p.add_argument("--opponent-level", type=int, default=42)
    p.add_argument("--opponent-nodes", type=int, default=1177)
    p.add_argument("--seed", type=int, default=2026100800)

    p = sub.add_parser("analyze")
    p.add_argument("--self-root", required=True)
    p.add_argument("--external-root", required=True)
    p.add_argument("--opponent-level", type=int, default=42)
    p.add_argument("--opponent-nodes", type=int, default=1177)
    p.add_argument("--output", required=True)
    p.add_argument("--summary", required=True)

    args = parser.parse_args()
    if args.cmd == "self":
        cmd_self(args)
    elif args.cmd == "external":
        cmd_external(args)
    else:
        cmd_analyze(args)


if __name__ == "__main__":
    main()
