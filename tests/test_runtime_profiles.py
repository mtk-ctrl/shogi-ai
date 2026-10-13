"""Check real USI profile selection against the static diagnosis probe."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from arena import Engine, parse_info_line

engine_path,probe_path=sys.argv[1:3]
fixtures=[
    'lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1',
    '4k4/9/4p4/3pPp3/3S1S3/4R4/9/4G4/4K4 b 2Pbg 50',
    '4k4/3r5/9/4s4/4P4/4S4/9/4G4/4K4 w BP2p 90',
]
expected=[json.loads(x) for x in subprocess.check_output([probe_path],
    input='\n'.join(fixtures)+'\n',text=True).splitlines()]
e=Engine(engine_path,'test',{'PositionKnowledge':True,'MateAssist':False,
    'MateLearning':False,'AdaptiveLongThink':False})
try:
    for sfen,row in zip(fixtures,expected):
        for profile in row['profiles']:
            i=profile['index']
            e.send(f'setoption name ResearchProfile value {i}')
            assert e.wait_prefix('info string research_profile_selected ',10)==f'info string research_profile_selected {i}'
            e.send('position sfen '+sfen);e.send('eval')
            tokens=e.wait_prefix('info string evaluation ',10).split()[3:]
            actual=dict(zip(tokens[::2],map(int,tokens[1::2])))
            assert actual['total']==profile['total'],(i,sfen,actual,profile)
            assert actual['material_term']==profile['material_term']
            terms=['safety','pressure','activity','danger','influence','potential',
                   'coordination','hand_potential','threat']
            assert [actual[k] for k in terms]==profile['terms']
    for i in range(len(expected[0]['profiles'])):
        e.send(f'setoption name ResearchProfile value {i}')
        e.wait_prefix('info string research_profile_selected ',10)
        e.send('position startpos');e.send('go depth 1 searchmoves 7g7f')
        phase=e.wait_prefix('info string phase ',10)
        assert parse_info_line(phase)['phase_research_profile']==i
        assert e.wait_prefix('bestmove ',10)=='bestmove 7g7f'
    print('PASS runtime USI: all profiles match 3 static fixtures and actual move profile records')
finally:
    e.close()
