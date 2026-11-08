"""Fixed-depth paired speed/identity check for search-speed research branches.

Runs the same 24 positions with a baseline binary and a candidate binary (optionally
with extra USI options) and reports whether move, score, depth and node counts are
identical, plus the wall-clock ratio. Single search thread for determinism.
"""
import argparse, json, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

ap = argparse.ArgumentParser()
ap.add_argument('--baseline', required=True)
ap.add_argument('--candidate', required=True)
ap.add_argument('--cand-option', action='append', default=[], help='NAME=VALUE for the candidate')
ap.add_argument('--base-option', action='append', default=[], help='NAME=VALUE for the baseline')
ap.add_argument('--depth', type=int, default=4)
ap.add_argument('--repeats', type=int, default=2)
ap.add_argument('--positions', type=int, default=24)
ap.add_argument('--output')
args = ap.parse_args()
cases = json.loads(Path('research/search-efficiency3-20261015/positions.json').read_text())['rows'][:args.positions]
common = {'OpeningRandomNonLance': False, 'MateAssist': False, 'MateLearning': False,
          'AdaptiveLongThink': False, 'PositionKnowledge': True, 'SearchThreads': 1, 'USI_Ponder': False}
def opts(extra):
    o = dict(common)
    for kv in extra:
        k, v = kv.split('=', 1)
        o[k] = v
    return o
engines = {'base': Engine(args.baseline, 'base', opts(args.base_option), f'go depth {args.depth}'),
           'cand': Engine(args.candidate, 'cand', opts(args.cand_option), f'go depth {args.depth}')}
rows, tt = [], {'base': 0.0, 'cand': 0.0}
mism = []
try:
    for rep in range(args.repeats):
        for i, c in enumerate(cases):
            keys = ['base', 'cand'] if (rep + i) % 2 == 0 else ['cand', 'base']
            res = {}
            for k in keys:
                e = engines[k]
                e.configure_game(2026110800 + i)
                e.send('isready'); e.wait_prefix('readyok', 10)
                t = time.perf_counter()
                move = e.bestmove(c['moves'])
                dt = time.perf_counter() - t
                info = dict(e.last_search)
                res[k] = {'move': move, 'dt': dt, **{f: info.get(f) for f in ('score_cp', 'score_mate', 'depth', 'nodes', 'qnodes', 'pv')}}
                tt[k] += dt
            same = all(res['base'][f] == res['cand'][f] for f in ('move', 'score_cp', 'score_mate', 'depth', 'nodes', 'qnodes'))
            if not same and rep == 0: mism.append(i)
            rows.append({'rep': rep, 'pos': i, 'same': same, 'res': res})
finally:
    for e in engines.values(): e.close()
ratios = [r['res']['base']['dt'] / r['res']['cand']['dt'] for r in rows]
summary = {'depth': args.depth, 'cases': len(rows), 'identical': sum(r['same'] for r in rows),
           'mismatch_positions_rep0': mism,
           'total_s': tt, 'speedup_total': tt['base'] / tt['cand'], 'speedup_median': statistics.median(ratios),
           'nodes_base': sum(r['res']['base']['nodes'] or 0 for r in rows),
           'nodes_cand': sum(r['res']['cand']['nodes'] or 0 for r in rows)}
print(json.dumps(summary, indent=1, ensure_ascii=False))
if args.output: Path(args.output).write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1))
