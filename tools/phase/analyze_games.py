#!/usr/bin/env python3
"""Diagnostic profiles from completed ordinary wins only (no draws/entering king)."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import subprocess

import shogi

FIELDS = ("development", "battle", "invasion", "king_threat", "progress")
ORDINARY_ENDINGS = {"checkmate", "resign", "no_legal_moves"}

def entered_camp(sfen: str) -> bool:
    ranks = sfen.split()[0].split("/")
    if len(ranks) != 9:
        raise ValueError("invalid SFEN board ranks")
    # Uppercase K (Black) in a-c, or lowercase k (White) in g-i.
    return any("K" in r for r in ranks[:3]) or any("k" in r for r in ranks[6:])

def select_games(details):
    kept, excluded = [], Counter()
    for game in details:
        # Always exclude entire games, not just the last few plies.
        if game.get("reason") in ("declare_win", "entering_king", "impasse"):
            excluded["entering_king"] += 1
            continue
        if game.get("winner") not in ("A","B"):
            excluded["draw"] += 1
            continue
        if game.get("reason") not in ORDINARY_ENDINGS or game.get("illegal_by"):
            excluded["other_or_invalid"] += 1
            continue
        moves=game.get("moves")
        if not isinstance(moves,list):
            raise ValueError("missing move sequence in accepted game")
        board=shogi.Board(game.get("start_sfen") or shogi.STARTING_SFEN)
        sfen_list=[board.sfen()]
        entered=entered_camp(sfen_list[0])
        for i,m in enumerate(moves,1):
            if not isinstance(m,str) or shogi.Move.from_usi(m) not in board.legal_moves:
                raise ValueError(f"invalid game move {i}: {m}")
            board.push_usi(m)
            sfen_list.append(board.sfen())
            entered |= entered_camp(sfen_list[-1])
        if entered:
            excluded["entering_king"] += 1
            continue
        kept.append({"winner":game["winner"],"reason":game["reason"],
                     "sfens":sfen_list})
    return kept, dict(excluded)

def run_probe(binary, sfens):
    commands="".join("position sfen "+s+"\n" for s in sfens)
    completed=subprocess.run([str(binary)],input=commands,text=True,
                             capture_output=True,timeout=180)
    if completed.returncode:
        raise RuntimeError("diagnostic failed: "+completed.stderr[-1000:])
    lines=completed.stdout.splitlines()
    if len(lines)!=len(sfens):
        raise ValueError(f"expected {len(sfens)} diagnostic rows, got {len(lines)}")
    result=[]
    for line in lines:
        words=line.split()
        if len(words)!=11 or words[0]!="phase":
            raise ValueError(f"invalid probe output: {line!r}")
        row={}
        for k,v in zip(words[1::2],words[2::2]):
            if k not in FIELDS:
                raise ValueError(f"unknown metric: {k}")
            row[k]=int(v)
        if set(row)!=set(FIELDS) or any(not 0<=v<=100 for v in row.values()):
            raise ValueError("malformed phase scores")
        result.append(row)
    return result

def profile(games, binary, interval=10):
    positions=[]
    for i,g in enumerate(games):
        final=len(g["sfens"])-1
        for ply in range(0,final+1):
            if ply==0 or ply%interval==0 or ply==final:
                positions.append((i,ply,g["sfens"][ply]))
    if not positions:
        return [], {}
    scores=run_probe(binary,[p[2] for p in positions])
    samples=[{"game":i,"ply":ply,**score} for (i,ply,_),score in zip(positions,scores)]
    per_ply=defaultdict(list)
    for row in samples:
        if row["ply"]%interval==0:
            per_ply[row["ply"]].append(row)
    table=[]
    for ply in sorted(per_ply):
        group=per_ply[ply]
        if not group:
            continue
        table.append({"ply":ply,"games":len(group),
                      **{k:round(statistics.median(r[k] for r in group),1) for k in FIELDS},
                      "development_min":min(r["development"] for r in group),
                      "development_max":max(r["development"] for r in group),
                      "battle_min":min(r["battle"] for r in group),
                      "battle_max":max(r["battle"] for r in group)})
    return samples, {"at_10_ply_intervals":table}

def analyze(path: Path, binary: Path, interval=10):
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("details"),list):
        raise ValueError("input is not an arena details dataset")
    games,excluded=select_games(data["details"])
    if not games:
        raise ValueError("no eligible ordinary decisive games")
    samples, summary=profile(games,binary,interval)
    output={
      "schema":"phase-diagnostic-v1", "source":path.as_posix(),
      "engine":"external phase probe; original playing engine left unchanged",
      "filter":"Only A/B wins with ordinary endings; remove entire draw and entering-king games",
      "games_input":len(data["details"]), "games_analyzed":len(games),
      "excluded":{"draw":excluded.get("draw",0),
                  "entering_king":excluded.get("entering_king",0),
                  "other_or_invalid":excluded.get("other_or_invalid",0)},
      "positions_measured":len(samples), "interval":interval,
      **summary,
    }
    return output

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--engine",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--interval",type=int,default=10)
    a=ap.parse_args()
    if a.interval<1: ap.error("interval must be >= 1")
    output=analyze(a.input,a.engine,a.interval)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PHASE SUMMARY "+json.dumps({
        k:output[k] for k in ("games_input","games_analyzed","excluded","positions_measured")
    },ensure_ascii=False))
    checkpoints=[r for r in output["at_10_ply_intervals"]
                 if r["ply"] in (0,10,20,30,40,60,80,100,120)]
    print("PHASE CHECKPOINTS "+json.dumps(checkpoints,ensure_ascii=False))
    print("PHASE REPORT "+str(a.output))
if __name__=="__main__":
    main()
