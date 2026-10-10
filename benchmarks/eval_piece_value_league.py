#!/usr/bin/env python3
"""Research-only eight-way material-value league; production source is untouched."""
import argparse
import hashlib
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

# Each row: board pawn/lance/knight/silver/bishop/rook/gold,
# promoted pawn/lance/knight/silver/bishop/rook, hand pawn/.../gold.
P = {
 "M": ("現行", [100,300,300,500,800,1000,600], [600,600,600,600,1000,1200], [100,300,300,500,800,1000,600]),
 "A": ("歩と小駒重視", [220,410,500,680,700,800,730], [700,760,820,900,1000,1250], [220,410,500,680,700,800,730]),
 "B": ("大駒重視", [70,200,230,430,1550,2200,600], [500,550,580,660,2350,3300], [70,200,230,430,1550,2200,600]),
 "C": ("成駒重視", [100,300,300,500,800,1000,600], [1050,920,900,880,1650,2250], [100,300,300,500,800,1000,600]),
 "D": ("持ち駒高評価", [100,300,300,500,800,1000,600], [600,600,600,600,1000,1200], [210,510,540,1000,1600,2100,1180]),
 "E": ("持ち駒低評価", [100,300,300,500,800,1000,600], [600,600,600,600,1000,1200], [50,150,160,270,430,530,300]),
 "F": ("金銀・守備重視", [130,260,320,1100,850,1000,1250], [1050,1150,1200,1300,1120,1350], [130,260,320,1100,850,1000,1250]),
 "G": ("複合強化", [120,310,440,650,1250,1650,750], [760,810,860,920,1850,2400], [180,460,630,900,1850,2350,1060])
}
PAIRS=list(itertools.combinations(P,2))
BASE_SEED=2026150000
OPTIONS={"AdaptiveLongThink":True,"PositionKnowledge":True,
         "PositionKnowledgeFile":"build/position-knowledge-v1.tsv"}

def verify(n):
    if not 1<=n<=20 or len(P)!=8 or len(PAIRS)!=28:
        raise ValueError("invalid shard/profile counts")
    for name,(_,b,p,h) in P.items():
        if [len(b),len(p),len(h)] != [7,6,7] or any(not 20<=v<=5000 for v in b+p+h):
            raise ValueError("invalid values: "+name)
    if BASE_SEED+28*1000+n*2>=2147483647:
        raise ValueError("seed out of range")

def patch(text,key):
    _,b,p,h=P[key]
    start=text.index("inline int piece_value(int kind")
    end=text.index("// Always Black",start)
    board=", ".join(map(str,[0]+b+[0]))
    promo=", ".join(map(str,[0]+p+[0,0]))
    hands=", ".join(map(str,[0]+h+[0]))
    code=(
      "inline int piece_value(int kind, bool promoted = false) {\n"
      f"  constexpr int base[] = {{{board}}};\n"
      f"  constexpr int promoted_values[] = {{{promo}}};\n"
      '  if(kind < 0 || kind > 8) throw std::logic_error("unknown piece kind");\n'
      "  if(promoted && kind>=1 && kind<=6) return promoted_values[kind];\n"
      "  return base[kind];\n}\n"
      "inline int hand_piece_value(int kind) {\n"
      f"  constexpr int hand_values[] = {{{hands}}};\n"
      '  if(kind < 1 || kind > 7) throw std::logic_error("unknown hand piece kind");\n'
      "  return hand_values[kind];\n}\n\n"
    )
    revised=text[:start]+code+text[end:]
    old="* piece_value(kind);"
    if revised.count(old)!=1: raise ValueError("unexpected hand material implementation")
    return revised.replace(old,"* hand_piece_value(kind);",1)

def build(source,engine_dir):
    source=source.resolve()
    engine_dir=engine_dir.resolve()
    engine_dir.mkdir(parents=True,exist_ok=True)
    material=source/"engine/strategy/material.h"
    before=material.read_text(encoding="utf-8")
    if ("constexpr int base[] = {0, 100, 300, 300, 500, 800, 1000, 600, 0};" not in before
        or "if (promoted && kind >= 1 && kind <= 4) return 600;" not in before):
        raise ValueError("production values differ; rebaseline before running")
    try:
        for key in P:
            material.write_text(patch(before,key),encoding="utf-8")
            binary=engine_dir/key
            subprocess.run([sys.executable,"scripts/build.py","--output",str(binary)],cwd=source,check=True)
            binary.chmod(0o755)
            print("compiled",key,hashlib.sha256(binary.read_bytes()).hexdigest(),flush=True)
    finally:
        material.write_text(before,encoding="utf-8")
    if material.read_text(encoding="utf-8")!=before:
        raise ValueError("source restoration failed")

def run(shards,shard,engines,result_dir,smoke=False):
    if shard<0 or shard>=shards: raise ValueError("invalid shard")
    result_dir.mkdir(parents=True,exist_ok=True)
    for i,(a,b) in enumerate(PAIRS[:1] if smoke else PAIRS):
        path=result_dir/f"pair-{i:02d}-{a}-{b}-shard-{shard:02d}.json"
        command=[sys.executable,str(Path(__file__).resolve().parent/"arena.py"),
            "--engine-a",str(engines/a),"--engine-b",str(engines/b),
            "--options-a",json.dumps(OPTIONS),"--options-b",json.dumps(OPTIONS),
            "--go-command","go movetime 200","--games","2","--max-plies","300",
            "--game-offset",str(shard*2),"--seed",str(BASE_SEED+i*1000+shard*2),
            "--output",str(path)]
        subprocess.run(command,check=True)
        row=json.loads(path.read_text(encoding="utf-8"))
        knowledge=row.get("position_knowledge",{})
        if (row.get("games")!=2 or row.get("illegal_games",0)!=0
            or knowledge.get("A",{}).get("positions",0)<1
            or knowledge.get("A")!=knowledge.get("B")
            or row.get("sha256_a")==row.get("sha256_b")):
            raise ValueError("bad game/knowledge/profile: "+str(path))
    print("finished",shard,"games",2*(1 if smoke else len(PAIRS)))

def aggregate(shards,result_dir,output):
    output.mkdir(parents=True,exist_ok=True)
    scores={k:{"wins":0,"draws":0,"losses":0} for k in P}
    pair_scores=[]
    hashes={}
    common_knowledge=None
    for i,(a,b) in enumerate(PAIRS):
        wa=wb=d=0
        for shard in range(shards):
            path=result_dir/f"pair-{i:02d}-{a}-{b}-shard-{shard:02d}.json"
            row=json.loads(path.read_text(encoding="utf-8"))
            if (row.get("games")!=2 or len(row.get("details",[]))!=2
                or row.get("illegal_games",0)!=0 or row.get("game_offset")!=shard*2
                or row.get("seed")!=BASE_SEED+i*1000+shard*2
                or row.get("options_a")!=OPTIONS or row.get("options_b")!=OPTIONS):
                raise ValueError("bad match: "+str(path))
            k=row.get("position_knowledge",{})
            if k.get("A",{}).get("positions",0)<1 or k.get("A")!=k.get("B"):
                raise ValueError("knowledge unavailable/asymmetric: "+str(path))
            if common_knowledge is None: common_knowledge=k
            elif k!=common_knowledge: raise ValueError("knowledge identity changed")
            for name,sha in ((a,row.get("sha256_a")),(b,row.get("sha256_b"))):
                if not sha or name in hashes and hashes[name]!=sha:
                    raise ValueError("binary missing/changed: "+name)
                hashes[name]=sha
            wa+=row["wins_a"];wb+=row["wins_b"];d+=row["draws"]
        if wa+wb+d !=2*shards: raise ValueError("missing games")
        scores[a]["wins"]+=wa;scores[a]["losses"]+=wb;scores[a]["draws"]+=d
        scores[b]["wins"]+=wb;scores[b]["losses"]+=wa;scores[b]["draws"]+=d
        frac=(wa+d/2)/(2*shards)
        err=1.96*math.sqrt(frac*(1-frac)/(2*shards))
        pair_scores.append({"a":a,"b":b,"a_wins":wa,"draws":d,"b_wins":wb,
            "a_score":frac,"a_approx_95":[max(0,frac-err),min(1,frac+err)]})
    if len(set(hashes.values()))!=8: raise ValueError("identical profile binaries")
    standings=[]
    for k,rec in scores.items():
        n=sum(rec.values())
        standings.append({"id":k,"name":P[k][0],**rec,"games":n,
            "points":rec["wins"]+rec["draws"]/2,
            "score":(rec["wins"]+rec["draws"]/2)/n})
    standings.sort(key=lambda x:(x["points"],x["wins"]),reverse=True)
    report={"profiles":P,"shards":shards,"games_total":len(PAIRS)*2*shards,
        "time":"go movetime 200, AdaptiveLongThink true","knowledge":common_knowledge,
        "hashes":hashes,"standings":standings,"pairs":pair_scores,
        "interpretation":"Screening only, no automatic adoption; shared starts and 28 pair comparisons."}
    (output/"piece-value-league.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 駒価値8型リーグ", "",
        f"全 {report['games_total']}局、{shards}並列、各組{2*shards}局。現行エンジンと局面知識を固定。","",
        "|順位|型|勝|分|敗|得点率|","|---:|---|---:|---:|---:|---:|"]
    for i,s in enumerate(standings,1):
        lines.append(f"|{i}|{s['id']} {s['name']}|{s['wins']}|{s['draws']}|{s['losses']}|{s['score']:.1%}|")
    lines+=["","## 組別","", "|A|B|A勝-分-B勝|A得点率|","|---|---|---|---:|"]
    for s in pair_scores:lines.append(f"|{s['a']}|{s['b']}|{s['a_wins']}-{s['draws']}-{s['b_wins']}|{s['a_score']:.1%}|")
    lines+=["","## 候補の配点", "", "盤上=歩香桂銀角飛金、成駒=と金成香成桂成銀馬龍、持ち駒=歩香桂銀角飛金。",""]
    for k,(name,b,p,h) in P.items():lines.append(f"- {k} {name}: 盤上 {b} / 成駒 {p} / 持ち駒 {h}")
    lines+=["","新候補は研究用。正式採用は行わない。"]
    (output/"piece-value-league.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("command",choices=["validate","build","run","smoke","aggregate"])
    a.add_argument("--shards",type=int,default=20)
    a.add_argument("--shard",type=int,default=0)
    a.add_argument("--source",type=Path,default=Path("engine-src"))
    a.add_argument("--engine-dir",type=Path,default=Path("build"))
    a.add_argument("--input-dir",type=Path,default=Path("results"))
    a.add_argument("--output-dir",type=Path,default=Path("report"))
    x=a.parse_args()
    verify(x.shards)
    if x.command=="validate":
        mat=x.source/"engine/strategy/material.h"
        if mat.exists():
            original=mat.read_text(encoding="utf-8")
            for k in P: patch(original,k)
        print(f"8 profiles, 28 pairs, {56*x.shards} games")
    elif x.command=="build":build(x.source,x.engine_dir)
    elif x.command=="smoke":run(1,0,x.engine_dir,x.input_dir,True)
    elif x.command=="run":run(x.shards,x.shard,x.engine_dir,x.input_dir)
    else:aggregate(x.shards,x.input_dir,x.output_dir)

if __name__=="__main__": main()
