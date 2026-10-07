#!/usr/bin/env python3
"""Direct 200-game validation of the four leading Evaluation-v2 candidates.

Stage 1: six round-robin pairings, 200 games per pairing.
Stage 2: each candidate vs current v1, 200 games each.

Each 200-game matchup is split into four 50-game lanes so one public
4-vCPU runner stays busy while preserving exact color balance.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
from pathlib import Path

COMMON={
    "OpeningBook":False,
    "ExperienceCache":False,
    "AdaptiveLongThink":False,
    "MateAssist":True,
}
FIXED={
    "EvalV2":True,
    "EvalPressure":474,
    "EvalActivity":150,
    "EvalDanger":200,
    "EvalPotential":25,
    "EvalCoordination":50,
    "EvalHandPotential":60,
    "EvalPositionalCap":5000,
}
CANDIDATES={
    "A":{
        **FIXED,
        "EvalMaterialWeight":100,
        "EvalSafety":500,
        "EvalThreat":0,
        "EvalInfluence":0,
    },
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
    "D":{
        **FIXED,
        "EvalMaterialWeight":3162,
        "EvalSafety":500,
        "EvalThreat":0,
        "EvalInfluence":0,
    },
}
CURRENT={
    # Pin the historical v1 baseline explicitly so future production-default
    # changes cannot silently redefine this comparison.
    "EvalV2":False,
    "EvalSafety":50,
    "EvalPressure":150,
    "EvalActivity":150,
    "EvalDanger":200,
    "EvalMaterialWeight":100,
    "EvalInfluence":0,
    "EvalPotential":0,
    "EvalCoordination":0,
    "EvalHandPotential":0,
    "EvalThreat":0,
    "EvalPositionalCap":300,
}
for d in list(CANDIDATES.values())+[CURRENT]:
    d.update(COMMON)

LABELS={
    "A":"Material1x Safety10x ThreatOFF InfluenceOFF",
    "B":"Material1x Safety10x ThreatOFF Influence0.316x",
    "C":"Material10x Safety31.6x Threat0.03x Influence0.03x",
    "D":"Material31.6x Safety10x ThreatOFF InfluenceOFF",
    "current":"current v1 evaluator",
}

def opts(name:str)->dict:
    if name=="current":
        return CURRENT
    if name not in CANDIDATES:
        raise SystemExit(f"unknown engine profile: {name}")
    return CANDIDATES[name]

def run_lane(engine:str,a:str,b:str,lane:int,outdir:Path,movetime:int,max_plies:int,seed:int)->dict:
    out=outdir/f"lane-{lane}.json"
    lane_seed=seed+lane*10000
    cmd=[
        sys.executable,"benchmarks/arena.py",
        "--engine-a",engine,"--engine-b",engine,
        "--options-a",json.dumps(opts(a),separators=(",",":")),
        "--options-b",json.dumps(opts(b),separators=(",",":")),
        "--games","50","--max-plies",str(max_plies),
        "--seed",str(lane_seed),
        "--go-command",f"go movetime {movetime}",
        "--output",str(out),
    ]
    subprocess.run(cmd,check=True)
    return json.loads(out.read_text())

def aggregate(a:str,b:str,rows:list[dict],movetime:int,output:Path)->dict:
    games=sum(r["games"] for r in rows)
    wa=sum(r["wins_a"] for r in rows)
    wb=sum(r["wins_b"] for r in rows)
    dr=sum(r["draws"] for r in rows)
    illegal=sum(r.get("illegal_games",0) for r in rows)
    score=(wa+.5*dr)/games
    # Normal approximation is only descriptive; raw W/D/L stays primary.
    se=math.sqrt(max(score*(1-score),1e-12)/games)
    lo=max(0.0,score-1.96*se); hi=min(1.0,score+1.96*se)
    elo=None
    if 0 < score < 1:
        elo=400*math.log10(score/(1-score))
    payload={
        "kind":"eval_v2_final_four_match",
        "profile_a":a,"profile_b":b,
        "label_a":LABELS[a],"label_b":LABELS[b],
        "options_a":opts(a),"options_b":opts(b),
        "games":games,"wins_a":wa,"draws":dr,"wins_b":wb,
        "score_a":score,"score_a_ci95_normal":[lo,hi],
        "elo_a_estimate":elo,
        "illegal_games":illegal,
        "movetime_ms":movetime,
        "lanes":len(rows),
        "lane_results":[{
            "wins_a":r["wins_a"],"draws":r["draws"],"wins_b":r["wins_b"],
            "score_a":r["score_a"],"average_plies":r["average_plies"],
            "elapsed_seconds":r["elapsed_seconds"],
        } for r in rows],
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    if illegal:
        raise SystemExit("illegal game detected")
    return payload

def cmd_match(args):
    outdir=Path(args.output_dir)
    outdir.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs=[pool.submit(run_lane,args.engine,args.a,args.b,lane,outdir,args.movetime,args.max_plies,args.seed)
              for lane in range(4)]
        rows=[f.result() for f in futs]
    aggregate(args.a,args.b,rows,args.movetime,outdir/"summary.json")

def cmd_analyze(args):
    root=Path(args.root)
    summaries=[]
    for p in root.rglob("summary.json"):
        try:
            d=json.loads(p.read_text())
        except Exception:
            continue
        if d.get("kind")=="eval_v2_final_four_match":
            summaries.append(d)
    key={(d["profile_a"],d["profile_b"]):d for d in summaries}
    expected_rr=[("A","B"),("A","C"),("A","D"),("B","C"),("B","D"),("C","D")]
    expected_cur=[(x,"current") for x in "ABCD"]
    missing=[k for k in expected_rr+expected_cur if k not in key]
    if missing:
        raise SystemExit(f"missing summaries: {missing}")

    # Candidate mini-league: score points across 600 games each.
    league={}
    for c in "ABCD":
        w=d=l=0
        for a,b in expected_rr:
            row=key[(a,b)]
            if c==a:
                w+=row["wins_a"]; d+=row["draws"]; l+=row["wins_b"]
            elif c==b:
                w+=row["wins_b"]; d+=row["draws"]; l+=row["wins_a"]
        games=w+d+l
        league[c]={"games":games,"wins":w,"draws":d,"losses":l,
                   "score":(w+.5*d)/games}

    current={c:key[(c,"current")] for c in "ABCD"}
    ranking=sorted("ABCD",key=lambda c:(current[c]["score_a"],league[c]["score"]),reverse=True)
    payload={
        "stage":"eval_v2_final_four_200",
        "round_robin_games_per_pair":200,
        "vs_current_games_per_candidate":200,
        "total_games":2000,
        "movetime_ms":next(iter(summaries))["movetime_ms"],
        "profiles":{k:{"label":LABELS[k],"options":opts(k)} for k in "ABCD"},
        "round_robin":{f"{a}-{b}":key[(a,b)] for a,b in expected_rr},
        "league":league,
        "vs_current":current,
        "ranking_by_vs_current_then_league":ranking,
        "selection_policy":"Report evidence; do not auto-promote production evaluator.",
    }
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    lines=[
        "# Evaluation-v2 final four: 200-game validation","",
        "- six round-robin pairings x 200 games = 1,200 games",
        "- four candidates vs current x 200 games = 800 games",
        "- total = 2,000 games",
        f"- fixed go movetime {payload['movetime_ms']} ms; Book/Experience/ALT OFF","",
        "## Round-robin league",
    ]
    for c in sorted("ABCD",key=lambda c:league[c]["score"],reverse=True):
        r=league[c]
        lines.append(f"- {c}: {r['wins']}-{r['draws']}-{r['losses']} / {r['games']}; score={r['score']:.1%}")
    lines+=["","## Versus current v1"]
    for c in sorted("ABCD",key=lambda c:current[c]["score_a"],reverse=True):
        r=current[c]
        ci=r["score_a_ci95_normal"]
        lines.append(f"- {c}: {r['wins_a']}-{r['draws']}-{r['wins_b']}; score={r['score_a']:.1%}; CI≈{ci[0]:.1%}–{ci[1]:.1%}; Elo≈{r['elo_a_estimate']:.0f}")
    lines+=["","## Profiles"]
    for c in "ABCD":
        lines.append(f"- {c}: {LABELS[c]}")
    Path(args.summary).write_text("\n".join(lines)+"\n")
    print("\n".join(lines))

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    m=sub.add_parser("match")
    m.add_argument("--engine",required=True)
    m.add_argument("--a",required=True,choices=list("ABCD"))
    m.add_argument("--b",required=True,choices=list("ABCD")+["current"])
    m.add_argument("--output-dir",required=True)
    m.add_argument("--movetime",type=int,default=200)
    m.add_argument("--max-plies",type=int,default=300)
    m.add_argument("--seed",type=int,default=2026100700)
    a=sub.add_parser("analyze")
    a.add_argument("--root",required=True)
    a.add_argument("--output",required=True)
    a.add_argument("--summary",required=True)
    args=p.parse_args()
    if args.cmd=="match": cmd_match(args)
    else: cmd_analyze(args)

if __name__=="__main__":
    main()
