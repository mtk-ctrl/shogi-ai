#!/usr/bin/env python3
"""For each big-drop position (KUMOJI to move, before its move), search with a
config and report whether KUMOJI now avoids the played move or foresees the drop.
'foresees' = score <= eval_before - half of the drop (own later eval as reference)."""
import argparse, csv, subprocess, concurrent.futures as cf, collections
def run(engine, opts, sfen, ms):
    cmds = ["usi","setoption name SearchThreads value 1","setoption name OpeningRandomNonLance value false",
            "setoption name PositionKnowledge value false","setoption name AdaptiveLongThink value false",
            "setoption name USI_Ponder value false","setoption name MateAssist value false"]
    cmds += [f"setoption name {k} value {v}" for k, v in opts]
    cmds += ["isready","usinewgame",f"position sfen {sfen}",f"go movetime {ms}"]
    p = subprocess.Popen([engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    p.stdin.write("\n".join(cmds)+"\n"); p.stdin.flush()
    score=depth=None; best=None
    for line in p.stdout:
        t=line.split()
        if t[:1]==["info"] and "score" in t and "depth" in t:
            depth=int(t[t.index("depth")+1]); k=t[t.index("score")+1]; v=int(t[t.index("score")+2])
            score=v if k=="cp" else (30000 if v>0 else -30000)
        if t[:1]==["bestmove"]: best=t[1]; break
    p.stdin.write("quit\n"); p.stdin.flush(); p.wait()
    return best, score, depth
ap=argparse.ArgumentParser(); ap.add_argument("engine"); ap.add_argument("set"); ap.add_argument("--ms",type=int,default=500)
ap.add_argument("--opt",action="append",default=[]); ap.add_argument("--jobs",type=int,default=2); ap.add_argument("--label",default="")
a=ap.parse_args(); opts=[o.split("=",1) for o in a.opt]
rows=list(csv.DictReader(open(a.set),delimiter="\t"))
with cf.ThreadPoolExecutor(a.jobs) as ex: res=list(ex.map(lambda r: run(a.engine,opts,r["sfen"],a.ms),rows))
C=collections.Counter(); K=collections.defaultdict(lambda:[0,0]); dsum=0
for r,(b,s,d) in zip(rows,res):
    eb,ea=int(r["eval_before"]),int(r["eval_after"])
    avoid=b!=r["played"]; fore=s is not None and s<=eb-(eb-ea)/2
    ok=avoid or fore; C["changed_move"]+=avoid; C["foresees"]+=fore; C["either"]+=ok; dsum+=d or 0
    kind=r["reply_kind"].split("+")[0]; K[kind][0]+=1; K[kind][1]+=ok
print(f"{a.label} ms={a.ms} n={len(rows)} changed={C['changed_move']} foresees={C['foresees']} either={C['either']} avg_depth={dsum/len(rows):.1f} by_reply="+" ".join(f"{k}:{v[1]}/{v[0]}" for k,v in sorted(K.items())))
