import json,sys,os,time
sys.path.insert(0,"/home/claude/shogi-ai/benchmarks")
import agreement_probe as ap
S="/tmp/claude-0/-home-claude/daa93b49-7eb9-5254-868e-711dce0f5bf1/scratchpad"
pos=json.load(open("/home/claude/shogi-ai/benchmarks/agreement/positions-v1.json"))["positions"][::4]
opts={"SearchThreads":1,"PositionKnowledge":False,"AdaptiveLongThink":False,"USI_Ponder":False,"SearchEfficiencyMask":56}
DEPTH=int(os.environ.get("QDEPTH","5"))
def run(env):
    for k in ("QLOSE","QMARGIN","QMINPLY","QKING"): os.environ.pop(k,None)
    os.environ.update(env)
    e=ap.Engine(S+"/kumoji_q",opts); rows=[]; t=0
    for p in pos:
        e.send("position startpos moves "+" ".join(p["moves"])); t0=time.time(); e.send(f"go depth {DEPTH}")
        L=e.wait("bestmove",300); t+=time.time()-t0
        nodes=[int(l.split()[2]) for l in L if l.startswith("info nodes")][-1]
        sc=[l for l in L if l.startswith(f"info depth {DEPTH}") and " score cp " in l]
        sc=int(sc[-1].split(" score cp ")[1].split()[0]) if sc else None
        rows.append((L[-1].split()[1],sc,nodes))
    e.close(); return rows,t
base,tb=run({})
print(f"baseline nodes {sum(r[2] for r in base)} time {tb:.1f}s",flush=True)
cfgs=json.loads(sys.argv[1])
for name,env in cfgs.items():
    rows,t=run(env)
    n=sum(r[2] for r in rows)
    same=sum(a[0]==b[0] for a,b in zip(base,rows))
    sc=[abs(a[1]-b[1]) for a,b in zip(base,rows) if a[1] is not None and b[1] is not None]
    big=sum(x>=100 for x in sc)
    print(f"{name:28s} nodes {n/sum(r[2] for r in base):.2f}x time {t/tb:.2f}x  same move {same}/{len(pos)}  |dscore|>=100: {big}  median {sorted(sc)[len(sc)//2]}",flush=True)
