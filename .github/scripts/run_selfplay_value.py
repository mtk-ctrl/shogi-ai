"""Selfplay outcome learning, independent confirmation, and actual inheritance."""
import argparse
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
from tools.research.postgame_cases import sha256,load_archive
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.train_selfplay_value import fit
REPO=transport.REPO
REF=transport.BASE_REF
BASE=transport.BASE
OUT=ROOT/'build/value-cycle'
save=transport.save

def probe_module():
    spec=importlib.util.spec_from_file_location('value_probe',ROOT/'research/selfplay-value-20261018/probe.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def preflight(binary,positions,candidates):
    probe=probe_module().probe
    controls=[]
    for case in tactical_cases():
        frames=[probe(binary,case['start_sfen'],extra_options=o) for o in [None]+[c['options'] for c in candidates]]
        controls.append(dict(case_id=case['case_id'],correct=[r['move'].startswith(case['expected_prefix']) for r in frames],observations=frames))
    speed=[]
    for row in positions[:16]:
        frames=[probe(binary,row['sfen'],extra_options=o) for o in [None]+[c['options'] for c in candidates]]
        speed.append(dict(game_hash=row['game_hash'],ply=row['ply'],observations=frames))
    depths=[sum(r['observations'][i].get('depth',0) for r in speed) for i in range(4)]
    ratios=[d/depths[0] if depths[0] else 0 for d in depths[1:]]
    passed=[all(r['correct'][0] and r['correct'][i+1] for r in controls) and ratios[i]>=.9 for i in range(3)]
    return dict(controls=controls,speed=speed,depth_sums=depths,depth_ratios=ratios,candidates_passed=passed)

def launch():
    request=json.loads((ROOT/'.github/selfplay-value-request.json').read_text())
    if request==dict(enabled=False):return
    if (not {'candidate_ref','request_id'}<=set(request) or set(request)-{'candidate_ref','request_id','value_loop','repair'}
            or len(request['candidate_ref'])!=40):raise ValueError('fixed request required')
    if 'value_loop' in request and request['value_loop'] is not True:raise ValueError('explicit loop request required')
    repair=request.get('repair',False)
    if 'repair' in request and (repair is not True or request.get('value_loop') is not True):raise ValueError('explicit loop repair required')
    runs=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    existing=[r for r in runs if r['display_title']=='Spiral '+request['request_id']]
    if existing:
        latest=max(existing,key=lambda r:r['id'])
        if (not repair or any(r['status']!='completed' for r in existing)
                or latest['conclusion'] not in ('failure','cancelled','timed_out')):
            raise ValueError('existing body; reconcile instead of retry')
    elif repair:raise ValueError('no failed controller to repair')
    result=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,inputs=dict(cycle_id=request['request_id'],
        plan_ref=request['candidate_ref'],order_only='true',value_loop=str(request.get('value_loop',False)).lower(),repair=str(repair).lower())))
    if type(result.get('workflow_run_id'))is not int:raise ValueError('actual run ID missing')
    print('VALUE_LAUNCH '+json.dumps(result),flush=True)

def compare(backend,values,games,seed,label,prior,new_parent=False):
    while not (free:=backend.free_runners(20)):time.sleep(30)
    oa=dict(BASE,**values);ob=oa if new_parent else BASE
    request=dict(ref_a=REF,ref_b=REF,games=games,shards=min(free,games),seed=seed,
        go_command='go movetime 200',max_plies=300,options_a=json.dumps(oa,sort_keys=True),options_b=json.dumps(ob,sort_keys=True))
    folder=OUT/label;folder.mkdir();save(folder/'request.json',request)
    response=api(f'repos/{REPO}/actions/workflows/engine-match.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,
        inputs={k:str(v) if type(v)is int else v for k,v in request.items()}))
    run=response.get('workflow_run_id')
    if type(run)is not int:raise ValueError('dispatch ID missing; reconcile instead of repeating')
    save(folder/'dispatch.json',response)
    print('VALUE_MATCH '+json.dumps(dict(label=label,run_id=run,request=request)),flush=True)
    transport.wait_body(run);source=transport.restore(run,folder)
    actual,report=transport.audit(source,request,run,prior,require_order_usage=False)
    if any(report['model_order_calls'].values()):raise ValueError('unexpected move-order experiment enabled')
    publication=transport.publish(backend,folder,source,report,label,prefix='selfplay-value')
    print('VALUE_RESULT '+json.dumps(dict(label=label,audit=report,publication=publication)),flush=True)
    return actual,report,publication,source

def main():
    p=argparse.ArgumentParser();p.add_argument('--launch',action='store_true');a=p.parse_args()
    if a.launch:return launch()
    if os.environ['GITHUB_REPOSITORY']!=REPO or os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1':raise ValueError('repository or retry differs')
    ref=os.environ['PLAN_REF']
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=ref:raise ValueError('frozen checkout differs')
    model=ROOT/'research/selfplay-value-20261018/model.json';m=json.loads(model.read_text())
    checks=json.loads((ROOT/'research/selfplay-value-20261018/preflight.json').read_text())
    if not m['eligible']:raise ValueError('outcome prediction did not pass predeclared proposal gate')
    OUT.mkdir(parents=True,exist_ok=False);backend=Backend(REPO,OUT/'transport')
    prior=set(json.loads((ROOT/'research/selfplay-value-20261018/source-trajectories.json').read_text()))
    predecessors=json.loads((ROOT/'research/selfplay-value-20261018/predecessors.json').read_text())
    for pub in predecessors:
        prior.update(transport.signature(g) for g in load_archive(backend.unpack(pub)))
    results=[]
    for i,c in enumerate(m['candidates']):
        if not checks['candidates_passed'][i]:continue
        label='screen-'+str(int(c['fraction']*100))
        actual,report,pub,_=compare(backend,c['options'],100,2051101801+i*1000000,label,prior)
        results.append(dict(candidate=c,report=report,publication=pub));prior.update(transport.signature(g) for g in actual)
    result=dict(schema='selfplay-value-cycle-v1',request_ref=ref,engine_ref=REF,model_sha256=sha256(model.read_bytes()),
        screens=results,formal_adoption=False,research_parent_updated=False,next_selfplay_completed=False)
    save(OUT/'result.json',result)
    eligible=[r for r in results if r['report']['raw']['score']>=.5]
    if not eligible:result['status']='screen_rejected';save(OUT/'result.json',result);return
    selected=max(eligible,key=lambda r:(r['report']['raw']['score'],-r['candidate']['fraction']))['candidate']
    actual,report,pub,source=compare(backend,selected['options'],1000,2056101801,'confirmation',prior)
    result.update(selected=selected,confirmation=report,confirmation_publication=pub);save(OUT/'result.json',result)
    if not(report['raw']['lower']>.5 and report['unique']['lower']>.5):
        result['status']='confirmation_rejected';save(OUT/'result.json',result);return
    parent=dict(engine_ref=REF,options=dict(BASE,**selected['options']),model_sha256=sha256(model.read_bytes()),
        confirmation_run=report['run_id'],formal_adoption=False)
    result.update(research_parent_updated=True,research_parent=parent);save(OUT/'research-parent.json',parent)
    prior.update(transport.signature(g) for g in actual)
    actual,report,pub,source=compare(backend,selected['options'],300,2061101801,'next-generation',prior,new_parent=True)
    result.update(status='research_parent_improved',next_selfplay_completed=True,next_selfplay=report,next_publication=pub)
    probe=probe_module().probe;binary=source/'binaries/build/engine-b';binary.chmod(0o755);positions=[]
    for game in actual[:8]:
        ply=min(30,len(game.moves)-1)
        obs=probe(binary,game.start_sfen,history=game.moves[:ply],extra_options=selected['options'])
        positions.append(dict(game_id=game.row['game_id'],ply=ply,start_sfen=game.start_sfen,
            history_moves=game.moves[:ply],observation=obs))
    result['next_reanalysis']=positions;save(OUT/'result.json',result)
    fit([source],binary,OUT/'next-model',parent_options=selected['options'])
    result['next_learning']=json.loads((OUT/'next-model/model.json').read_text())
    save(OUT/'result.json',result)

if __name__=='__main__':
    try:main()
    finally:
        if (OUT/'result.json').exists():
            backend=Backend(REPO,OUT/'transport');package=OUT/('selfplay-value-result-'+str(backend.run_id)+'.tgz')
            with tarfile.open(package,'w:gz') as tar:
                tar.add(OUT/'result.json',arcname='result.json',recursive=False)
                if (OUT/'research-parent.json').exists():tar.add(OUT/'research-parent.json',arcname='research-parent.json',recursive=False)
                if (OUT/'next-model/model.json').exists():tar.add(OUT/'next-model/model.json',arcname='next-model.json',recursive=False)
                for p in sorted((ROOT/'research/selfplay-value-20261018').glob('*')):
                    if p.is_file():tar.add(p,arcname='research/'+p.name,recursive=False)
            receipt=backend.upload(package);readback=backend.unpack(receipt)
            if json.loads((readback/'result.json').read_text())!=json.loads((OUT/'result.json').read_text()):raise ValueError('cycle readback differs')
            save(OUT/'final-publication.json',receipt)
            print('VALUE_CYCLE_PUBLICATION '+json.dumps(receipt),flush=True)
