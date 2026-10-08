#!/usr/bin/env python3
"""Research selected opening positions with one isolated long USI search each."""
import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

def load(path):
    rows = []
    for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) != 3:
            raise ValueError(f"line {ln}: require ID, expected SFEN, and USI moves")
        rid, sfen, raw_moves = p
        rows.append({"id": rid, "sfen": sfen, "moves": raw_moves.split()})
    if len(rows) != 20 or len({r["id"] for r in rows}) != 20:
        raise ValueError(f"expected exactly 20 unique positions, got {len(rows)}")
    if [r["id"] for r in rows] != [f"kumoji-160-{i:03d}" for i in range(1, 21)]:
        raise ValueError("position ID order mismatch")
    return rows

def validate(rows, knowledge):
    import shogi
    known = set()
    for line in Path(knowledge).read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            known.add(line.split("\t",1)[0])
    seen = set()
    for r in rows:
        board = shogi.Board()
        for move in r["moves"]:
            board.push_usi(move)
        actual = " ".join(board.sfen().split()[:3])
        if actual != r["sfen"]:
            raise ValueError(f"{r['id']}: SFEN mismatch: {actual} != {r['sfen']}")
        if actual in seen or actual in known:
            raise ValueError(f"{r['id']}: duplicate or already adopted research position")
        seen.add(actual)
    print(f"preflight OK: {len(rows)} distinct legal historical openings; no active knowledge overlap", flush=True)

class Usi:
    def __init__(self, engine, knowledge):
        self.proc = subprocess.Popen([str(Path(engine).resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.send("usi")
        self.wait("usiok", 30)
        self.send("setoption name AdaptiveLongThink value false")
        self.send("setoption name PositionKnowledge value true")
        self.send("setoption name PositionKnowledgeFile value "+str(Path(knowledge).resolve()))
        self.send("isready")
        self.wait("readyok", 30)
    def _read(self):
        for line in self.proc.stdout:
            self.queue.put(line.rstrip())
        self.queue.put(None)
    def send(self, command):
        self.proc.stdin.write(command+"\n")
        self.proc.stdin.flush()
    def wait(self, prefix, timeout):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            line=self.queue.get(timeout=max(.01,until-time.monotonic()))
            if line is None: raise RuntimeError("engine exited")
            if line.startswith(prefix): return line
        raise TimeoutError(prefix)
    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
    def research(self, row, millis, progress_path):
        self.send("usinewgame")
        self.send("isready")
        self.wait("readyok",30)
        self.send("position startpos moves "+" ".join(row["moves"]))
        self.send(f"go movetime {millis}")
        start=time.monotonic()
        last_info={}
        changes=[]
        old_first=None
        last_progress=-300
        out={"id":row["id"],"sfen":row["sfen"],"history_moves":row["moves"],"research_ms_requested":millis,"completed":False}
        while True:
            elapsed=time.monotonic()-start
            if elapsed>=millis/1000+180:
                self.send("stop")
                raise TimeoutError(f"search went over expected time: {elapsed:.0f}s")
            try: line=self.queue.get(timeout=20)
            except queue.Empty: line=""
            if line is None: raise RuntimeError("engine exited before bestmove")
            if line.startswith("info "):
                tokens=line.split()
                for name in ("depth","seldepth","nodes","time"):
                    if name in tokens:
                        try: last_info[name]=int(tokens[tokens.index(name)+1])
                        except (ValueError,IndexError): pass
                if "score" in tokens:
                    try:
                        j=tokens.index("score")
                        last_info["score_type"]=tokens[j+1]
                        last_info["score_value"]=int(tokens[j+2])
                    except (ValueError,IndexError): pass
                if "pv" in tokens:
                    pv=tokens[tokens.index("pv")+1:]
                    last_info["pv"]=pv[:32]
                    if pv and pv[0]!=old_first:
                        changes.append({"seconds":round(elapsed,1),"move":pv[0],"depth":last_info.get("depth")})
                        old_first=pv[0]
            if elapsed-last_progress>=300:
                last_progress=elapsed
                out.update({"elapsed_seconds":round(elapsed,1),"last_info":last_info,"move_changes":changes[-100:]})
                Path(progress_path).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                print(f"heartbeat {row['id']} elapsed={elapsed:.0f}s depth={last_info.get('depth')} nodes={last_info.get('nodes')}", flush=True)
            if line.startswith("bestmove "):
                out.update({"completed":True,"bestmove":line.split()[1],"elapsed_seconds":round(time.monotonic()-start,1),"final":last_info,"move_changes":changes})
                Path(progress_path).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                return out

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["validate","research"])
    parser.add_argument("--input",default=".github/research-opening-20-positions.tsv")
    parser.add_argument("--knowledge",default="position-knowledge-v1.tsv")
    parser.add_argument("--lane",type=int,default=0)
    parser.add_argument("--engine",default="build/kumoji")
    parser.add_argument("--ms",type=int,default=3000000)
    parser.add_argument("--output",default="result.json")
    a=parser.parse_args()
    rows=load(a.input)
    validate(rows,a.knowledge)
    if a.mode=="validate": return
    if not (0<=a.lane<20): raise ValueError("invalid lane")
    row=rows[a.lane]
    print(f"start {row['id']} lane={a.lane} 50-minute research", flush=True)
    eng=Usi(a.engine,a.knowledge)
    try:
        result=eng.research(row,a.ms,a.output)
    finally:
        eng.close()
    print(f"completed {row['id']} move={result['bestmove']} elapsed={result['elapsed_seconds']}s",flush=True)

if __name__=="__main__":
    main()
