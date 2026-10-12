"""Reconstruct actually played positions; keep retrospective evaluations separate."""
import argparse
import collections
import json
import subprocess
from pathlib import Path
import shogi

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',nargs='+',required=True)
    p.add_argument('--probe',required=True)
    p.add_argument('--every',type=int,default=10)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    assert args.every>=1
    states=[];original=[]
    for path in args.input:
        r=json.loads(Path(path).read_text())
        for game_index,g in enumerate(r['details']):
            board=shogi.Board()
            assert len(g['moves'])==g['plies']
            for ply,move in enumerate(g['moves']):
                if ply%args.every==0:
                    states.append(board.sfen())
                    original.append(dict(source=path,game_index=game_index,ply=ply+1,
                        observed=g['move_records'][ply].get('search',{})))
                m=shogi.Move.from_usi(move)
                assert m in board.legal_moves
                board.push(m)
    result=subprocess.run([args.probe],input='\n'.join(states)+'\n',text=True,capture_output=True,check=True)
    rows=[json.loads(x) for x in result.stdout.splitlines()]
    assert len(rows)==len(states)
    stats=collections.defaultdict(lambda:dict(samples=0,clamped=0,material_abs=0,terms_abs=[0]*9,
        maturity_counts=[0]*101,hand_weight_min=10000,hand_weight_max=0))
    for row in rows:
        for model in row['profiles']:
            s=stats[model['index']];s['samples']+=1;s['clamped']+=model['clamp']!=0
            s['material_abs']+=abs(model['material_term'])
            s['maturity_counts'][row['maturity']]+=1
            s['hand_weight_min']=min(s['hand_weight_min'],model['hand_weight'])
            s['hand_weight_max']=max(s['hand_weight_max'],model['hand_weight'])
            for i,x in enumerate(model['terms']):s['terms_abs'][i]+=abs(x)
    for s in stats.values():
        s['clamp_rate']=s['clamped']/s['samples']
        s['mean_abs_material']=s['material_abs']/s['samples']
        s['mean_abs_terms']=[x/s['samples'] for x in s['terms_abs']]
    out=dict(note='Retrospective static evaluations of played positions, not original search scores or move-quality labels.',
        samples=len(rows),summary=dict(stats),observations=[dict(**o,reanalysis=r) for o,r in zip(original,rows)])
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(samples=len(rows),summary=dict(stats)),ensure_ascii=False))

if __name__=='__main__':main()
