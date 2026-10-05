#!/usr/bin/env python3
"""Retrospective diagnosis for arena game artifacts.

Reconstruct every position in every game, scan static evaluation breakdowns,
then deeply re-analyse only short windows with large evaluation swings.
External engines are never used.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, subprocess, sys, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import shogi

EVAL_FIELDS=("material","safety","pressure","activity","danger","clamp","total")

def color_name(c): return "black" if c==shogi.BLACK else "white"
def side_sign(c): return 1 if c==shogi.BLACK else -1
def normalized_sfen(s): return " ".join(s.split()[:3])
def stable_id(prefix,text): return prefix+hashlib.sha256(text.encode()).hexdigest()[:20]

def winner_color(game):
    w=game.get("winner")
    if w not in ("A","B"): return None
    a_black=bool(game.get("a_black"))
    if w=="A": return shogi.BLACK if a_black else shogi.WHITE
    return shogi.WHITE if a_black else shogi.BLACK

def engine_label(game,color):
    return "A" if ((color==shogi.BLACK)==bool(game.get("a_black"))) else "B"

class Engine:
    def __init__(self,path,options):
        self.p=subprocess.Popen([path],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.i,self.o=self.p.stdin,self.p.stdout
        if self.i is None or self.o is None: raise RuntimeError("engine pipes unavailable")
        self.send("usi"); self.wait("usiok")
        for k,v in options.items():
            if isinstance(v,bool): v="true" if v else "false"
            self.send(f"setoption name {k} value {v}")
        self.send("isready"); self.wait("readyok")
    def send(self,s,flush=True):
        self.i.write(s+"\n")
        if flush: self.i.flush()
    def wait(self,prefix):
        while True:
            line=self.o.readline()
            if line=="": raise RuntimeError(f"engine exited waiting for {prefix}")
            line=line.rstrip()
            if line.startswith(prefix): return line
    def eval_many(self,sfens):
        for s in sfens:
            self.send("position sfen "+s,False); self.send("eval",False)
        self.i.flush(); out=[]
        while len(out)<len(sfens):
            line=self.o.readline()
            if line=="": raise RuntimeError("engine exited during eval")
            line=line.rstrip()
            if not line.startswith("info string evaluation "): continue
            p=line.split(); row={}
            for n in EVAL_FIELDS:
                try: row[n]=int(p[p.index(n)+1])
                except (ValueError,IndexError): pass
            if "total" not in row: raise RuntimeError("malformed eval: "+line)
            out.append(row)
        return out
    @staticmethod
    def score(parts):
        if "score" not in parts: return None
        try:
            i=parts.index("score"); kind=parts[i+1]; v=int(parts[i+2])
        except (ValueError,IndexError): return None
        if kind=="cp": return v
        if kind=="mate": return (1 if v>=0 else -1)*(100000000-min(abs(v),999999))
        return None
    @staticmethod
    def integer(parts,key):
        try: return int(parts[parts.index(key)+1])
        except (ValueError,IndexError): return None
    def search(self,sfen,ms):
        self.send("position sfen "+sfen); self.send(f"go movetime {ms}")
        r={"bestmove":None,"score":None,"depth":None,"seldepth":None,
           "nodes":None,"time_ms":None,"pv":[],"stats":{}}
        while True:
            line=self.o.readline()
            if line=="": raise RuntimeError("engine exited during search")
            line=line.rstrip()
            if line.startswith("bestmove "):
                q=line.split(); r["bestmove"]=q[1] if len(q)>1 else None; return r
            if not line.startswith("info "): continue
            p=line.split(); s=self.score(p)
            if s is not None: r["score"]=s
            for k,dst in (("depth","depth"),("seldepth","seldepth"),("nodes","nodes"),("time","time_ms")):
                v=self.integer(p,k)
                if v is not None: r[dst]=v
            if "pv" in p: r["pv"]=p[p.index("pv")+1:]
            if "string" in p:
                tail=p[p.index("string")+1:]
                for j in range(0,len(tail)-1,2):
                    try: r["stats"][tail[j]]=int(tail[j+1])
                    except ValueError: pass
    def close(self):
        if self.p.poll() is not None: return
        try: self.send("quit"); self.p.wait(timeout=5)
        except Exception: self.p.kill()

def load_games(root):
    rows=[]
    for path in sorted(root.rglob("*.json")):
        try: data=json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        if not isinstance(data.get("details"),list): continue
        for i,g in enumerate(data["details"]):
            if isinstance(g,dict) and isinstance(g.get("moves"),list): rows.append((path,i,g))
    return rows

def reconstruct(moves):
    b=shogi.Board(); sfens=[b.sfen()]; actors=[]
    for ply,tok in enumerate(moves,1):
        m=shogi.Move.from_usi(tok)
        if m not in b.legal_moves: raise ValueError(f"illegal ply {ply}: {tok}")
        actors.append(b.turn); b.push(m); sfens.append(b.sfen())
    return sfens,actors

def detect_swings(evals,max_window,threshold):
    totals=[int(x["total"]) for x in evals]; raw=[]
    for start in range(len(totals)-1):
        best=None
        for end in range(start+1,min(len(totals),start+max_window+1)):
            d=totals[end]-totals[start]
            if abs(d)>=threshold and (best is None or abs(d)>abs(best[1])): best=(end,d)
        if best: raw.append({"start":start,"end":best[0],"delta_black":best[1]})
    out=[]
    for x in raw:
        sign=1 if x["delta_black"]>0 else -1
        if out and x["start"]<=out[-1]["end"] and sign==(1 if out[-1]["delta_black"]>0 else -1):
            if abs(x["delta_black"])>abs(out[-1]["delta_black"]): out[-1]=x
        else: out.append(x)
    return out

def select_deep(rows,limit):
    ranked=sorted(rows,key=lambda r:(-r["priority"],-abs(r["delta_black"]),r["source_file"],r["game_index"]))
    out=[]; seen=set()
    for r in ranked:
        k=(r["source_file"],r["game_index"])
        if k in seen: continue
        out.append(r); seen.add(k)
        if len(out)>=limit: return out
    ids={r["interval_id"] for r in out}
    for r in ranked:
        if r["interval_id"] in ids: continue
        out.append(r)
        if len(out)>=limit: break
    return out

def classify(actor,gainer,played,delta_gain,pre_static,sh_pre,sh_post,dp_pre,dp_post,
             move_signal,blunder,good_tol,gap,eventual_loser):
    dplayed=-dp_post["score"] if dp_post.get("score") is not None else None
    splayed=-sh_post["score"] if sh_post.get("score") is not None else None
    dloss=dp_pre.get("score")-dplayed if dp_pre.get("score") is not None and dplayed is not None else None
    sloss=sh_pre.get("score")-splayed if sh_pre.get("score") is not None and splayed is not None else None
    tags=[]
    if sh_pre.get("bestmove")!=dp_pre.get("bestmove"): tags.append("bestmove-disagreement")
    if sh_pre.get("score") is not None and dp_pre.get("score") is not None and abs(sh_pre["score"]-dp_pre["score"])>=gap:
        tags.append("shallow-deep-score-gap")
    static_turn=pre_static["total"]*side_sign(actor)
    if dp_pre.get("score") is not None and abs(static_turn-dp_pre["score"])>=gap: tags.append("static-search-gap")
    if dloss is not None and dloss>=blunder:
        tags.append("deep-blunder")
        if eventual_loser: tags.append("loss-move-candidate")
    if delta_gain>=move_signal:
        if actor==gainer:
            if dloss is not None and dloss<=good_tol: tags.append("gainer-good-move")
            elif dloss is not None and dloss>=blunder: tags.append("static-overreaction")
            else: tags.append("gainer-move-uncertain")
        else:
            if dloss is not None and dloss>=blunder: tags.append("opponent-mistake")
            elif dloss is not None and dloss<=good_tol: tags.append("forced-concession")
            else: tags.append("opponent-move-uncertain")
    if sh_pre.get("bestmove")==played and dp_pre.get("bestmove")!=played and dloss is not None and dloss>=blunder:
        tags.append("search-horizon-candidate")
    if "static-search-gap" in tags or "static-overreaction" in tags: tags.append("evaluation-candidate")
    if any(t in tags for t in ("bestmove-disagreement","shallow-deep-score-gap","search-horizon-candidate")):
        tags.append("search-insufficiency-candidate")
    return {"static_delta_toward_gainer":delta_gain,"shallow_loss":sloss,"deep_loss":dloss,
            "deep_bestmove_matches_played":dp_pre.get("bestmove")==played,"tags":sorted(set(tags))}

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
def mean(v): return sum(v)/len(v) if v else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True); ap.add_argument("--engine",required=True); ap.add_argument("--output-dir",required=True)
    ap.add_argument("--expected-games",type=int,default=0); ap.add_argument("--expected-plies",type=int,default=0)
    ap.add_argument("--max-window-plies",type=int,default=4); ap.add_argument("--swing-threshold",type=int,default=300)
    ap.add_argument("--deep-intervals",type=int,default=300); ap.add_argument("--shallow-ms",type=int,default=50); ap.add_argument("--deep-ms",type=int,default=500)
    ap.add_argument("--move-signal",type=int,default=100); ap.add_argument("--blunder-threshold",type=int,default=150)
    ap.add_argument("--good-tolerance",type=int,default=80); ap.add_argument("--score-gap",type=int,default=200)
    ap.add_argument("--experience-file",default=""); ap.add_argument("--learning-ms",type=int,default=500); ap.add_argument("--warm-verify",type=int,default=100)
    a=ap.parse_args(); root=Path(a.input); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    games=load_games(root); plies=sum(len(g.get("moves",[])) for _,_,g in games)
    if a.expected_games and len(games)!=a.expected_games: raise SystemExit(f"expected {a.expected_games} games, found {len(games)}")
    if a.expected_plies and plies!=a.expected_plies: raise SystemExit(f"expected {a.expected_plies} plies, found {plies}")

    e=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":False}); intervals=[]; reasons=collections.Counter(); positions_scanned=0; invalid=0; started=time.monotonic()
    try:
        for n,(path,gi,g) in enumerate(games,1):
            try:
                sfens,_=reconstruct(g["moves"]); ev=e.eval_many(sfens)
            except Exception as ex:
                invalid+=1; print(f"invalid {path.name}#{gi}: {ex}",file=sys.stderr); continue
            positions_scanned+=len(sfens); reasons[str(g.get("reason"))]+=1; rel=str(path.relative_to(root)); wc=winner_color(g)
            for s in detect_swings(ev,a.max_window_plies,a.swing_threshold):
                gain=shogi.BLACK if s["delta_black"]>0 else shogi.WHITE
                end_adv=ev[s["end"]]["total"]*side_sign(gain)
                surprise=wc is not None and wc!=gain and end_adv>=max(a.swing_threshold,500)
                key=f"{rel}:{gi}:{s['start']}:{s['end']}:{s['delta_black']}"
                intervals.append({"interval_id":stable_id("sw-",key),"source_file":rel,"game_index":gi,
                    "start_ply":s["start"],"end_ply":s["end"],"length_plies":s["end"]-s["start"],
                    "delta_black":s["delta_black"],"gainer_color":color_name(gain),"gainer_engine":engine_label(g,gain),
                    "start_total":ev[s["start"]]["total"],"end_total":ev[s["end"]]["total"],
                    "winner":g.get("winner"),"reason":g.get("reason"),"surprise":surprise,
                    "priority":abs(s["delta_black"])+(250 if surprise else 0)})
            if n%100==0 or n==len(games):
                print(json.dumps({"progress_games":n,"total_games":len(games),"positions":positions_scanned,"swings":len(intervals),"elapsed_seconds":round(time.monotonic()-started,1)}))
    finally: e.close()

    scan={"games":len(games),"valid_games":len(games)-invalid,"invalid_games":invalid,"plies":plies,
          "positions_evaluated":positions_scanned,"max_window_plies":a.max_window_plies,"swing_threshold":a.swing_threshold,
          "swing_intervals":len(intervals),"game_reasons":dict(reasons)}
    dump(out/"scan-summary.json",scan); jsonl(out/"swings-all.jsonl",intervals)
    selected=select_deep(intervals,a.deep_intervals); dump(out/"selected-intervals.json",selected)

    e=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":False}); cache={}; file_cache={}; deep_rows=[]; problems=[]; posmap={}; causes=collections.Counter(); tags_count=collections.Counter()
    def search(sfen,ms):
        k=(normalized_sfen(sfen),ms)
        if k not in cache: cache[k]=e.search(sfen,ms)
        return cache[k]
    try:
        for idx,it in enumerate(selected,1):
            rel=it["source_file"]
            if rel not in file_cache: file_cache[rel]=json.loads((root/rel).read_text(encoding="utf-8"))
            g=file_cache[rel]["details"][it["game_index"]]; moves=list(g["moves"]); sfens,actors=reconstruct(moves)
            st,en=it["start_ply"],it["end_ply"]; stat=e.eval_many(sfens[st:en+1]); gain=shogi.BLACK if it["gainer_color"]=="black" else shogi.WHITE; wc=winner_color(g)
            details=[]; own=False; opp=False; forced=False; uncertain=False
            for li,ply in enumerate(range(st+1,en+1),1):
                actor=actors[ply-1]; played=moves[ply-1]; pre,post=sfens[ply-1],sfens[ply]
                sp,so=search(pre,a.shallow_ms),search(post,a.shallow_ms); dp,do=search(pre,a.deep_ms),search(post,a.deep_ms)
                dg=(stat[li]["total"]-stat[li-1]["total"])*side_sign(gain)
                c=classify(actor,gain,played,dg,stat[li-1],sp,so,dp,do,a.move_signal,a.blunder_threshold,a.good_tolerance,a.score_gap,wc is not None and actor!=wc)
                t=c["tags"]; own|="gainer-good-move" in t; opp|="opponent-mistake" in t; forced|="forced-concession" in t; uncertain|=any(x.endswith("uncertain") for x in t); tags_count.update(t)
                d={"ply":ply,"actor_color":color_name(actor),"actor_engine":engine_label(g,actor),"played":played,"pre_sfen":pre,"post_sfen":post,
                   "static_pre":stat[li-1],"static_post":stat[li],"shallow_pre":sp,"shallow_post":so,"deep_pre":dp,"deep_post":do,**c}; details.append(d)
                ptag=[x for x in t if x in {"opponent-mistake","gainer-good-move","deep-blunder","loss-move-candidate","search-horizon-candidate","search-insufficiency-candidate","evaluation-candidate","static-overreaction","static-search-gap","bestmove-disagreement"}]
                if ptag:
                    pid=stable_id("pr-",normalized_sfen(pre)+":"+played)
                    row={"id":pid,"interval_id":it["interval_id"],"source":{"file":rel,"game":it["game_index"],"ply":ply},"sfen":pre,"side_to_move":color_name(actor),
                         "played_move":played,"deep_bestmove":dp.get("bestmove"),"deep_loss":c.get("deep_loss"),"tags":sorted(set(ptag)),"static":stat[li-1],"shallow":sp,"deep":dp,"winner":g.get("winner"),"final_reason":g.get("reason")}
                    problems.append(row); posid=stable_id("pos-",normalized_sfen(pre)); prow={"id":posid,"sfen":pre,"side_to_move":color_name(actor),"tags":sorted(set(ptag+["eval-swing"])),"source":row["source"],"static":stat[li-1],"shallow":sp,"deep":dp,"played_move":played,"deep_loss":c.get("deep_loss"),"final_result":g.get("winner"),"use_count":0,"last_used":None}
                    if posid not in posmap or abs(c.get("deep_loss") or 0)>abs(posmap[posid].get("deep_loss") or 0): posmap[posid]=prow
            cause="mixed-good-move-and-opponent-mistake" if own and opp else "opponent-mistake" if opp else "gainer-good-move" if own else "forced-concession-or-pressure" if forced else "uncertain" if uncertain else "unresolved"
            causes[cause]+=1; deep_rows.append({**it,"cause":cause,"moves":details})
            if idx%25==0 or idx==len(selected): print(json.dumps({"deep_intervals":idx,"total":len(selected),"problems":len(problems)}))
    finally: e.close()

    pmap={}
    for r in problems:
        old=pmap.get(r["id"])
        if old is None or abs(r.get("deep_loss") or 0)>abs(old.get("deep_loss") or 0): pmap[r["id"]]=r
    problems=sorted(pmap.values(),key=lambda r:(-abs(r.get("deep_loss") or 0),r["id"])); positions=sorted(posmap.values(),key=lambda r:(-abs(r.get("deep_loss") or 0),r["id"]))
    jsonl(out/"problem-suite.jsonl",problems); jsonl(out/"position-bank.jsonl",positions); dump(out/"deep-diagnosis.json",{"intervals":len(deep_rows),"problem_positions":len(problems),"details":deep_rows})

    learning={"enabled":False}; exp=Path(a.experience_file) if a.experience_file else None
    if exp and positions:
        exp.parent.mkdir(parents=True,exist_ok=True); le=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":True,"ExperienceFile":str(exp)})
        try:
            for i,r in enumerate(positions,1):
                le.search(r["sfen"],a.learning_ms)
                if i%50==0 or i==len(positions): print(json.dumps({"learning_positions":i,"total":len(positions)}))
        finally: le.close()
        cold={normalized_sfen(r["sfen"]):r["shallow"] for r in positions}; verify=positions[:max(0,a.warm_verify)]; warm=[]
        if verify:
            we=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":True,"ExperienceFile":str(exp)})
            try:
                for r in verify: warm.append(we.search(r["sfen"],a.shallow_ms))
            finally: we.close()
        cn=[]; wn=[]; ct=[]; wt=[]; same=hits=probes=0
        for r,w in zip(verify,warm):
            c=cold.get(normalized_sfen(r["sfen"]),{})
            if isinstance(c.get("nodes"),int) and isinstance(w.get("nodes"),int): cn.append(c["nodes"]); wn.append(w["nodes"])
            if isinstance(c.get("time_ms"),int) and isinstance(w.get("time_ms"),int): ct.append(c["time_ms"]); wt.append(w["time_ms"])
            same+=c.get("bestmove")==w.get("bestmove"); probes+=int(w.get("stats",{}).get("experience_probes",0)); hits+=int(w.get("stats",{}).get("experience_hits",0))
        red=lambda c,w: None if not c or not w or mean(c)==0 else 1-mean(w)/mean(c)
        learning={"enabled":True,"positions_learned":len(positions),"learning_ms":a.learning_ms,"experience_file":str(exp),"warm_verify_positions":len(verify),
                  "warm_bestmove_matches_cold":same,"warm_experience_probes":probes,"warm_experience_hits":hits,"warm_hit_rate":hits/probes if probes else None,
                  "cold_nodes_mean":mean(cn),"warm_nodes_mean":mean(wn),"nodes_reduction":red(cn,wn),"cold_time_ms_mean":mean(ct),"warm_time_ms_mean":mean(wt),"time_reduction":red(ct,wt)}
        dump(out/"experience-learning.json",learning)

    summary={"schema_version":1,"scan":scan,"deep":{"selected_intervals":len(selected),"causes":dict(causes),"diagnosis_tags":dict(tags_count),"problem_positions":len(problems),"position_bank_records":len(positions),"shallow_ms":a.shallow_ms,"deep_ms":a.deep_ms},"experience":learning}; dump(out/"summary.json",summary)
    lines=["# 6,520局 遡及Diagnosis","","## 全棋譜軽量走査",f"- 対象局数: {scan['games']}",f"- 対象手数: {scan['plies']}",f"- 評価した局面数: {scan['positions_evaluated']}",f"- 数手以内の評価急変区間: {scan['swing_intervals']}",f"- 検出条件: 最大 {a.max_window_plies} ply / |評価変化| >= {a.swing_threshold}",f"- 不正・復元失敗局: {scan['invalid_games']}","","## 深掘り",f"- 深掘り区間: {len(selected)}",f"- 条件: {a.shallow_ms}ms vs {a.deep_ms}ms",f"- Problem Suite: {len(problems)}局面",f"- Position Bank: {len(positions)}局面","","### 評価上昇/下降の原因"]
    lines += [f"- {k}: {v}" for k,v in causes.most_common()]; lines += ["","### Diagnosisタグ"]+[f"- {k}: {v}" for k,v in tags_count.most_common()]+["","## Experience Cacheへの学習"]
    if learning.get("enabled"):
        lines += [f"- 学習局面: {learning['positions_learned']}",f"- warm検証局面: {learning['warm_verify_positions']}",f"- Experience hit率: {learning.get('warm_hit_rate')}",f"- nodes削減率: {learning.get('nodes_reduction')}",f"- 実時間削減率: {learning.get('time_reduction')}",f"- cold/warm bestmove一致: {learning.get('warm_bestmove_matches_cold')}/{learning.get('warm_verify_positions')}"]
    else: lines.append("- 未実行")
    lines += ["","## 解釈","- `gainer-good-move`: 評価を得た側の着手が深い探索でも大きく損をせず、上昇を維持した。","- `opponent-mistake`: 評価を失った側の着手に深い探索上の大きな損失があった。","- `mixed-good-move-and-opponent-mistake`: 好手と相手ミスの両方が同じ急変区間に含まれた。","- `forced-concession-or-pressure`: 相手の着手自体は深い探索でも大きなミスではなく、既に圧力がかかっていた可能性が高い。","- `search-horizon` / `static-search-gap`: 探索不足または現評価関数で説明しにくい候補として日中研究へ回す。"]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
