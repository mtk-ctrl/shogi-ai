#!/usr/bin/env python3
"""Balanced 50-minute self-research using saved self-play positions."""
import argparse, gzip, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path

def norm(s): return " ".join(s.split()[:3])
def prior(knowledge,opening,older):
    known=set()
    for p in (Path(knowledge),Path(opening)):
        for ln in p.read_text(encoding="utf8").splitlines():
            if ln and not ln.startswith("#") and "\t" in ln: known.add(norm(ln.split("\t")[0]))
    for p in Path(older).glob("*.jsonl.gz"):
        with gzip.open(p,"rt",encoding="utf8") as f:
            for ln in f:
                try: x=json.loads(ln)
                except json.JSONDecodeError: continue
                def rec(x):
                    if isinstance(x,dict):
                        for k,v in x.items():
                            if k in ("sfen","position_sfen","start_sfen","board_sfen") and isinstance(v,str) and "/" in v: known.add(norm(v))
                            elif isinstance(v,(dict,list)):rec(v)
                    elif isinstance(x,list):
                        for v in x:rec(v)
                rec(x)
    for p in Path(older).glob("*.json.gz"):
        with gzip.open(p,"rt",encoding="utf8") as f:
            obj=json.load(f)
        def rec(x):
            if isinstance(x,dict):
                for k,v in x.items():
                    if k in ("sfen","position_sfen","start_sfen","board_sfen") and isinstance(v,str) and "/" in v: known.add(norm(v))
                    elif isinstance(v,(dict,list)): rec(v)
            elif isinstance(x,list):
                for v in x: rec(v)
        rec(obj)
    return known

def kind(m):
    if m.get("in_check_before") or m.get("gave_check"):return "check"
    if m.get("is_capture"):return "capture"
    if m.get("is_drop"):return "drop"
    return "quiet"

def parse(path):
    rows=[]
    for ln in Path(path).read_text(encoding="utf8").splitlines():
        if ln and not ln.startswith("#"):
            a=ln.split("\t")
            if len(a)!=3:raise ValueError("Invalid TSV")
            rows.append(dict(id=a[0],sfen=a[1],moves=a[2].split()))
    if len(rows)!=40 or len(set(x["id"] for x in rows))!=40:raise ValueError("40 unique rows required")
    return rows

def validate(path,knowledge,opening):
    import shogi
    known=prior(knowledge,opening,"older")
    used=set()
    for x in parse(path):
        b=shogi.Board()
        for move in x["moves"]:
            m=shogi.Move.from_usi(move)
            if m not in b.legal_moves:raise ValueError("Invalid move "+move)
            b.push(m)
        k=norm(b.sfen())
        if k!=x["sfen"] or k in known or k in used:raise ValueError("Prior research or SFEN collision "+x["id"])
        used.add(k)
    print("Validated: 40 legal new positions, no duplicate with adopted or prior archived studies",flush=True)

def choose(a):
    import shogi
    known=prior(a.knowledge,a.opening,a.older)
    request=json.loads(Path(a.request).read_text(encoding="utf8"))
    targets=request["stages"]
    if set(targets)!=set(("opening","middle","end")) or sum(targets.values())!=40:
        raise ValueError("Expected 40 positions divided across opening/middle/end")
    pool={stage:[] for stage in targets}; seen=set()
    with gzip.open(a.games,"rt",encoding="utf8") as f:
        for ln in f:
            g=json.loads(ln); n=len(g["moves"])
            if n<95:continue
            b=shogi.Board(); hist=[]
            for m in g["moves"]:
                ply=len(hist)
                stage=("opening" if 16<=ply<=50 and n-ply>=40 else
                       "middle" if 60<=ply<=95 and n-ply>=20 else
                       "end" if n>=110 and 100<=ply<=220 and 10<=n-ply<=40 else None)
                if stage:
                    k=norm(b.sfen())
                    sc=m.get("search",{}).get("score_black_cp")
                    if k not in known and k not in seen and sc is not None and abs(sc)<=1600 and len(list(b.legal_moves))>=8:
                        pool[stage].append(dict(stage=stage,sfen=k,history_moves=hist.copy(),game_id=g["game_id"],
                           ply=ply,side="black" if b.turn==shogi.BLACK else "white",type=kind(m),score_black_cp=sc,
                           source_game_index=g["source_game_index"],next_move_in_game=m["move"]))
                        seen.add(k)
                b.push_usi(m["move"]);hist.append(m["move"])
    selected=[]; games=set()
    for stage in ("opening","middle","end"):
        side={"black":0,"white":0}
        sorted_pool=sorted(pool[stage],key=lambda x:hashlib.sha256((str(a.seed)+x["game_id"]+str(x["ply"])).encode()).hexdigest())
        for typ in ("quiet","capture","drop","check","*"):
            candidates=[x for x in sorted_pool if typ=="*" or x["type"]==typ]
            quota=(targets[stage]+3)//4 if typ!="*" else targets[stage]
            count=0
            for x in candidates:
                if sum(y["stage"]==stage for y in selected)==targets[stage] or count==quota:break
                if x["game_id"] in games or side[x["side"]]>=((targets[stage]+1)//2):continue
                selected.append(x);games.add(x["game_id"]);side[x["side"]]+=1;count+=1
        if sum(x["stage"]==stage for x in selected)!=targets[stage]:raise ValueError("insufficient diverse "+stage)
    out=[]
    code_map={"opening":"O","middle":"M","end":"E"}
    run_label=request["request_id"].replace("-","")
    for stage,code in ((x,code_map[x]) for x in ("opening","middle","end")):
        for i,x in enumerate((x for x in selected if x["stage"]==stage),1):
            x["id"]=f"kumoji-{run_label}-{code}{i:02d}";out.append(x)
    Path(a.output).write_text("#id\tSFEN\tUSI move history\n"+"".join(
       x["id"]+"\t"+x["sfen"]+"\t"+" ".join(x["history_moves"])+"\n" for x in out),encoding="utf8")
    Path(a.metadata).write_text(json.dumps(dict(source_run=request["source_run"],total=40,stages=targets,
        prior_exclusion_count=len(known),unique_games=len(games),seed=a.seed,positions=out),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    validate(a.output,a.knowledge,a.opening)
    print("Selected 40:",targets,"from 40 separate games",flush=True)

def study(a):
    from run_opening20 import Usi
    x=parse(a.positions)[a.lane]
    start=datetime.fromisoformat(a.start);deadline=datetime.fromisoformat(a.deadline)
    pause=(start-datetime.now(timezone.utc)).total_seconds()
    if pause>0:
        print(f"Wait {pause:.0f} seconds until scheduled research start",flush=True)
        time.sleep(pause)
    remaining=(deadline-datetime.now(timezone.utc)).total_seconds()
    if remaining<a.ms/1000+20:
        Path(a.output).write_text(json.dumps(dict(id=x["id"],completed=False,reason="insufficient time before cutoff",remaining_seconds=remaining))+"\n")
        return
    print("Start 50min",x["id"],len(x["moves"]),"plies",flush=True)
    e=Usi(a.engine,a.knowledge)
    try:r=e.research(x,a.ms,a.output)
    finally:e.close()
    print("Done",x["id"],r["bestmove"],r["elapsed_seconds"],flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["choose","validate","study"])
    p.add_argument("--games",default="source-archive/played-games.jsonl.gz")
    p.add_argument("--older",default="older")
    p.add_argument("--knowledge",default="position-knowledge-v1.tsv")
    p.add_argument("--opening",default=".github/research-opening-20-positions.tsv")
    p.add_argument("--output",default="positions.tsv")
    p.add_argument("--metadata",default="selection.json")
    p.add_argument("--positions",default="positions.tsv")
    p.add_argument("--request",default=".github/research-timebox40-request.json")
    p.add_argument("--seed",type=int,default=20261009)
    p.add_argument("--lane",type=int,default=0)
    p.add_argument("--engine",default="build/kumoji")
    p.add_argument("--ms",type=int,default=3000000)
    p.add_argument("--start",default="2026-10-09T09:30:00+09:00")
    p.add_argument("--deadline",default="2026-10-09T11:30:00+09:00")
    a=p.parse_args()
    if a.action=="choose":choose(a)
    elif a.action=="validate":validate(a.positions,a.knowledge,a.opening)
    else:
        if not 0<=a.lane<40:raise ValueError("lane")
        study(a)
