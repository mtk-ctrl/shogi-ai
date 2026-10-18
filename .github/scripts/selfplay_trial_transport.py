"""Shared runner, replay, telemetry and immutable publication for learned candidates."""
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

def audit(source,request,run,prior,require_order_usage=True):
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
    if require_order_usage and request['options_a']!=request['options_b'] and (usage['A']<=0 or usage['B']!=0):
        raise ValueError('model enabled/disabled actual usage failed')
    if require_order_usage and request['options_a']==request['options_b'] and min(usage['A'],usage['B'])<=0:
        raise ValueError('inherited model not used on both sides')
    return games,report

def publish(backend,folder,source,report,label,prefix="selfplay-order"):
    save(folder/'audit.json',report)
    package=folder/(prefix+'-'+label+'-'+str(backend.run_id)+'.tgz')
    with tarfile.open(package,'w:gz') as tar:
        for name in ('manifest.json','played-games.jsonl.gz','engine-binaries.tgz','aggregate.json'):
            tar.add(source/name,arcname=name,recursive=False)
        tar.add(folder/'audit.json',arcname='audit.json',recursive=False)
    receipt=backend.upload(package);readback=backend.unpack(receipt)
    if [g.row for g in load_archive(readback)]!=[g.row for g in load_archive(source)]:
        raise ValueError('published moves replay differs')
    save(folder/'publication.json',receipt)
    return receipt

