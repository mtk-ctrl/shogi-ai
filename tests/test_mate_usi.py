"""USI go mate integration checks for the bounded self-authored solver."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

engine = Engine(sys.argv[1], 'mate-test')
try:
    exact5 = "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105"
    engine.send('position sfen ' + exact5)
    engine.send('go mate 5000')
    line = engine.wait_prefix('checkmate ', 10)
    moves = line.split()[1:]
    assert len(moves) == 5, line
    assert moves[0] == '2b3b', line
    print('PASS USI go mate returns a five-ply mating line')

    exact7 = "ln2k1l2/5b3/p1p1gs1g1/2PNsp3/3Pp1pp1/P2p1P3/2NG1S2l/5G3/L+rNK5 w BPrs6p 124"
    engine.send('position sfen ' + exact7)
    engine.send('go mate 2000')
    line = engine.wait_prefix('checkmate ', 10)
    moves = line.split()[1:]
    assert len(moves) == 7, line
    print('PASS USI go mate returns a fixed seven-ply mating line')

    engine.send('position sfen 4k4/9/9/9/9/9/9/9/4K4 b - 1')
    engine.send('go mate 50')
    line = engine.wait_prefix('checkmate ', 10)
    assert line == 'checkmate timeout', line
    print('PASS bounded go mate does not claim global nomate beyond seven plies')
finally:
    engine.close()
