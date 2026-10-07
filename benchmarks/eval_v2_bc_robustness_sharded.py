#!/usr/bin/env python3
"""20-shard scheduler for B/C robustness validation.

Total evidence is exactly 2,200 games:
- B vs C: 1,000 games = 100 blocks x 10 games
- B/C vs YaneuraOu Material L20/L30/L40:
  6 matchups x 200 games = 120 blocks x 10 games

The 220 ten-game blocks are round-robin distributed over 20 GitHub runner
shards, exactly 11 blocks = 110 games per shard.  Each runner executes four
blocks concurrently, matching the observed 4 logical CPUs.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.eval_v2_bc_robustness import (
    PROFILES, LABELS, LEVEL_NODES, OPPONENT_OPTIONS
)

def all_blocks():
    blocks=[]
    for i in range(100):
        blocks.append({"kind":"bc","index":i})
    for profile in "BC":
        for level in (20,30,40):
            for i in range(20):
                blocks.append({"kind":"external","profile":profile,"level":level,"index":i})
    assert len(blocks)==220
    return blocks

def shard_blocks(shard:int):
    rows=[(gid,b) for gid,b in enumerate(all_blocks()) if gid%20==shard]
    assert len(rows)==11
    return rows

def run(cmd):
    subprocess.run(cmd,check=True)

def execute(engine:str,opponent:str,gid:int,b:dict,outdir:Path):
    if b["kind"]=="bc":
        out=outdir/f"bc-{b['index']:03d}.json"
        seed=2026200000 + b["index"]*100
        run([
            sys.executable,"benchmarks/arena.py",
            "--engine-a",engine,"--engine-b",engine,
            "--options-a",json.dumps(PROFILES["B"],separators=(",",":")),
            "--options-b",json.dumps(PROFILES["C"],separators=(",",":")),
            "--games","10","--max-plies","300",
            "--seed",str(seed),
            "--go-command","go movetime 200",
            "--output",str(out),
        ])
        return str(out)

    p=b["profile"]; level=b["level"]; i=b["index"]
    out=outdir/f"ext-{p}-L{level}-{i:03d}.json"
    seed=2026210000 + (0 if p=="B" else 500000) + level*1000 + i*100
    run([
        sys.executable,"benchmarks/external_match.py",
        "--self-engine",engine,"--opponent-engine",opponent,
        "--self-options",json.dumps(PROFILES[p],separators=(",",":")),
        "--opponent-options",json.dumps(OPPONENT_OPTIONS,separators=(",",":")),
        "--self-go","go movetime 200",
        "--opponent-go",f"go nodes {LEVEL_NODES[level]}",
        "--games","10","--max-plies","300",
        "--seed",str(seed),
        "--output",str(out),
    ])
    return str(out)

def ci(score,n):
    se=math.sqrt(max(score*(1-score),1e-12)/n)
    return [max(0.0,score-1.96*se),min(1.0,score+1.96*se)]

def elo(score):
    if not 0<score<1:return None
    return 400*math.log10(score/(1-score))

def cmd_shard(args):
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    rows=shard_blocks(args.shard)
    manifest={
        "shard":args.shard,
        "games":110,
        "blocks":[{"global_id":gid,**b} for gid,b in rows],
    }
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs=[pool.submit(execute,args.engine,args.opponent,gid,b,out) for gid,b in rows]
        for fut in concurrent.futures.as_completed(futs):
            print("completed",fut.result(),flush=True)

def cmd_analyze(args):
    root=Path(args.root)
    bc=list(root.rglob("bc-*.json"))
    if len(bc)!=100:
        raise SystemExit(f"expected 100 B-C blocks, got {len(bc)}")
    bcd=[json.loads(p.read_text()) for p in bc]
    n=sum(x["games"] for x in bcd)
    wb=sum(x["wins_a"] for x in bcd); wc=sum(x["wins_b"] for x in bcd); dr=sum(x["draws"] for x in bcd)
    illegal=sum(x.get("illegal_games",0) for x in bcd)
    sb=(wb+.5*dr)/n
    bc_total={"games":n,"wins_b":wb,"draws":dr,"wins_c":wc,"score_b":sb,
              "score_b_ci95_normal":ci(sb,n),"elo_b_estimate":elo(sb),"illegal_games":illegal}

    external={}
    for p in "BC":
        for level in (20,30,40):
            files=list(root.rglob(f"ext-{p}-L{level}-*.json"))
            if len(files)!=20:
                raise SystemExit(f"expected 20 {p} L{level} blocks, got {len(files)}")
            ds=[json.loads(f.read_text()) for f in files]
            n=sum(x["games"] for x in ds)
            w=sum(x["wins_self"] for x in ds); l=sum(x["losses_self"] for x in ds); d=sum(x["draws"] for x in ds)
            ill=sum(x.get("illegal_games",0) for x in ds)
            s=(w+.5*d)/n
            external[f"{p}-L{level}"]={
                "profile":p,"level":level,"nodes_per_move":LEVEL_NODES[level],
                "games":n,"wins_self":w,"draws":d,"losses_self":l,
                "score_self":s,"score_self_ci95_normal":ci(s,n),
                "elo_vs_opponent_estimate":elo(s),"illegal_games":ill,
            }
            illegal+=ill
    if illegal:
        raise SystemExit(f"illegal games detected: {illegal}")

    robustness={}
    for p in "BC":
        scores=[external[f"{p}-L{l}"]["score_self"] for l in (20,30,40)]
        robustness[p]={"mean_external_score":sum(scores)/3,
                       "minimum_external_score":min(scores),
                       "scores_by_level":{str(l):external[f"{p}-L{l}"]["score_self"] for l in (20,30,40)}}
    payload={
        "stage":"eval_v2_bc_robustness_20shard",
        "scheduling":{"runner_shards":20,"games_per_shard":110,"local_parallel":4},
        "total_games":2200,
        "official_time":{"go":"go movetime 200","AdaptiveLongThink":True,"max_ms":1000,"max_uses_per_game":10},
        "bc_1000":bc_total,"external":external,"robustness":robustness,
        "profiles":{p:{"label":LABELS[p],"options":PROFILES[p]} for p in "BC"},
    }
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    lines=[
        "# Evaluation-v2 B/C robustness validation","",
        "- 20 runner shards x 110 games; 4 local lanes/runner",
        "- total 2,200 games","",
        "## B vs C",
        f"- B {wb}-{dr}-{wc} C; B score={sb:.1%}; CI≈{bc_total['score_b_ci95_normal'][0]:.1%}–{bc_total['score_b_ci95_normal'][1]:.1%}",
        "","## YaneuraOu Material",
    ]
    for level in (20,30,40):
        for p in "BC":
            r=external[f"{p}-L{level}"]
            lines.append(f"- {p} vs L{level} ({r['nodes_per_move']} nodes): {r['wins_self']}-{r['draws']}-{r['losses_self']}; score={r['score_self']:.1%}")
    lines+=["","## Robustness"]
    for p in "BC":
        r=robustness[p]
        lines.append(f"- {p}: mean={r['mean_external_score']:.1%}; minimum={r['minimum_external_score']:.1%}")
    Path(args.summary).write_text("\n".join(lines)+"\n")
    print("\n".join(lines))

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("shard")
    s.add_argument("--engine",required=True);s.add_argument("--opponent",required=True)
    s.add_argument("--shard",type=int,choices=range(20),required=True)
    s.add_argument("--output-dir",required=True)
    a=sub.add_parser("analyze")
    a.add_argument("--root",required=True);a.add_argument("--output",required=True);a.add_argument("--summary",required=True)
    args=p.parse_args()
    if args.cmd=="shard":cmd_shard(args)
    else:cmd_analyze(args)

if __name__=="__main__":
    main()
