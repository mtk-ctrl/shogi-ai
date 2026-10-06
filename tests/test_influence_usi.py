"""Option validation, profile isolation and repeated ON/OFF search transitions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
from benchmarks.influence_validation import evaluation

e=Engine(sys.argv[1],'switch',{'OpeningBook':False,'ExperienceCache':False,'Quiescence':False},'go depth 2')
try:
    moves=['7g7f','3c3d','2g2f','8c8d','2f2e','8d8e','6i7h','4a3b']
    before=evaluation(e,moves);e.configure_game(99);old_move=e.bestmove(moves);old=dict(e.last_search)
    for _ in range(3):
        e.send('setoption name EvalInfluence value true')
        on=evaluation(e,moves)
        for invalid in ('-1','401','bad','12junk'):
            e.send('setoption name EvalInfluenceWeight value '+invalid)
            assert evaluation(e,moves)==on
        e.send('setoption name EvalInfluence value bad');assert evaluation(e,moves)==on
        e.send('setoption name EvalProfile value material')
        material=evaluation(e,moves);assert material['total']==material['material']
        e.send('setoption name EvalProfile value features');assert evaluation(e,moves)==on
        e.configure_game(99);e.bestmove(moves)
        e.send('setoption name EvalInfluence value false');assert evaluation(e,moves)==before
        e.configure_game(99);assert e.bestmove(moves)==old_move
        for key in ('score_cp','score_mate','nodes'):assert e.last_search.get(key)==old.get(key)
    print('PASS influence USI option validation, material isolation and repeated ON/OFF TT transitions')
finally:e.close()
