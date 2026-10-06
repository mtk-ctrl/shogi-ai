"""Preregistered ON-vs-ON screening, final and independent baseline validation."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def params(guard,pressure,mix=0,reinforcement=50,tempo=50):
    return {'EvalInfluence':True,'EvalInfluenceGuardWeight':guard,
            'EvalInfluencePressureWeight':pressure,'EvalInfluenceLegacyMix':mix,
            'EvalInfluenceReinforcementBonus':reinforcement,'EvalInfluenceTempoBonus':tempo}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--engine',required=True)
    parser.add_argument('--output-dir',required=True);parser.add_argument('--lanes',type=int,default=4)
    args=parser.parse_args();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    candidates=[
        {'id':'A_guard75_pressure150','options':params(75,150),'hypothesis':'reduce overweighted guard'},
        {'id':'B_guard50_pressure250','options':params(50,250),'hypothesis':'restore observed attack/defence scale'},
        {'id':'C_guard50_pressure75','options':params(50,75),'hypothesis':'reduce noisy new positional influence'},
        {'id':'D_mix50_guard75_pressure200','options':params(75,200,50),'hypothesis':'retain half of existing shelter/escape-denial cues'},
        {'id':'E_mix75_guard75_pressure200','options':params(75,200,75),'hypothesis':'retain more existing cues with a smaller new correction'},
        {'id':'F_mix50_uncertainty_neutral','options':params(75,200,50,0,0),'hypothesis':'avoid scoring uncertain arrival/tempo approximations'},
        {'id':'G_mix50_guard150_pressure150','options':params(150,150,50),'hypothesis':'blend old and first-candidate scales'},
        {'id':'H_mix75_guard150_pressure150','options':params(150,150,75),'hypothesis':'small correction with original common new weights'},
    ]
    anchor=params(150,150)
    plan={'engine_sha256':hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
          'anchor':anchor,'candidates':candidates,'screen_games_per_candidate':40,
          'screen_seed':2026100640,'final_seed':2026100740,'on_holdout_seed':2026100840,
          'off_holdout_seed':2026100940,'final_games':100,'on_holdout_games':100,'off_holdout_games':200,
          'selection':'rank screen score vs anchor; tie by ID; top 2 head-to-head on independent seed; choose score>=0.5 as A else B',
          'all_candidates_compute_same_influence_features':True,'movetime_ms':50,
          'book':True,'experience':False,'mate_assist':True,'max_plies':200,
          'no_parameter_changes_after_plan':True}
    pp=out/'plan.json'
    if pp.exists() and json.loads(pp.read_text())!=plan:raise SystemExit('Plan changed; use a new experiment directory')
    pp.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    def run(name,oa,ob,games,seed):
        folder=out/name
        subprocess.run([sys.executable,'benchmarks/influence_match.py','--engine',args.engine,
                        '--pairs',str(games//2),'--lanes',str(args.lanes),'--seed',str(seed),
                        '--options-a',json.dumps(oa),'--options-b',json.dumps(ob),'--output-dir',str(folder)],check=True)
        return json.loads((folder/'summary.json').read_text())
    progress={'stage':'screen','screen':[]};results=[]
    for candidate in candidates:
        print('\nSCREEN '+candidate['id'],flush=True)
        r=run('screen/'+candidate['id'],candidate['options'],anchor,40,plan['screen_seed'])
        row={'id':candidate['id'],'score':r['score_a'],'wins':r['wins_a'],'losses':r['wins_b'],
             'draws':r['draws'],'illegal':r['illegal_games']}
        results.append(row);progress['screen']=results
        (out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    ranked=sorted(results,key=lambda r:(-r['score'],r['id']));ids={c['id']:c for c in candidates}
    ca,cb=ids[ranked[0]['id']],ids[ranked[1]['id']]
    progress.update(stage='final',finalists=[ca['id'],cb['id']]);(out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    print('\nFINAL '+ca['id']+' vs '+cb['id'],flush=True)
    final=run('final',ca['options'],cb['options'],100,plan['final_seed'])
    selected=ca if final['score_a']>=0.5 else cb
    progress.update(stage='independent_on_holdout',selected=selected);(out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    print('\nON HOLDOUT '+selected['id'],flush=True)
    on=run('on-holdout',selected['options'],anchor,100,plan['on_holdout_seed'])
    progress['stage']='independent_off_holdout';(out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    print('\nOFF HOLDOUT '+selected['id'],flush=True)
    off=run('off-holdout',selected['options'],{'EvalInfluence':False},200,plan['off_holdout_seed'])
    summary={'plan':plan,'screen':ranked,'finalists':[ca['id'],cb['id']],
             'final':final,'selected':selected,'on_holdout':on,'off_holdout':off,
             'total_games':320+100+100+200,'automatically_adopted':False}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    progress['stage']='complete';(out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    print(json.dumps({'selected':selected,'on_score':on['score_a'],'off_score':off['score_a'],'games':720},indent=2),flush=True)
if __name__=='__main__':main()
