"""Bounded research model comparison; reuse Generic Engine Match unchanged."""
import argparse
import base64
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from run_postgame_spiral import Backend,api,gh
from tools.records.archive_played_moves import archive
from tools.research.postgame_bridge import validate_shard
from tools.research.postgame_cases import load_archive,sha256

OUT=ROOT/'build/order-cycle'
REPO='mtk-ctrl/shogi-ai'
BASE_REF='4448f40400a893feb3b4d79237111008026547da'
BASE=dict(SearchResearchMask=23,SearchEfficiencyMask=8,SearchReuseMask=6,SearchNextMask=4,
    SearchProbeMask=7,SearchThreads=2,RiskVerify=True,AdaptiveLongThink=True,USI_Ponder=True,
    OpeningRandomNonLance=True,PositionKnowledge=True,PositionKnowledgeFile='build/position-knowledge-v1.tsv')

def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def launch():
    request=json.loads((ROOT/'.github/selfplay-order-request.json').read_text())
    if request==dict(enabled=False):return
    if set(request)!={'candidate_ref','request_id'} or len(request['candidate_ref'])!=40:
        raise ValueError('fixed explicit request required')
    existing=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    if any(r['display_title']=='Spiral '+request['request_id'] for r in existing):
        raise ValueError('research body already exists; reconcile instead of retry')
    result=api(f'repos/{REPO}/actions/workflows/postgame-spiral.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,inputs=dict(
        cycle_id=request['request_id'],plan_ref=request['candidate_ref'],order_only='true')))
    if type(result.get('workflow_run_id')) is not int:raise ValueError('missing actual body run')
    print('ORDER_LAUNCH '+json.dumps(result),flush=True)

def wait_body(run):
    subprocess.run(['gh','run','watch',str(run),'--repo',REPO,'--interval','60','--exit-status'],check=True)

def restore(run,folder):
    dest=folder/'downloads';dest.mkdir(parents=True,exist_ok=False)
    subprocess.run(['gh','run','download',str(run),'--repo',REPO,'--dir',str(dest)],check=True)
    source=folder/'source';source.mkdir()
    for name in ('aggregate.json','manifest.json','played-games.jsonl.gz','engine-binaries.tgz'):
        found=list(dest.rglob(name))
        if len(found)!=1:raise ValueError('missing/duplicate artifact '+name)
        shutil.copyfile(found[0],source/name)
    (source/'shards').mkdir()
    for p in dest.rglob('shard-*.json'):shutil.copyfile(p,source/'shards'/p.name)
    with tarfile.open(source/'engine-binaries.tgz') as tar:tar.extractall(source/'binaries',filter='data')
    return source

def confidence(games):
    n=len(games)
    if not n:return dict(games=0,score=0,lower=0,wins=0,losses=0,draws=0)
    c=Counter(g.row['winner'] for g in games)
    p=(c['A']+.5*c[None])/n
    # Same predeclared conservative normal approximation as the ordinary gates.
    return dict(games=n,wins=c['A'],losses=c['B'],draws=c[None],score=p,
                lower=max(0,p-1.96*math.sqrt(p*(1-p)/n)))

def signature(g):return sha256(' '.join(g.moves).encode())

def audit(source,request,run,prior):
    build=source/'binaries/build'
    binaries={s:sha256((build/('engine-'+s.lower())).read_bytes()) for s in ('A','B')}
    knowledge=sha256((build/'position-knowledge-v1.tsv').read_bytes())
    if knowledge!='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c':raise ValueError('knowledge changed')
    shards=sorted((source/'shards').glob('shard-*.json'))
    if sorted(int(p.stem.split('-')[-1]) for p in shards)!=list(range(request['shards'])):raise ValueError('missing lane')
    usage=Counter();depths={s:[] for s in ('A','B')};elapsed={s:[] for s in ('A','B')}
    for p in shards:
        row=json.loads(p.read_text());validate_shard(row,int(p.stem.split('-')[-1]),request,binaries,knowledge)
        for g in row['details']:
            for m in g['move_records']:
                s=m['engine'];r=m['search'];usage[s]+=r.get('selfplay_order_calls',0)
                if r.get('depth'):depths[s].append(r['depth'])
                if 'elapsed_ms' in r:elapsed[s].append(r['elapsed_ms'])
    manifest=json.loads((source/'manifest.json').read_text())
    if manifest['requested_ref_a']!=request['ref_a'] or manifest['requested_ref_b']!=request['ref_b']:
        raise ValueError('archive refs differ')
    rebuilt=source/'rebuilt';archive(shards,rebuilt,str(run),request['ref_a'],request['ref_b'])
    games=load_archive(source);again=load_archive(rebuilt)
    if [g.row for g in games]!=[g.row for g in again] or len(games)!=request['games']:
        raise ValueError('archive replay differs')
    unique={}
    for g in games:
        h=signature(g)
        if h not in prior:unique.setdefault(h,g)
    report=dict(run_id=run,request=request,actual_binary_sha256=binaries,knowledge_sha256=knowledge,
        all_moves_legal=True,all_terminations_verified=True,raw=confidence(games),
        unique=confidence(list(unique.values())),model_order_calls=dict(usage),
        mean_depth={s:sum(v)/len(v) if v else 0 for s,v in depths.items()},
        mean_elapsed_ms={s:sum(v)/len(v) if v else 0 for s,v in elapsed.items()},
        complete_trajectory_overlap=sum(signature(g) in prior for g in games),
        limitation='Complete-trajectory deduplication does not establish independent openings.')
    if request['options_a']!=request['options_b'] and (usage['A']<=0 or usage['B']!=0):
        raise ValueError('model enabled/disabled actual usage failed')
    if request['options_a']==request['options_b'] and min(usage['A'],usage['B'])<=0:
        raise ValueError('inherited model not used on both sides')
    return games,report

def publish(backend,folder,source,report,label):
    save(folder/'audit.json',report)
    package=folder/('selfplay-order-'+label+'-'+str(backend.run_id)+'.tgz')
    with tarfile.open(package,'w:gz') as tar:
        for name in ('manifest.json','played-games.jsonl.gz','engine-binaries.tgz','aggregate.json'):
            tar.add(source/name,arcname=name,recursive=False)
        tar.add(folder/'audit.json',arcname='audit.json',recursive=False)
    receipt=backend.upload(package);readback=backend.unpack(receipt)
    if [g.row for g in load_archive(readback)]!=[g.row for g in load_archive(source)]:
        raise ValueError('published moves replay differs')
    save(folder/'publication.json',receipt)
    return receipt

def compare(backend,ref,scale,games,seed,label,prior,new_parent=False):
    while True:
        free=backend.free_runners(20)
        if free:break
        time.sleep(30)
    oa=dict(BASE,SelfplayOrder=True,SelfplayOrderScale=scale)
    ob=oa if new_parent else BASE
    request=dict(ref_a=ref,ref_b=ref if new_parent else BASE_REF,games=games,shards=min(free,games),
        seed=seed,go_command='go movetime 200',max_plies=300,
        options_a=json.dumps(oa,sort_keys=True),options_b=json.dumps(ob,sort_keys=True))
    folder=OUT/label;folder.mkdir()
    save(folder/'request.json',request)
    response=api(f'repos/{REPO}/actions/workflows/engine-match.yml/dispatches',dict(
        ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,
        inputs={k:str(v) if type(v)is int else v for k,v in request.items()}))
    run=response.get('workflow_run_id')
    if type(run)is not int:raise ValueError('missing dispatch run ID; reconcile, do not repeat')
    save(folder/'dispatch.json',response)
    print('ORDER_MATCH '+json.dumps(dict(label=label,run_id=run,request=request)),flush=True)
    wait_body(run)
    source=restore(run,folder);actual,report=audit(source,request,run,prior)
    publication=publish(backend,folder,source,report,label)
    print('ORDER_RESULT '+json.dumps(dict(label=label,audit=report,publication=publication)),flush=True)
    return actual,report,publication,source

def main():
    p=argparse.ArgumentParser();p.add_argument('--launch',action='store_true');args=p.parse_args()
    if args.launch:return launch()
    if os.environ['GITHUB_REPOSITORY']!=REPO or os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1':
        raise ValueError('unexpected repository or retry; reconcile prior output')
    ref=os.environ['PLAN_REF']
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=ref:raise ValueError('fixed candidate checkout differs')
    model=ROOT/'research/selfplay-order-20261018/model.json'
    if sha256(model.read_bytes())!='fb1b4ad58e7e14a649e5a80db7c38709cf4356aaf8b89be4d775468e500e4f9c':raise ValueError('frozen model changed')
    preflight=json.loads((ROOT/'research/selfplay-order-20261018/preflight.json').read_text())
    if not preflight['passed']:raise ValueError('actual engine preflight failed')
    OUT.mkdir(parents=True,exist_ok=False);backend=Backend(REPO,OUT/'transport')
    prior=set(json.loads((ROOT/'research/selfplay-order-20261018/source-trajectories.json').read_text()))
    results=[]
    for i,scale in enumerate((50,100,200)):
        actual,report,pub,_=compare(backend,ref,scale,100,2031101801+i*1000000,'screen-'+str(scale),prior)
        results.append(dict(scale=scale,report=report,publication=pub))
        prior.update(signature(g) for g in actual)
    eligible=[r for r in results if r['report']['raw']['score']>=.5]
    result=dict(schema='selfplay-order-cycle-v1',candidate_ref=ref,formal_adoption=False,screens=results,
                research_parent_updated=False,next_selfplay_completed=False)
    save(OUT/'result.json',result)
    if not eligible:
        result['status']='screen_rejected';save(OUT/'result.json',result);return
    selected=max(eligible,key=lambda r:(r['report']['raw']['score'],-r['scale']))['scale']
    actual,report,pub,source=compare(backend,ref,selected,200,2036101801,'confirmation',prior)
    result.update(selected_scale=selected,confirmation=report,confirmation_publication=pub)
    save(OUT/'result.json',result)
    if not (report['raw']['lower']>.5 and report['unique']['lower']>.5):
        result['status']='confirmation_rejected';save(OUT/'result.json',result);return
    parent=dict(engine_ref=ref,model_sha256=sha256(model.read_bytes()),options=dict(BASE,SelfplayOrder=True,SelfplayOrderScale=selected),
                confirmation_run=report['run_id'],formal_adoption=False)
    result.update(research_parent_updated=True,research_parent=parent)
    save(OUT/'research-parent.json',parent)
    actual,report,pub,source=compare(backend,ref,selected,100,2041101801,'next-generation',prior,new_parent=True)
    result.update(status='research_parent_improved',next_selfplay_completed=True,next_selfplay=report,next_publication=pub)
    # The next generation is both replayed and reanalyzed using the inherited
    # research parent. Only actual position and selected search heads are saved.
    spec=importlib.util.spec_from_file_location('order_preflight',ROOT/'research/selfplay-order-20261018/preflight.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    binary=source/'binaries/build/engine-a';binary.chmod(0o755)
    positions=[]
    import shogi
    for game in actual[:8]:
        board=shogi.Board(game.start_sfen)
        ply=min(30,len(game.moves)-1)
        for m in game.moves[:ply]:board.push_usi(m)
        obs=mod.probe(binary,game.start_sfen,selected,history=game.moves[:ply])
        positions.append(dict(game_id=game.row['game_id'],ply=ply,start_sfen=game.start_sfen,
                              history_moves=game.moves[:ply],sfen=board.sfen(),observation=obs))
    result['next_reanalysis']=positions
    save(OUT/'result.json',result)


if __name__=='__main__':
    try:main()
    finally:
        if (OUT/'result.json').exists():
            backend=Backend(REPO,OUT/'transport')
            package=OUT/('selfplay-order-result-'+str(backend.run_id)+'.tgz')
            with tarfile.open(package,'w:gz') as tar:
                tar.add(OUT/'result.json',arcname='result.json',recursive=False)
                if (OUT/'research-parent.json').exists():tar.add(OUT/'research-parent.json',arcname='research-parent.json',recursive=False)
                for p in sorted((ROOT/'research/selfplay-order-20261018').glob('*')):
                    if p.is_file():tar.add(p,arcname='research/'+p.name,recursive=False)
            receipt=backend.upload(package)
            readback=backend.unpack(receipt)
            if json.loads((readback/'result.json').read_text())!=json.loads((OUT/'result.json').read_text()):
                raise ValueError('cycle readback differs')
            save(OUT/'final-publication.json',receipt)
            print('ORDER_CYCLE_PUBLICATION '+json.dumps(receipt),flush=True)
