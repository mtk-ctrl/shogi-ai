"""Third-round switches must preserve the exact bounded search, including nodes."""
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

def run(e, sf, command):
    e.configure_game(2026101591)
    e.send('position sfen ' + sf)
    e.send(command)
    info = {}
    while True:
        line = e.lines.get(timeout=30)
        if line.startswith('info '): merge_info_line(info, line)
        if line.startswith('bestmove '):
            move = line.split()[1]
            break
    board = shogi.Board(sf)
    assert shogi.Move.from_usi(move) in board.legal_moves
    for m in info.get('pv', []):
        assert shogi.Move.from_usi(m) in board.legal_moves
        board.push_usi(m)
    fields = ('score_cp', 'score_mate', 'depth', 'nodes', 'qnodes', 'cutoffs', 'pv')
    return (move, *(info.get(f) for f in fields)), info

e = Engine(sys.argv[1], 'reuse-regression', options)
reference = Engine(sys.argv[2], 'official-v2015', options) if len(sys.argv)>2 else None
try:
    expected = [run(reference, *case)[0] for case in cases] if reference else None
    defaults = [run(e, *case) for case in cases]
    assert all(info['reuse_mask'] == 6 for _, info in defaults)
    if expected is not None: assert [sig for sig, _ in defaults] == expected
    for mask in range(16):
        e.send(f'setoption name SearchReuseMask value {mask}')
        observed = []
        for sf, command in cases:
            signature, info = run(e, sf, command)
            assert info['reuse_mask'] == mask, (mask, info)
            observed.append(signature)
        if expected is None: expected = observed
        assert observed == expected, (mask, observed, expected)
    print('PASS selected research default 6 and all 16 reuse combinations: exact choices/scores/depth/nodes/qnodes/cutoffs/PV and actual mask')
finally:
    e.close()
    if reference: reference.close()
