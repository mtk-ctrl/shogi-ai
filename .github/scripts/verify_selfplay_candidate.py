#!/usr/bin/env python3
"""Frozen-model timing and finished-match audits on a GitHub runner."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT=Path.cwd()
OUT=ROOT/'build/selfplay-verification'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def run(args,cwd=None):subprocess.run([str(x) for x in args],cwd=cwd,check=True)
def gh(*args):return subprocess.check_output(['gh',*map(str,args)],text=True)
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def request():
    d=json.loads(Path('.github/selfplay-verification-request.json').read_text())
    if set(d)!={'request_id','mode','candidate_ref','baseline_ref','match_run'}:raise ValueError('request keys')
    if d['mode'] not in ('benchmark','audit'):raise ValueError('mode')
    if not all(re.fullmatch('[0-9a-f]{40}',d[k]) for k in ('candidate_ref','baseline_ref')):raise ValueError('fixed refs required')
    if type(d['match_run']) is not int or d['match_run']<0 or (d['mode']=='audit' and d['match_run']==0):raise ValueError('match run')
    return d
def restore_match(run_id):
    info=json.loads(gh('run','view',run_id,'--repo',os.environ['GITHUB_REPOSITORY'],'--json','conclusion,status'))
    if info!={'conclusion':'success','status':'completed'}:raise ValueError('match not successful')
    source=OUT/'source';downloads=source/'downloads';downloads.mkdir(parents=True)
    run(['gh','run','download',run_id,'--repo',os.environ['GITHUB_REPOSITORY'],'--dir',downloads])
    (source/'shards').mkdir()
    for p in downloads.rglob('shard-*.json'):shutil.copyfile(p,source/'shards'/p.name)
    for name in ('aggregate.json','manifest.json','played-games.jsonl.gz','engine-binaries.tgz'):
        matches=list(downloads.rglob(name))
        if len(matches)!=1:raise ValueError('missing/ambiguous original '+name)
        shutil.copyfile(matches[0],source/name)
    with tarfile.open(source/'engine-binaries.tgz') as t:t.extractall(source/'binaries',filter='data')
    return source
def publish(mode,files):
    pack=module('pack',ROOT/'engine-a-src/research/selfplay-learning-20261016/persist.py')
    name=f"selfplay-{mode}-{os.environ['GITHUB_RUN_ID']}.tgz"
    package=OUT/name;pack.pack(package,files)
    if package.stat().st_size>256*1024*1024:raise ValueError('asset split required')
    repo=os.environ['GITHUB_REPOSITORY'];tag='records-2026-10-01';check=OUT/'release-readback';check.mkdir()
    run(['gh','release','upload',tag,package,'--repo',repo])
    run(['gh','release','download',tag,'--repo',repo,'--pattern',name,'--dir',check])
    if sha(package)!=sha(check/name):raise ValueError('release readback mismatch')
    result={'release':tag,'name':name,'sha256':sha(package),'bytes':package.stat().st_size,'readback_verified':True}
    save(OUT/'publication.json',result);return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--plan-only',action='store_true');a=p.parse_args();d=request()
    if a.plan_only:
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for k in ('mode','candidate_ref','baseline_ref'):f.write(f'{k}={d[k]}\n')
        return
    OUT.mkdir(parents=True,exist_ok=True)
    candidate=ROOT/'engine-a-src';base=ROOT/'engine-b-src'
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=candidate,text=True).strip()
    if actual!=d['candidate_ref']:raise ValueError('candidate checkout mismatch')
    training=json.loads((candidate/'research/selfplay-learning-20261016/training-report.json').read_text())
    provenance={'candidate_ref':actual,'baseline_ref':d['baseline_ref'],'model_sha256':training['model_sha256']}
    files={}
    if d['mode']=='benchmark':
        if subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip()!=d['baseline_ref']:raise ValueError('baseline checkout mismatch')
        for side,source in (('a',candidate),('b',base)):
            run(['python3','scripts/build.py','--output',OUT/('engine-'+side)],cwd=source)
        provenance['compiler']=subprocess.check_output(['g++','--version'],text=True).splitlines()[0]
        for side in ('a','b'):provenance['binary_sha256_'+side]=sha(OUT/('engine-'+side))
        run(['python3','research/selfplay-learning-20261016/benchmark.py',OUT/'engine-b',OUT/'engine-a',OUT/'measurements.json'],cwd=candidate)
        m=json.loads((OUT/'measurements.json').read_text())
        summary={n:{k:v for k,v in s.items() if k not in ('full_mismatches','score_mismatches')} for n,s in m['summary'].items()}
        ratio=summary['learned100']['timed_depth_sum']/summary['official_v2020']['timed_depth_sum']
        result={'mode':'benchmark','provenance':provenance,'conditions':m['conditions'],'summary':summary,
                'off_exact':not m['summary']['control']['full_mismatches'],
                'timed_depth_ratio':ratio,'comparison_gate_pass':training['validation_pass'] and ratio>=.9,
                'discarded_local_measurement':'Unconfirmed local timing was discarded after exec-server transport loss; only this complete single-runner comparison is used.'}
        files['measurements.json']=OUT/'measurements.json'
    else:
        source=restore_match(d['match_run'])
        run(['python3',candidate/'research/selfplay-learning-20261016/audit_match.py',source,
             '--candidate-ref',d['candidate_ref'],'--baseline-ref',d['baseline_ref'],'--output',OUT/'audit.json'])
        result=json.loads((OUT/'audit.json').read_text());result['mode']='audit'
        repo=os.environ['GITHUB_REPOSITORY']
        jobs=json.loads(gh('api',f"repos/{repo}/actions/runs/{d['match_run']}/jobs?per_page=100"))['jobs']
        build=[j for j in jobs if j['name']=='build' and j['conclusion']=='success']
        if len(build)!=1:raise ValueError('match build proof')
        restore=module('restore',candidate/'research/selfplay-learning-20261016/restore.py')
        log=restore.read_job_log(repo,build[0]['id'])
        provenance['build_job']=build[0]['id']
        for side,ref in (('a',d['candidate_ref']),('b',d['baseline_ref'])):
            if not re.search(r'git checkout --progress --force '+ref,log):raise ValueError('actual match source not proven')
            expected=re.findall(r'([a-f0-9]{64})  build/engine-'+side,log)
            binary=source/'binaries/build'/('engine-'+side)
            if len(expected)!=1 or sha(binary)!=expected[0]:raise ValueError('match binary proof')
            provenance['binary_sha256_'+side]=expected[0]
        result['provenance']=provenance
        pub=json.loads((candidate/'research/selfplay-learning-20261016/publication.json').read_text())
        original=next(x for x in pub['assets'] if x['name'].startswith('selfplay-source-'))
        orig=OUT/'original-training';orig.mkdir()
        run(['gh','release','download','records-2026-10-01','--repo',repo,'--pattern',original['name'],'--dir',orig])
        if sha(orig/original['name'])!=original['sha256']:raise ValueError('training original hash')
        with tarfile.open(orig/original['name']) as t:t.extractall(orig,filter='data')
        manifest=json.loads((orig/'manifest.json').read_text())
        index={s['source_id']:int(Path(s['file']).stem.split('-')[-1]) for s in manifest['sources']}
        def signature(g):return hashlib.sha256(('startpos\n'+' '.join(r['move'] for r in g['moves'])).encode()).hexdigest()
        all_games=set();train_games=set()
        with gzip.open(orig/'played-games.jsonl.gz','rt') as f:
            for line in f:
                game=json.loads(line);sig=signature(game);all_games.add(sig)
                if index[game['source_id']]<13 and game['reason']!='move_limit':train_games.add(sig)
        with gzip.open(source/'played-games.jsonl.gz','rt') as f:signatures=[signature(json.loads(line)) for line in f]
        result['training_game_trajectory_overlap']=sum(s in train_games for s in signatures)
        result['source_corpus_trajectory_overlap']=sum(s in all_games for s in signatures)
        for name in ('aggregate.json','manifest.json','played-games.jsonl.gz','engine-binaries.tgz'):files[name]=source/name
        files['audit.json']=OUT/'audit.json'
    save(OUT/'report.json',result);save(OUT/'build-provenance.json',provenance)
    files.update({'report.json':OUT/'report.json','build-provenance.json':OUT/'build-provenance.json'})
    publication=publish(d['mode'],files)
    result['publication']=publication;save(OUT/'report.json',result)
    print('VALIDATION_RESULT '+json.dumps(result,ensure_ascii=False,separators=(',',':')),flush=True)
if __name__=='__main__':main()
