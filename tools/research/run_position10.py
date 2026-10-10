#!/usr/bin/env python3
"""Ten independent 50-minute position-knowledge research tasks."""
import argparse
import glob
import gzip
import hashlib
import json
import os
from pathlib import Path

def norm(s):
    return " ".join(s.split()[:3])

def read_source(path, checksum):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != checksum:
        raise ValueError("source archive SHA256 mismatch")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def select(args):
    import shogi
    from timebox40 import prior
    req=json.loads(Path(".github/research10-request.json").read_text(encoding="utf8"))
    reference=json.loads(Path(".github/research-evalshift40-selection.json").read_text(encoding="utf8"))
    if (req["source_run"] != int(reference["source_run"])
        or req["positions"] != 10 or req["minutes"] != 50 or req["runners"] != 10
        or req["adopt"] is not False):
        raise ValueError("request parameters do not match approved ten-lane design")
    games=read_source(args.source, reference["source_archive_sha256"])
    known=prior("position-knowledge-v1.tsv", ".github/research-opening-20-positions.tsv", "older")
    for line in Path(".github/research-opening-20-positions.tsv").read_text(encoding="utf8").splitlines():
        if line and not line.startswith("#") and len(line.split("\t"))>=3:
            known.add(norm(line.split("\t")[1]))
    quotas={"opening":3,"middle":4,"end":3}
    pools={"opening":[], "middle":[], "end":[]}
    for index,(row,ply) in enumerate(reference["positions"]):
        stage="opening" if index<14 else "middle" if index<30 else "end"
        pools[stage].append((row,ply))
    selected=[]; seen=set(); used_games=set()
    # Stable, reproducible selection from 40 recorded eligible candidate positions.
    for stage in ("opening","middle","end"):
        for game_number,ply in pools[stage]:
            if sum(x["stage"]==stage for x in selected)>=quotas[stage]:
                break
            if game_number in used_games:
                continue
            game=games[game_number-1]
            moves=game["moves"]
            if not 0<=ply<len(moves):
                raise ValueError("invalid source ply")
            board=shogi.Board(); history=[]
            for move in moves[:ply]:
                u=move["move"] if isinstance(move,dict) else move
                if shogi.Move.from_usi(u) not in board.legal_moves:
                    raise ValueError("source game has illegal move")
                board.push_usi(u); history.append(u)
            sfen=norm(board.sfen())
            if sfen in known or sfen in seen:
                continue
            selected.append(dict(id="kumoji-"+req["request_id"]+"-"+stage[0].upper()+str(len(selected)+1).zfill(2),
                stage=stage,source_game_row=game_number,source_ply=ply,
                sfen=sfen,history_moves=history))
            seen.add(sfen); used_games.add(game_number)
        if sum(x["stage"]==stage for x in selected)!=quotas[stage]:
            raise ValueError("not enough unresearched "+stage+" positions")
    Path(args.output).write_text("#id\tSFEN\tUSI move history\n"+"".join(
        x["id"]+"\t"+x["sfen"]+"\t"+" ".join(x["history_moves"])+"\n" for x in selected),encoding="utf8")
    obj=dict(schema="position10-v1",request=req,source_run=req["source_run"],
        source_sha256=reference["source_archive_sha256"],engine_commit=os.getenv("GITHUB_SHA"),
        knowledge_sha256=hashlib.sha256(Path("position-knowledge-v1.tsv").read_bytes()).hexdigest(),
        positions=selected,stage_counts=quotas,knowledge_adopted=False)
    Path(args.metadata).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("Selected",len(selected),"previously unstudied positions:",quotas,flush=True)

def parse(path):
    rows=[]
    for line in Path(path).read_text(encoding="utf8").splitlines():
        if line and not line.startswith("#"):
            parts=line.split("\t")
            if len(parts)!=3:raise ValueError("expected TSV 3 fields")
            rows.append(dict(id=parts[0],sfen=parts[1],moves=parts[2].split()))
    if len(rows)!=10 or len({r["id"] for r in rows})!=10:
        raise ValueError("10 unique positions required")
    return rows

def study(args):
    from run_opening20 import Usi
    import shogi
    rows=parse(args.positions)
    if not 0<=args.lane<10:raise ValueError("invalid lane")
    row=rows[args.lane]
    board=shogi.Board()
    for move in row["moves"]:
        m=shogi.Move.from_usi(move)
        if m not in board.legal_moves:raise ValueError("illegal historical move")
        board.push(m)
    if norm(board.sfen())!=row["sfen"]:raise ValueError("SFEN mismatch")
    engine=Usi(args.engine,args.knowledge)
    try:
        result=engine.research(row,3000000,args.output)
    finally:
        engine.close()
    print("Completed",row["id"],result["bestmove"],result["elapsed_seconds"],flush=True)

def aggregate(args):
    meta=json.loads(Path(args.metadata).read_text(encoding="utf8"))
    files=sorted(glob.glob(args.results+"/**/result.json",recursive=True))
    results=[json.loads(Path(p).read_text(encoding="utf8")) for p in files]
    expected={x["id"] for x in meta["positions"]}
    received=[x.get("id") for x in results]
    if len(received)!=len(set(received)) or any(x not in expected for x in received):
        raise ValueError("duplicate or foreign result IDs")
    complete=sum(1 for x in results if x.get("completed") is True and bool(x.get("bestmove")) )
    record=dict(schema="position10-results-v1",run_id=os.getenv("GITHUB_RUN_ID"),
        selection=meta,results=results,received=len(results),completed=complete,
        missing=sorted(expected-set(received)),knowledge_adopted=False)
    with gzip.open(args.output,"wt",encoding="utf8") as f:
        json.dump(record,f,ensure_ascii=False)
    summary=dict(run_id=os.getenv("GITHUB_RUN_ID"),expected=10,received=len(results),
        completed=complete,missing=record["missing"],knowledge_adopted=False,
        research_sha256=hashlib.sha256(Path(args.output).read_bytes()).hexdigest())
    Path(args.summary).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("Research completed",complete,"/10; no automatic adoption",flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("select","study","aggregate"))
    p.add_argument("--source",default="source-archive/played-games.jsonl.gz")
    p.add_argument("--positions",default="positions.tsv")
    p.add_argument("--output",default="result.json")
    p.add_argument("--metadata",default="selection10.json")
    p.add_argument("--knowledge",default="build/position-knowledge-v1.tsv")
    p.add_argument("--engine",default="build/kumoji")
    p.add_argument("--lane",type=int,default=0)
    p.add_argument("--results",default="results")
    p.add_argument("--summary",default="research10-summary.json")
    args=p.parse_args()
    if args.action=="select":select(args)
    elif args.action=="study":study(args)
    else:aggregate(args)

if __name__=="__main__":
    main()
