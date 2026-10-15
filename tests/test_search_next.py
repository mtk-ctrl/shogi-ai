"""Adopted tier-6 ordering and other diagnostic toggles: legality, score, PV."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine, merge_info_line
import shogi

options = {'OpeningRandomNonLance': False, 'MateAssist': False,
           'MateLearning': False, 'AdaptiveLongThink': False,
           'PositionKnowledge': True, 'EvalProfile': 'material'}
cases = [
    ('4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1', 'go searchmoves 5h5d 5h4h depth 2'),
    ('8k/9/9/9/9/9/2P6/9/K8 b - 1', 'go depth 2'),
    ('8k/9/9/9/9/9/2P6/9/K8 w - 1', 'go depth 2'),
    ('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1', 'go searchmoves 5c5b 5i4i depth 3'),
]

def run(engine, sfen, command):
    engine.configure_game(2026101591)
    engine.send('position sfen ' + sfen)
    engine.send(command)
    info = {}
    while True:
        line = engine.lines.get(timeout=60)
        if line.startswith('info '):
            merge_info_line(info, line)
        if line.startswith('bestmove '):
            move = line.split()[1]
            break
    board = shogi.Board(sfen)
    assert shogi.Move.from_usi(move) in board.legal_moves, (sfen, move)
    for step in info.get('pv', []):
        parsed = shogi.Move.from_usi(step)
        assert parsed in board.legal_moves, (sfen, command, info)
        board.push(parsed)
    return move, info

# Verify the formal default chooses exactly the tested tier-6 setting.
default_engine = Engine(sys.argv[1], 'next-default', options)
tier6_engine = Engine(sys.argv[1], 'next-tier6', {**options, 'SearchNextMask': 4})
try:
    for case in cases:
        assert run(default_engine, *case) == run(tier6_engine, *case), (
            'default must use SearchNextMask=4', case)
finally:
    default_engine.close()
    tier6_engine.close()

engine = Engine(sys.argv[1], 'next-adopted', {**options, 'SearchNextMask': 0})
try:
    baseline = [run(engine, *case) for case in cases]
    signature = lambda pair: (
        pair[0], pair[1].get('score_cp'), pair[1].get('score_mate'),
        pair[1].get('depth'), pair[1].get('nodes'), pair[1].get('qnodes'),
        pair[1].get('cutoffs'), pair[1].get('pv'))
    baseline_full = [signature(x) for x in baseline]
    baseline_scores = [(x[1].get('score_cp'), x[1].get('score_mate')) for x in baseline]
    for reuse in (6, 14):
        engine.send(f'setoption name SearchReuseMask value {reuse}')
        for next_mask in (0, 1, 2, 4, 8, 9, 10, 12, 15):
            engine.send(f'setoption name SearchNextMask value {next_mask}')
            for case_index, case in enumerate(cases):
                move, info = run(engine, *case)
                assert info.get('reuse_mask') == reuse, (reuse, info)
                if next_mask in (0, 1):
                    assert signature((move, info)) == baseline_full[case_index], (
                        reuse, next_mask, case_index, signature((move, info)), baseline_full[case_index])
                # Different move order and cross-depth TT can change PV or cutoff nodes,
                # but must preserve the bounded minimax/alpha-beta score.
                if next_mask in (2, 4, 8, 9, 10, 12, 15):
                    assert (info.get('score_cp'), info.get('score_mate')) == baseline_scores[case_index], (
                        reuse, next_mask, case_index, info, baseline_scores[case_index])
    print('PASS 2 ray strategies x 9 independent/combined flags: bounded value, legal PV, fixed-depth equality where required')
finally:
    engine.close()
