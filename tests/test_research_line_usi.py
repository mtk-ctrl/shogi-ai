#!/usr/bin/env python3
"""Exact-reply continuation and conservative fallback for archived research lines."""
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

class Usi:
    def __init__(self,exe):
        self.p=subprocess.Popen([exe],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.q=queue.Queue()
        threading.Thread(target=self.read,daemon=True).start()
    def read(self):
        for line in self.p.stdout:self.q.put(line.strip())
    def send(self,command):
        self.p.stdin.write(command+"\n");self.p.stdin.flush()
    def until(self,prefix):
        lines=[]
        while True:
            line=self.q.get(timeout=30)
            lines.append(line)
            if line.startswith(prefix):return lines
    def close(self):
        self.send("quit");self.p.wait(timeout=5)
def bestmove(u,pos):
    u.send("position "+pos)
    u.send("go depth 1")
    lines=u.until("bestmove")
    return lines[-1], lines
root="lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -"
with tempfile.TemporaryDirectory() as d:
    p=Path(d)
    knowledge=p/"knowledge.tsv"
    knowledge.write_text(root+"\t7g7f\ttest\t1\t1800001\t8\t4000\tcp\t50\t100000\n")
    linesfile=p/"lines.tsv"
    linesfile.write_text(root+"\t7g7f 3c3d 2g2f 8c8d 2f2e\tsynthetic-research\n")
    u=Usi(sys.argv[1])
    try:
        u.send("usi")
        hello=u.until("usiok")
        assert any("option name ResearchDecisionMinMinutes" in x for x in hello)
        assert any("option name ResearchLinesFile" in x for x in hello)
        u.send("setoption name PositionKnowledgeFile value "+str(knowledge))
        u.send("setoption name ResearchLinesFile value "+str(linesfile))
        u.send("setoption name MateAssist value false")
        u.send("isready")
        assert any("research_lines loaded 1 positions" in x for x in u.until("readyok"))
        u.send("usinewgame")
        mv,info=bestmove(u,"startpos")
        assert mv=="bestmove 7g7f",(mv,info)
        assert any("research_decision source synthetic-research step 1" in x for x in info)
        mv,info=bestmove(u,"startpos moves 7g7f 3c3d")
        assert mv=="bestmove 2g2f",(mv,info)
        assert any("research_decision source synthetic-research step 3" in x for x in info)
        # A different enemy reply must invalidate the active variation.
        mv,info=bestmove(u,"startpos moves 7g7f 8c8d")
        assert not any("info string research_decision" in x for x in info),info
        # Opting out keeps the adopted hint-only behavior.
        u.send("setoption name ResearchDecisionMinMinutes value 0")
        mv,info=bestmove(u,"startpos")
        assert not any("info string research_decision" in x for x in info),info
        u.send("setoption name ResearchDecisionMinMinutes value 30")
        u.send("setoption name ResearchLinesFile value "+str(p/"missing.tsv"))
        u.send("isready")
        assert any("research_lines unavailable" in x for x in u.until("readyok"))
        mv,info=bestmove(u,"startpos")
        assert not any("info string research_decision" in x for x in info),info
    finally:
        u.close()
print("PASS research root, exact continuation, deviation, threshold off and missing asset")
