#!/usr/bin/env python3
"""Re-analyse Position Bank records and emit explainable nightly diagnosis.

Uses only the self-authored engine. It records static evaluation breakdown and
compares short/long searches; no external engine is used as a teacher.
"""
import argparse, json, queue, subprocess, threading, time
from pathlib import Path

class Usi:
    def __init__(self,path,options):
        self.p=subprocess.Popen([path],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.q=queue.Queue(); threading.Thread(target=self._read,daemon=True).start()
        self.send('usi'); self.wait('usiok',10)
        for k,v in options.items(): self.send(f'setoption name {k} value {str(v).lower() if isinstance(v,bool) else v}')
        self.send('isready'); self.wait('readyok',10)
    def _read(self):
        for line in self.p.stdout: self.q.put(line.rstrip())
    def send(self,s): self.p.stdin.write(s+'\n'); self.p.stdin.flush()
    def wait(self,prefix,timeout):
        end=time.monotonic()+timeout; seen=[]
        while time.monotonic()<end:
            try: line=self.q.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty: break
            seen.append(line)
            if line.startswith(prefix): return line,seen
        raise TimeoutError(f'waiting {prefix}; seen={seen[-10:]}')
    def position(self,moves): self.send('position startpos'+((' moves '+' '.join(moves)) if moves else ''))
    def eval(self,moves):
        self.position(moves); self.send('eval'); line,_=self.wait('info string evaluation ',5)
        parts=line.split(); names=('material','safety','pressure','activity','danger','clamp','total')
        out={}
        for n in names:
            try: out[n]=int(parts[parts.index(n)+1])
            except Exception: pass
        return out
    def search(self,moves,ms):
        self.position(moves); self.send(f'go movetime {ms}')
        end=time.monotonic()+max(30,ms/1000+10); score=None; pv=[]; depth=None
        while time.monotonic()<end:
            try: line=self.q.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty: break
            if line.startswith('info '):
                parts=line.split()
                if 'depth' in parts:
                    try: depth=int(parts[parts.index('depth')+1])
                    except Exception: pass
                if 'score' in parts:
                    try:
                        i=parts.index('score'); kind=parts[i+1]; val=int(parts[i+2])
                        score=(100000000-(abs(val) if kind=='mate' else 0))*(1 if val>0 else -1) if kind=='mate' else val
                    except Exception: pass
                if 'pv' in parts: pv=parts[parts.index('pv')+1:]
            elif line.startswith('bestmove '):
                return {'bestmove':line.split()[1],'score':score,'depth':depth,'pv':pv}
        raise TimeoutError('bestmove timeout')
    def close(self):
        if self.p.poll() is None:
            try: self.send('quit'); self.p.wait(timeout=2)
            except Exception: self.p.kill()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--engine',required=True); p.add_argument('--bank',required=True)
    p.add_argument('--output',required=True); p.add_argument('--problems-output',required=True)
    p.add_argument('--limit',type=int,default=100); p.add_argument('--shallow-ms',type=int,default=50)
    p.add_argument('--deep-ms',type=int,default=500); p.add_argument('--score-gap',type=int,default=200)
    args=p.parse_args()
    rows=[]
    for line in Path(args.bank).read_text(encoding='utf-8').splitlines():
        if line.strip(): rows.append(json.loads(line))
        if len(rows)>=args.limit: break
    e=Usi(args.engine,{'OpeningBook':False,'ExperienceCache':False})
    diagnosed=[]; problems=[]
    try:
        for row in rows:
            moves=row.get('moves',[])
            static=e.eval(moves); shallow=e.search(moves,args.shallow_ms); deep=e.search(moves,args.deep_ms)
            reasons=[]
            if shallow.get('bestmove')!=deep.get('bestmove'): reasons.append('disagreement')
            ss,ds=shallow.get('score'),deep.get('score')
            if ss is not None and ds is not None and abs(ss-ds)>=args.score_gap: reasons.append('eval-swing')
            if static and ds is not None and abs(static.get('total',0)-ds)>=args.score_gap: reasons.append('static-search-gap')
            item={'id':row.get('id'),'tags':row.get('tags',[]),'moves':moves,'static':static,
                  'shallow':shallow,'deep':deep,'diagnosis_tags':reasons}
            diagnosed.append(item)
            if reasons: problems.append(item)
            print(row.get('id'),','.join(reasons) or 'stable')
    finally: e.close()
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps({'positions':len(diagnosed),'problems':len(problems),'details':diagnosed},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Path(args.problems_output).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in problems),encoding='utf-8')
if __name__=='__main__': main()
