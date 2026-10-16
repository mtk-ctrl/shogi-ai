"""Differential full-depth search, both colors, tactics, history and all masks."""
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
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

legacy=json.loads(Path('research/search-efficiency3-20261015/positions.json').read_text())['rows'][:24]
played=json.loads(Path('research/v220-root-balance-20261016/played-positions.json').read_text())['rows']
checks=0
for threads in (1,2):
    engines=[Engine(baseline,'formal',{**options,'SearchThreads':threads}),Engine(candidate,'balanced',{**options,'SearchThreads':threads})]
    try:
        for row in legacy+played:
            expected=run(engines[0],row['moves'],'go depth 2')
            for mode in (0,1,2):
                engines[1].send('setoption name SearchRootBalance value '+str(mode))
                actual=run(engines[1],row['moves'],'go depth 2')
                assert score(actual)==score(expected),'score drift'
                assert actual[0]==expected[0],'root choice drift'
                if mode==0 or threads==1:assert exact(actual)==exact(expected),'OFF/serial drift'
                checks+=1
    finally:
        for e in engines:e.close()
print(json.dumps(dict(positions=48,checks=checks,scores_and_moves_equal=True,off_and_serial_exact=True,pvs_legal=True)))
