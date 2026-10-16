"""Differential full-depth search, both colors, tactics, history and all masks."""
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine, merge_info_line
import shogi

baseline, candidate = sys.argv[1:3]
options = dict(OpeningRandomNonLance=False, MateAssist=False, MateLearning=False,
               AdaptiveLongThink=False, PositionKnowledge=True, USI_Ponder=False)
cases = [
    ([], 'go depth 2'),
    ('4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1', 'go depth 3 searchmoves 5h5d 5h4h'),
    ('8k/9/9/9/9/9/2P6/9/K8 b - 1', 'go depth 3'),
    ('8k/9/9/9/9/9/2P6/9/K8 w - 1', 'go depth 3'),
    ('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1', 'go depth 3 searchmoves 5c5b 5i4i'),
    ('4k4/9/9/9/9/9/9/9/4K4 b P 1', 'go depth 2 searchmoves P*5e 5i4i'),
    ('8k/4r4/9/9/9/9/9/9/K8 b P 1', 'go depth 2 searchmoves P*5e 9i8i'),
    (['7i6h','3a4b','6h7i','4b3a'], 'go depth 2'),
]
rng = random.Random(2026101601)
board = shogi.Board()
moves = []
for ply in range(48):
    if board.is_game_over(): break
    moves.append(rng.choice(list(board.legal_moves)).usi())
    board.push_usi(moves[-1])
    if ply in (5,12,19,26,33,40,47): cases.append((list(moves), 'go depth 2'))


def run(e, position, command):
    e.configure_game(5489)
    b = shogi.Board(position) if isinstance(position, str) else shogi.Board()
    if not isinstance(position, str):
        for move in position: b.push_usi(move)
    e.send('position sfen '+b.sfen() if isinstance(position, str)
           else 'position startpos'+(' moves '+' '.join(position) if position else ''))
    e.send(command)
    info = {}
    while True:
        line = e.lines.get(timeout=60)
        if line.startswith('info '): merge_info_line(info, line)
        if line.startswith('bestmove '): move = line.split()[1]; break
    assert shogi.Move.from_usi(move) in b.legal_moves, (position, command, move)
    for step in info.get('pv', []):
        m = shogi.Move.from_usi(step)
        assert m in b.legal_moves, (position, command, info, b.sfen())
        b.push(m)
    return move, info


def score(x): return tuple(x[1].get(k) for k in ('score_cp','score_mate','depth'))
def exact(x): return (x[0], *(x[1].get(k) for k in ('score_cp','score_mate','depth','nodes','qnodes','cutoffs','pv')))

checks = 0
fast_calls = 0
lazy_calls = 0
lazy_snapshots = 0
for threads in (1, 2):
    engines = [Engine(baseline, 'formal-v220', {**options,'SearchThreads':threads}),
               Engine(candidate, 'ordering-candidate', {**options,'SearchThreads':threads})]
    try:
        assert exact(run(engines[0], *cases[0])) == exact(run(engines[1], *cases[0])), 'default drift'
        for quiescence in (False, True):
            for e in engines: e.send('setoption name Quiescence value '+str(quiescence).lower())
            for mask in (0, 1, 2, 3, 7):
                for e in engines: e.send('setoption name SearchProbeMask value '+str(mask))
                for case in cases:
                    expected = run(engines[0], *case)
                    for enabled in (False, True):
                        for lazy in (False, True):
                            engines[1].send('setoption name SearchOrderingFast value '+str(enabled).lower())
                            engines[1].send('setoption name SearchOrderingLazySnapshot value '+str(lazy).lower())
                            actual = run(engines[1], *case)
                            assert exact(actual) == exact(expected), (threads,quiescence,mask,enabled,lazy,case,'search drift')
                            counters = ('seldepth','tt_probes','tt_hits','knowledge_probes','knowledge_hits',
                                        'knowledge_promotions','pvs_probes','pvs_researches',
                                        'killer_priorities','history_priorities','ordering_updates')
                            assert all(actual[1].get(k) == expected[1].get(k) for k in counters), (mask,case,'counter drift')
                            calls = actual[1].get('killer_fast_calls',0)
                            copies = actual[1].get('killer_lazy_snapshots',0)
                            if not enabled or mask not in (2,3): assert calls == 0
                            if not enabled or not lazy or mask not in (2,3): assert copies == 0
                            assert copies <= calls
                            if lazy:
                                lazy_calls += calls
                                lazy_snapshots += copies
                            fast_calls += calls
                            checks += 1
    finally:
        for e in engines: e.close()
assert fast_calls > 0
assert 0 < lazy_snapshots < lazy_calls
print(json.dumps(dict(checks=checks,cases=len(cases),all_fingerprints_equal=True,
                     both_threads=True,all_pv_legal=True,fast_calls=fast_calls,lazy_calls=lazy_calls,lazy_snapshots=lazy_snapshots)))
