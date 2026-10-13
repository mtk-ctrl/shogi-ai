"""Allocation and adversarial telemetry checks for multi-profile studies."""
import copy
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
from variable_eval_search import allocation,audit,load_plan,options,KNOWLEDGE_HASH,interval

plan,registry=load_plan('round2-coarse')
lanes=allocation(plan,10)
assert len(registry)>=71 and len(plan['profiles'])==40
assert [sum(f['games'] for f in lane) for lane in lanes]==[96]*10

def check_coverage(p,lanes):
    games=Counter()
    for lane in lanes:
        for f in lane:
            for i in range(f['games']):
                games[(f['profile'],f['baseline'],f['offset']+i)]+=1
                assert f['seed']+i*2==p['seeds'][f['baseline']]+(f['offset']+i)*2
    assert len(games)==len(p['profiles'])*2*p['games_per_baseline']
    assert set(games.values())=={1}
    for profile in p['profiles']:
        for baseline in ['M','Q14']:
            assert [g for (a,b,g) in games if (a,b)==(profile,baseline)]==list(range(p['games_per_baseline']))
check_coverage(plan,lanes)
follow=dict(plan,stage='followup',profiles=plan['profiles'][:8],games_per_baseline=24)
follow_lanes=allocation(follow,10)
assert max(sum(f['games'] for f in l) for l in follow_lanes)-min(sum(f['games'] for f in l) for l in follow_lanes)==1
check_coverage(follow,follow_lanes)
for n in [0,11,True]:
    try: allocation(plan,n)
    except ValueError: pass
    else: raise AssertionError('runner limit not enforced')
try: allocation(follow,1)
except ValueError: pass
else: raise AssertionError('timeout-safe lane limit not enforced')

f={'profile':32,'baseline':'M','offset':0,'games':2,'seed':plan['seeds']['M']}
k={'enabled':True,'available':True,'positions':163,'sha256':KNOWLEDGE_HASH}
data=dict(games=2,seed=f['seed'],game_offset=0,max_plies=300,go_command=plan['go_command'],
    options_a=options(32,plan),options_b=options(1,plan),sha256_a='0'*64,sha256_b='0'*64,
    position_knowledge={'A':k,'B':k},wins_a=1,draws=1,wins_b=0,illegal_games=0,
    details=[dict(winner=winner,a_black=(i==0),plies=2,moves=['7g7f','3c3d'],
        move_records=[{'engine':side,'search':{'phase_maturity':10,
            'phase_research_profile':32 if side=='A' else 1}}
            for side in (['A','B'] if i==0 else ['B','A'])])
        for i,winner in enumerate(['A',None])])
assert audit(data,f,plan)==(1,1,0)
broken=copy.deepcopy(data);broken['details'][0]['move_records'][0]['search']['phase_research_profile']=0
try: audit(broken,f,plan)
except ValueError: pass
else: raise AssertionError('ignored profile option must invalidate the experiment')
broken=copy.deepcopy(data);broken['position_knowledge']['B']['positions']=153
try: audit(broken,f,plan)
except ValueError: pass
else: raise AssertionError('knowledge mismatch must invalidate the experiment')
broken=copy.deepcopy(data);broken['details'][0]['move_records'][0]['search']['long_think_used']=1
try: audit(broken,f,plan)
except ValueError: pass
else: raise AssertionError('long think in fast stage must invalidate the experiment')
assert interval(0,10,0)[1][0]<.5<interval(0,10,0)[1][1]
assert 0<interval(12,0,0)[1][0]<1
print('PASS balanced coverage/seed preservation, runner/timeout limits and rejected invalid telemetry')
