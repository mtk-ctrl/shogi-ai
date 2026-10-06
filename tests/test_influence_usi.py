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
    e.send('setoption name EvalInfluence value true')
    e.send('setoption name EvalInfluenceLegacyMix value 100');assert evaluation(e,moves)==before
    e.send('setoption name EvalInfluenceLegacyMix value 50')
    e.send('setoption name EvalInfluenceGuardWeight value 75')
    e.send('setoption name EvalInfluencePressureWeight value 200')
    e.send('setoption name EvalInfluenceReinforcementBonus value 0')
    e.send('setoption name EvalInfluenceTempoBonus value 0')
    tuned=evaluation(e,moves)
    for name,limit in [('EvalInfluenceGuardWeight',400),('EvalInfluencePressureWeight',400),
                       ('EvalInfluenceLegacyMix',100),('EvalInfluenceReinforcementBonus',100),('EvalInfluenceTempoBonus',100)]:
        for value in ('-1',str(limit+1),'bad','12junk'):
            e.send('setoption name '+name+' value '+value);assert evaluation(e,moves)==tuned
    e.send('setoption name EvalInfluence value false');assert evaluation(e,moves)==before
    print('PASS independent guard/pressure weights, convex mix and uncertainty bonus validation')
finally:e.close()
