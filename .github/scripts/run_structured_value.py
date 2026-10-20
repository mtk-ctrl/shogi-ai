"""Frozen contextual value learning -> ordinary games -> learned next parent."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
import selfplay_trial_transport as transport
from run_postgame_spiral import Backend,api
from tools.research.postgame_cases import load_archive,sha256
from tools.research.train_structured_value import train,PARENT
from structured_execution import validate_execution,comparison_request
REPO=transport.REPO;OUT=ROOT/'build/structured-cycle';save=transport.save
STUDY=ROOT/('research/structured-successor-20261020' if os.environ.get('CYCLE_ID')=='structured-value-20261020-g2' else 'research/structured-eval-20261019')
SOURCE=dict(release='records-2026-10-01',name='selfplay-value-next-generation-39120804144.tgz',
    sha256='2bd392425a066c3a1bc88878c21d952c0acf1284638e52918fe89bb7173a760c',bytes=7408409)
EXTRA_SOURCE=dict(release='records-2026-10-01',name='value-loop-selfplay-two-rounds-20261019-01-r1-next-source.tgz',
    sha256='5355763ddec17d6662f5d064b8f0f1ca24b9e9ae13059bd459bd5ca7c91b4515',bytes=7413226)

def stop_requested():
    data=api(f'repos/{REPO}/contents/.github/structured-value-control.json?ref='+os.environ['GITHUB_REF_NAME'])
    control=json.loads(base64.b64decode(data['content']))
    if set(control)!={'stop_requested'} or type(control['stop_requested'])is not bool:
        raise ValueError('invalid explicit stop control')
    return control['stop_requested']

def wait_body(run):
    while True:
        state=api(f'repos/{REPO}/actions/runs/{run}')
        if state['status']=='completed':
            if state['conclusion']!='success':raise ValueError('match did not succeed: '+state['conclusion'])
            return
        if stop_requested():
            api(f'repos/{REPO}/actions/runs/{run}/cancel',{})
            raise ValueError('stopped by the explicit user control; no next stage')
        time.sleep(30)

def launch():
    request=json.loads((ROOT/'.github/structured-value-request.json').read_text())
    if request==dict(enabled=False):return
    if set(request)!={'candidate_ref','request_id'} or len(request['candidate_ref'])!=40:
        raise ValueError('explicit frozen request required')
    execution=json.loads((STUDY/'EXECUTION.json').read_text())
    if execution['cycle_id']!=request['request_id']:
        raise ValueError('cycle ID changed without freezing a new execution plan')
    runs=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    if any(r['display_title']=='Spiral '+request['request_id'] for r in runs):
        raise ValueError('existing controller; reconcile instead of retrying')
    response=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,
        inputs=dict(cycle_id=request['request_id'],plan_ref=request['candidate_ref'],order_only='true',structured_only='true')))
    if type(response.get('workflow_run_id'))is not int:raise ValueError('controller dispatch ID missing')
    print('STRUCTURED_LAUNCH '+json.dumps(response),flush=True)

def compare(backend,ref,scale,games,seed,label,prior,parent,own=False):
    if stop_requested():raise ValueError('stopped by explicit user control before dispatch')
    while not (free:=backend.free_runners(20)):time.sleep(30)
    request=comparison_request(ref,parent,transport.BASE,PARENT,scale,games,min(free,games),seed,own)
    folder=OUT/label;folder.mkdir();save(folder/'request.json',request)
    state=json.loads((OUT/'result.json').read_text())
    state['active_operation']=dict(label=label,request=request,status='intent_saved');save(OUT/'result.json',state)
    response=api(f'repos/{REPO}/actions/workflows/engine-match.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,
        inputs={k:str(v) if type(v)is int else v for k,v in request.items()}))
    run=response.get('workflow_run_id')
    if type(run)is not int:raise ValueError('body ID missing; reconcile existing run')
    save(folder/'dispatch.json',response)
    state['active_operation'].update(run_id=run,status='running');save(OUT/'result.json',state)
    print('STRUCTURED_MATCH '+json.dumps(dict(label=label,run_id=run,request=request)),flush=True)
    wait_body(run);source=transport.restore(run,folder)
    actual,report=transport.audit(source,request,run,prior,require_order_usage=False)
    model_sha=sha256((STUDY/'model.json').read_bytes())
    for side in ('a','b') if own else ('a',):
        if model_sha.encode() not in (source/'binaries/build'/('engine-'+side)).read_bytes():
            raise ValueError('actual binary does not contain the frozen learned model identity')
    if not own and parent['model_sha256'] is not None:
        if parent['model_sha256'].encode() not in (source/'binaries/build/engine-b').read_bytes():
            raise ValueError('the baseline did not retain the previously learned model')
    usage=dict(A=0,B=0)
    for shard in (source/'shards').glob('shard-*.json'):
        for game in json.loads(shard.read_text())['details']:
            for m in game['move_records']:usage[m['engine']]+=m['search'].get('structured_eval_calls',0)
    learned_baseline=own or parent['model_sha256'] is not None
    if usage['A']<=0 or (learned_baseline and usage['B']<=0) or (not learned_baseline and usage['B']!=0):
        raise ValueError('actual learned evaluation usage differs from frozen comparison')
    report.update(structured_eval_calls=usage,model_sha256=model_sha,compiled_model_identity_verified=True)
    receipt=transport.publish(backend,folder,source,report,label,prefix='structured-value')
    state['active_operation'].update(status='saved',publication=receipt,audit=report);save(OUT/'result.json',state)
    print('STRUCTURED_RESULT '+json.dumps(dict(label=label,audit=report,publication=receipt)),flush=True)
    return actual,report,receipt,source

def main():
    p=argparse.ArgumentParser();p.add_argument('--launch',action='store_true');a=p.parse_args()
    if a.launch:return launch()
    ref=os.environ['PLAN_REF']
    if (os.environ['GITHUB_REPOSITORY']!=REPO or os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1'
            or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=ref):
        raise ValueError('repository, attempt or frozen checkout differs')
    OUT.mkdir(parents=True,exist_ok=False);backend=Backend(REPO,OUT/'transport')
    model_path=STUDY/'model.json';model=json.loads(model_path.read_text())
    checks=json.loads((STUDY/'preflight.json').read_text())
    execution=json.loads((STUDY/'EXECUTION.json').read_text())
    comparison_parent,seeds=validate_execution(execution,model,transport.BASE,PARENT)
    if execution['cycle_id']!=os.environ['CYCLE_ID']:raise ValueError('controller cycle does not match frozen plan')
    if not(model['features']==4893 and model['eligible'] and checks['disabled_exact'] and checks['integer_evaluation_exact']):
        raise ValueError('model or preflight gate missing')
    games=[]
    for publication in execution['training_publications']:games.extend(load_archive(backend.unpack(publication)))
    prior={transport.signature(g) for g in games}
    # Previously completed ordinary comparisons remain used evaluation, not a
    # fresh independent confirmation. Include all stored played trajectories.
    for receipt in json.loads((STUDY/'prior-publications.json').read_text()):
        prior.update(transport.signature(g) for g in load_archive(backend.unpack(receipt)))
    report=dict(schema='structured-value-cycle-v1',candidate_ref=ref,model_sha256=sha256(model_path.read_bytes()),
        parent_options=PARENT,comparison_parent=comparison_parent,execution=execution,
        learned_coefficients=model['nonzero_coefficients'],screens=[],
        research_parent_updated=False,next_selfplay_completed=False,formal_adoption=False)
    save(OUT/'result.json',report)
    for i,scale in enumerate((50,100,150)):
        if not checks['candidates_passed'][i]:continue
        actual,audit,pub,_=compare(backend,ref,scale,100,seeds['screens'][i],'screen-'+str(scale),prior,comparison_parent)
        report['screens'].append(dict(scale=scale,audit=audit,publication=pub));save(OUT/'result.json',report)
        prior.update(transport.signature(g) for g in actual)
    eligible=[r for r in report['screens'] if r['audit']['raw']['score']>=.5]
    if not eligible:report['status']='screen_rejected';save(OUT/'result.json',report);return
    selected=max(eligible,key=lambda r:(r['audit']['raw']['score'],-r['scale']))['scale']
    actual,audit,pub,_=compare(backend,ref,selected,1000,seeds['confirmation'],'confirmation',prior,comparison_parent)
    report.update(selected_scale=selected,confirmation=audit,confirmation_publication=pub);save(OUT/'result.json',report)
    if not(audit['raw']['lower']>.5 and audit['unique']['lower']>.5):
        report['status']='confirmation_rejected';save(OUT/'result.json',report);return
    parent=dict(engine_ref=ref,options=dict(transport.BASE,**PARENT,StructuredEval=True,StructuredScale=selected),
        model_sha256=sha256(model_path.read_bytes()),formal_adoption=False)
    report.update(research_parent_updated=True,research_parent=parent);save(OUT/'research-parent.json',parent)
    prior.update(transport.signature(g) for g in actual)
    actual,audit,pub,source=compare(backend,ref,selected,300,seeds['next_source'],'next-generation',prior,comparison_parent,own=True)
    report.update(status='research_parent_improved',next_selfplay_completed=True,next_selfplay=audit,next_publication=pub)
    save(OUT/'result.json',report)
    subprocess.run([sys.executable,'scripts/build.py','--structured-value-probe','--output','build/next-structured-probe'],check=True)
    exclusions=set()
    for g in games:
        import shogi
        b=shogi.Board(g.start_sfen)
        for move in g.moves:
            exclusions.add(sha256(' '.join(b.sfen().split()[:3]).encode()));b.push_usi(move)
    for label in [r['scale'] for r in report['screens']]+['confirmation']:
        folder=OUT/('screen-'+str(label) if type(label)is int else label)/'source'
        for g in load_archive(folder):
            b=shogi.Board(g.start_sfen)
            for move in g.moves:
                exclusions.add(sha256(' '.join(b.sfen().split()[:3]).encode()));b.push_usi(move)
    try:
        next_model=train([source],ROOT/'build/next-structured-probe',OUT/'next-model',model_path,selected,exclusions)
        report['next_learning']={k:v for k,v in next_model.items() if k not in ('weights','parent_weights')}
        report['next_model_sha256']=sha256((OUT/'next-model/model.json').read_bytes())
    except ValueError as error:
        if 'too few distinct actual positions' not in str(error):raise
        report['next_learning']=dict(status='insufficient_new_independent_data',detail=str(error),parent_retained=True)
    save(OUT/'result.json',report)

if __name__=='__main__':
    try:main()
    finally:
        if (OUT/'result.json').exists():
            backend=Backend(REPO,OUT/'transport');package=OUT/('structured-value-result-'+str(backend.run_id)+'.tgz')
            with tarfile.open(package,'w:gz') as tar:
                tar.add(OUT/'result.json',arcname='result.json',recursive=False)
                for p in sorted(STUDY.glob('*')):
                    if p.is_file():tar.add(p,arcname='research/'+p.name,recursive=False)
                for name in ('model.json','structured_value_weights.h','actual-positions.jsonl'):
                    p=OUT/'next-model'/name
                    if p.exists():tar.add(p,arcname='next-model/'+name,recursive=False)
                if (OUT/'research-parent.json').exists():tar.add(OUT/'research-parent.json',arcname='research-parent.json',recursive=False)
            pub=backend.upload(package);readback=backend.unpack(pub)
            if json.loads((readback/'result.json').read_text())!=json.loads((OUT/'result.json').read_text()):raise ValueError('result readback differs')
            save(OUT/'final-publication.json',pub)
            print('STRUCTURED_CYCLE_PUBLICATION '+json.dumps(pub),flush=True)
