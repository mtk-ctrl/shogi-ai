#!/usr/bin/env python3
"""Diagnostic regression: calm opening vs a complex, material-exchanged position."""
import queue
import re
import subprocess
import sys
import threading
import time

class Engine:
    def __init__(self, binary):
        self.p = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
    def _reader(self):
        for line in self.p.stdout: self.q.put(line.strip())
    def send(self, line):
        self.p.stdin.write(line+"\n");self.p.stdin.flush()
    def until(self, prefix):
        lines=[]
        while True:
            item=self.q.get(timeout=30)
            lines.append(item)
            if item.startswith(prefix): return lines
    def close(self):
        self.send("quit");self.p.wait(timeout=5)

def stage_from(lines):
    line=next(x for x in lines if x.startswith("info string game_stage "))
    scores=dict((k,int(v)) for k,v in re.findall(r"(progress|urgency|complexity) (\d+)",line))
    assert len(scores)==3
    assert all(0<=v<=100 for v in scores.values()),scores
    return scores

engine=Engine(sys.argv[1])
try:
    engine.send("usi")
    lines=engine.until("usiok")
    assert any("option name StageAwareMateAssist type check default false" in x for x in lines)
    engine.send("isready");engine.until("readyok")
    engine.send("position startpos")
    engine.send("go movetime 80")
    lines=engine.until("bestmove")
    scores=stage_from(lines)
    assert scores["progress"]==0 and scores["urgency"]==0,scores
    assert any("info string mate_assist " in x for x in lines),lines[-10:]
    engine.send("setoption name StageAwareMateAssist value true")
    engine.send("position startpos")
    engine.send("go movetime 80")
    lines=engine.until("bestmove")
    assert not any("info string mate_assist " in x for x in lines),lines[-10:]
    assert stage_from(lines)["progress"]==0
    # Capture/promotions/hands at a saved research root should not look like an opening.
    sf="Sn4g2/3+R1sg2/2p1pppp1/8p/9/3P1G2P/1+l1KP+nN2/1k7/1+l1+b4L b RB2SNLPg8p 103"
    engine.send("position sfen "+sf)
    engine.send("go depth 1")
    lines=engine.until("bestmove")
    assert stage_from(lines)["progress"]>0,lines
finally:
    engine.close()
print("PASS game-stage independent axes and optional quiet-opening mate gate")
