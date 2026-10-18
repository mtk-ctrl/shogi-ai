"""Same-binary paired check: static-search sorting allocation removal, never pruning."""
import json,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmarks.arena import Engine
import shogi
binary=sys.argv[1]
rows=json.loads(Path("research/search-efficiency3-20261015/positions.json").read_text())["rows"][:24]
assert len(rows)==24
options={"SearchThreads":1,"OpeningRandomNonLance":False,"MateAssist":False,
         "MateLearning":False,"AdaptiveLongThink":False,"PositionKnowledge":True,
         "USI_Ponder":False}
engines={
    "baseline":Engine(binary,"qsort-old",{**options,"SearchResearchMask":23}),
    "inplace":Engine(binary,"qsort-inplace",{**options,"SearchResearchMask":55}),
}
data=[]
try:
    for mode,command in (("fixed","go depth 2"),("timed","go movetime 200")):
        for n,row in enumerate(rows):
            game_moves=row["moves"]
            results={}
            order=("baseline","inplace") if n%2==0 else ("inplace","baseline")
            for k in order:
                e=engines[k]
                e.configure_game(2026101601+n)
                e.go_command=command
                move=e.bestmove(game_moves)
                info=dict(e.last_search)
                board=shogi.Board()
                for prev in game_moves:board.push_usi(prev)
                assert shogi.Move.from_usi(move) in board.legal_moves
                for pv in info.get("pv",[]):
                    assert shogi.Move.from_usi(pv) in board.legal_moves,(k,n,pv)
                    board.push_usi(pv)
                results[k]={"move":move,**info}
            data.append({"type":mode,"index":n,"results":results})
finally:
    for e in engines.values():e.close()
fixed=[r for r in data if r["type"]=="fixed"]
timed=[r for r in data if r["type"]=="timed"]
fingerprint=("move","score_cp","score_mate","depth","nodes","qnodes","cutoffs","pv")
mismatches=[(r["index"],[k for k in fingerprint if r["results"]["baseline"].get(k)!=r["results"]["inplace"].get(k)]) for r in fixed]
mismatches=[x for x in mismatches if x[1]]
speed=[r["results"]["baseline"]["elapsed_ms"]/max(.01,r["results"]["inplace"]["elapsed_ms"]) for r in fixed]
t_speed=[r["results"]["baseline"]["elapsed_ms"]/max(.01,r["results"]["inplace"]["elapsed_ms"]) for r in timed]
out={"samples":len(rows),"fixed_mismatches":mismatches,
     "fixed_median_speed":statistics.median(speed),
     "fixed_total_speed":sum(r["results"]["baseline"]["elapsed_ms"] for r in fixed)/sum(r["results"]["inplace"]["elapsed_ms"] for r in fixed),
     "timed_median_time_ratio":statistics.median(t_speed),
     "timed_total_nodes":{k:sum(r["results"][k].get("nodes",0) for r in timed) for k in engines},
     "timed_complete_depth":{k:sum(r["results"][k].get("depth",0) for r in timed) for k in engines}}
print("QSORT BENCH",json.dumps(out,ensure_ascii=False))
Path("build/qsort-benchmark.json").write_text(json.dumps({"summary":out,"rows":data},ensure_ascii=False,indent=2)+"\n")
assert not mismatches,"semantics changed by the pure ordering allocation optimization"
