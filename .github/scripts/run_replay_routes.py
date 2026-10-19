"""Individually compare frozen non-evaluation routes and save actual use."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from run_postgame_spiral import Backend,api
import selfplay_trial_transport as transport
from tools.research.train_structured_value import PARENT
from tools.research.postgame_routes import MODEL
from tools.research.postgame_cases import sha256,load_archive
OUT=ROOT/'build/replay-cycle';REPO=transport.REPO;save=transport.save

def publish_local_evidence(backend):
    import base64
    import io
    meta=json.loads((ROOT/'research/experience-routes-20261019/local-evidence-transport.json').read_text())
    raw=bytearray()
    for expected,part in enumerate(meta['parts']):
        if part['index']!=expected:raise ValueError('transport part order differs')
        blob=api(f"repos/{REPO}/git/blobs/{part['blob_sha']}")
        chunk=base64.b64decode(blob['content'])
        if len(chunk)!=part['bytes'] or sha256(chunk)!=part['sha256']:raise ValueError('transport part bytes differ')
        raw.extend(chunk)
    if len(raw)!=meta['bytes'] or sha256(raw)!=meta['sha256']:raise ValueError('transport package differs')
    def no_pv(value):
        if isinstance(value,dict):
            if 'pv' in value:raise ValueError('diagnostic PV must not enter permanent evidence')
            for item in value.values():no_pv(item)
        elif isinstance(value,list):
            for item in value:no_pv(item)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith('.json'):no_pv(json.load(tar.extractfile(member)))
    package=OUT/('replay-routes-local-evidence-'+str(backend.run_id)+'.tgz');package.write_bytes(raw)
    pub=backend.upload(package);source=backend.unpack(pub)
    generation=json.loads((source/'generation/report.json').read_text())
    if sha256((source/'binaries/parent').read_bytes())!=generation['binary_sha256']:raise ValueError('actual practice parent binary differs')
    old=backend.unpack(meta['older_binary_source'])
    with tarfile.open(old/'engine-binaries.tgz') as t:t.extractall(OUT/'older-binaries',filter='data')
    if sha256((OUT/'older-binaries/build/engine-b').read_bytes())!=meta['older_binary_sha256']:raise ValueError('actual old opponent is not recoverable')
    games=load_archive(source/'practice/archive');report=json.loads((source/'practice/report.json').read_text())
    if len(games)!=report['games'] or len(games)>16 or report['independent_new_groups']!=0:raise ValueError('practice count/lineage differs')
    new_plies=0
    for g in games:
        segments=g.metadata['execution_segments'];prefix=segments[0]['last_ply']
        if segments[0]['role']!='replayed_original_history' or segments[1]['first_ply']!=prefix+1:raise ValueError('practice execution scopes differ')
        if g.metadata['training_lineage']['split']!='train':raise ValueError('practice leaked a protected group')
        if g.row['moves'][prefix]['search']['score_status']=='recorded':raise ValueError('forced move has a fabricated search value')
        new_plies+=len(g.moves)-prefix
        for side in ('a','b'):
            if g.metadata['sha256_'+side] not in (generation['binary_sha256'],meta['older_binary_sha256']):raise ValueError('practice opponent identity differs')
    if new_plies!=report['new_plies']:raise ValueError('practice move count differs')
    if sha256((source/'generation/replay-knowledge.tsv').read_bytes())!=generation['memory_sha256']:raise ValueError('memory does not match actual source')
    receipt=dict(publication=pub,practice_games=len(games),new_plies=new_plies,actual_binaries_recoverable=True,
                 actual_moves_and_terminations_verified=True,independent_new_groups=0)
    save(OUT/'local-evidence.json',receipt);print('REPLAY_LOCAL_EVIDENCE '+json.dumps(receipt),flush=True)
    return receipt

def launch():
    req=json.loads((ROOT/'.github/replay-routes-request.json').read_text())
    if req==dict(enabled=False):return
    if set(req)!={'candidate_ref','request_id'} or len(req['candidate_ref'])!=40:raise ValueError('frozen request required')
    runs=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    if any(r['display_title']=='Spiral '+req['request_id'] for r in runs):raise ValueError('existing controller; reconcile instead of duplicate')
    response=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/dispatches',dict(ref=os.environ['GITHUB_REF_NAME'],
        return_run_details=True,inputs=dict(cycle_id=req['request_id'],plan_ref=req['candidate_ref'],order_only='true',replay_only='true')))
    if type(response.get('workflow_run_id'))is not int:raise ValueError('missing controller ID; do not retry')
    print('REPLAY_LAUNCH '+json.dumps(response),flush=True)

def stopped():
    import base64
    item=api(f'repos/{REPO}/contents/.github/structured-value-control.json?ref='+os.environ['GITHUB_REF_NAME'])
    obj=json.loads(base64.b64decode(item['content']))
    if set(obj)!={'stop_requested'} or type(obj['stop_requested'])is not bool:raise ValueError('invalid stop control')
    return obj['stop_requested']

def compare(backend,ref,mode,games,seed,label,prior):
    if stopped():raise ValueError('explicit stop before next operation')
    while not(free:=backend.free_runners(20)):
        time.sleep(30)
        if stopped():raise ValueError('explicit stop while waiting for capacity')
    base=dict(transport.BASE,**PARENT,StructuredEval=True,StructuredScale=50)
    req=dict(ref_a=ref,ref_b=ref,games=games,shards=min(games,free),seed=seed,go_command='go movetime 200',max_plies=300,
             options_a=json.dumps(dict(base,**{mode:True}),sort_keys=True),options_b=json.dumps(base,sort_keys=True))
    folder=OUT/label;folder.mkdir();save(folder/'request.json',req)
    report=json.loads((OUT/'result.json').read_text());report['active_operation']=dict(label=label,mode=mode,request=req,status='intent_saved');save(OUT/'result.json',report)
    response=api(f'repos/{REPO}/actions/workflows/engine-match.yml/dispatches',dict(ref=os.environ['GITHUB_REF_NAME'],
        return_run_details=True,inputs={k:str(v) if type(v)is int else v for k,v in req.items()}))
    run=response.get('workflow_run_id')
    if type(run)is not int:raise ValueError('missing body ID; reconcile saved intent, never retry blindly')
    save(folder/'dispatch.json',response);report['active_operation'].update(run_id=run,status='running');save(OUT/'result.json',report)
    print('REPLAY_MATCH '+json.dumps(dict(label=label,run_id=run,request=req)),flush=True)
    while True:
        state=api(f'repos/{REPO}/actions/runs/{run}')
        if state['status']=='completed':
            if state['conclusion']!='success':raise ValueError('comparison failed: '+state['conclusion'])
            break
        if stopped():
            api(f'repos/{REPO}/actions/runs/{run}/cancel',{});raise ValueError('explicit user stop')
        time.sleep(30)
    source=transport.restore(run,folder);actual,audit=transport.audit(source,req,run,prior,require_order_usage=False)
    usage={s:Counter() for s in ('A','B')};reasons={s:Counter() for s in ('A','B')}
    for g in actual:
        for row in g.row['moves']:
            stats=row['search'];side=row['engine']
            for k in ('structured_eval_calls','replay_probes','replay_order_promotions','replay_research_promotions','replay_time_match'):
                usage[side][k]+=stats.get(k,0)
            if stats.get('long_think_reason'):reasons[side][stats['long_think_reason']]+=1
    memory=json.loads((ROOT/'research/experience-routes-20261019/generation-report.json').read_text())['memory_sha256']
    for side in ('a','b'):
        raw=(source/'binaries/build'/('engine-'+side)).read_bytes()
        if MODEL.encode() not in raw or memory.encode() not in raw:raise ValueError('executed model/knowledge asset identity differs')
    if min(usage[s]['structured_eval_calls'] for s in ('A','B'))<=0:raise ValueError('learned parent not used on both sides')
    if any(usage['B'][k] for k in ('replay_probes','replay_order_promotions','replay_research_promotions','replay_time_match')):
        raise ValueError('baseline route is not disabled')
    key={'ReplayOrder':'replay_order_promotions','ReplayResearch':'replay_research_promotions','ReplayTime':'replay_time_match'}[mode]
    used=reasons['A']['replay_read_more'] if mode=='ReplayTime' else usage['A'][key]
    audit.update(route=mode,route_usage=usage,long_think_reasons=reasons,actual_route_used=used>0,
                 route_uses=used,asset_sha256=memory,model_sha256=MODEL,compiled_asset_identity_verified=True)
    pub=transport.publish(backend,folder,source,audit,label,prefix='replay-routes')
    report['active_operation'].update(status='saved',audit=audit,publication=pub);save(OUT/'result.json',report)
    print('REPLAY_RESULT '+json.dumps(dict(label=label,audit=audit,publication=pub)),flush=True)
    prior.update(transport.signature(g) for g in actual)
    return audit,pub

def main():
    p=argparse.ArgumentParser();p.add_argument('--launch',action='store_true');a=p.parse_args()
    if a.launch:return launch()
    ref=os.environ['PLAN_REF'];cycle=os.environ['CYCLE_ID']
    if os.environ['GITHUB_REPOSITORY']!=REPO or os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1' or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=ref:
        raise ValueError('immutable checkout/repository/attempt differs')
    if cycle!='replay-routes-20261019-01':raise ValueError('wrong frozen cycle')
    pre=json.loads((ROOT/'research/experience-routes-20261019/preflight.json').read_text())
    if not pre['passed']:raise ValueError('preflight not passed')
    OUT.mkdir(parents=True,exist_ok=False);backend=Backend(REPO,OUT/'transport')
    generation=json.loads((ROOT/'research/experience-routes-20261019/generation-report.json').read_text())
    counts=dict(ReplayOrder=generation['order_hints'],ReplayResearch=generation['research_hints'],ReplayTime=generation['time_cases'])
    report=dict(schema='replay-routes-cycle-v1',candidate_ref=ref,parent_model=MODEL,parent_scale=50,
        screens=[],research_parent_updated=False,formal_adoption=False,max_normal_games=1300,skipped=[])
    save(OUT/'result.json',report);prior=set()
    report['local_evidence']=publish_local_evidence(backend);save(OUT/'result.json',report)
    pubs=json.loads((ROOT/'research/experience-routes-20261019/used-publications.json').read_text())
    for publication in pubs:
        prior.update(transport.signature(g) for g in load_archive(backend.unpack(publication)))
    for mode,seed in [('ReplayOrder',2106101901),('ReplayResearch',2108101901),('ReplayTime',2110101901)]:
        if counts[mode]==0:
            report['skipped'].append(dict(mode=mode,reason='no_eligible_asset'));save(OUT/'result.json',report);continue
        audit,pub=compare(backend,ref,mode,100,seed,'screen-'+mode,prior)
        report['screens'].append(dict(mode=mode,audit=audit,publication=pub));save(OUT/'result.json',report)
    eligible=[r for r in report['screens'] if r['audit']['raw']['score']>=.5 and r['audit']['actual_route_used']]
    if not eligible:report['status']='no_used_promising_route'
    else:
        selected=max(eligible,key=lambda r:(r['audit']['raw']['score'],-['ReplayOrder','ReplayResearch','ReplayTime'].index(r['mode'])))
        audit,pub=compare(backend,ref,selected['mode'],1000,2113101901,'confirmation',prior)
        report.update(selected_route=selected['mode'],confirmation=audit,confirmation_publication=pub)
        if audit['actual_route_used'] and audit['raw']['lower']>.5 and audit['unique']['lower']>.5:
            parent=dict(engine_ref=ref,model_sha256=MODEL,model_scale=50,replay_asset_sha256=generation['memory_sha256'],
                enabled_routes=[selected['mode']],formal_adoption=False,
                inherited_assets=['replay_knowledge_data.h','retention.json','research.json','practice-report.json'],
                next_parent_change_requires_revalidation=True)
            save(OUT/'research-parent.json',parent);report.update(research_parent_updated=True,research_parent=parent,status='research_parent_improved')
        else:report['status']='confirmation_rejected_parent_retained'
    save(OUT/'result.json',report)

if __name__=='__main__':
    try:main()
    finally:
        if (OUT/'result.json').exists():
            backend=Backend(REPO,OUT/'transport');package=OUT/('replay-routes-result-'+str(backend.run_id)+'.tgz')
            with tarfile.open(package,'w:gz') as tar:
                tar.add(OUT/'result.json',arcname='result.json')
                if (OUT/'research-parent.json').exists():tar.add(OUT/'research-parent.json',arcname='research-parent.json')
                tar.add(ROOT/'research/experience-routes-20261019',arcname='research')
                tar.add(ROOT/'engine/strategy/replay_knowledge_data.h',arcname='replay_knowledge_data.h')
                tar.add(ROOT/'research/structured-eval-20261019/model.json',arcname='value-model.json')
            pub=backend.upload(package);restored=backend.unpack(pub)
            if json.loads((restored/'result.json').read_text())!=json.loads((OUT/'result.json').read_text()):raise ValueError('final readback differs')
            save(OUT/'final-publication.json',pub);print('REPLAY_PUBLICATION '+json.dumps(pub),flush=True)
