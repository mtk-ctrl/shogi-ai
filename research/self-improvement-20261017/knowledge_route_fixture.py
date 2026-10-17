#!/usr/bin/env python3
"""Actual normal-arena transport/audit smoke; synthetic intent, never a teacher."""
import argparse,copy,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from knowledge_fixture import exercise
from tools.research.postgame_runtime import initialize,comparison_request,POLICY_KNOWLEDGE_EXECUTION
from tools.research.postgame_knowledge import POLICY_KNOWLEDGE
from tools.research.postgame_progress import POLICY_PROGRESS
from tools.research.postgame_cycle import request
from tools.research.postgame_ranker import BASE,OPTIONS,digest
from tools.research.postgame_bridge import dump
from tools.research.postgame_knowledge_route import materialize,audit


def run(binary,base,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    old=exercise(binary,base,output/'target-wiring')
    prep=output/'prep';(prep/'knowledge-stage').mkdir(parents=True)
    import shutil
    shutil.copytree(output/'target-wiring/knowledge',prep/'knowledge-stage',dirs_exist_ok=True)
    k=json.loads((prep/'knowledge-stage/result.json').read_bytes());parent=k['manifest']['parent'];params=dict(zip(OPTIONS,BASE))
    source=output/'source';(source/'build').mkdir(parents=True)
    shutil.copyfile(binary,source/'build/engine-a');shutil.copyfile(base,source/'build/position-knowledge-v1.tsv')
    dump(source/'stage-result.json',dict(audit=dict(parent_ref=parent['engine_ref'],actual_binary_sha256=dict(A=old['binary_sha256']),
             all_moves_legal=True,all_terminations_verified=True,binary_verified=True,knowledge_snapshot_verified=True,
             purpose='synthetic_fixture_source_provenance')))
    plan=dict(cycle_id='synthetic-knowledge-route',purpose='integration_smoke',parent=parent,parent_options=params,
              generate_initial_source=True,candidate_kind='knowledge',max_generations=1,max_new_games=300,source_games=2,
              runner_capacity=20,knowledge_policy=POLICY_KNOWLEDGE,progress_policy=POLICY_PROGRESS,
              knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION,
              seeds=[dict(source=2130101801,screen=2130101802,confirm=2130101803)])
    from tools.research.postgame_ranker import POLICY
    from tools.research.postgame_eval_preflight import POLICY_LIVE
    plan.update(learning_policy=POLICY,live_policy=POLICY_LIVE)
    env=initialize(plan,params,'c'*64);s=env['state'];s.update(stage='screen',expected_parameters_sha256=parent['parameters_sha256'],
               expected_knowledge_sha256=k['manifest']['candidate_sha256'],candidate=dict(parent,knowledge_sha256=k['manifest']['candidate_sha256']))
    env['state']=request(s,dict(parent=parent,candidate=s['candidate']),s['revision'])
    # Explicit transport fixture, not an operation accepted by core's normal
    # 100-game screen. Production entry refuses this smoke purpose/size.
    env['state']['pending']['payload']['games']=2
    env['state']['pending']['operation_id']=digest(env['state']['pending']['payload'])
    env.update(candidate_options=params,knowledge_candidate=k,source_publication='source',preparation_publication='prep')
    env['match_request']=comparison_request(env,1);env['match_request']['max_plies']=4
    env['dispatch']=dict(attempted=True,body_run=None)
    work=output/'arena';work.mkdir();proof=materialize(env,lambda name:output/name,work/'build','integration_smoke')
    req=env['match_request']
    subprocess.run([sys.executable,str(ROOT/'benchmarks/arena.py'),'--engine-a','build/engine-a','--engine-b','build/engine-b',
                   '--options-a',req['options_a'],'--options-b',req['options_b'],'--games','2','--max-plies','4','--seed',str(req['seed']),
                   '--go-command','go movetime 200','--output','results/shard-0.json'],cwd=work,check=True,stdout=subprocess.DEVNULL)
    verified=audit(work/'build',work/'results',req,'synthetic-route-smoke',work/'audit')
    raw=json.loads((work/'results/shard-0.json').read_bytes())
    assert verified['audit']['all_moves_legal'] and verified['audit']['all_terminations_verified']
    return dict(schema='postgame-knowledge-route-smoke-v1',purpose='integration_smoke',not_a_training_source=True,
                synthetic_source_provenance=True,normal_arena_games=2,normal_arena_plies=verified['audit']['plies'],
                target_wiring=old,actual_binary_sha256=proof['actual_binary_sha256'],snapshots=proof['snapshots'],
                audit=verified['audit'],ponder=raw['ponder'],formal_adoption=False,strength_improvement_demonstrated=False,
                limitation='Local/CI actual arena and audit transport only. Synthetic operation/source evidence is refused by the production entry; no real 100/200-game knowledge comparison.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--base',type=Path,default=ROOT/'position-knowledge-v1.tsv')
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=run(a.binary.resolve(),a.base.resolve(),a.directory);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
