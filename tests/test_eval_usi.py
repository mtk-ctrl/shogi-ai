"""Production USI profile/weight/promotion integration checks."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
import shogi

probe = subprocess.run(
    [sys.argv[1]], input='usi\nquit\n', text=True, capture_output=True, check=True
).stdout
for expected in [
    'option name EvalSafety type spin default 500 ',
    'option name EvalPressure type spin default 474 ',
    'option name EvalActivity type spin default 150 ',
    'option name EvalDanger type spin default 200 ',
    'option name EvalV2 type check default true',
    'option name EvalMaterialWeight type spin default 100 ',
    'option name EvalInfluence type spin default 19 ',
    'option name EvalPotential type spin default 25 ',
    'option name EvalCoordination type spin default 50 ',
    'option name EvalHandPotential type spin default 60 ',
    'option name EvalThreat type spin default 0 ',
    'option name EvalPositionalCap type spin default 5000 ',
]:
    assert expected in probe, expected

engine = Engine(sys.argv[1], 'test')
def fixture(pieces, turn='b'):
    b = shogi.Board(); b.clear()
    for square, piece in pieces.items():
        b.set_piece_at(shogi.SQUARE_NAMES.index(square), shogi.Piece.from_symbol(piece))
    b.turn = turn == 'w'
    return b.sfen()
def position(sf):
    engine.send('position sfen '+sf)
def best(candidates):
    engine.send('go searchmoves '+' '.join(candidates))
    return engine.wait_prefix('bestmove ', 30).split()[1]
def evaluate():
    engine.send('eval')
    tokens = engine.wait_prefix('info string evaluation ', 10).split()[3:]
    return dict(zip(tokens[::2], map(int, tokens[1::2])))
try:
    for piece, source, target in [('P','5c','5b'),('B','5d','4c'),('R','5d','5c')]:
        for white in [False, True]:
            rotate = lambda s: str(10-int(s[0]))+chr(ord('i')-(ord(s[1])-ord('a')))
            pcs = {'9i':'K','1a':'k',source:piece}
            move = source+target
            if white:
                pcs = {rotate(k):v.swapcase() for k,v in pcs.items()}
                move = rotate(source)+rotate(target)
            position(fixture(pcs, 'w' if white else 'b'))
            for seed in (1, 17, 5489):
                engine.send(f'setoption name RandomSeed value {seed}')
                assert best([move,move+'+']) == move+'+'
            assert best([move]) == move  # explicit single searchmoves remains supported
    for piece, source, target in [('S','5d','4c'),('N','5e','4c'),('L','5d','5c')]:
        position(fixture({'9i':'K','1a':'k',source:piece}))
        assert best([source+target]) == source+target
    print('PASS USI promotes P/B/R for both colors; retains S/N/L and explicit searchmoves')

    position(fixture({'5i':'K','1a':'k','5h':'G','4h':'S'}))
    engine.send('setoption name EvalSafety value 100')
    original = evaluate(); assert original['safety'] > 0
    assert original['safety_black_points'] > original['safety_white_points']
    assert original['safety_black_gold_guards'] == 1
    assert original['safety_black_silver_guards'] == 1
    assert original['safety_black_pawn_guards'] == 0
    assert original['safety_white_gold_guards'] == 0
    assert original['safety_white_silver_guards'] == 0
    assert original['safety_white_pawn_guards'] == 0
    engine.send('setoption name EvalSafety value 0'); disabled = evaluate()
    assert disabled['safety'] == 0 and original['total']-disabled['total'] == original['safety']
    for invalid in ['-1','10001','12junk','999999999999999999999999','x']:
        engine.send('setoption name EvalSafety value '+invalid); assert evaluate() == disabled
    engine.send('setoption name EvalProfile value material'); material = evaluate()
    assert material['total'] == material['material']
    assert all(material[n] == 0 for n in ['safety','pressure','activity','danger','clamp'])
    engine.send('setoption name EvalSafety value 100')
    engine.send('setoption name EvalProfile value features'); assert evaluate() == original
    print('PASS USI independent weights, validation, profile switch and exact breakdown')
finally:
    engine.close()
