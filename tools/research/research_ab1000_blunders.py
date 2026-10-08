#!/usr/bin/env python3
import argparse,gzip,json,queue,subprocess,threading,time,zipfile
from pathlib import Path

def extract(inp,out,limit=40):
    zips=list(Path(inp).rglob("*.zip"))
    if zips:
        with zipfile.ZipFile(zips[0]) as z: raw=z.read("played-games.jsonl.gz")
        import io
        fh=gzip.GzipFile(fileobj=io.BytesIO(raw))
    else:
        p=next(Path(inp).rglob("played-games.jsonl.gz")); fh=gzip.open(p,"rb")
    cand=[]
    for line in fh:
        g=json.loads(line); moves=g["moves"]; prefix=[]
        for i,m in enumerate(moves[:-1]):
            s=m.get("search",{}); n=moves[i+1].get("search",{})
            a=s.get("score_cp_stm"); b=n.get("score_cp_stm")
            if isinstance(a,(int,float)) and isinstance(b,(int,float)) and s.get("score_status")=="recorded" and n.get("score_status")=="recorded":
                after=-b; loss=a-after
                if loss>=500 and abs(a)<=1500 and abs(after)<=5000 and g.get("winner") is not None:
                    cand.append({"moves":list(prefix),"original_move":m["move"],"observed_loss_cp":loss,"before_cp":a,"after_cp":after,"engine":m["engine"],"game_id":g["game_id"],"ply":m["ply"],"winner":g["winner"]})
            prefix.append(m["move"])
    cand.sort(key=lambda x:x["observed_loss_cp"],reverse=True)
    chosen=[]; seen=set(); count={"A":0,"B":0}
    for target in ("A","B"):
        for x in cand:
            k=tuple(x["moves"])
            if x["engine"]!=target or k in seen: continue
            chosen.append(x); seen.add(k); count[target]+=1
            if count[target]>=limit//2: break
    chosen.sort(key=lambda x:x["observed_loss_cp"],reverse=True)
    for i,x in enumerate(chosen): x["id"]=f"ab1000-drop-{i+1:02d}"
    Path(out).write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in chosen),encoding="utf-8")
    print(json.dumps({"selected":len(chosen),"A":count["A"],"B":count["B"],"min_loss":min(x["observed_loss_cp"] for x in chosen)},ensure_ascii=False))

class Usi:
    def __init__(self,path,knowledge):
        self.p=subprocess.Popen([path],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.q=queue.Queue(); threading.Thread(target=self._read,daemon=True).start()
        self.send("usi"); self.wait("usiok",10)
        opts={"OpeningBook":False,"ExperienceCache":False,"AdaptiveLongThink":False,"PositionKnowledge":True,"PositionKnowledgeFile":knowledge}
        for k,v in opts.items(): self.send(f"setoption name {k} value {str(v).lower() if isinstance(v,bool) else v}")
        self.send("isready"); self.wait("readyok",10)
    def _read(self):
        for line in self.p.stdout:self.q.put(line.rstrip())
    def send(self,s): self.p.stdin.write(s+"\n"); self.p.stdin.flush()
    def wait(self,prefix,timeout):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=self.q.get(timeout=max(.01,end-time.monotonic()))
            if line.startswith(prefix): return line
        raise TimeoutError(prefix)
    def search(self,moves,ms):
        self.send("usinewgame"); self.send("isready"); self.wait("readyok",10)
        self.send("position startpos"+((" moves "+" ".join(moves)) if moves else ""))
        self.send(f"go movetime {ms}")
        start=time.monotonic(); last={}; checkpoints={}; changes=[]; last_pv_move=None
        targets=[300000,1200000,ms]
        while True:
            line=self.q.get(timeout=max(30,ms/1000+60))
            if line.startswith("info "):
                p=line.split(); cur={}
                for key in ("depth","seldepth","nodes","time"):
                    if key in p:
                        try: cur[key]=int(p[p.index(key)+1])
                        except: pass
                if "score" in p:
                    try:
                        i=p.index("score"); cur["score_kind"]=p[i+1]; cur["score_value"]=int(p[i+2])
                    except: pass
                if "pv" in p:
                    cur["pv"]=p[p.index("pv")+1:]
                    if cur["pv"]:
                        mv=cur["pv"][0]
                        if mv!=last_pv_move:
                            changes.append({"elapsed_ms":int((time.monotonic()-start)*1000),"move":mv,"depth":cur.get("depth"),"score_kind":cur.get("score_kind"),"score_value":cur.get("score_value")})
                            last_pv_move=mv
                if cur: last.update(cur)
                elapsed=int((time.monotonic()-start)*1000)
                for t in targets:
                    if t<=ms and elapsed>=t and str(t) not in checkpoints: checkpoints[str(t)]=dict(last)
            elif line.startswith("bestmove "):
                return {"bestmove":line.split()[1],"elapsed_ms":int((time.monotonic()-start)*1000),"final":last,"checkpoints":checkpoints,"pv_changes":changes}
    def close(self):
        try:self.send("quit"); self.p.wait(timeout=2)
        except:self.p.kill()

def research(engine,knowledge,candidates,lane,lanes,ms,out):
    rows=[json.loads(x) for x in Path(candidates).read_text(encoding="utf-8").splitlines() if x.strip()]
    mine=[x for i,x in enumerate(rows) if i%lanes==lane]; e=Usi(engine,knowledge); res=[]
    try:
        for x in mine:
            print("research",x["id"],"lane",lane,flush=True)
            r=e.search(x["moves"],ms); x["research"]=r; x["same_as_original"]=r["bestmove"]==x["original_move"]; res.append(x)
    finally:e.close()
    Path(out).write_text(json.dumps({"lane":lane,"results":res},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("extract"); q.add_argument("--input",required=True); q.add_argument("--output",required=True); q.add_argument("--limit",type=int,default=40)
    q=sub.add_parser("research"); q.add_argument("--engine",required=True); q.add_argument("--knowledge",required=True); q.add_argument("--candidates",required=True); q.add_argument("--lane",type=int,required=True); q.add_argument("--lanes",type=int,default=20); q.add_argument("--ms",type=int,default=3000000); q.add_argument("--output",required=True)
    a=p.parse_args()
    if a.cmd=="extract":extract(a.input,a.output,a.limit)
    else:research(a.engine,a.knowledge,a.candidates,a.lane,a.lanes,a.ms,a.output)
