import json,re,statistics as st
from probe import *
g=json.load(open("games.json"))
pos=[]
for gi,m in enumerate(g):
    for ply in range(12,len(m)-2,6): pos.append((gi,ply,m[:ply]))
opts={"AdaptiveLongThink":"false","USI_Ponder":"false","PositionKnowledge":"false","SearchThreads":"1"}
e=E(opts)
rows=[]
for gi,ply,mv in pos:
    r={"g":gi,"ply":ply}
    for ms in (200,1000):
        lines,dt=e.go(mv,f"go movetime {ms}")
        d=parse(lines)
        ph=[l for l in lines if l.startswith("info string phase")][0]
        mat=int(re.search(r"maturity (\d+)",ph).group(1)); sb=int(re.search(r"static_cp_black (-?\d+)",ph).group(1))
        stm=1 if ply%2==0 else -1
        r["mat"]=mat; r["static"]=sb*stm
        # per-depth scores
        ds=[(int(m.group(1)),int(m.group(2))) for l in lines for m in [re.match(r"info depth (\d+) .*score cp (-?\d+)",l)] if m]
        r[f"d{ms}"]=d.get("depth"); r[f"s{ms}"]=d.get("score"); r[f"b{ms}"]=d["best"]; r[f"n{ms}"]=d.get("nodes"); r[f"q{ms}"]=d.get("qnodes"); r[f"ql{ms}"]=d.get("qlimit_leaves"); r[f"ttp{ms}"]=d.get("tt_probes"); r[f"tth{ms}"]=d.get("tt_hits"); r[f"ds{ms}"]=ds
        r[f"ech{ms}"]=d.get("eval_cache_hits"); r[f"lv{ms}"]=d.get("leaves")
    rows.append(r); print(r["g"],r["ply"],r["mat"],r["static"],r["d200"],r["s200"],r["d1000"],r["s1000"],r["b200"]==r["b1000"],r["n200"],r["q200"],flush=True)
e.quit()
json.dump(rows,open("rows.json","w"))
