"""OFF exactness, real leaf activation, fixed-model inference and recovery."""
import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile

import numpy as np
import shogi

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from benchmarks.arena import Engine,merge_info_line
spec=importlib.util.spec_from_file_location('learn',ROOT/'research/selfplay-learning-20261016/learn.py')
learn=importlib.util.module_from_spec(spec);spec.loader.exec_module(learn)
baseline,candidate=sys.argv[1:3]
embedded_model=Path(sys.argv[3]) if len(sys.argv)>3 else None
options=dict(OpeningRandomNonLance=False,MateAssist=False,MateLearning=False,
             AdaptiveLongThink=False,PositionKnowledge=True,USI_Ponder=False)
cases=[([], 'go depth 2'),
       ('4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1','go depth 3 searchmoves 5h5d 5h4h'),
       ('8k/9/9/9/9/9/2P6/9/K8 b - 1','go depth 3'),
       ('8k/9/9/9/9/9/2P6/9/K8 w - 1','go depth 3'),
       ('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1','go depth 3 searchmoves 5c5b 5i4i'),
       ('4k4/9/9/9/9/9/9/9/4K4 b P 1','go depth 2'),
       ('8k/4r4/9/9/9/9/9/9/K8 b P 1','go depth 2'),
       (['7i6h','3a4b','6h7i','4b3a'],'go depth 2')]
board=shogi.Board();moves=[];rng=random.Random(2026101601)
for ply in range(48):
    moves.append(rng.choice(list(board.legal_moves)).usi());board.push_usi(moves[-1])
    if ply in (5,12,19,26,33,40,47):cases.append((list(moves),'go depth 2'))

def position(e,p):
    b=shogi.Board(p) if isinstance(p,str) else shogi.Board()
    if not isinstance(p,str):
        for m in p:b.push_usi(m)
    e.send('position sfen '+p if isinstance(p,str) else 'position startpos moves '+' '.join(p))
    return b

def run(e,p,go):
    e.configure_game(5489);b=position(e,p);e.send(go);info={}
    while True:
        line=e.lines.get(timeout=60)
        if line.startswith('info '):merge_info_line(info,line)
        if line.startswith('bestmove '):move=line.split()[1];break
    assert shogi.Move.from_usi(move) in b.legal_moves
    for step in info.get('pv',[]):
        assert shogi.Move.from_usi(step) in b.legal_moves;b.push_usi(step)
    return (move,*(info.get(k) for k in ('score_cp','score_mate','depth','nodes','qnodes','cutoffs','pv'))),info

def evaluate(e,p):
    position(e,p);e.send('eval')
    tokens=e.wait_prefix('info string evaluation ',10).split()[3:]
    return {k:int(v) for k,v in zip(tokens[::2],tokens[1::2])}

with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp);model=learn.Residual(8,600);rng=np.random.default_rng(47)
    model.w1=rng.normal(0,.4,(8,12));model.w2=rng.normal(0,.4,8)
    if embedded_model:model=learn.Residual.from_text(embedded_model.read_text())
    model_path=tmp/'model.txt';model_path.write_text(model.text())
    checks=0;active=0;static_checks=0
    for threads in (1,2):
        a=Engine(baseline,'A',{**options,'SearchThreads':threads})
        b=Engine(candidate,'B',{**options,'SearchThreads':threads,'SelfPlayEvalFile':'embedded' if embedded_model else str(model_path)})
        try:
            for q in (False,True):
                for e in (a,b):e.send('setoption name Quiescence value '+str(q).lower())
                for p,go in cases:
                    expected,_=run(a,p,go)
                    for enabled,scale in ((False,100),(True,0)):
                        b.send('setoption name SelfPlayEval value '+str(enabled).lower())
                        b.send('setoption name SelfPlayEvalScale value '+str(scale))
                        actual,_=run(b,p,go);assert actual==expected,('OFF/zero drift',p,threads,q)
                        checks+=1
                    b.send('setoption name SelfPlayEval value true');b.send('setoption name SelfPlayEvalScale value 100')
                    actual,info=run(b,p,go);assert info['learned_eval']==1 and info['learned_scale']==100
                    active+=1
            for p,_ in cases:
                base=evaluate(a,p)
                turn=p.split()[1] if isinstance(p,str) else ('b' if len(p)%2==0 else 'w')
                x=[base['material_term']/3000]+[base[k]/1000 for k in learn.TERMS]+[base['clamp']/1000,1 if turn=='b' else -1]
                raw=float(model.predict(np.array([x]))[0]);correction=int(np.sign(raw)*np.floor(abs(raw)+.5))
                actual=evaluate(b,p);assert actual['total']==base['total']+correction,(p,actual,base,correction)
                static_checks+=1
            reload_expected=evaluate(b,cases[1][0])
            b.send('setoption name SelfPlayEvalFile value '+str(tmp/'missing'))
            assert evaluate(b,cases[1][0])==evaluate(a,cases[1][0]),'stale model after missing file'
            b.send('setoption name SelfPlayEvalFile value '+str(model_path))
            assert evaluate(b,cases[1][0])==reload_expected,'reload did not restore model'
            assert run(b,*cases[1])[1]['learned_eval']==1,'reload did not reactivate'
            b.send('setoption name EvalProfile value material');a.send('setoption name EvalProfile value material')
            assert evaluate(b,cases[1][0])==evaluate(a,cases[1][0]),'material diagnostic must remain exact'
        finally:a.close();b.close()
    print(json.dumps({'off_or_zero_exact_checks':checks,'active_legal_searches':active,
                      'python_cpp_static_checks':static_checks,'missing_reload_material':'PASS'}))
