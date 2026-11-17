#!/usr/bin/env python3
"""Measure how KUMOJI evaluates the advantage set (illusion vs true).

usage: measure.py ENGINE SET.tsv --depth 6 [--opt Name=Value ...] [--jobs 4]
Reports, per label: mean eval (KUMOJI view), share still >= +300, and the
separation = mean(true) - mean(illusion). A better evaluation lowers the
illusion set while keeping the true set high.
"""
import argparse, csv, subprocess, statistics, concurrent.futures as cf

def run(engine, opts, sfen, depth, movetime):
    cmds = ["usi", "setoption name SearchThreads value 1", "setoption name OpeningRandomNonLance value false",
            "setoption name PositionKnowledge value false", "setoption name AdaptiveLongThink value false",
            "setoption name USI_Ponder value false"]
    cmds += [f"setoption name {k} value {v}" for k, v in opts]
    go = f"go depth {depth}" if depth else f"go movetime {movetime}"
    cmds += ["isready", "usinewgame", f"position sfen {sfen}", "eval", go]
    p = subprocess.Popen([engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    p.stdin.write("\n".join(cmds) + "\n"); p.stdin.flush()
    static = score = None
    for line in p.stdout:
        t = line.split()
        if line.startswith("info string evaluation"):
            static = int(t[t.index("total") + 1])
        elif t[:1] == ["info"] and "score" in t and "cp" in t:
            score = int(t[t.index("cp") + 1])
        elif t[:1] == ["bestmove"]:
            break
    p.stdin.write("quit\n"); p.stdin.flush(); p.wait()
    black = sfen.split()[1] == "b"
    return (static if black else -static), score

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine"); ap.add_argument("set")
    ap.add_argument("--depth", type=int, default=6); ap.add_argument("--movetime", type=int, default=0)
    ap.add_argument("--opt", action="append", default=[]); ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dump")
    a = ap.parse_args()
    opts = [o.split("=", 1) for o in a.opt]
    rows = list(csv.DictReader(open(a.set, encoding="utf-8"), delimiter="\t"))
    depth = 0 if a.movetime else a.depth
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda r: run(a.engine, opts, r["sfen"], depth, a.movetime), rows))
    out = {}
    for lab in ("illusion", "true"):
        st = [s for r, (s, _) in zip(rows, res) if r["label"] == lab]
        sc = [max(-3000, min(3000, c)) for r, (_, c) in zip(rows, res) if r["label"] == lab and c is not None]
        out[lab] = (statistics.mean(st), statistics.mean(sc), sum(c >= 300 for c in sc) / len(sc), len(sc))
        print(f"{lab:8s} n={len(sc)} static_mean={out[lab][0]:7.0f} search_mean={out[lab][1]:7.0f} share>=300={out[lab][2]:.2f}")
    print(f"separation(search) = {out['true'][1]-out['illusion'][1]:.0f}   separation(static) = {out['true'][0]-out['illusion'][0]:.0f}")
    if a.dump:
        with open(a.dump, "w") as f:
            for r, (s, c) in zip(rows, res): f.write(f"{r['label']}\t{r['game_id']}\t{r['ply']}\t{s}\t{c}\n")

main()
