"""Coarse-to-holdout Evaluation-v2 tuning against the adopted evaluator.

The goal is not to discover a final universal optimum in one run. It is to
construct one coherent multi-axis challenger, select its rough scale without
peeking at the final seeds, and then ask whether it can beat the adopted
material-dominant model at 200ms.
"""
import argparse,json,subprocess,sys
from pathlib import Path

BASELINE={
    'EvalV2':False,
    'AdaptiveLongThink':False,
}
COMMON={
    'EvalV2':True,
    'AdaptiveLongThink':False,
}
CANDIDATES=[
    # First isolate the structural hypothesis: widen the old evaluator's room
    # before adding any new concept.
    ('A_wider_core',{
        'EvalMaterialWeight':100,'EvalSafety':50,'EvalPressure':150,'EvalActivity':150,'EvalDanger':200,
        'EvalInfluence':0,'EvalPotential':0,'EvalCoordination':0,'EvalHandPotential':0,'EvalThreat':0,
        'EvalPositionalCap':700}),
    # The first genuinely new model: unresolved tactical value plus hand option
    # value, without paying for weaker research signals.
    ('B_threat_core',{
        'EvalMaterialWeight':100,'EvalSafety':65,'EvalPressure':160,'EvalActivity':150,'EvalDanger':185,
        'EvalInfluence':0,'EvalPotential':0,'EvalCoordination':0,'EvalHandPotential':60,'EvalThreat':25,
        'EvalPositionalCap':900}),
    # Broad but still conservative. Influence/coordination are lightweight and
    # Potential is omitted because its previous standalone 50-weight test lost.
    ('C_balanced_lite',{
        'EvalMaterialWeight':100,'EvalSafety':75,'EvalPressure':160,'EvalActivity':160,'EvalDanger':180,
        'EvalInfluence':50,'EvalPotential':0,'EvalCoordination':50,'EvalHandPotential':60,'EvalThreat':25,
        'EvalPositionalCap':1000}),
    # Permit positional factors collectively to outweigh material when several
    # independent signals agree; keep only a tiny Potential contribution.
    ('D_broad',{
        'EvalMaterialWeight':90,'EvalSafety':90,'EvalPressure':170,'EvalActivity':170,'EvalDanger':180,
        'EvalInfluence':75,'EvalPotential':15,'EvalCoordination':60,'EvalHandPotential':75,'EvalThreat':25,
        'EvalPositionalCap':1300}),
    # Tactical variant: stronger unresolved fork/skewer value, but material stays
    # at full scale and the global position budget is bounded.
    ('E_tactical',{
        'EvalMaterialWeight':100,'EvalSafety':70,'EvalPressure':175,'EvalActivity':150,'EvalDanger':175,
        'EvalInfluence':40,'EvalPotential':0,'EvalCoordination':40,'EvalHandPotential':50,'EvalThreat':35,
        'EvalPositionalCap':1000}),
]

def run(engine,out,pairs,seed,a,b,adaptive=False):
    a={**COMMON,**a,'AdaptiveLongThink':adaptive}
    b={**BASELINE,**b,'AdaptiveLongThink':adaptive}
    cmd=[sys.executable,'benchmarks/eval_v2_match.py','--engine',engine,
         '--pairs',str(pairs),'--lanes','4','--seed',str(seed),'--max-plies','240',
         '--go-command','go movetime 200','--output-dir',str(out),
         '--options-a',json.dumps(a,separators=(',',':')),
         '--options-b',json.dumps(b,separators=(',',':'))]
    subprocess.run(cmd,check=True)
    return json.loads((Path(out)/'summary.json').read_text())

def main():
    p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--output-dir',required=True)
    args=p.parse_args();root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
    plan={'baseline':BASELINE,'candidates':[{'id':i,'options':o} for i,o in CANDIDATES],
          'screen_games_each':10,'holdout_games_each':20,'final_games':60,
          'movetime_ms':200,'selection':'screen top2, independent 20-game holdout, then 60-game confirmation'}
    (root/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')

    screen=[]
    for ident,opts in CANDIDATES:
        s=run(args.engine,root/'screen'/ident,5,2026102000,opts,{})
        screen.append({'id':ident,'options':opts,'score':s['score_a'],'wins':s['wins_a'],
                       'draws':s['draws'],'losses':s['wins_b']})
    screen.sort(key=lambda x:(x['score'],x['id']),reverse=True)
    finalists=screen[:2]

    holdout=[]
    for identrow in finalists:
        s=run(args.engine,root/'holdout'/identrow['id'],10,2026103000,identrow['options'],{})
        holdout.append({**identrow,'holdout_score':s['score_a'],'holdout_wins':s['wins_a'],
                        'holdout_draws':s['draws'],'holdout_losses':s['wins_b']})
    holdout.sort(key=lambda x:(x['holdout_score'],x['score'],x['id']),reverse=True)
    selected=holdout[0]

    final=run(args.engine,root/'final',30,2026104000,selected['options'],{})
    summary={'screen':screen,'holdout':holdout,'selected':selected,
             'final_200ms_no_longthink':final}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
