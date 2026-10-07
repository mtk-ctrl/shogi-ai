#!/usr/bin/env python3
"""Robustness validation for Evaluation-v2 candidates B and C.

- B vs C: 1,000 games under the adopted official time setting:
  go movetime 200 + AdaptiveLongThink ON (up to 1s, max 10/game).
- B and C vs pinned YaneuraOu Material benchmark levels 20/30/40:
  200 games per candidate/level.

OpeningBook and ExperienceCache remain OFF so this measures evaluator/search
strength rather than book/experience effects.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
from pathlib import Path

FIXED={
    "EvalV2":True,
    "EvalPressure":474,
    "EvalActivity":150,
    "EvalDanger":200,
    "EvalPotential":25,
    "EvalCoordination":50,
    "EvalHandPotential":60,
    "EvalPositionalCap":5000,
    "OpeningBook":False,
    "ExperienceCache":False,
    "AdaptiveLongThink":True,
    "MateAssist":True,
}
PROFILES={
    "B":{
        **FIXED,
        "EvalMaterialWeight":100,
        "EvalSafety":500,
        "EvalThreat":0,
        "EvalInfluence":19,
    },
    "C":{
        **FIXED,
        "EvalMaterialWeight":1000,
        "EvalSafety":1581,
        "EvalThreat":1,
        "EvalInfluence":2,
    },
}
LABELS={
    "B":"Material1x Safety10x ThreatOFF Influence0.316x",
    "C":"Material10x Safety31.6x Threat0.03x Influence0.03x",
}
LEVEL_NODES={20:91,30:292,40:933}
OPPONENT_OPTIONS={"Threads":1,"USI_Hash":16,"USI_OwnBook":False}


def run(cmd:list[str])->None:
    print("+"," ".join(cmd),flush=True)
    subprocess.run(cmd,check=True)


def arena_lane(engine:str,lane:int,out:Path,seed:int)->dict:
    p=out/f"lane-{lane}.json"
    run([
        sys.executable,"benchmarks/arena.py",
        "--engine-a",engine,"--engine-b",engine,
        "--options-a",json.dumps(PROFILES["B"],separators=(",",":")),
        "--options-b",json.dumps(PROFILES["C"],separators=(",",":")),
        "--games","50","--max-plies","300",
        "--seed",str(seed+lane*10000),
        "--go-command","go movetime 200",
        "--output",str(p),
    ])
    return json.loads(p.read_text())


def external_lane(engine:str,opponent:str,profile:str,level:int,lane:int,out:Path,seed:int)->dict:
    p=out/f"lane-{lane}.json"
    run([
        sys.executable,"benchmarks/external_match.py",
        "--self-engine",engine,
        "--opponent-engine",opponent,
        "--self-options",json.dumps(PROFILES[profile],separators=(",",":")),
        "--opponent-options",json.dumps(OPPONENT_OPTIONS,separators=(",",":")),
        "--self-go","go movetime 200",
        "--opponent-go",f"go nodes {LEVEL_NODES[level]}",
        "--games","50","--max-plies","300",
        "--seed",str(seed+lane*10000),
        "--output",str(p),
    ])
    return json.loads(p.read_text())


def ci(score:float,n:int)->list[float]:
    se=math.sqrt(max(score*(1-score),1e-12)/n)
    return [max(0.0,score-1.96*se),min(1.0,score+1.96*se)]


def elo(score:float):
    if not 0 < score < 1:
        return None
    return 400*math.log10(score/(1-score))


def aggregate_bc(rows:list[dict],batch:int,out:Path)->dict:
    n=sum(r["games"] for r in rows)
    wb=sum(r["wins_a"] for r in rows)
    wc=sum(r["wins_b"] for r in rows)
    d=sum(r["draws"] for r in rows)
    illegal=sum(r.get("illegal_games",0) for r in rows)
    score=(wb+0.5*d)/n
    payload={
        "kind":"eval_v2_bc_official_time_batch",
        "batch":batch,
        "games":n,"wins_b":wb,"draws":d,"wins_c":wc,
        "score_b":score,"score_b_ci95_normal":ci(score,n),"elo_b_estimate":elo(score),
        "illegal_games":illegal,
        "time_setting":{"go":"go movetime 200","AdaptiveLongThink":True,
                        "max_ms":1000,"max_uses_per_game":10},
        "profile_b":PROFILES["B"],"profile_c":PROFILES["C"],
    }
    (out/"summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(payload,ensure_ascii=False,indent=2),flush=True)
    if illegal: raise SystemExit("illegal game detected")
    return payload


def aggregate_external(rows:list[dict],profile:str,level:int,out:Path)->dict:
    n=sum(r["games"] for r in rows)
    w=sum(r["wins_self"] for r in rows)
    l=sum(r["losses_self"] for r in rows)
    d=sum(r["draws"] for r in rows)
    illegal=sum(r.get("illegal_games",0) for r in rows)
    score=(w+0.5*d)/n
    payload={
        "kind":"eval_v2_bc_yaneuraou_level",
        "profile":profile,"label":LABELS[profile],
        "level":level,"nodes_per_move":LEVEL_NODES[level],
        "games":n,"wins_self":w,"draws":d,"losses_self":l,
        "score_self":score,"score_self_ci95_normal":ci(score,n),
        "elo_vs_opponent_estimate":elo(score),
        "illegal_games":illegal,
        "self_time_setting":{"go":"go movetime 200","AdaptiveLongThink":True,
                             "max_ms":1000,"max_uses_per_game":10},
        "profile_options":PROFILES[profile],
    }
    (out/"summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(payload,ensure_ascii=False,indent=2),flush=True)
    if illegal: raise SystemExit("illegal game detected")
    return payload


def cmd_bc(args):
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(lambda lane:arena_lane(args.engine,lane,out,args.seed),range(4)))
    aggregate_bc(rows,args.batch,out)


def cmd_external(args):
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(lambda lane:external_lane(args.engine,args.opponent,args.profile,args.level,lane,out,args.seed),range(4)))
    aggregate_external(rows,args.profile,args.level,out)


def cmd_analyze(args):
    root=Path(args.root)
    docs=[]
    for p in root.rglob("summary.json"):
        try: d=json.loads(p.read_text())
        except Exception: continue
        if d.get("kind") in {"eval_v2_bc_official_time_batch","eval_v2_bc_yaneuraou_level"}:
            docs.append(d)
    bc=sorted((d for d in docs if d["kind"]=="eval_v2_bc_official_time_batch"),key=lambda d:d["batch"])
    ex={(d["profile"],d["level"]):d for d in docs if d["kind"]=="eval_v2_bc_yaneuraou_level"}
    if len(bc)!=5:
        raise SystemExit(f"expected 5 B-C batches, got {len(bc)}")
    missing=[(p,l) for p in "BC" for l in (20,30,40) if (p,l) not in ex]
    if missing: raise SystemExit(f"missing external results: {missing}")

    n=sum(d["games"] for d in bc)
    wb=sum(d["wins_b"] for d in bc); dr=sum(d["draws"] for d in bc); wc=sum(d["wins_c"] for d in bc)
    score=(wb+0.5*dr)/n
    bc_total={
        "games":n,"wins_b":wb,"draws":dr,"wins_c":wc,
        "score_b":score,"score_b_ci95_normal":ci(score,n),"elo_b_estimate":elo(score),
    }
    robustness={}
    for p in "BC":
        scores=[ex[(p,l)]["score_self"] for l in (20,30,40)]
        robustness[p]={
            "mean_external_score":sum(scores)/len(scores),
            "minimum_external_score":min(scores),
            "scores_by_level":{str(l):ex[(p,l)]["score_self"] for l in (20,30,40)},
        }
    payload={
        "stage":"eval_v2_bc_robustness",
        "total_games":2200,
        "official_time":{"go":"go movetime 200","AdaptiveLongThink":True,
                         "max_ms":1000,"max_uses_per_game":10},
        "bc_1000":bc_total,
        "external":{f"{p}-L{l}":ex[(p,l)] for p in "BC" for l in (20,30,40)},
        "robustness":robustness,
        "note":"External opponents are pinned YaneuraOu Material benchmarks; results are measurement only, not training data.",
    }
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    lines=[
        "# Evaluation-v2 B/C robustness validation","",
        "- B vs C: 1,000 games, official 200ms + AdaptiveLongThink",
        "- B/C vs YaneuraOu Material L20/L30/L40: 200 games each",
        "- total: 2,200 games","",
        "## B vs C",
        f"- B {wb}-{dr}-{wc} C; B score={score:.1%}; CI≈{bc_total['score_b_ci95_normal'][0]:.1%}–{bc_total['score_b_ci95_normal'][1]:.1%}",
        "","## YaneuraOu benchmark",
    ]
    for l in (20,30,40):
        for p in "BC":
            r=ex[(p,l)]
            lines.append(f"- {p} vs L{l} ({r['nodes_per_move']} nodes): {r['wins_self']}-{r['draws']}-{r['losses_self']}; score={r['score_self']:.1%}")
    lines+=["","## Robustness summary"]
    for p in "BC":
        r=robustness[p]
        lines.append(f"- {p}: mean external={r['mean_external_score']:.1%}; minimum across levels={r['minimum_external_score']:.1%}")
    Path(args.summary).write_text("\n".join(lines)+"\n")
    print("\n".join(lines),flush=True)


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    b=sub.add_parser("bc")
    b.add_argument("--engine",required=True);b.add_argument("--batch",type=int,required=True)
    b.add_argument("--output-dir",required=True);b.add_argument("--seed",type=int,required=True)
    e=sub.add_parser("external")
    e.add_argument("--engine",required=True);e.add_argument("--opponent",required=True)
    e.add_argument("--profile",choices=["B","C"],required=True)
    e.add_argument("--level",choices=[20,30,40],type=int,required=True)
    e.add_argument("--output-dir",required=True);e.add_argument("--seed",type=int,required=True)
    a=sub.add_parser("analyze")
    a.add_argument("--root",required=True);a.add_argument("--output",required=True);a.add_argument("--summary",required=True)
    args=p.parse_args()
    if args.cmd=="bc":cmd_bc(args)
    elif args.cmd=="external":cmd_external(args)
    else:cmd_analyze(args)

if __name__=="__main__":
    main()
