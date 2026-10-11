#!/usr/bin/env python3
"""Compare owner-approved difficult positions with forced study moves OFF."""
import argparse
import hashlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

class Usi:
    def __init__(self, exe):
        self.proc=subprocess.Popen([str(Path(exe).resolve())],stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                   text=True,bufsize=1)
        self.output=queue.Queue()
        threading.Thread(target=self._read,daemon=True).start()
        self.send("usi")
        self.until("usiok")
        for name,value in (("OpeningRandomNonLance","false"),("PositionKnowledge","false"),
                           ("MateAssist","false"),("AdaptiveLongThink","false"),
                           ("RandomSeed","5489")):
            self.send("setoption name "+name+" value "+value)
        self.send("isready")
        self.until("readyok")
    def _read(self):
        for line in self.proc.stdout: self.output.put(line.strip())
    def send(self,line):
        self.proc.stdin.write(line+"\n")
        self.proc.stdin.flush()
    def until(self,needle):
        out=[]
        until=time.monotonic()+90
        while True:
            line=self.output.get(timeout=max(0.001,until-time.monotonic()))
            out.append(line)
            if line.startswith(needle): return line,out
    def search(self,key,cmd):
        self.send("position sfen "+key+" 1")
        start=time.monotonic()
        self.send(cmd)
        best,lines=self.until("bestmove ")
        duration=round(1000*(time.monotonic()-start),2)
        infos=[line.split() for line in lines if line.startswith("info depth ")]
        telemetry=[line.split() for line in lines if line.startswith("info nodes ")]
        assert len(telemetry)==1 and infos and "search error" not in "\n".join(lines),lines
        last=infos[-1]
        data=telemetry[-1]
        def val(x,k): return int(x[x.index(k)+1])
        move=best.split()[1]
        assert move==last[last.index("pv")+1],(move,infos)
        assert val(data,"qnodes")<=val(data,"nodes")
        return dict(move=move,score_type=last[last.index("score")+1],
                    score=val(last,last[last.index("score")+1]),
                    depth=val(last,"depth"),nodes=val(data,"nodes"),
                    qnodes=val(data,"qnodes"),elapsed_ms=duration)
    def close(self):
        self.send("quit")
        try: self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired: self.proc.kill()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",required=True)
    parser.add_argument("--candidate",required=True)
    parser.add_argument("--out",default="six-opt-results.json")
    parser.add_argument("--variant",required=True,choices=["tt","order","pv","eval","lmr","see"])
    args=parser.parse_args()
    knowledge=Path("position-knowledge-v1.tsv")
    entries=[x.split("\t") for x in knowledge.read_text().splitlines()
             if x and not x.startswith("#")]
    assert len(entries)>=163,len(entries)
    rows=[x for x in entries if "position10-38091143128" in x[11]]
    assert len(rows)==10,len(rows)
    def run(exe,key,cmd):
        e=Usi(exe)
        try: return e.search(key,cmd)
        finally: e.close()
    cases=[]
    for i,entry in enumerate(rows):
        names=("baseline","candidate") if i%2==0 else ("candidate","baseline")
        trial={}
        for name in names:
            trial[name]=run(getattr(args,name),entry[0],"go movetime 200")
        cases.append(dict(id=entry[11],sfen=entry[0],**trial))
    fixed=[]
    for i in (0,3,6,9):
        trial={name:run(getattr(args,name),rows[i][0],"go depth 1")
               for name in ("baseline","candidate")}
        if args.variant in ("pv","eval","tt","order"):
            for field in ("move","score_type","score","depth"):
                assert trial["baseline"][field]==trial["candidate"][field],(i,field,trial)
        fixed.append(dict(id=rows[i][11],**trial))
    summary=dict(cases=len(cases),same_move=sum(x["baseline"]["move"]==x["candidate"]["move"] for x in cases),
        depth_sum_baseline=sum(x["baseline"]["depth"] for x in cases),
        depth_sum_candidate=sum(x["candidate"]["depth"] for x in cases),
        node_sum_baseline=sum(x["baseline"]["nodes"] for x in cases),
        node_sum_candidate=sum(x["candidate"]["nodes"] for x in cases),
        fixed_depth_equivalence=len(fixed))
    record=dict(schema="six-optimization-screen-v1",variant=args.variant,baseline_binary_sha256=hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
                candidate_binary_sha256=hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest(),
                knowledge_sha256=hashlib.sha256(knowledge.read_bytes()).hexdigest(),
                configuration=dict(time_ms=200,position_knowledge=False,mate_assist=False,adaptive_longthink=False),
                results=cases,fixed_depth_tests=fixed,summary=summary,
                caveat="Intentional hard-position selection: NOT an Elo/strength comparison")
    Path(args.out).write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    print("EXPERIMENT_ONLY_NO_AUTO_ADOPTION",flush=True)
if __name__=="__main__":main()
