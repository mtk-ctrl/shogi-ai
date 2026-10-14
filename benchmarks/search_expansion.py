"""Paired search research: one binary, independent masks, legal PV validation."""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
import shogi

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', required=True)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--masks', default='0,1,2,4,8,16,3,7,15,23,31')
    ap.add_argument('--positions', type=int, default=12)
    ap.add_argument('--repeats', type=int, default=2)
    ap.add_argument('--depth', type=int, default=3)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source = Path('benchmarks/results/2026-10-04_iterative-identical-positions.json')
    cases = json.loads(source.read_text())['rows']
    # Include opening, contact, both sides and late positions. No result labels.
    indexes = [0, 5, 10, 15, 24, 25, 28, 29, 32, 33, 34, 35,
               1, 2, 3, 6, 7, 11, 18, 19, 38, 39, 40, 41]
    cases = [cases[i] for i in indexes[:args.positions]]
    options = {'OpeningRandomNonLance': False, 'MateAssist': False,
               'MateLearning': False, 'AdaptiveLongThink': False,
               'PositionKnowledge': True}
    masks = [int(x) for x in args.masks.split(',')]
    engines = {'previous': Engine(args.baseline, 'previous', options)}
    engines.update({str(mask): Engine(args.engine, str(mask),
                    {**options, 'SearchResearchMask': mask}) for mask in masks})
    rows = []
    try:
        for mode, command in [('fixed', f'go depth {args.depth}'), ('timed', 'go movetime 200')]:
            for rep in range(args.repeats):
                for i, case in enumerate(cases):
                    keys = list(engines)
                    offset = (rep + i) % len(keys)
                    keys = keys[offset:] + keys[:offset]
                    if (rep + i) % 2: keys.reverse()
                    measurements = {}
                    for key in keys:
                        e = engines[key]
                        e.configure_game(2026101500 + i)
                        e.go_command = command
                        move = e.bestmove(case['moves'])
                        info = dict(e.last_search)
                        board = shogi.Board()
                        for m in case['moves']: board.push_usi(m)
                        assert shogi.Move.from_usi(move) in board.legal_moves, (key, i, move)
                        for m in info.get('pv', []):
                            assert shogi.Move.from_usi(m) in board.legal_moves, (key, i, m)
                            board.push_usi(m)
                        measurements[key] = {'move': move, **info}
                    rows.append({'mode': mode, 'repeat': rep, 'position': i,
                                 'moves': case['moves'], 'measurements': measurements})
                    print(mode, rep, i, flush=True)
    finally:
        for e in engines.values(): e.close()
    summaries = {}
    fixed = [r for r in rows if r['mode'] == 'fixed']
    timed = [r for r in rows if r['mode'] == 'timed']
    for key in engines:
        mismatches = [r['position'] for r in fixed if any(
            r['measurements'][key].get(field) != r['measurements']['previous'].get(field)
            for field in ['move', 'score_cp', 'score_mate', 'depth'])]
        ratios = [r['measurements']['previous']['elapsed_ms'] / r['measurements'][key]['elapsed_ms'] for r in fixed]
        summaries[key] = {
            'fixed_trials': len(fixed), 'fixed_mismatches': mismatches,
            'median_speedup': statistics.median(ratios),
            'total_speedup': sum(r['measurements']['previous']['elapsed_ms'] for r in fixed) /
                             sum(r['measurements'][key]['elapsed_ms'] for r in fixed),
            'timed_depth_sum': sum(r['measurements'][key].get('depth', 0) for r in timed),
            'timed_nodes_sum': sum(r['measurements'][key].get('nodes', 0) for r in timed),
            'timed_higher': sum(r['measurements'][key].get('depth', 0) > r['measurements']['previous'].get('depth', 0) for r in timed),
            'timed_lower': sum(r['measurements'][key].get('depth', 0) < r['measurements']['previous'].get('depth', 0) for r in timed),
            'fixed_order_hits': sum(r['measurements'][key].get('order_reuse_hits', 0) for r in fixed),
            'fixed_qtt_hits': sum(r['measurements'][key].get('qtt_hits', 0) for r in fixed),
            'timed_elapsed_max_ms': max(r['measurements'][key]['elapsed_ms'] for r in timed),
        }
    result = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'binary_sha256': {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
                                for k, v in [('candidate', args.engine), ('previous', args.baseline)]},
              'options': options, 'depth': args.depth, 'cases': len(cases),
              'repeats': args.repeats, 'summaries': summaries, 'rows': rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summaries, indent=2), flush=True)

if __name__ == '__main__': main()
