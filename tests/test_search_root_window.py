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
usage = {k:0 for k in ('root_window_probes','root_window_fail_low','root_window_fail_high')}
for threads in (1, 2):
    engines = [Engine(baseline, 'formal-v220', {**options,'SearchThreads':threads}),
               Engine(candidate, 'root-window-candidate', {**options,'SearchThreads':threads})]
    try:
        for quiescence in (False, True):
            for e in engines: e.send('setoption name Quiescence value '+str(quiescence).lower())
            for probe_mask in (0, 3):
                for e in engines: e.send('setoption name SearchProbeMask value '+str(probe_mask))
                for case in cases:
                    expected = run(engines[0], *case)
                    for width in (0, 1, 50, 200, 600, 2000):
                        engines[1].send('setoption name SearchRootWindow value '+str(width))
                        actual = run(engines[1], *case)
                        assert actual[1].get('root_window') == width
                        assert score(actual) == score(expected), (threads,quiescence,probe_mask,width,case,score(expected),score(actual))
                        assert actual[0] == expected[0], (threads,quiescence,probe_mask,width,case,'root tie choice drift')
                        if width == 0:
                            assert exact(actual) == exact(expected), 'disabled drift'
                            assert actual[1].get('root_window_probes',0) == 0
                        for key in usage: usage[key] += actual[1].get(key,0)
                        checks += 1
    finally:
        for e in engines: e.close()
assert all(usage.values()), usage
print(json.dumps(dict(checks=checks,cases=len(cases),scores_and_moves_equal=True,
                     zero_exact=True,all_pv_legal=True,usage=usage)))
