#!/usr/bin/env python3
"""Full-night retrospective Diagnosis v2: deduped swing patterns and causal blame."""
from __future__ import annotations
import argparse, collections, hashlib, json, math, subprocess, sys, time
from pathlib import Path
import shogi

FIELDS=("material","safety","pressure","activity","danger","clamp","total")
def cname(c): return "black" if c==shogi.BLACK else "white"
def sign(c): return 1 if c==shogi.BLACK else -1
def nsfen(s): return " ".join(s.split()[:3])
def sid(p,s): return p+hashlib.sha256(s.encode()).hexdigest()[:20]
def winner_color(g):
    w=g.get("winner")
    if w not in ("A","B"): return None
    ab=bool(g.get("a_black"))
    return (shogi.BLACK if ab else shogi.WHITE) if w=="A" else (shogi.WHITE if ab else shogi.BLACK)
def elabel(g,c): return "A" if ((c==shogi.BLACK)==bool(g.get("a_black"))) else "B"

class Engine:
    def __init__(self,path,opts):
        self.p=subprocess.Popen([path],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.i,self.o=self.p.stdin,self.p.stdout
        self.send("usi"); self.wait("usiok")
        for k,v in opts.items(): self.send(f"setoption name {k} value {str(v).lower() if isinstance(v,bool) else v}")
        self.send("isready"); self.wait("readyok")
    def send(self,s,flush=True):
        self.i.write(s+"\n")
        if flush:self.i.flush()
    def wait(self,p):
        while 1:
            x=self.o.readline()
            if x=="": raise RuntimeError("engine exited")
            x=x.rstrip()
            if x.startswith(p): return x
    def evals(self,sfens):
        for s in sfens:self.send("position sfen "+s,False);self.send("eval",False)
        self.i.flush();out=[]
        while len(out)<len(sfens):
            x=self.o.readline()
            if x=="":raise RuntimeError("engine exited")
            if not x.startswith("info string evaluation "):continue
            q=x.split();r={}
            for n in FIELDS:
                try:r[n]=int(q[q.index(n)+1])
                except:pass
            out.append(r)
        return out
    def search(self,sfen,ms):
        self.send("position sfen "+sfen);self.send(f"go movetime {ms}")
        r={"bestmove":None,"score":None,"depth":None,"nodes":None,"time_ms":None,"stats":{}}
        while 1:
            x=self.o.readline()
            if x=="":raise RuntimeError("engine exited")
            x=x.rstrip();q=x.split()
            if x.startswith("bestmove "):r["bestmove"]=q[1] if len(q)>1 else None;return r
            if not x.startswith("info "):continue
            if "score" in q:
                try:
                    j=q.index("score");k=q[j+1];v=int(q[j+2]);r["score"]=v if k=="cp" else (1 if v>=0 else -1)*(100000000-min(abs(v),999999))
                except:pass
            for k,d in (("depth","depth"),("nodes","nodes"),("time","time_ms")):
                if k in q:
                    try:r[d]=int(q[q.index(k)+1])
                    except:pass
            if "string" in q:
                t=q[q.index("string")+1:]
                for j in range(0,len(t)-1,2):
                    try:r["stats"][t[j]]=int(t[j+1])
                    except:pass
    def close(self):
        if self.p.poll() is None:
            try:self.send("quit");self.p.wait(timeout=5)
            except:self.p.kill()

def games(root):
    for p in sorted(root.rglob("*.json")):
        try:d=json.loads(p.read_text())
        except:continue
        for i,g in enumerate(d.get("details",[])):
            if isinstance(g.get("moves"),list):yield p,i,g

def replay(moves):
    b=shogi.Board();sf=[b.sfen()];actors=[]
    for ply,t in enumerate(moves,1):
        m=shogi.Move.from_usi(t)
        if m not in b.legal_moves:raise ValueError(f"illegal {ply} {t}")
        actors.append(b.turn);b.push(m);sf.append(b.sfen())
    return sf,actors

def swings(ev,h,thr):
    v=[x["total"] for x in ev];raw=[]
    for a in range(len(v)-1):
        best=None
        for b in range(a+1,min(len(v),a+h+1)):
            d=v[b]-v[a]
            if abs(d)>=thr and (best is None or abs(d)>abs(best[1])):best=(b,d)
        if best:raw.append({"start":a,"end":best[0],"delta_black":best[1]})
    out=[]
    for x in raw:
        sg=1 if x["delta_black"]>0 else -1
        if out and x["start"]<=out[-1]["end"] and sg==(1 if out[-1]["delta_black"]>0 else -1):
            if abs(x["delta_black"])>abs(out[-1]["delta_black"]):out[-1]=x
        else:out.append(x)
    return out

def aggregate(rows):
    g={}
    for r in rows:
        z=g.setdefault(r["pattern_id"],{"rep":r,"n":0,"surprises":0,"sources":[]});z["n"]+=1;z["surprises"]+=int(r["surprise"])
        if len(z["sources"])<8:z["sources"].append({"file":r["source_file"],"game":r["game_index"]})
        if abs(r["delta_black"])>abs(z["rep"]["delta_black"]):z["rep"]=r
    out=[]
    for pid,z in g.items():
        r=dict(z["rep"]);r["occurrences"]=z["n"];r["surprise_count"]=z["surprises"];r["source_examples"]=z["sources"]
        r["priority"]=abs(r["delta_black"])+(250 if r["surprise"] else 0)+min(1000,int(120*math.log2(1+z["n"])))
        out.append(r)
    return out

def blame(actor,gainer,played,dg,st,sp,so,dp,do,a):
    dplayed=-do["score"] if do.get("score") is not None else None;splayed=-so["score"] if so.get("score") is not None else None
    dl=dp.get("score")-dplayed if dp.get("score") is not None and dplayed is not None else None
    sl=sp.get("score")-splayed if sp.get("score") is not None and splayed is not None else None
    tags=[]
    if sp.get("bestmove")!=dp.get("bestmove"):tags.append("bestmove-disagreement")
    if sp.get("score") is not None and dp.get("score") is not None and abs(sp["score"]-dp["score"])>=a.score_gap:tags.append("shallow-deep-score-gap")
    if dp.get("score") is not None and abs(st["total"]*sign(actor)-dp["score"])>=a.score_gap:tags.append("static-search-gap")
    if dl is not None and dl>=a.blunder_threshold:
        tags.append("deep-blunder")
        if actor!=gainer:
            tags.append("opponent-mistake")
            if dg<a.move_signal:tags.append("latent-opponent-mistake")
    if dg>=a.move_signal:
        if actor==gainer:
            if dl is not None and dl<=a.good_tolerance:tags.append("gainer-good-move")
            elif dl is not None and dl>=a.blunder_threshold:tags.append("static-overreaction")
            else:tags.append("gainer-move-uncertain")
        elif dl is not None and dl<=a.good_tolerance:tags.append("forced-concession")
        elif dl is None or dl<a.blunder_threshold:tags.append("opponent-move-uncertain")
    if sp.get("bestmove")==played and dp.get("bestmove")!=played and dl is not None and dl>=a.blunder_threshold:tags.append("search-horizon-candidate")
    if "static-search-gap" in tags or "static-overreaction" in tags:tags.append("evaluation-candidate")
    if any(x in tags for x in ("bestmove-disagreement","shallow-deep-score-gap","search-horizon-candidate")):tags.append("search-insufficiency-candidate")
    return {"static_delta_toward_gainer":dg,"shallow_loss":sl,"deep_loss":dl,"deep_bestmove_matches_played":dp.get("bestmove")==played,"tags":sorted(set(tags))}

def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
def jl(p,rows):p.parent.mkdir(parents=True,exist_ok=True);p.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows))
def avg(x):return sum(x)/len(x) if x else None

def main():
    q=argparse.ArgumentParser();q.add_argument("--input",required=True);q.add_argument("--engine",required=True);q.add_argument("--output-dir",required=True)
    q.add_argument("--expected-games",type=int,default=0);q.add_argument("--expected-plies",type=int,default=0);q.add_argument("--max-window-plies",type=int,default=4);q.add_argument("--swing-threshold",type=int,default=300);q.add_argument("--deep-intervals",type=int,default=300)
    q.add_argument("--shallow-ms",type=int,default=50);q.add_argument("--deep-ms",type=int,default=500);q.add_argument("--move-signal",type=int,default=100);q.add_argument("--blunder-threshold",type=int,default=150);q.add_argument("--good-tolerance",type=int,default=80);q.add_argument("--score-gap",type=int,default=200)
    q.add_argument("--experience-file",default="");q.add_argument("--learning-ms",type=int,default=500);q.add_argument("--warm-verify",type=int,default=100);a=q.parse_args()
    root=Path(a.input);out=Path(a.output_dir);gs=list(games(root));plies=sum(len(g["moves"]) for _,_,g in gs)
    if a.expected_games and len(gs)!=a.expected_games:raise SystemExit(f"games {len(gs)} != {a.expected_games}")
    if a.expected_plies and plies!=a.expected_plies:raise SystemExit(f"plies {plies} != {a.expected_plies}")
    e=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":False});raw=[];invalid=0;posn=0;reasons=collections.Counter();t0=time.monotonic()
    try:
        for n,(p,gi,g) in enumerate(gs,1):
            try:sf,actors=replay(g["moves"]);ev=e.evals(sf)
            except Exception as ex:invalid+=1;print("invalid",p.name,gi,ex,file=sys.stderr);continue
            posn+=len(sf);reasons[str(g.get("reason"))]+=1;rel=str(p.relative_to(root));wc=winner_color(g)
            for s in swings(ev,a.max_window_plies,a.swing_threshold):
                gain=shogi.BLACK if s["delta_black"]>0 else shogi.WHITE;endadv=ev[s["end"]]["total"]*sign(gain);sur=wc is not None and wc!=gain and endadv>=max(500,a.swing_threshold)
                line=g["moves"][s["start"]:s["end"]];sk=nsfen(sf[s["start"]]);pid=sid("pat-",sk+"|"+" ".join(line));iid=sid("sw-",f"{rel}:{gi}:{s['start']}:{s['end']}:{s['delta_black']}")
                raw.append({"interval_id":iid,"pattern_id":pid,"start_sfen_key":sk,"line_moves":line,"source_file":rel,"game_index":gi,"start_ply":s["start"],"end_ply":s["end"],"length_plies":s["end"]-s["start"],"delta_black":s["delta_black"],"gainer_color":cname(gain),"gainer_engine":elabel(g,gain),"start_total":ev[s["start"]]["total"],"end_total":ev[s["end"]]["total"],"winner":g.get("winner"),"reason":g.get("reason"),"surprise":sur})
            if n%200==0 or n==len(gs):print(json.dumps({"games":n,"positions":posn,"raw_swings":len(raw),"seconds":round(time.monotonic()-t0,1)}))
    finally:e.close()
    pats=aggregate(raw);selected=sorted(pats,key=lambda r:(-r["priority"],-r["occurrences"],-abs(r["delta_black"]),r["pattern_id"]))[:a.deep_intervals]
    scan={"games":len(gs),"valid_games":len(gs)-invalid,"invalid_games":invalid,"plies":plies,"positions_evaluated":posn,"max_window_plies":a.max_window_plies,"swing_threshold":a.swing_threshold,"swing_intervals":len(raw),"unique_swing_patterns":len(pats),"game_reasons":dict(reasons)}
    dump(out/"scan-summary.json",scan);jl(out/"swings-all.jsonl",raw);jl(out/"swing-patterns.jsonl",pats);dump(out/"selected-intervals.json",selected)
    e=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":False});fc={};sc={};deep=[];pm={};posmap={};causes=collections.Counter();tc=collections.Counter()
    def sr(s,ms):
        k=(nsfen(s),ms)
        if k not in sc:sc[k]=e.search(s,ms)
        return sc[k]
    try:
        for ix,it in enumerate(selected,1):
            rel=it["source_file"]
            if rel not in fc:fc[rel]=json.loads((root/rel).read_text())
            g=fc[rel]["details"][it["game_index"]];mv=g["moves"];sf,actors=replay(mv);st,en=it["start_ply"],it["end_ply"];ev=e.evals(sf[st:en+1]);gain=shogi.BLACK if it["gainer_color"]=="black" else shogi.WHITE;wc=winner_color(g)
            md=[];own=opp=forced=unc=False
            for li,ply in enumerate(range(st+1,en+1),1):
                actor=actors[ply-1];played=mv[ply-1];pre,post=sf[ply-1],sf[ply];sp,so,dp,do=sr(pre,a.shallow_ms),sr(post,a.shallow_ms),sr(pre,a.deep_ms),sr(post,a.deep_ms);dg=(ev[li]["total"]-ev[li-1]["total"])*sign(gain);c=blame(actor,gain,played,dg,ev[li-1],sp,so,dp,do,a);tags=c["tags"]
                if wc is not None and actor!=wc and c.get("deep_loss") is not None and c["deep_loss"]>=a.blunder_threshold:tags=sorted(set(tags+["loss-move-candidate"]))
                own|="gainer-good-move" in tags;opp|="opponent-mistake" in tags;forced|="forced-concession" in tags;unc|=any(x.endswith("uncertain") for x in tags);tc.update(tags)
                z={"ply":ply,"actor_color":cname(actor),"actor_engine":elabel(g,actor),"played":played,"pre_sfen":pre,"post_sfen":post,"static_pre":ev[li-1],"static_post":ev[li],"shallow_pre":sp,"shallow_post":so,"deep_pre":dp,"deep_post":do,**c,"tags":tags};md.append(z)
                keep={"opponent-mistake","latent-opponent-mistake","gainer-good-move","deep-blunder","loss-move-candidate","search-horizon-candidate","search-insufficiency-candidate","evaluation-candidate","static-overreaction","static-search-gap","bestmove-disagreement"};pt=sorted(set(tags)&keep)
                if pt:
                    pid=sid("pr-",nsfen(pre)+":"+played);r={"id":pid,"interval_id":it["interval_id"],"pattern_id":it["pattern_id"],"pattern_occurrences":it["occurrences"],"source":{"file":rel,"game":it["game_index"],"ply":ply},"sfen":pre,"side_to_move":cname(actor),"played_move":played,"deep_bestmove":dp.get("bestmove"),"deep_loss":c.get("deep_loss"),"tags":pt,"static":ev[li-1],"shallow":sp,"deep":dp,"winner":g.get("winner"),"final_reason":g.get("reason")}
                    if pid not in pm or abs(r.get("deep_loss") or 0)>abs(pm[pid].get("deep_loss") or 0):pm[pid]=r
                    po=sid("pos-",nsfen(pre));pr={"id":po,"sfen":pre,"side_to_move":cname(actor),"tags":sorted(set(pt+["eval-swing"])),"source":r["source"],"pattern_occurrences":it["occurrences"],"static":ev[li-1],"shallow":sp,"deep":dp,"played_move":played,"deep_loss":c.get("deep_loss"),"final_result":g.get("winner"),"use_count":0,"last_used":None}
                    if po not in posmap or abs(pr.get("deep_loss") or 0)>abs(posmap[po].get("deep_loss") or 0):posmap[po]=pr
            cause="mixed-good-move-and-opponent-mistake" if own and opp else "opponent-mistake" if opp else "gainer-good-move" if own else "forced-concession-or-pressure" if forced else "uncertain" if unc else "unresolved";causes[cause]+=1;deep.append({**it,"cause":cause,"moves":md})
            if ix%25==0 or ix==len(selected):print(json.dumps({"deep":ix,"problems":len(pm)}))
    finally:e.close()
    probs=sorted(pm.values(),key=lambda r:(-r.get("pattern_occurrences",1),-abs(r.get("deep_loss") or 0),r["id"]));poss=sorted(posmap.values(),key=lambda r:(-r.get("pattern_occurrences",1),-abs(r.get("deep_loss") or 0),r["id"]));jl(out/"problem-suite.jsonl",probs);jl(out/"position-bank.jsonl",poss);dump(out/"deep-diagnosis.json",{"intervals":len(deep),"problem_positions":len(probs),"details":deep})
    learning={"enabled":False};exp=Path(a.experience_file) if a.experience_file else None
    if exp and poss:
        exp.parent.mkdir(parents=True,exist_ok=True);le=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":True,"ExperienceFile":str(exp)})
        try:
            for r in poss:le.search(r["sfen"],a.learning_ms)
        finally:le.close()
        verify=poss[:a.warm_verify];cold={nsfen(r["sfen"]):r["shallow"] for r in poss};warm=[]
        if verify:
            we=Engine(a.engine,{"OpeningBook":False,"ExperienceCache":True,"ExperienceFile":str(exp)})
            try:warm=[we.search(r["sfen"],a.shallow_ms) for r in verify]
            finally:we.close()
        cn=[];wn=[];ct=[];wt=[];same=hits=probes=0
        for r,w in zip(verify,warm):
            c=cold[nsfen(r["sfen"])]
            if c.get("nodes") is not None and w.get("nodes") is not None:cn.append(c["nodes"]);wn.append(w["nodes"])
            if c.get("time_ms") is not None and w.get("time_ms") is not None:ct.append(c["time_ms"]);wt.append(w["time_ms"])
            same+=c.get("bestmove")==w.get("bestmove");hits+=w["stats"].get("experience_hits",0);probes+=w["stats"].get("experience_probes",0)
        red=lambda x,y:None if not x or not y or avg(x)==0 else 1-avg(y)/avg(x)
        learning={"enabled":True,"positions_learned":len(poss),"learning_ms":a.learning_ms,"warm_verify_positions":len(verify),"warm_bestmove_matches_cold":same,"warm_experience_hits":hits,"warm_experience_probes":probes,"warm_hit_rate":hits/probes if probes else None,"cold_nodes_mean":avg(cn),"warm_nodes_mean":avg(wn),"nodes_reduction":red(cn,wn),"cold_time_ms_mean":avg(ct),"warm_time_ms_mean":avg(wt),"time_reduction":red(ct,wt)};dump(out/"experience-learning.json",learning)
    summary={"schema_version":2,"scan":scan,"deep":{"selected_patterns":len(selected),"causes":dict(causes),"diagnosis_tags":dict(tc),"problem_positions":len(probs),"position_bank_records":len(poss),"shallow_ms":a.shallow_ms,"deep_ms":a.deep_ms},"experience":learning};dump(out/"summary.json",summary)
    lines=["# 6,520局 遡及Diagnosis v2","",f"- 対象局数: {scan['games']}",f"- 対象手数: {scan['plies']}",f"- 評価局面数: {scan['positions_evaluated']}",f"- 急変区間: {scan['swing_intervals']}",f"- 重複集約後パターン: {scan['unique_swing_patterns']}",f"- 深掘り固有パターン: {len(selected)}","","## 原因"]+[f"- {k}: {v}" for k,v in causes.most_common()]+["","## Diagnosis"]+[f"- {k}: {v}" for k,v in tc.most_common()]+["","## Experience",f"- 学習局面: {learning.get('positions_learned',0)}",f"- warm hit率: {learning.get('warm_hit_rate')}",f"- nodes削減率: {learning.get('nodes_reduction')}",f"- 実時間削減率: {learning.get('time_reduction')}",f"- cold/warm bestmove一致: {learning.get('warm_bestmove_matches_cold')}/{learning.get('warm_verify_positions')}"]
    (out/"report.md").write_text("\n".join(lines)+"\n");print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__":main()
