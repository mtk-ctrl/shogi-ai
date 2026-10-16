"""Paired timing diagnostics for independent v2.0.19 search probes."""
import hashlib
import json
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.arena import Engine
import shogi

baseline_binary, candidate_binary, output = sys.argv[1:4]
cases = json.loads(Path('research/search-efficiency3-20261015/positions.json').read_text())['rows'][:24]
assert len({tuple(row['moves']) for row in cases}) == 24
options = {
    'OpeningRandomNonLance': False,
    'MateAssist': False, 'MateLearning': False, 'AdaptiveLongThink': False,
    'PositionKnowledge': True, 'USI_Ponder':False, 'SearchThreads':2,
}
config = json.loads(sys.argv[4]) if len(sys.argv)>4 else {'control':0,'pvs':1,'killer':2,'history':4}
engines = {'official_v2019': Engine(baseline_binary, 'official_v2019', options)}
for name, update_mask in config.items():
    engines[name] = Engine(candidate_binary, name,
        {**options, 'SearchProbeMask':update_mask})
measurements = []
try:
    for mode, command in (('fixed', 'go depth 2'), ('timed', 'go movetime 200')):
        for rep in range(3):
            for case_idx, row in enumerate(cases):
                names = list(engines)
                offset = (rep + case_idx) % len(names)
                names = names[offset:] + names[:offset]
                if (rep + case_idx) % 2: names.reverse()
                results = {}
                for name in names:
                    engine = engines[name]
                    engine.configure_game(2026101583 + case_idx)
                    engine.send('isready')
                    engine.wait_prefix('readyok', 10)
                    engine.go_command = command
                    move = engine.bestmove(row['moves'])
                    info = dict(engine.last_search)
                    board = shogi.Board()
                    for m in row['moves']: board.push_usi(m)
                    assert shogi.Move.from_usi(move) in board.legal_moves, (name, case_idx, move)
                    for m in info.get('pv', []):
                        assert shogi.Move.from_usi(m) in board.legal_moves, (name, case_idx, m)
                        board.push_usi(m)
                    results[name] = {'move': move, **info}
                measurements.append({
                    'mode': mode, 'repeat': rep, 'position': case_idx,
                    'results': results,
                })
            print('complete', mode, rep, flush=True)
finally:
    for engine in engines.values(): engine.close()

summary = {}
fixed = [r for r in measurements if r['mode'] == 'fixed']
timed = [r for r in measurements if r['mode'] == 'timed']
for name in engines:
    speeds = []
    mismatches = []
    score_mismatches = []
    for row in fixed:
        x = row['results']['official_v2019']
        y = row['results'][name]
        speeds.append(x['elapsed_ms'] / max(0.001, y['elapsed_ms']))
        if any(x.get(k) != y.get(k) for k in ('score_cp', 'score_mate')):
            score_mismatches.append((row['repeat'], row['position']))
        if any(x.get(k) != y.get(k) for k in (
            'move','score_cp','score_mate','depth','nodes','qnodes','cutoffs','pv')):
            mismatches.append((row['repeat'], row['position']))
    summary[name] = {
        'fixed_trials': len(fixed),
        'fixed_nodes_sum': sum(r['results'][name].get('nodes',0) for r in fixed),
        'fixed_qnodes_sum': sum(r['results'][name].get('qnodes',0) for r in fixed),
        'median_speedup': statistics.median(speeds),
        'total_speedup': sum(r['results']['official_v2019']['elapsed_ms'] for r in fixed)
          / sum(r['results'][name]['elapsed_ms'] for r in fixed),
        'score_mismatches': score_mismatches,
        'full_mismatches': mismatches,
        'timed_depth_sum': sum(r['results'][name].get('depth',0) for r in timed),
        'timed_nodes_sum': sum(r['results'][name].get('nodes',0) for r in timed),
        'timed_deeper': sum(r['results'][name].get('depth',0)>
                           r['results']['official_v2019'].get('depth',0) for r in timed),
        'timed_shallower': sum(r['results'][name].get('depth',0)<
                              r['results']['official_v2019'].get('depth',0) for r in timed),
        'timed_max_ms': max(r['results'][name]['elapsed_ms'] for r in timed),
    }

result = {
    'candidate_binary_sha256': hashlib.sha256(Path(candidate_binary).read_bytes()).hexdigest(),
    'baseline_binary_sha256': hashlib.sha256(Path(baseline_binary).read_bytes()).hexdigest(),
    'source_sha256': hashlib.sha256(Path('research/search-efficiency3-20261015/positions.json').read_bytes()).hexdigest(),
    'conditions': {'positions':24,'repeats':3,'fixed':'go depth 2','timed':'go movetime 200','options':options,'config':config},
    'summary':summary,'rows':[{**r,'results':{name:{k:v for k,v in result.items() if k in ('elapsed_ms','depth','nodes','qnodes','cutoffs','score_cp','score_mate','pvs_probes','pvs_researches','killer_priorities','history_priorities','ordering_updates')} for name,result in r['results'].items()}} for r in measurements],
}
Path(output).parent.mkdir(parents=True,exist_ok=True)
Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({n:{k:v for k,v in row.items() if k not in ('full_mismatches','score_mismatches')} for n,row in summary.items()},indent=2))
# Bounded full-search scores should not change at fixed depth. PV-only / index / ray
# changes must also retain node counts and PVs exactly.
assert all(not summary[n]['score_mismatches'] for n in config), 'fixed-depth score drift'
assert not summary['control']['full_mismatches'], 'disabled probe changes search'
