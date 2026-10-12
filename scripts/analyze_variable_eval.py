"""Audit match shards and score research models without promoting an engine."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

KNOWLEDGE_SHA='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'

def interval(w,d,l):
    """Student/normal approximation from 1/0.5/0 observations, not Bernoulli draws."""
    n=w+d+l
    score=(w+0.5*d)/n
    variance=(w+0.25*d-n*score*score)/(n-1) if n>1 else 0.25
    radius=1.96*math.sqrt(max(0,variance)/n)
    return score,[max(0,score-radius),min(1,score+radius)]

def audit_shard(path):
    r=json.loads(path.read_text())
    assert r['games']==len(r['details']),f'{path}: missing games'
    assert r['games']==r['wins_a']+r['wins_b']+r['draws']
    assert r['illegal_games']==0,f'{path}: illegal move'
    for side in ['A','B']:
        k=r['position_knowledge'][side]
        assert k['enabled'] and k['available'] and k['positions']==163 and k['sha256']==KNOWLEDGE_SHA
        opts=r['options_'+side.lower()]
        assert str(opts['PositionKnowledge']).lower()=='true'
    color=collections.Counter()
    stages=collections.defaultdict(list)
    missing=0
    for game in r['details']:
        color['A' if game['a_black'] else 'B']+=1
        for row in game['move_records']:
            obs=row.get('search',{})
            if 'phase_maturity' in obs:
                stages[row['engine']].append(obs['phase_maturity'])
            else: missing+=1
    return r,dict(color),dict(stages),missing

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--registry',required=True,help='candidate refs.json')
    p.add_argument('--input',nargs='+',required=True,help='raw shard JSON files/globs')
    p.add_argument('--output',required=True)
    args=p.parse_args()
    import glob
    paths=sorted({Path(s) for pattern in args.input for s in glob.glob(pattern)})
    refs=json.loads(Path(args.registry).read_text())['profiles']
    # The binary SHA belongs to the compiled engine, not the Git source commit.
    # Use an adjacent match.json with observed refs/run to resolve its model.
    matches=collections.defaultdict(list)
    seen=set()
    for path in paths:
        row,colors,stages,missing=audit_shard(path)
        meta=json.loads((path.parent/'match.json').read_text())
        key=(meta['run_id'],row['game_offset'])
        assert key not in seen,f'duplicate shard {key}'
        seen.add(key)
        expected=meta['go_command']
        assert row['go_command']==expected
        for side in ['a','b']:
            assert row['options_'+side]==meta['options_'+side]
        matches[meta['request_id']].append((meta,row,colors,stages,missing))
    out=[]
    by_ref={x['sha']:x for x in refs}
    for key,rows in sorted(matches.items()):
        meta=rows[0][0]
        n=sum(r[1]['games'] for r in rows)
        assert n==meta['games'],f'{key}: {n}/{meta["games"]} games'
        counts=collections.Counter()
        for _,_,colors,_,_ in rows: counts.update(colors)
        assert abs(counts['A']-counts['B'])<=1,f'{key}: unbalanced colors'
        w=sum(x[1]['wins_a'] for x in rows);d=sum(x[1]['draws'] for x in rows);l=sum(x[1]['wins_b'] for x in rows)
        score,ci=interval(w,d,l)
        out.append(dict(request_id=key,run_id=meta['run_id'],
            a=by_ref.get(meta['ref_a'],{}).get('name',meta['ref_a']),
            b=by_ref.get(meta['ref_b'],{}).get('name',meta['ref_b']),
            wins=w,draws=d,losses=l,score=score,approx_95pct=ci,colors=dict(counts),
            phase_missing_plies=sum(x[4] for x in rows),
            raw_sha256={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths
                        if json.loads((x.parent/'match.json').read_text())['request_id']==key}))
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
