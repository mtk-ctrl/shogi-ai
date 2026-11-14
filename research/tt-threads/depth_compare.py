"""固定深さで2設定を比べる（手・評価値・節点数・時間）。使い方:
python3 depth_compare.py ENGINE_A "optA" ENGINE_B "optB" DEPTH [STEP]
optは "Name=Value,Name=Value"。局面は games.json（自己対局の着手列）から STEP 手ごと。"""
import sys, json, re, time
sys.path.insert(0, "../plan-20261110")
import probe
def opts(s):
    d={"AdaptiveLongThink":"false","USI_Ponder":"false","PositionKnowledge":"false","SearchThreads":"1"}
    for kv in filter(None,s.split(",")):
        k,v=kv.split("="); d[k]=v
    return d
def run(engine, optstr, depth, step):
    probe.ENG=engine
    e=probe.E(opts(optstr)); rows=[]
    games=json.load(open("games.json"))
    for gi,m in enumerate(games):
        for ply in range(8,len(m)-2,step):
            t=time.time(); lines,dt=e.go(m[:ply],f"go depth {depth}"); d=probe.parse(lines)
            rows.append(dict(g=gi,ply=ply,best=d["best"],score=d.get("score"),nodes=d.get("nodes",0),dt=dt,
                tt_probes=d.get("tt_probes",0),tt_hits=d.get("tt_hits",0),tt_exact=d.get("tt_exact_hits",0),tt_cut=d.get("tt_bound_cutoffs",0)))
    e.quit(); return rows
if __name__=="__main__":
    ea,oa,eb,ob,depth=sys.argv[1:6]; step=int(sys.argv[6]) if len(sys.argv)>6 else 4
    A=run(ea,oa,int(depth),step); B=run(eb,ob,int(depth),step)
    n=len(A); same=sum(a["best"]==b["best"] for a,b in zip(A,B))
    big=sum(abs((a["score"] or 0)-(b["score"] or 0))>=100 for a,b in zip(A,B))
    f=lambda R,k:sum(r[k] for r in R)
    print(f"局面{n} 深さ{depth}  手が同じ {same}/{n}  評価値が100以上違う {big}")
    for lab,R in (("A",A),("B",B)):
        print(f" {lab}: 節点 {f(R,'nodes')}  時間 {f(R,'dt'):.1f}s  TT照会 {f(R,'tt_probes')} 命中 {f(R,'tt_hits')} 打切り(正確{f(R,'tt_exact')}+境界{f(R,'tt_cut')})")
    print(f" 節点比 B/A {f(B,'nodes')/f(A,'nodes'):.3f}  時間比 B/A {f(B,'dt')/f(A,'dt'):.3f}")
