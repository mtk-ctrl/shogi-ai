"""All research combinations preserve known tactics, score and legal PVs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine, merge_info_line
import shogi

e = Engine(sys.argv[1], 'research-regression', {
    'OpeningRandomNonLance': False, 'MateAssist': False,
    'MateLearning': False, 'AdaptiveLongThink': False,
    'PositionKnowledge': True, 'EvalProfile': 'material',
})
cases = [
    ('4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1',
     'go searchmoves 5h5d 5h4h depth 2', '5h4h', None),
    ('8k/9/9/9/9/9/2P6/9/K8 b - 1', 'go depth 2', None, 120),
    ('8k/9/9/9/9/9/2P6/9/K8 w - 1', 'go depth 2', None, -120),
    ('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1',
     'go searchmoves 5c5b 5i4i depth 3', '5c5b', None),
]
try:
    for mask in range(32):
        e.send(f'setoption name SearchResearchMask value {mask}')
        for sf, command, expected_move, expected_cp in cases:
            e.configure_game(20261015)
            e.send('position sfen ' + sf)
            e.send(command)
            info = {}
            while True:
                line = e.lines.get(timeout=30)
                if line.startswith('info '): merge_info_line(info, line)
                if line.startswith('bestmove '):
                    move = line.split()[1]
                    break
            assert info['research_mask'] == mask, (mask, info)
            board = shogi.Board(sf)
            assert shogi.Move.from_usi(move) in board.legal_moves
            for m in info.get('pv', []):
                assert shogi.Move.from_usi(m) in board.legal_moves, (mask, sf, info)
                board.push_usi(m)
            if expected_move: assert move == expected_move, (mask, sf, move)
            if expected_cp is not None: assert info['score_cp'] == expected_cp, (mask, sf, info)
            if '5c5b' in command: assert info['score_mate'] == 3, (mask, info)
    print('PASS all 32 combinations: poisoned pawn, both-color scores, mate distance, legal PV, actual mask')
finally:
    e.close()
