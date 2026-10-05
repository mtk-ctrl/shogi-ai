"""Replay recorded games; report feature ranges and time identical snapshots.

No position search is included in the leaf-cost microbenchmark. Time columns
in arena include USI/position replay and therefore answer a different question.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import shogi

p=argparse.ArgumentParser();p.add_argument('--match',required=True);p.add_argument('--probe',required=True);p.add_argument('--output',required=True);p.add_argument('--repeats',type=int,default=200)
a=p.parse_args();match=json.loads(Path(a.match).read_text()); sfens=[]
for game in match['details']:
    board=shogi.Board()
    sfens.append(board.sfen())
    for i,move in enumerate(game['moves']):
        board.push_usi(move)
        if i%4==3:sfens.append(board.sfen())
text='\n'.join(sfens)+'\n'
rows=[json.loads(r) for r in subprocess.run([a.probe,'--inspect'],input=text,text=True,capture_output=True,check=True).stdout.splitlines()]
assert len(rows)==len(sfens)
def distribution(values):
    values=sorted(values)
    return {'min':values[0],'p05':values[int((len(values)-1)*.05)],'median':statistics.median(values),'p95':values[int((len(values)-1)*.95)],'max':values[-1]}
bench=json.loads(subprocess.run([a.probe,'--bench',str(a.repeats)],input=text,text=True,capture_output=True,check=True).stdout)
bench['material_ns_median']=statistics.median(r['material_ns'] for r in bench['trials'])
bench['features_ns_median']=statistics.median(r['features_ns'] for r in bench['trials'])
bench['ratio']=bench['features_ns_median']/bench['material_ns_median']
result={'source_match':a.match,'sampling':'start position and every fourth ply of each recorded game; includes repeats',
        'samples':len(rows),'ranges':{k:distribution([r[k] for r in rows]) for k in rows[0]},
        'microbenchmark':bench,'positions':[dict(sfen=sf,**r) for sf,r in zip(sfens,rows)]}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='positions'},ensure_ascii=False,indent=2))
