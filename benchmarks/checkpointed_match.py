"""Resume a cold-cache timed match; atomically save every completed game."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine, play_game, search_summary

def summarize(config, games, target):
    n = len(games)
    wins_a = sum(g['winner'] == 'A' for g in games)
    wins_b = sum(g['winner'] == 'B' for g in games)
    draws = n - wins_a - wins_b
    timing, search = {}, {}
    for label in ('A','B'):
        count = sum(g['timing'][label]['moves'] for g in games)
        total = sum(g['timing'][label]['total_ms'] for g in games)
        timing[label] = {'moves':count,'mean':total/count if count else 0,
                         'max':max((g['timing'][label]['max_ms'] for g in games),default=0)}
        totals = {}
        for g in games:
            for key,value in (g['search'][label] or {}).items():
                if key.endswith('_total') or key == 'samples': totals[key] = totals.get(key,0) + value
        search[label] = totals
    return {'config':config,'target_games':target,'games':n,'complete':n == target,
            'wins_a':wins_a,'wins_b':wins_b,'draws':draws,
            'score_a':(wins_a+0.5*draws)/n if n else None,
            'illegal_games':sum('illegal_by' in g for g in games),
            'timing_ms':timing,'search':search,'details':games}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--current',required=True)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--games',type=int,default=100)
    parser.add_argument('--seed',type=int,default=20263005)
    parser.add_argument('--max-plies',type=int,default=256)
    parser.add_argument('--movetime',type=int,default=200,
                        help='Default formal-comparison movetime for both engines')
    parser.add_argument('--movetime-current',type=int,
                        help='Override movetime for engine A/current')
    parser.add_argument('--movetime-baseline',type=int,
                        help='Override movetime for engine B/baseline')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    movetimes = {
        'A': args.movetime_current if args.movetime_current is not None else args.movetime,
        'B': args.movetime_baseline if args.movetime_baseline is not None else args.movetime,
    }
    if (args.games < 1 or args.max_plies < 1 or any(v < 1 for v in movetimes.values())
            or not 0 <= args.seed <= 2147483647-2*args.games):
        raise SystemExit('Invalid match limits')
    paths = {'A':str(Path(args.current).resolve()),'B':str(Path(args.baseline).resolve())}
    go = {label:f'go movetime {movetimes[label]}' for label in ('A','B')}
    config = {'sha256':{k:hashlib.sha256(Path(p).read_bytes()).hexdigest() for k,p in paths.items()},
              'seed':args.seed,'max_plies':args.max_plies,'go':go,
              'options':{'ExperienceCache':False},'cold_process_per_game':True}
    out = Path(args.output); games = []
    if out.exists():
        saved = json.loads(out.read_text())
        if saved['config'] != config or len(saved['details']) > args.games:
            raise SystemExit('Checkpoint configuration/binary mismatch; use a different output')
        games = saved['details']
        if any('illegal_by' in g for g in games): raise SystemExit('Checkpoint contains illegal move')
    out.parent.mkdir(parents=True,exist_ok=True)
    for i in range(len(games),args.games):
        engines = []
        try:
            for label in ('A','B'):
                engines.append(Engine(paths[label],label,config['options'],config['go'][label]))
            result = play_game(*engines,i,args.max_plies,args.seed)
            result['game_index'] = i
            result['timing'] = {e.label:{'moves':len(e.elapsed),'total_ms':1000*sum(e.elapsed),
                                        'max_ms':1000*max(e.elapsed,default=0)} for e in engines}
            result['search'] = {e.label:search_summary(e) for e in engines}
        finally:
            for engine in engines: engine.close()
        games.append(result)
        summary = summarize(config,games,args.games)
        temporary = out.with_suffix(out.suffix+'.tmp')
        temporary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        temporary.replace(out)
        print(f"game {i+1}/{args.games}: {result['winner'] or 'draw'} {result['reason']} "
              f"({summary['wins_a']}W {summary['draws']}D {summary['wins_b']}L)",flush=True)
        if 'illegal_by' in result: raise SystemExit('Illegal move; checkpoint saved')
    print(json.dumps({k:v for k,v in summarize(config,games,args.games).items() if k!='details'},indent=2))

if __name__ == '__main__': main()
