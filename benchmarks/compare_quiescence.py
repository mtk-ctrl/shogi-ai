"""Identical-position qsearch cost and OFF compatibility; separate from match strength."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine, SEARCH_STAT_NAMES
import shogi

def measure(engine, prefix, seed, command):
    engine.configure_game(seed)
    engine.send('position startpos' + (' moves ' + ' '.join(prefix) if prefix else ''))
    start = time.monotonic()
    engine.send(command)
    info, stats = {}, {}
    while True:
        line = engine.lines.get(timeout=30)
        parts = line.split()
        if line.startswith('info depth '):
            info = {'depth': int(parts[parts.index('depth')+1]),
                    'score': parts[parts.index('score')+1:parts.index('score')+3] if 'score' in parts else None,
                    'pv': parts[parts.index('pv')+1:] if 'pv' in parts else []}
        if line.startswith('info '):
            for name in SEARCH_STAT_NAMES:
                if name in parts:
                    stats[name] = int(parts[parts.index(name)+1])
        if line.startswith('bestmove '):
            move = parts[1]; break
    board = shogi.Board()
    for m in prefix: board.push_usi(m)
    assert shogi.Move.from_usi(move) in board.legal_moves, (move,prefix)
    for m in info['pv']:
        assert shogi.Move.from_usi(m) in board.legal_moves, (m,info)
        board.push_usi(m)
    return {**info, 'move': move, 'stats':stats, 'elapsed_ms':1000*(time.monotonic()-start)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--current',required=True)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--positions',default='benchmarks/results/2026-10-04_iterative-identical-positions.json')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    engines = {
        'on':Engine(args.current,'on',{'ExperienceCache':False}),
        'off':Engine(args.current,'off',{'ExperienceCache':False,'Quiescence':False}),
        'baseline':Engine(args.baseline,'baseline',{'ExperienceCache':False}),
    }
    rows = []
    try:
        for i, case in enumerate(json.loads(Path(args.positions).read_text())['rows']):
            order = list(engines) if i%2 == 0 else list(reversed(engines))
            measurements = {key:measure(engines[key],case['moves'],case['seed'],'go depth 3') for key in order}
            rows.append({'moves':case['moves'],'seed':case['seed'],**measurements})
    finally:
        for engine in engines.values(): engine.close()
    result = {
        'go':'go depth 3','experience':False,'cases':len(rows),
        'off_equivalent':sum(r['off']['move']==r['baseline']['move'] and r['off']['score']==r['baseline']['score'] for r in rows),
        'on_changed_moves':sum(r['on']['move']!=r['baseline']['move'] for r in rows),
        'nodes':{k:sum(r[k]['stats']['nodes'] for r in rows) for k in engines},
        'elapsed_ms':{k:sum(r[k]['elapsed_ms'] for r in rows) for k in engines},
        'qnodes':sum(r['on']['stats'].get('qnodes',0) for r in rows),
        'qlimit_leaves':sum(r['on']['stats'].get('qlimit_leaves',0) for r in rows),
        'sha256':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in [('current',args.current),('baseline',args.baseline)]},
        'rows':rows,
    }
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
    assert result['off_equivalent']==result['cases'], 'OFF must preserve v0.0.14 fixed-horizon results'

if __name__=='__main__': main()
