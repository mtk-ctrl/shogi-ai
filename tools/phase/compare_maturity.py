#!/usr/bin/env python3
"""Offline, fixed-hypothesis maturity/urgency/complexity calibration.

Uses the same historical filtered games and independent phase probe as the
2026-10-08 terminal-stage study. Does not change live evaluation or search.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys
import argparse
import shogi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.phase.correlate_terminal_ply import (
    load_dataset, correlation, group_folds, train_linear, summarize_errors,
)

# All alternatives are fixed BEFORE looking at these game results.
MATURITY_WEIGHTS = {
    "balanced_35_35_30": (0.35, 0.35, 0.30),
    "development_50_20_30": (0.50, 0.20, 0.30),
    "combat_20_50_30": (0.20, 0.50, 0.30),
    "invasion_25_25_50": (0.25, 0.25, 0.50),
}
STAGE_NAMES = ("序盤", "中盤", "終盤")
def stage(value):
    return min(2, int(value >= 33.333) + int(value >= 66.667))

def clipped(value):
    return max(0., min(100., value))

def assigned_values(row):
    for name, w in MATURITY_WEIGHTS.items():
        row[name] = clipped(sum(x*row[k] for x,k in zip(
            w, ("development","battle","invasion"))))
    # King danger is an independent immediate threat, not the game's age.
    board = shogi.Board(row["_sfen"])
    legal_count = len(list(board.legal_moves))
    row["urgency"] = clipped(max(row["king_threat"], 80 if board.is_check() else 0))
    branch_width = clipped((legal_count-15) * 100 / 100)
    hand_options = clipped(row["hand_count"] * 9)
    tactical = clipped(row["battle"]*.6 + row["king_threat"]*.4)
    row["complexity"] = clipped(.5*branch_width + .3*hand_options + .2*tactical)
    row["legal_count"] = legal_count
    # No future position or actual game length is used above.

def cv_calibrated(rows, feature):
    fold_of = group_folds(rows)
    preds=[None]*len(rows)
    for k in range(5):
        train=[r for r in rows if fold_of[r["game"]]!=k]
        test=[(i,r) for i,r in enumerate(rows) if fold_of[r["game"]]==k]
        fit=train_linear(train,[feature])
        for i,row in test:
            preds[i]=fit(row)
    return summarize_errors(rows,preds)

def summarize(rows, name):
    labels=Counter()
    equal=0
    errors=[]
    conf=[[0]*3 for _ in range(3)]  # true stage, predicted stage
    bygame=defaultdict(list)
    for row in rows:
        pred=row[name]
        actual=row["target"]
        t,p=stage(actual),stage(pred)
        conf[t][p]+=1
        equal+=int(t==p)
        labels[(STAGE_NAMES[t],STAGE_NAMES[p])]+=1
        errors.append(abs(actual-pred))
        bygame[row["game"]].append(abs(actual-pred))
    at_ply={}
    for ply in (20,40,60,80,100):
        subs=[r for r in rows if r["ply"]==ply]
        if not subs: continue
        at_ply[str(ply)]={
            "games":len(subs),
            "corr_with_terminal_fraction":round(correlation(subs,name),4),
            "mae":round(statistics.mean(abs(r[name]-r["target"]) for r in subs),3),
            "stage_accuracy":round(sum(stage(r[name])==stage(r["target"]) for r in subs)/len(subs),4),
            "value_range":[round(min(r[name] for r in subs),1),round(max(r[name] for r in subs),1)]
        }
    return {
        "mae_per_game":round(statistics.mean(statistics.mean(g) for g in bygame.values()),3),
        "classification_accuracy":round(equal/len(rows),4),
        "confusion_true_rows_pred_columns":conf,
        "pooled_correlation_descriptive_only":round(correlation(rows,name),4),
        "same_move":at_ply
    }

def analyze(paths, probe, interval=10):
    # Loading keeps whole draws / entering-king games excluded, de-duplicates,
    # and returns independent probe scores for all 10-ply checkpoints.
    from tools.phase.correlate_terminal_ply import history_features, position_features
    from tools.phase.analyze_games import select_games, run_probe
    seen=set()
    games=[]
    counts=Counter()
    for path in paths:
        d=json.loads(path.read_text(encoding="utf-8"))
        kept,dropped=select_games(d["details"])
        counts.update(dropped)
        for g in kept:
            key=tuple(g["moves"])
            if key in seen:
                counts["duplicate"]+=1
                continue
            seen.add(key); games.append(g)
    if len(games)<10: raise ValueError("need at least ten complete distinct games")
    rows=[]
    for gid,g in enumerate(games):
        total=len(g["moves"])
        checkpoints=set(range(0,total+1,interval)) | {total}
        hist=history_features(g,checkpoints)
        for ply in sorted(checkpoints):
            sfen=g["sfens"][ply]
            row={"game":gid,"ply":ply,"final_ply":total,
                 "target":100*ply/total,"_sfen":sfen}
            row.update(position_features(sfen))
            row.update(hist[ply])
            rows.append(row)
    scores=run_probe(probe,[r["_sfen"] for r in rows])
    for row,score in zip(rows,scores):
        row.update(score)
        assigned_values(row)
        del row["_sfen"]
    candidates={"old_progress":summarize(rows,"progress")}
    for name in MATURITY_WEIGHTS:
        candidates[name]=summarize(rows,name)
        candidates[name]["cv_linear_calibrated_mae"]=cv_calibrated(rows,name)
    # Diagnostic dimensions are purposely NOT folded into maturity.
    urgent_early=[r for r in rows if r["balanced_35_35_30"]<33.333 and r["urgency"]>=40]
    peak_urgency=[r for r in rows if r["urgency"]>=60]
    urgency_by_stage={}
    for index,label in enumerate(STAGE_NAMES):
        subset=[r for r in rows if stage(r["balanced_35_35_30"])==index]
        urgency_by_stage[label]={
            "positions":len(subset),
            "urgency_mean":round(statistics.mean(r["urgency"] for r in subset),1) if subset else None,
            "urgency_ge40":sum(r["urgency"]>=40 for r in subset),
            "complexity_mean":round(statistics.mean(r["complexity"] for r in subset),1) if subset else None,
        }
    ranking=sorted(MATURITY_WEIGHTS,
                  key=lambda n:candidates[n]["mae_per_game"])
    top=ranking[0]
    disagree=sorted(rows,
            key=lambda r:abs(r[top]-r["target"]),reverse=True)[:12]
    return {
        "schema":"phase-maturity-independent-exploration-v1",
        "source_paths":[str(p) for p in paths],
        "source_engine":"historic v0.0.19 only; not current KUMOJI",
        "official_engine_changed":False,
        "hypothesis_only":True,
        "game_count":len(games),"position_count":len(rows),
        "excluded":dict(counts),
        "reference":"terminal fraction (100*ply/actual final ply); only for retrospective validation, NOT a ground truth for tactical maturity",
        "stage_definition":"0-<33.333 opening, 33.333-<66.667 middle, >=66.667 end; deliberately retrospective",
        "weights":MATURITY_WEIGHTS,
        "results":candidates,
        "ranking_by_unadjusted_mae":ranking,
        "urgent_while_immature_count":len(urgent_early),
        "urgent_while_immature_examples":[{"game":r["game"],"ply":r["ply"],
                  "maturity":round(r["balanced_35_35_30"],1),
                  "urgency":round(r["urgency"],1),
                  "terminal_fraction":round(r["target"],1)}
                  for r in urgent_early[:10]],
        "urgency_ge60_positions":len(peak_urgency),
        "urgency_by_maturity":urgency_by_stage,
        "complexity_definition":"50% clipped legal-move width above 15, 30% hand count, 20% combat/king tension; provisional only",
        "biggest_maturity_vs_terminal_disagreements":[{"game":r["game"],"ply":r["ply"],
                  "final_ply":r["final_ply"],"maturity":round(r[top],1),
                  "terminal_fraction":round(r["target"],1),
                  "urgency":round(r["urgency"],1),"complexity":round(r["complexity"],1)}
                  for r in disagree],
        "warnings":[
          "Scoring against terminal percentage rewards elapsed-time prediction, not necessarily the phase relevant to chess strategy.",
          "Weights are pre-specified hypotheses; choosing the minimum-error candidate among them is exploratory selection.",
          "All positions from the same game must stay together when fitting linear calibration.",
          "No independent contemporary v2.0.6 match corpus has been included.",
          "Legal move width does not prove a position is computationally difficult.",
        ],
    }

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--input",type=Path,action="append",required=True)
    a.add_argument("--probe",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    report=analyze(args.input,args.probe)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("MATURITY_STUDY "+json.dumps({
        k:report[k] for k in ("game_count","position_count","excluded",
             "ranking_by_unadjusted_mae","urgent_while_immature_count",
             "urgency_ge60_positions","urgency_by_maturity","results",
             "biggest_maturity_vs_terminal_disagreements")
    },ensure_ascii=False))
    print("MATURITY_REPORT "+str(args.output))
if __name__=="__main__":
    main()
