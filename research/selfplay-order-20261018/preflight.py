"""Actual binary controls for the selfplay ordering experiment."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.arena import Engine,merge_info_line
from tools.research.postgame_eval_preflight import tactical_cases


def probe(binary,sfen,scale,depth=None,history=()):
    options=dict(SelfplayOrder=scale>0,SelfplayOrderScale=scale,
        SearchThreads=1,AdaptiveLongThink=False,USI_Ponder=False,
        OpeningRandomNonLance=False,RandomSeed=2031101801,
        PositionKnowledge=True,PositionKnowledgeFile=str(ROOT/'position-knowledge-v1.tsv'))
    e=Engine(binary,'probe',options)
    try:
        e.send('usinewgame');e.send('position sfen '+sfen+(' moves '+' '.join(history) if history else ''))
        start=time.monotonic();e.send('go depth '+str(depth) if depth else 'go movetime 200')
        info={}
        while True:
            line=e.lines.get(timeout=20)
            if line.startswith('info '):merge_info_line(info,line)
            if line.startswith('bestmove '):
                keys=('depth','nodes','score_cp','score_mate','selfplay_order_calls','selfplay_order_moves')
                return dict(move=line.split()[1],elapsed_ms=(time.monotonic()-start)*1000,
                            **{k:info[k] for k in keys if k in info})
    finally:e.close()


def run(candidate,parent,actual_choices):
    import shogi
    rows=[json.loads(l) for l in Path(actual_choices).read_text().splitlines()][:16]
    out=dict(controls=[],disabled=[],speed=[],passed=False)
    for case in tactical_cases():
        obs=[probe(candidate,case['start_sfen'],s) for s in (0,50,100,200)]
        correct=all(r['move'].startswith(case['expected_prefix']) for r in obs)
        out['controls'].append(dict(case=case['case_id'],correct=correct,observations=obs))
    for row in rows[:8]:
        obs=[probe(b,row['sfen'],0,2) for b in (parent,candidate)]
        keys=('move','depth','score_cp','score_mate','nodes')
        same=all(obs[0].get(k)==obs[1].get(k) for k in keys)
        out['disabled'].append(dict(game_hash=row['game_hash'],ply=row['ply'],same=same,observations=obs))
    for row in rows:
        obs=[probe(candidate,row['sfen'],s) for s in (0,50,100,200)]
        legal=all(shogi.Move.from_usi(r['move']) in shogi.Board(row['sfen']).legal_moves for r in obs)
        out['speed'].append(dict(game_hash=row['game_hash'],ply=row['ply'],legal=legal,observations=obs))
    sums=[sum(r['observations'][i].get('depth',0) for r in out['speed']) for i in range(4)]
    out['depth_sums']=sums
    out['depth_ratios']=[v/sums[0] if sums[0] else 0 for v in sums[1:]]
    out['passed']=bool(all(r['correct'] for r in out['controls'])
        and all(r['same'] for r in out['disabled']) and all(r['legal'] for r in out['speed'])
        and min(out['depth_ratios'])>=.9
        and all(sum(r['observations'][i].get('selfplay_order_calls',0) for r in out['speed'])>0 for i in (1,2,3)))
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--parent',required=True)
    p.add_argument('--actual-choices',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=run(a.candidate,a.parent,a.actual_choices);a.output.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('controls','disabled','speed')},indent=2))
    if not out['passed']:raise SystemExit('preflight failed')
