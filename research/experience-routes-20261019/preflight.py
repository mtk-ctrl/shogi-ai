"""Actual USI checks: unchanged OFF, legal hints, retention, time and cost."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.research.postgame_routes import OwnAnalyzer,dump,key
from tools.research.postgame_analyze import exact_cp
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.postgame_cases import load_archive,make_case

def probe(binary,knowledge,case,modes=(),depth=None,extra=None,ms=200):
    e=OwnAnalyzer(binary,knowledge,modes=modes)
    try:
        if extra:
            for name,value in extra.items():e.send('setoption name '+name+' value '+str(value).lower())
        return e.search(case['start_sfen'],tuple(case['history_moves']),ms,depth,include_telemetry=True)
    finally:e.close()

def run(binary,parent,knowledge,research,output,source):
    rows=json.loads(Path(research).read_text());report=dict(disabled_exact=True,retention=[],targets=[],cost=[])
    fields=('bestmove','kind','value_stm','depth','bound','status')
    for row in rows[:8]:
        case=row['case'];a=probe(parent,knowledge,case,depth=2,extra={'SearchThreads':1});b=probe(binary,knowledge,case,depth=2,extra={'SearchThreads':1})
        same=all(a[k]==b[k] for k in fields) and a['played_telemetry'].get('nodes')==b['played_telemetry'].get('nodes')
        report['disabled_exact'] &= same
    for case in tactical_cases():
        frames=[probe(binary,knowledge,case,modes) for modes in [(),('ReplayOrder',),('ReplayResearch',),('ReplayTime',)]]
        report['retention'].append(dict(case_id=case['case_id'],passed=[f['bestmove'].startswith(case['expected_prefix']) for f in frames]))
    for row in rows:
        case=row['case'];b=probe(binary,knowledge,case);a=probe(binary,knowledge,case,('ReplayOrder',))
        report['cost'].append(dict(case_id=case['case_id'],parent=b,candidate=a))
        if row['time_need']:
            f=probe(binary,knowledge,case,('ReplayTime',),extra={'AdaptiveLongThink':True})
            report['targets'].append(dict(case_id=case['case_id'],kind='time',frame=f))
    embedded=(ROOT/'engine/strategy/replay_knowledge_data.h').read_text().split('R"KUMOJIREPLAY(',1)[1].split(')KUMOJIREPLAY"',1)[0]
    memory={line.split('\t')[0]:line.split('\t')[1] for line in embedded.splitlines()}
    memory_cases=[]
    import shogi
    for game in load_archive(source):
        board=shogi.Board(game.start_sfen)
        for ply,token in enumerate(game.moves,1):
            if key(board.sfen()) in memory and memory[key(board.sfen())]!='-':
                memory_cases.append(make_case(game,ply));break
            board.push_usi(token)
        if len(memory_cases)==8:break
    for case in memory_cases:
        a=probe(binary,knowledge,case,('ReplayOrder',))
        report['targets'].append(dict(case_id=case['case_id'],kind='order',case=case,frame=a))
    hints=[r for r in report['cost'] if r['candidate']['played_telemetry'].get('replay_order_promotions',0)>0]
    order_targets=[r for r in report['targets'] if r['kind']=='order' and r['frame']['played_telemetry'].get('replay_order_promotions',0)>0]
    report['order_targets_used']=len(order_targets)
    report['parent_depth_sum']=sum(r['parent']['depth'] or 0 for r in report['cost'])
    report['candidate_depth_sum']=sum(r['candidate']['depth'] or 0 for r in report['cost'])
    report['depth_ratio']=report['candidate_depth_sum']/max(1,report['parent_depth_sum'])
    # A changed parent cannot use a stale asset even if the option is left ON.
    if order_targets:
        case=order_targets[0]['case']
        stale=probe(binary,knowledge,case,('ReplayOrder',),extra={'StructuredScale':100})
        report['stale_parent_disabled']=stale['played_telemetry'].get('replay_probes')==0
    else:report['stale_parent_disabled']=False
    report['passed']=report['disabled_exact'] and all(all(r['passed']) for r in report['retention']) and report['depth_ratio']>=.9 and report['stale_parent_disabled'] and report['order_targets_used']>0
    dump(output,report);print({k:v for k,v in report.items() if k not in ('cost','retention','targets')})
    if not report['passed']:raise ValueError('actual route preflight failed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',required=True);p.add_argument('--parent',required=True)
    p.add_argument('--knowledge',required=True);p.add_argument('--research',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source',required=True)
    a=p.parse_args();run(a.binary,a.parent,a.knowledge,a.research,a.output,a.source)
