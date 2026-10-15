"""Compare the adopted two-lane search with the serial engine's exact values."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine,merge_info_line
import shogi

options={'OpeningRandomNonLance':False,'MateAssist':False,'MateLearning':False,
         'AdaptiveLongThink':False,'PositionKnowledge':True}
engines=[Engine(sys.argv[1],f'lanes-{n}',{**options,'SearchThreads':n}) for n in (1,2)]
default_engine=Engine(sys.argv[1],'lanes-default',options)
cases=[
    (shogi.Board().sfen(),'go depth 2'),
    ('4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1','go depth 3 searchmoves 5h5d 5h4h'),
    ('8k/9/9/9/9/9/2P6/9/K8 b - 1','go depth 3'),
    ('8k/9/9/9/9/9/2P6/9/K8 w - 1','go depth 3'),
    ('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1',
     'go depth 3 searchmoves 5c5b 5i4i'),
]
try:
    # An unset option must really run the adopted two-thread default.
    default_engine.configure_game(5489)
    default_engine.go_command='go depth 2'
    default_engine.bestmove([])
    assert default_engine.last_search.get('search_threads')==2,default_engine.last_search
    for quiescence in (False,True):
        for sfen,command in cases:
            values=[]
            for n,engine in enumerate(engines,1):
                engine.configure_game(5489)
                engine.send('setoption name Quiescence value '+str(quiescence).lower())
                engine.send('position sfen '+sfen);engine.send(command)
                info={}
                while True:
                    line=engine.lines.get(timeout=30)
                    if line.startswith('info '):merge_info_line(info,line)
                    if line.startswith('bestmove '):move=line.split()[1];break
                board=shogi.Board(sfen)
                assert shogi.Move.from_usi(move) in board.legal_moves
                for step in info.get('pv',[]):
                    assert shogi.Move.from_usi(step) in board.legal_moves
                    board.push_usi(step)
                assert info.get('search_threads')==n,info
                values.append((info.get('score_cp'),info.get('score_mate'),info.get('depth')))
            assert values[0]==values[1],(quiescence,sfen,values)
    print('PASS serial/parallel exact score, depth, legal moves/PV, both colors, mate, restricted roots, quiescence OFF/ON')
finally:
    default_engine.close()
    for engine in engines:engine.close()
