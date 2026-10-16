#!/usr/bin/env python3
"""Read back the standard played-move archive; retain metrics, never PVs."""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

import shogi


def wilson(wins, games):
    z = 1.959963984540054
    p = wins / games
    c = (p + z*z/(2*games)) / (1 + z*z/games)
    h = z*math.sqrt(p*(1-p)/games + z*z/(4*games*games))/(1+z*z/games)
    return [c-h, c+h]


def audit(directory):
    root = Path(directory)
    aggregate = json.loads((root / 'aggregate.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    archive = root / manifest['archive']
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest == manifest['archive_sha256']
    with gzip.open(archive, 'rt') as f:
        games = [json.loads(line) for line in f]
    assert len(games) == manifest['games'] == aggregate['games']
    assert sum(len(g['moves']) for g in games) == manifest['plies']
    assert len({g['game_id'] for g in games}) == len(games)
    sources = {s['source_id']: s for s in manifest['sources']}
    assert len(sources) == aggregate['shards']
    expected_knowledge = aggregate['position_knowledge']
    assert aggregate['games'] == 200 and aggregate['illegal_games'] == 0
    assert aggregate['ref_a'] == 'f34ffd4745836b81d5e8eb80f9c53a9c681bc2ed'
    assert aggregate['ref_b'] == '8d19b5453173d2fb7489aefe07fbbd018f30a5ad'
    assert aggregate['options_a']['SearchProbeMask'] in (1, 3)
    for label in ('a', 'b'):
        opts = aggregate['options_' + label]
        assert opts['SearchThreads'] == 2
        assert all(opts[k] for k in ('AdaptiveLongThink', 'PositionKnowledge',
                                    'OpeningRandomNonLance', 'RiskVerify', 'USI_Ponder'))
    assert expected_knowledge['A'] == expected_knowledge['B']
    assert expected_knowledge['A']['enabled'] and expected_knowledge['A']['available']
    assert expected_knowledge['A']['positions'] == 163
    assert expected_knowledge['A']['sha256'] == '6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'
    hashes = {}
    for side in ('A', 'B'):
        metadata = [s['metadata'] for s in sources.values()]
        assert all(m['options_' + side.lower()] == aggregate['options_' + side.lower()] for m in metadata)
        assert all(m['go_command'] == 'go movetime 200' for m in metadata)
        assert all(m['position_knowledge'] == expected_knowledge for m in metadata)
        assert all(m['options_' + side.lower()]['AdaptiveLongThink'] for m in metadata)
        hashes[side] = sorted({m['sha256_' + side.lower()] for m in metadata})
        assert len(hashes[side]) == 1
    results = collections.Counter(g['winner'] for g in games)
    assert results['A'] == aggregate['wins_a'] and results['B'] == aggregate['wins_b']
    assert results.get(None, 0) == aggregate['draws']
    raw_paths = sorted((root / 'shards').glob('shard-*.json'))
    assert len(raw_paths) == len(sources), 'download every raw shard for ponder usage audit'
    ponder = {side: {'hits': 0, 'misses': 0} for side in ('A', 'B')}
    raw_hashes = set()
    for path in raw_paths:
        raw = path.read_bytes()
        digest_raw = hashlib.sha256(raw).hexdigest()
        assert digest_raw in sources
        raw_hashes.add(digest_raw)
        shard = json.loads(raw)
        for side in ponder:
            for key in ('hits', 'misses'):
                value = shard['ponder'][side][key]
                assert isinstance(value, int) and value >= 0
                ponder[side][key] += value
    assert raw_hashes == set(sources)
    for side, counts in ponder.items():
        assert counts['hits'] + counts['misses'] > 0
        counts['hit_rate_when_prediction_available'] = counts['hits'] / sum(counts.values())
    color = {}
    samples = {'A': [], 'B': []}
    long_counts = {'A': [], 'B': []}
    reasons = collections.Counter()
    signatures = collections.Counter()
    for g in games:
        board = shogi.Board()
        assert 0 <= g['plies'] <= 300
        positions = [' '.join(board.sfen().split()[:3])]
        checks = []
        counts = collections.Counter()
        assert len(g['moves']) == g['plies']
        for ply, row in enumerate(g['moves'], 1):
            move = shogi.Move.from_usi(row['move'])
            assert move in board.legal_moves, (g['game_id'], ply, row['move'])
            assert row['ply'] == ply
            assert row['side_to_move'] == ('black' if board.turn == shogi.BLACK else 'white')
            expected = 'A' if (board.turn == shogi.BLACK) == g['a_black'] else 'B'
            assert row['engine'] == expected
            info = row.get('search', {})
            samples[expected].append(info)
            if 'long_think_used' in info:
                counts[expected] += 1
                assert info['long_think_used'] == counts[expected] <= 10
                assert info['long_think_base_ms'] == 200 and info['long_think_max_ms'] == 1000
            board.push(move)
            checks.append((board.turn ^ 1, board.is_check()))
            positions.append(' '.join(board.sfen().split()[:3]))
        assert board.sfen() == g['final_sfen'], g['game_id']
        if g['reason'] == 'checkmate':
            assert board.is_checkmate()
            winning_color = board.turn ^ 1
            assert g['winner'] == ('A' if (winning_color == shogi.BLACK) == g['a_black'] else 'B')
        if g['reason'] == 'move_limit':
            assert g['plies'] == 300 and g['winner'] is None
        if g['reason'] in ('fourfold_repetition', 'perpetual_check'):
            occurrences = [i for i, key in enumerate(positions) if key == positions[-1]]
            assert len(occurrences) >= 4
            interval = checks[occurrences[-4]:]
            continuous = [color for color in (shogi.BLACK, shogi.WHITE)
                          if all(check for mover, check in interval if mover == color)]
            if g['reason'] == 'fourfold_repetition':
                assert not continuous and g['winner'] is None
            else:
                assert continuous
                winning_color = continuous[0] ^ 1
                assert g['winner'] == ('A' if (winning_color == shogi.BLACK) == g['a_black'] else 'B')
        reasons[g['reason']] += 1
        signatures[tuple(row['move'] for row in g['moves'])] += 1
        for side in ('A', 'B'):
            long_counts[side].append(counts[side])
    for is_black, name in ((True, 'A_black'), (False, 'A_white')):
        subset = [g for g in games if g['a_black'] == is_black]
        color[name] = dict(games=len(subset), wins=sum(g['winner'] == 'A' for g in subset),
                           losses=sum(g['winner'] == 'B' for g in subset))
    assert abs(color['A_black']['games'] - color['A_white']['games']) <= 1
    observed = {}
    for side, rows in samples.items():
        elapsed = sorted(r['elapsed_ms'] for r in rows if 'elapsed_ms' in r)
        depths = [r['depth'] for r in rows if 'depth' in r]
        observed[side] = {
            'played_moves': len(rows),
            'depth_recorded_moves': len(depths),
            'mean_completed_depth_on_recorded_moves': statistics.mean(depths),
            'nodes_total': sum(r.get('nodes', 0) for r in rows),
            'wall_ms_median': statistics.median(elapsed),
            'wall_ms_p95': elapsed[math.ceil(.95*len(elapsed))-1],
            'wall_ms_max': max(elapsed),
            'wall_over_1100ms': sum(t > 1100 for t in elapsed),
            'long_think_moves': sum(long_counts[side]),
            'maximum_long_thinks_per_game': max(long_counts[side]),
            **{key: sum(r.get(key, 0) for r in rows) for key in
               ('knowledge_probes', 'knowledge_hits', 'knowledge_promotions')},
        }
    out = {
        'run_id': manifest['run_id'],
        'requested_ref_a': manifest['requested_ref_a'],
        'requested_ref_b': manifest['requested_ref_b'],
        'go_command': aggregate['go_command'],
        'options_a': aggregate['options_a'],
        'options_b': aggregate['options_b'],
        'shards': aggregate['shards'],
        'archive_sha256': digest,
        'archive_bytes': archive.stat().st_size,
        'games': len(games), 'plies': manifest['plies'],
        'wins_a': results['A'], 'draws': results.get(None, 0), 'wins_b': results['B'],
        'score_a': aggregate['score_a'],
        'score_a_approx_95_interval': aggregate['score_a_approx_95pct'],
        'color_assignment': color,
        'all_moves_legal_and_final_positions_verified': True,
        'termination_reasons': dict(reasons),
        'duplicate_complete_move_sequences': sum(n-1 for n in signatures.values()),
        'binary_sha256': hashes,
        'position_knowledge': expected_knowledge,
        'observed': observed,
        'ponder': ponder,
        'resource_note': ('Both engines use two search threads and USI pondering; up to four search '
                          'threads may run concurrently on a lane. CPU-seconds and energy were not '
                          'measured. This is not a single-thread or ponder-disabled comparison.'),
        'missing_score_plies': manifest['missing_score_plies'],
        'phase_missing_plies': manifest['phase_missing_plies'],
        'timing_note': 'Wall time includes reconstruction and USI I/O; depths/nodes in different game positions are descriptive, not controlled speed comparisons.',
        'storage': 'Actions artifacts expire after 90 days; not permanent Release storage.',
    }
    if not aggregate['draws']:
        out['wilson_95_interval_a'] = wilson(results['A'], len(games))
        n, k = len(games), min(results['A'], results['B'])
        out['two_sided_binomial_p_equal_strength'] = min(1., 2*sum(math.comb(n, i) for i in range(k+1))/2**n)
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('directory')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = audit(args.directory)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
