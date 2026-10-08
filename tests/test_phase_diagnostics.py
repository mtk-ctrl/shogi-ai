#!/usr/bin/env python3
"""Diagnostic-only stage classifier and exclusions from the source game set."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.phase.analyze_games import entered_camp, select_games, analyze, run_probe
import json

engine=Path(sys.argv[1]).resolve()

def run(commands):
    p=subprocess.run([str(engine)],input="\n".join(commands)+"\n",
                     capture_output=True,text=True,check=True,timeout=20)
    return p.stdout.strip().splitlines()

start=run(["position startpos"])[0]
def parse(line):
    parts=line.split()
    assert parts[0]=="phase"
    return dict(zip(parts[1::2],map(int,parts[2::2])))
zero=parse(start)
assert set(zero)=={"development","battle","invasion","king_threat","progress"}
assert all(v==0 for v in zero.values()),zero
partial=parse(run(["position startpos moves 7g7f 3c3d"])[0])
assert partial["development"]>0,(zero,partial)
assert partial["king_threat"]==0,partial
# Swapping turns on an identical static position cannot change progress.
same=run(["position startpos","position sfen "+(
    "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL w - 1")])
assert same[0]==same[1],same

assert not entered_camp("lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1")
assert entered_camp("4K4/9/9/9/9/9/9/9/4k4 b - 1")
assert entered_camp("4k4/9/9/9/9/9/9/9/4K4 w - 1") is False
fake=[
 {"winner":None,"reason":"move_limit","moves":[]},
 {"winner":"A","reason":"declare_win","moves":[]},
 {"winner":"B","reason":"checkmate","start_sfen":"4K4/9/9/9/9/9/9/9/4k4 b - 1","moves":[]},
 {"winner":"A","reason":"checkmate","moves":["7g7f","3c3d"]},
]
kept,excluded=select_games(fake)
assert len(kept)==1,(len(kept),excluded)
assert excluded["draw"]==1 and excluded["entering_king"]==2,excluded

# Fixed prior real matches are a diagnostic sample, not current-engine matches.
data_path=ROOT/"benchmarks/results/2026-10-05_v019-mate-assist-50ms-100games.json"
report=analyze(data_path,engine)
assert report["games_input"]==100
assert report["games_analyzed"]+sum(report["excluded"].values())==100
assert report["excluded"]["draw"]>=1
assert report["positions_measured"]>100
assert report["at_10_ply_intervals"][0]["development"]==0
assert report["at_10_ply_intervals"][0]["progress"]==0
assert all(0<=row[name]<=100 for row in report["at_10_ply_intervals"]
           for name in ("development","battle","invasion","king_threat","progress"))
print("PASS independent phase probe, beginning=0, board/turn invariance, all-game draw and entering-king exclusion")
print("PASS historical game sample "+json.dumps({
    k:report[k] for k in ("games_input","games_analyzed","excluded","positions_measured")
},ensure_ascii=False))
