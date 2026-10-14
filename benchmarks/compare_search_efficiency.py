"""Alternate paired fixed-depth and time trials; keep strength separate from speed."""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--games-json',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--positions',type=int,default=24)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--depth',type=int,default=3)
    args=parser.parse_args()
    games=json.loads(Path(args.games_json).read_text())['details']
    # Round-robin plies across separate stored self-play games, no chosen move labels.
    prefixes=[]
    for ply in [10,30,60,90,120,150,180,210]:
        for game in games[:6]:
            if ply<len(game['moves']):prefixes.append(game['moves'][:ply])
    count=min(len(prefixes),args.positions)
    prefixes=[prefixes[i*len(prefixes)//count] for i in range(count)] if count>0 else []
    if not prefixes or args.repeats<1:raise ValueError('need positive positions/repeats')
    options={'OpeningRandomNonLance':False,'MateAssist':False,'MateLearning':False,
             'AdaptiveLongThink':False,'PositionKnowledge':True}
    engines={k:Engine(path,k,options) for k,path in [('candidate',args.candidate),('baseline',args.baseline)]}
    rows=[]
    try:
        for mode,command in [('fixed',f'go depth {args.depth}'),('timed','go movetime 200')]:
            for rep in range(args.repeats):
                for i,prefix in enumerate(prefixes):
                    order=list(engines)
                    if (rep+i)%2:order.reverse()
                    measurements={}
                    for key in order:
                        e=engines[key];e.configure_game(2026101400+i);e.go_command=command
                        move=e.bestmove(prefix)
                        measurements[key]={'move':move,**{k:e.last_search.get(k) for k in
                            ['depth','seldepth','score_cp','score_mate','pv','nodes','qnodes','cutoffs','qcutoffs','elapsed_ms']}}
                    rows.append({'mode':mode,'repeat':rep,'position':i,**measurements})
    finally:
        for e in engines.values():e.close()
    fixed=[r for r in rows if r['mode']=='fixed'];timed=[r for r in rows if r['mode']=='timed']
    invariant=['move','depth','seldepth','score_cp','score_mate','pv','nodes','qnodes','cutoffs','qcutoffs']
    mismatches=[{'position':r['position'],'repeat':r['repeat'],'fields':[k for k in invariant if r['candidate'][k]!=r['baseline'][k]]}
                for r in fixed if any(r['candidate'][k]!=r['baseline'][k] for k in invariant)]
    totals={k:sum(r[k]['elapsed_ms'] for r in fixed) for k in engines}
    result={'positions':len(prefixes),'repeats':args.repeats,'fixed_depth':args.depth,
        'isolation_options':options,'knowledge_sha256':hashlib.sha256((Path(__file__).resolve().parents[1]/'position-knowledge-v1.tsv').read_bytes()).hexdigest(),
        'binary_sha256':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in [('candidate',args.candidate),('baseline',args.baseline)]},
        'fixed_trials':len(fixed),'fixed_identical':len(fixed)-len(mismatches),'mismatches':mismatches,
        'fixed_elapsed_ms':totals,'fixed_total_speedup':totals['baseline']/totals['candidate'],
        'fixed_median_paired_speedup':statistics.median(r['baseline']['elapsed_ms']/r['candidate']['elapsed_ms'] for r in fixed),
        'timed_trials':len(timed),'timed_depth_sum':{k:sum(r[k]['depth'] or 0 for r in timed) for k in engines},
        'timed_nodes_sum':{k:sum(r[k]['nodes'] or 0 for r in timed) for k in engines},
        'timed_depth_comparison':{'higher':sum(r['candidate']['depth']>r['baseline']['depth'] for r in timed),
            'equal':sum(r['candidate']['depth']==r['baseline']['depth'] for r in timed),
            'lower':sum(r['candidate']['depth']<r['baseline']['depth'] for r in timed)},
        'rows':rows}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
    if mismatches:raise SystemExit('fixed-depth search changed')

if __name__=='__main__':main()
