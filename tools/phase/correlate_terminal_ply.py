#!/usr/bin/env python3
"""Find diagnostic features correlated with relative terminal ply.

This is OFFLINE research only: the target requires knowledge of the future
terminal move. No changes to production playing/search/evaluation are made.
Exclude whole draws and entering-king games before any fitting. De-duplicate
identical move sequences across sources. Validate by GAME (not by position).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random
import statistics
import sys

import shogi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.phase.analyze_games import run_probe, select_games

PHASE = ("development", "battle", "invasion", "king_threat", "progress")
BASE = ("hand_count", "hand_weight", "hand_major", "promoted",
        "enemy_camp", "frontline", "board_nonking",
        "cumulative_captures", "cumulative_promotions", "cumulative_checks")
FIELDS = ("ply",) + PHASE + BASE

# All current-position values are reproducible from a single snapshot.
def position_features(sfen):
    board, _turn, hand, *_ = sfen.split()
    result = dict.fromkeys(BASE, 0)
    ranks = board.split("/")
    if len(ranks) != 9:
        raise ValueError("invalid SFEN ranks")
    for rank, row in enumerate(ranks):
        f = 0
        promo = False
        for token in row:
            if token.isdigit():
                f += int(token)
                continue
            if token == "+":
                promo = True
                continue
            if f >= 9:
                raise ValueError("invalid SFEN rank width")
            piece = token.upper()
            if piece != "K":
                result["board_nonking"] += 1
                result["promoted"] += int(promo)
                forward = (8-rank) if token.isupper() else rank
                result["enemy_camp"] += int(forward >= 6)
                result["frontline"] += int(forward >= 4)
            f += 1
            promo = False
        if f != 9:
            raise ValueError("invalid SFEN rank width")
    if hand != "-":
        amount = ""
        for token in hand:
            if token.isdigit():
                amount += token
                continue
            count = int(amount) if amount else 1
            amount = ""
            weight = {"P":1,"L":2,"N":2,"S":3,"G":3,"B":6,"R":6}[token.upper()]
            result["hand_count"] += count
            result["hand_weight"] += count*weight
            if token.upper() in ("B","R"):
                result["hand_major"] += count
        if amount:
            raise ValueError("invalid SFEN hands")
    # A reminder that count of pieces on board and count in hand are redundant.
    if result["board_nonking"] + result["hand_count"] != 38:
        raise ValueError("invalid piece conservation")
    return result

def history_features(game, checkpoints):
    board=shogi.Board(game["sfens"][0])
    captures=promos=checks=0
    out={0:{"cumulative_captures":0,"cumulative_promotions":0,"cumulative_checks":0}}
    for ply, token in enumerate(game["moves"], 1):
        move=shogi.Move.from_usi(token)
        if not move.drop_piece_type and board.piece_at(move.to_square) is not None:
            captures += 1
        promos += int(move.promotion)
        board.push(move)
        checks += int(board.is_check())
        if ply in checkpoints:
            out[ply]={"cumulative_captures":captures,
                      "cumulative_promotions":promos,
                      "cumulative_checks":checks}
    if board.sfen().split()[:3] != game["sfens"][-1].split()[:3]:
        raise ValueError("history mismatch")
    return out

def load_dataset(paths, binary, interval):
    eligible=[]
    excluded=Counter()
    seen=set()
    duplicates=0
    for path in paths:
        data=json.loads(path.read_text(encoding="utf-8"))
        details=data.get("details")
        if not isinstance(details,list):
            raise ValueError("missing details in "+str(path))
        kept, drops=select_games(details)
        excluded.update(drops)
        for g in kept:
            key=tuple(g["moves"])
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            eligible.append(g)
    if len(eligible)<10:
        raise ValueError("not enough eligible unique games")
    pending=[]
    lengths=[]
    for game_id,g in enumerate(eligible):
        length=len(g["moves"])
        if length<1:
            raise ValueError("empty winning match")
        lengths.append(length)
        checkpoints=set(range(0,length+1,interval)) | {length}
        his=history_features(g,checkpoints)
        for ply in sorted(checkpoints):
            features=position_features(g["sfens"][ply])
            features.update(his[ply])
            pending.append({"game":game_id,"ply":ply,"target":100.0*ply/length,
                            **features,"_sfen":g["sfens"][ply]})
    scores=run_probe(binary,[r["_sfen"] for r in pending])
    for row,phase in zip(pending,scores):
        row.update(phase)
        row.pop("_sfen")
    return pending, {"sources":[p.as_posix() for p in paths],
        "raw_games":sum(len(json.loads(p.read_text(encoding="utf-8"))["details"]) for p in paths),
        "excluded_before_dedup":dict(excluded),
        "duplicate_eligible_games_removed":duplicates,
        "unique_eligible_games":len(eligible),
        "positions":len(pending),
        "game_lengths":{"min":min(lengths),"median":statistics.median(lengths),"max":max(lengths)}}

def correlation(rows, feature):
    vals=[float(r[feature]) for r in rows]
    ys=[r["target"] for r in rows]
    ax=sum(vals)/len(vals); ay=sum(ys)/len(ys)
    numerator=sum((v-ax)*(y-ay) for v,y in zip(vals,ys))
    vx=sum((v-ax)**2 for v in vals)
    vy=sum((y-ay)**2 for y in ys)
    return numerator/math.sqrt(vx*vy) if vx*vy>0 else 0.0

def solve_linear(a, y):
    n=len(y)
    z=[row[:]+[target] for row,target in zip(a,y)]
    for j in range(n):
        pivot=max(range(j,n),key=lambda k:abs(z[k][j]))
        z[j],z[pivot]=z[pivot],z[j]
        if abs(z[j][j])<1e-12:
            raise ValueError("singular model")
        scale=z[j][j]
        for k in range(j,n+1):
            z[j][k] /= scale
        for i in range(n):
            if i==j:
                continue
            multiplier=z[i][j]
            for k in range(j,n+1):
                z[i][k] -= multiplier*z[j][k]
    return [z[i][-1] for i in range(n)]

def train_linear(rows, names, ridge=0.1):
    bygame=Counter(r["game"] for r in rows)
    weights=[1.0/bygame[r["game"]] for r in rows]
    tw=sum(weights)
    mu=[]; sd=[]
    for name in names:
        avg=sum(w*r[name] for w,r in zip(weights,rows))/tw
        var=sum(w*(r[name]-avg)**2 for w,r in zip(weights,rows))/tw
        mu.append(avg)
        sd.append(max(math.sqrt(var),1e-8))
    n=len(names)+1
    gram=[[0.0]*n for _ in range(n)]
    rhs=[0.0]*n
    for r,w in zip(rows,weights):
        xs=[1.0]+[(r[name]-a)/b for name,a,b in zip(names,mu,sd)]
        for i in range(n):
            rhs[i]+=w*xs[i]*r["target"]
            for j in range(n):
                gram[i][j]+=w*xs[i]*xs[j]
    for i in range(1,n):
        gram[i][i]+=ridge*tw
    coeff=solve_linear(gram,rhs)
    def predict(row):
        return max(0.0,min(100.0,coeff[0]+sum(
            coeff[i+1]*(row[name]-mu[i])/sd[i] for i,name in enumerate(names)
        )))
    return predict

MODELS={
 "ply_only":("ply",),
 "old_progress_calibrated":("progress",),
 "development":("development",),
 "battle":("battle",),
 "invasion":("invasion",),
 "king_threat":("king_threat",),
 "hand_count":("hand_count",),
 "hand_value":("hand_weight",),
 "cumulative_captures":("cumulative_captures",),
 "dev_and_hand":("development","hand_count"),
 "four_phase":("development","battle","invasion","king_threat"),
 "four_plus_captures":("development","battle","invasion","king_threat","cumulative_captures"),
 "board_only_extended":("development","battle","invasion","king_threat",
                         "hand_count","hand_major","promoted","enemy_camp"),
 "history_extended":("development","battle","invasion","king_threat",
                     "hand_count","hand_major","promoted","enemy_camp",
                     "cumulative_captures","cumulative_promotions","cumulative_checks"),
 "ply_plus_board":("ply","development","battle","invasion","king_threat",
                   "hand_count","hand_major","promoted","enemy_camp"),
}
def group_folds(rows, k=5):
    keys=sorted({r["game"] for r in rows})
    random.Random(20261008).shuffle(keys)
    return {game:i%k for i,game in enumerate(keys)}

def summarize_errors(rows, pred):
    bygame=defaultdict(list)
    for r,p in zip(rows,pred):
        bygame[r["game"]].append(abs(p-r["target"]))
    per_game=[statistics.mean(vals) for vals in bygame.values()]
    return round(statistics.mean(per_game),3)

def run_cv(rows, groups):
    folds=group_folds(rows)
    results={}
    prediction_cache={}
    for name,names in MODELS.items():
        predictions=[None]*len(rows)
        for fold in range(5):
            train=[r for r in rows if folds[r["game"]]!=fold]
            test=[(i,r) for i,r in enumerate(rows) if folds[r["game"]]==fold]
            model=train_linear(train,names)
            for i,r in test:
                predictions[i]=model(r)
        if any(p is None for p in predictions):
            raise ValueError("missing prediction")
        mae=summarize_errors(rows,predictions)
        idx40=[i for i,r in enumerate(rows) if r["ply"]==40]
        groups40=defaultdict(list)
        for i in idx40:
            groups40[rows[i]["game"]].append(abs(predictions[i]-rows[i]["target"]))
        err40=statistics.mean([statistics.mean(v) for v in groups40.values()]) if groups40 else None
        results[name]={"cv_game_mae":mae,"mae_at_move_40":round(err40,3) if err40 is not None else None}
        prediction_cache[name]=predictions
    results["old_progress_unfitted"]={"cv_game_mae":summarize_errors(rows,[r["progress"] for r in rows]),
             "mae_at_move_40":round(statistics.mean(abs(r["progress"]-r["target"]) for r in rows if r["ply"]==40),3)}
    corr={name:round(correlation(rows,name),4) for name in FIELDS}
    at40=[r for r in rows if r["ply"]==40]
    corr40={name:round(correlation(at40,name),4) for name in FIELDS} if len(at40)>3 else {}
    return results,corr,corr40

def analyze(paths, binary, interval=10):
    rows,meta=load_dataset(paths,binary,interval)
    scores,corr,corr40=run_cv(rows, meta)
    return {"schema":"relative-game-stage-v1","target_definition":"100*current_ply/actual_final_ply",
        "validation":"5-fold grouped by complete game; each game equally weighted",
        "label_warning":"future actual final ply used only for retrospective target, never as a predictor",
        "input":meta,"cv_models":scores,"pooled_correlations_descriptive_only":corr,
        "correlations_same_40th_move":corr40}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path,action="append",required=True)
    ap.add_argument("--probe",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--interval",type=int,default=10)
    a=ap.parse_args()
    if a.interval<1:
        ap.error("interval must be positive")
    report=analyze(a.input,a.probe,a.interval)
    a.output.parent.mkdir(exist_ok=True,parents=True)
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("RELATIVE STAGE INPUT "+json.dumps(report["input"],ensure_ascii=False))
    print("RELATIVE STAGE MODELS "+json.dumps(report["cv_models"],ensure_ascii=False))
    print("RELATIVE STAGE CORRELATIONS "+json.dumps(report["pooled_correlations_descriptive_only"],ensure_ascii=False))
    print("RELATIVE STAGE AT40 "+json.dumps(report["correlations_same_40th_move"],ensure_ascii=False))
    print("RELATIVE STAGE REPORT "+str(a.output))
if __name__=="__main__":
    main()
