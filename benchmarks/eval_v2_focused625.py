#!/usr/bin/env python3
"""Focused 625-grid for Evaluation-v2 after the 100x broad cross-benchmark.

Four axes remain open and are exhaustively crossed:
- Material: 1, sqrt(10), 10, 10*sqrt(10), 100 x
- Safety:   1, sqrt(10), 10, 10*sqrt(10), 100 x
- Threat:   0, .03, .1, sqrt(.1), 1 x
- Influence:0, .03, .1, sqrt(.1), 1 x

Other axes are fixed at the broad-search interior values:
Pressure=3.162x, Activity=1x, Danger=1x, Potential=1x,
Coordination=1x, HandPotential=1x.

All 5^4=625 combinations are tested; no OA approximation is needed.
The same three evidence streams are retained:
startpos vs v1, phase-balanced positions vs v1, and pinned YaneuraOu Material.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

from benchmarks import eval_v2_crossbench as cross

AXES=("EvalMaterialWeight","EvalSafety","EvalThreat","EvalInfluence")
LEVELS={
    "EvalMaterialWeight":(1.0, math.sqrt(10.0), 10.0, 10.0*math.sqrt(10.0), 100.0),
    "EvalSafety":(1.0, math.sqrt(10.0), 10.0, 10.0*math.sqrt(10.0), 100.0),
    "EvalThreat":(0.0, 0.03, 0.1, math.sqrt(0.1), 1.0),
    "EvalInfluence":(0.0, 0.03, 0.1, math.sqrt(0.1), 1.0),
}
LABELS={
    k: tuple("0" if x==0 else f"{x:.4g}x" for x in vals)
    for k,vals in LEVELS.items()
}
BASE=cross.BASE
FIXED_MULT={
    "EvalPressure":math.sqrt(10.0),
    "EvalActivity":1.0,
    "EvalDanger":1.0,
    "EvalPotential":1.0,
    "EvalCoordination":1.0,
    "EvalHandPotential":1.0,
}
STREAM_WEIGHTS=cross.STREAM_WEIGHTS
PHASES=cross.PHASES


def weight(base: int, multiplier: float) -> int:
    if multiplier == 0:
        return 0
    return max(1, int(math.floor(base * multiplier + 0.5)))


def design_rows() -> list[dict]:
    rows=[]
    for idx,codes in enumerate(itertools.product(range(5), repeat=4)):
        opts={
            "EvalV2":True,
            "AdaptiveLongThink":False,
            "EvalPositionalCap":5000,
        }
        relative={}
        for name,mult in FIXED_MULT.items():
            opts[name]=weight(BASE[name],mult)
            relative[name]=f"{mult:.4g}x-fixed"
        for name,code in zip(AXES,codes):
            mult=LEVELS[name][code]
            opts[name]=weight(BASE[name],mult)
            relative[name]=LABELS[name][code]
        rows.append({
            "index":idx,
            "codes":list(codes),
            "relative":relative,
            "options":opts,
        })
    assert len(rows)==625
    assert max(r["options"]["EvalMaterialWeight"] for r in rows)==10000
    assert max(r["options"]["EvalSafety"] for r in rows)==5000
    return rows


def rows_for_shard(shards: int, shard: int) -> list[dict]:
    rows=design_rows()
    return [r for pos,r in enumerate(rows) if pos % shards == shard]


def cmd_self(args) -> None:
    rows=rows_for_shard(args.shards,args.shard)
    bank=cross.load_bank(Path(args.bank))
    root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
    cross.atomic(root/"stage.json",{
        "kind":"focused625-self","shard":args.shard,"shards":args.shards,
        "configs":len(rows),"movetime_ms":args.movetime,
        "axes":AXES,"levels":{k:LEVELS[k] for k in AXES},"fixed":FIXED_MULT,
    })
    import concurrent.futures
    jobs=[(r,args.engine,bank,root,args.movetime,args.seed) for r in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for done,idx in enumerate(pool.map(lambda x:cross.self_one(*x),jobs),1):
            print(f"focused self shard {args.shard}: {done}/{len(rows)} cfg={idx}",flush=True)


def cmd_external(args) -> None:
    rows=rows_for_shard(args.shards,args.shard)
    root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
    cross.atomic(root/"stage.json",{
        "kind":"focused625-external","shard":args.shard,"shards":args.shards,
        "configs":len(rows),"movetime_ms":args.movetime,
        "opponent_level":args.opponent_level,"opponent_nodes":args.opponent_nodes,
        "axes":AXES,"levels":{k:LEVELS[k] for k in AXES},"fixed":FIXED_MULT,
    })
    import concurrent.futures
    jobs=[(r,args.engine,args.opponent,root,args.movetime,args.opponent_nodes,args.seed) for r in rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for done,idx in enumerate(pool.map(lambda x:cross.external_one(*x),jobs),1):
            print(f"focused external shard {args.shard}: {done}/{len(rows)} cfg={idx}",flush=True)


def collect(path: str, filename: str) -> dict[int,dict]:
    return cross.collect(path,filename)


def metric_records(selfs,externals):
    records={}
    for idx in sorted(selfs):
        s=selfs[idx];e=externals[idx]
        if s["result"]["illegal_games"] or e["result"]["illegal_games"]:
            raise SystemExit(f"illegal game in config {idx}")
        start=float(s["result"]["start"]["score"])
        positions=float(s["result"]["positions"]["score"])
        external=float(e["result"]["score_self"])
        combined=(STREAM_WEIGHTS["start"]*start+
                  STREAM_WEIGHTS["positions"]*positions+
                  STREAM_WEIGHTS["external"]*external)
        records[idx]={
            "row":s["row"],"start":start,"positions":positions,
            "external":external,"combined":combined,
            **{f"phase_{p}":float(s["result"]["positions"]["phase_scores"][p]) for p in PHASES},
        }
    return records


def main_effects(records,metric):
    mu=sum(r[metric] for r in records.values())/len(records)
    effects={}
    for ai,axis in enumerate(AXES):
        vals=[]
        for level in range(5):
            group=[r[metric] for r in records.values() if r["row"]["codes"][ai]==level]
            vals.append(sum(group)/len(group))
        effects[axis]=vals
    return mu,effects


def pair_tables(records,metric,mu,main):
    ranked=[];tables={}
    for i,j in itertools.combinations(range(4),2):
        table=[]
        residual=[]
        for a in range(5):
            row=[]
            for b in range(5):
                group=[r[metric] for r in records.values()
                       if r["row"]["codes"][i]==a and r["row"]["codes"][j]==b]
                score=sum(group)/len(group)
                res=score-mu-(main[AXES[i]][a]-mu)-(main[AXES[j]][b]-mu)
                row.append(score);residual.append(res)
            table.append(row)
        rms=math.sqrt(sum(x*x for x in residual)/len(residual))
        key=f"{AXES[i]} x {AXES[j]}"
        tables[key]=table
        ranked.append({"pair":[AXES[i],AXES[j]],"rms":rms,"max_abs":max(abs(x) for x in residual)})
    ranked.sort(key=lambda x:(x["rms"],x["max_abs"]),reverse=True)
    return tables,ranked


def cmd_analyze(args) -> None:
    selfs=collect(args.self_root,"self-summary.json")
    externals=collect(args.external_root,"external.json")
    if len(selfs)!=625 or len(externals)!=625:
        raise SystemExit(f"incomplete: self={len(selfs)}/625 external={len(externals)}/625")
    records=metric_records(selfs,externals)
    metrics=("start","positions","external","combined","phase_early","phase_middle","phase_late")
    overall={};mains={}
    for metric in metrics:
        mu,e=main_effects(records,metric);overall[metric]=mu;mains[metric]=e
    tables,pairs=pair_tables(records,"combined",overall["combined"],mains["combined"])

    ranked_configs=sorted(records.values(),key=lambda r:r["combined"],reverse=True)
    boundary={}
    for axis in AXES:
        boundary[axis]={}
        for metric in ("start","positions","external","combined"):
            vals=mains[metric][axis];best=max(range(5),key=lambda i:vals[i])
            boundary[axis][metric]={
                "best_level":LABELS[axis][best],
                "best_score":vals[best],
                "at_low_boundary":best==0,
                "at_high_boundary":best==4,
            }

    payload={
        "stage":"eval_v2_focused625",
        "design":{
            "configs":625,"games_per_config":10,"total_games":6250,
            "axes":AXES,
            "levels":{k:[{"multiplier":LEVELS[k][i],"label":LABELS[k][i],
                          "weight":weight(BASE[k],LEVELS[k][i])} for i in range(5)] for k in AXES},
            "fixed":{k:{"multiplier":v,"weight":weight(BASE[k],v)} for k,v in FIXED_MULT.items()},
            "stream_weights":STREAM_WEIGHTS,
            "selection":"full factorial 5^4; no automatic elimination",
        },
        "overall":overall,
        "main_effects":{
            metric:{axis:{LABELS[axis][i]:vals[i] for i in range(5)}
                    for axis,vals in effects.items()}
            for metric,effects in mains.items()
        },
        "boundary_flags":boundary,
        "pair_score_tables_combined":tables,
        "pair_interactions_combined":pairs,
        "top_configs":[{
            "index":r["row"]["index"],"relative":r["row"]["relative"],
            "weights":{k:r["row"]["options"][k] for k in AXES},
            "start":r["start"],"positions":r["positions"],"external":r["external"],
            "combined":r["combined"],
        } for r in ranked_configs[:50]],
    }
    cross.atomic(Path(args.output),payload)

    lines=[
        "# Evaluation-v2 focused 625 result","",
        "- full factorial: 5^4 = 625 configurations",
        "- 10 games/config = 6,250 games",
        "- no automatic candidate elimination","",
        "## Overall",
        f"- start vs v1: {overall['start']:.3f}",
        f"- phase-bank vs v1: {overall['positions']:.3f}",
        f"- YaneuraOu: {overall['external']:.3f}",
        f"- combined: {overall['combined']:.3f}","",
        "## Main effects (combined)",
    ]
    for axis in AXES:
        vals=mains["combined"][axis]
        chunks=[f"{LABELS[axis][i]}={vals[i]:.3f}" for i in range(5)]
        best=max(range(5),key=lambda i:vals[i])
        flag=" BOUNDARY" if best in (0,4) else ""
        lines.append(f"- {axis}: "+", ".join(chunks)+f"; best={LABELS[axis][best]}{flag}")
    lines+=["","## Pair interactions"]
    for p in pairs:
        lines.append(f"- {p['pair'][0]} x {p['pair'][1]}: rms={p['rms']:.4f}, max={p['max_abs']:.4f}")
    lines+=["","## Top 10 raw configs"]
    for r in ranked_configs[:10]:
        lines.append(
            f"- cfg {r['row']['index']}: combined={r['combined']:.3f}, "
            f"start={r['start']:.3f}, positions={r['positions']:.3f}, external={r['external']:.3f}; "
            +", ".join(f"{a}={r['row']['relative'][a]}" for a in AXES)
        )
    Path(args.summary).parent.mkdir(parents=True,exist_ok=True)
    Path(args.summary).write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("self")
    s.add_argument("--engine",required=True);s.add_argument("--bank",required=True)
    s.add_argument("--output-dir",required=True);s.add_argument("--shards",type=int,default=20)
    s.add_argument("--shard",type=int,required=True);s.add_argument("--parallel",type=int,default=4)
    s.add_argument("--movetime",type=int,default=100);s.add_argument("--seed",type=int,default=2026100900)
    e=sub.add_parser("external")
    e.add_argument("--engine",required=True);e.add_argument("--opponent",required=True)
    e.add_argument("--output-dir",required=True);e.add_argument("--shards",type=int,default=20)
    e.add_argument("--shard",type=int,required=True);e.add_argument("--parallel",type=int,default=4)
    e.add_argument("--movetime",type=int,default=100);e.add_argument("--opponent-level",type=int,default=42)
    e.add_argument("--opponent-nodes",type=int,default=1177);e.add_argument("--seed",type=int,default=2026101000)
    a=sub.add_parser("analyze")
    a.add_argument("--self-root",required=True);a.add_argument("--external-root",required=True)
    a.add_argument("--output",required=True);a.add_argument("--summary",required=True)
    args=p.parse_args()
    if args.cmd=="self":cmd_self(args)
    elif args.cmd=="external":cmd_external(args)
    else:cmd_analyze(args)


if __name__=="__main__":
    main()
