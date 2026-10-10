#!/usr/bin/env python3
"""Reproducible eight-profile KUMOJI evaluation round robin; no automatic promotion."""
import argparse
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

KEYS = ("EvalMaterialWeight", "EvalSafety", "EvalPressure", "EvalActivity",
        "EvalDanger", "EvalInfluence", "EvalPotential", "EvalCoordination",
        "EvalHandPotential", "EvalThreat")
# 2026-10-10: M is adopted v2.0.6; S/A/T are earlier experimental profiles.
# X/Y/Z/W are new hypotheses. Engine code and all non-evaluation settings are fixed.
PROFILES = {"M":{"name":"現行・機動協調","weights":[100,480,380,410,150,140,210,340,60,20]},"S":{"name":"守備重視","weights":[100,900,320,120,320,50,35,250,30,8]},"A":{"name":"攻撃圧力重視","weights":[100,260,980,300,120,75,100,80,100,45]},"T":{"name":"駒得・戦術重視","weights":[175,420,540,150,420,50,60,110,90,110]},"X":{"name":"機動力大幅強化","weights":[100,360,290,700,140,230,400,520,60,20]},"Y":{"name":"攻守均衡強化","weights":[100,720,650,380,270,140,230,360,70,35]},"Z":{"name":"両取り・脅威強化","weights":[120,470,540,310,260,150,190,290,150,200]},"W":{"name":"支配領域・連係強化","weights":[100,520,410,360,190,370,310,600,60,25]}}
PAIRS = list(itertools.combinations(PROFILES, 2))
BASE_SEED = 2026110000

def options(pid):
    p = {"AdaptiveLongThink": True, "PositionKnowledge": True,
         "PositionKnowledgeFile": "build/position-knowledge-v1.tsv",
         "EvalV2": True, "EvalPositionalCap": 5000}
    p.update(dict(zip(KEYS, PROFILES[pid]["weights"])))
    return p

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["validate", "run", "aggregate"])
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--engine", default="build/engine")
    ap.add_argument("--input-dir", default="results")
    ap.add_argument("--output-dir", default="report")
    args = ap.parse_args()
    if not 1 <= args.shards <= 20:
        raise SystemExit("shards must be 1..20")
    if len(PROFILES) != 8 or len(PAIRS) != 28 or any(len(p["weights"]) != len(KEYS) for p in PROFILES.values()):
        raise SystemExit("wrong profile count or weight dimensions")
    if any(not 0 <= x <= 10000 for p in PROFILES.values() for x in p["weights"]):
        raise SystemExit("USI parameter out of range")
    if BASE_SEED + len(PAIRS) * 1000 + args.shards * 2 >= 2147483647:
        raise SystemExit("seed exceeds signed USI range")
    if args.command == "validate":
        print(f"profiles=8 pairs=28 games={len(PAIRS)*args.shards*2} shards={args.shards}")
        return
    if args.command == "run":
        if not 0 <= args.shard < args.shards:
            raise SystemExit("invalid shard")
        output = Path(args.input_dir)
        output.mkdir(parents=True, exist_ok=True)
        for index, (a, b) in enumerate(PAIRS):
            path = output / f"pair-{index:02d}-{a}-{b}-shard-{args.shard:02d}.json"
            command = [
                sys.executable, "benchmarks/arena.py",
                "--engine-a", args.engine, "--engine-b", args.engine,
                "--options-a", json.dumps(options(a), separators=(",", ":")),
                "--options-b", json.dumps(options(b), separators=(",", ":")),
                "--go-command", "go movetime 200",
                "--games", "2", "--max-plies", "300",
                "--game-offset", str(args.shard * 2),
                "--seed", str(BASE_SEED + index * 1000 + args.shard * 2),
                "--output", str(path),
            ]
            subprocess.run(command, check=True)
            result = json.loads(path.read_text(encoding="utf-8"))
            if result["games"] != 2 or result.get("illegal_games", 0):
                raise SystemExit(f"invalid match {a}-{b}")
            if result.get("position_knowledge", {}).get("A", {}).get("positions", 0) < 1:
                raise SystemExit("position knowledge not loaded")
        print(f"completed shard {args.shard}: {len(PAIRS)*2} games")
        return
    inp, out = Path(args.input_dir), Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    wins = {p: 0 for p in PROFILES}
    draws = {p: 0 for p in PROFILES}
    losses = {p: 0 for p in PROFILES}
    pair_results = []
    all_knowledge = None
    hashes = set()
    total_illegal = 0
    for index, (a, b) in enumerate(PAIRS):
        wa = wb = d = 0
        for shard in range(args.shards):
            path = inp / f"pair-{index:02d}-{a}-{b}-shard-{shard:02d}.json"
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["games"] != 2 or len(row["details"]) != 2:
                raise SystemExit(f"incomplete results: {path}")
            if row.get("options_a") != options(a) or row.get("options_b") != options(b):
                raise SystemExit(f"parameter mismatch: {path}")
            if row["game_offset"] != shard*2 or row["seed"] != BASE_SEED + index*1000 + shard*2:
                raise SystemExit(f"seed/side mismatch: {path}")
            if row.get("illegal_games"):
                total_illegal += row["illegal_games"]
            meta = row.get("position_knowledge")
            if meta is None or meta.get("A", {}).get("positions", 0) < 1 or meta.get("A") != meta.get("B"):
                raise SystemExit(f"missing or asymmetric knowledge: {path}")
            if all_knowledge is None:
                all_knowledge = meta
            elif meta != all_knowledge:
                raise SystemExit(f"knowledge snapshot mismatch: {path}")
            if row.get("sha256_a") != row.get("sha256_b"):
                raise SystemExit(f"different engine binaries: {path}")
            hashes.add(row["sha256_a"])
            wa += row["wins_a"]
            wb += row["wins_b"]
            d += row["draws"]
        n = wa+wb+d
        if n != 2*args.shards:
            raise SystemExit(f"missing games: {a}-{b}")
        wins[a] += wa
        losses[a] += wb
        draws[a] += d
        wins[b] += wb
        losses[b] += wa
        draws[b] += d
        score = (wa + d/2)/n
        se = math.sqrt(score*(1-score)/n)
        pair_results.append({"A": a, "B": b, "wins_A": wa, "draws": d, "wins_B": wb,
                             "games": n, "score_A": score,
                             "approx_95pct_A": [max(0,score-1.96*se),min(1,score+1.96*se)]})
    if total_illegal or len(hashes) != 1:
        raise SystemExit(f"illegal={total_illegal}; binary count={len(hashes)}")
    table = []
    for p in PROFILES:
        n = wins[p] + losses[p] + draws[p]
        table.append({"profile": p, "name": PROFILES[p]["name"],
                      "wins": wins[p], "draws": draws[p], "losses": losses[p],
                      "games": n, "points": wins[p] + draws[p]/2,
                      "score": (wins[p]+draws[p]/2)/n, "weights": dict(zip(KEYS, PROFILES[p]["weights"]))})
    table.sort(key=lambda p:(p["points"],p["wins"]),reverse=True)
    report = {"schema":1,"engine_sha256":next(iter(hashes)), "profiles":PROFILES,
              "shards":args.shards,"games_per_pair":2*args.shards,
              "games_total":len(PAIRS)*2*args.shards,
              "go_command":"go movetime 200","adaptive_long_think":True,
              "knowledge":all_knowledge,"illegal_games":total_illegal,
              "standings":table,"pair_results":pair_results,
              "interpretation":"League screening only; short pairwise matches and shared starts are not proof of best strength; no automatic adoption."}
    (out/"league-summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# KUMOJI 評価パラメータ8型総当たりリーグ","",
           f"- 対局: {report['games_total']}局、各組{report['games_per_pair']}局、{args.shards}並列",
           "- 現行M型とS/A/T型、新規X/Y/Z/W型。全組で先後を均等化。",
           "- 同一バイナリ、局面知識あり、200ms＋条件付き最大1秒、最大300手。",
           "- 採用候補のスクリーニングであり、自動採用しない。","",
           "| 順位 | 型 | 得点 | 勝-分-敗 | 得点率 |",
           "|---:|---|---:|---|---:|"]
    for i,p in enumerate(table,1):
        lines.append(f"| {i} | {p['profile']}（{p['name']}） | {p['points']:.1f} | {p['wins']}-{p['draws']}-{p['losses']} | {p['score']:.1%} |")
    lines.extend(["","## 全組み合わせ","",
                  "| A | B | A勝-分-B勝 | A得点率 |",
                  "|---|---|---|---:|"])
    for p in pair_results:
        lines.append(f"| {p['A']} | {p['B']} | {p['wins_A']}-{p['draws']}-{p['wins_B']} | {p['score_A']:.1%} |")
    lines.extend(["","## 評価設定", "", "| 型 | "+ " | ".join(KEYS) + " |",
                  "|---|" + "---:|" * len(KEYS)])
    for key,profile in PROFILES.items():
        lines.append("| "+key+" | "+ " | ".join(map(str,profile["weights"]))+" |")
    lines.extend(["","注: 95%区間はJSONに参考値を記録。局面や乱数への依存があるため、独立な全局の統計として過信しない。"])
    (out/"league-summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines[:17]))

if __name__=="__main__":
    main()
