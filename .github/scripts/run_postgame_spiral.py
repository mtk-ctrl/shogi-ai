#!/usr/bin/env python3
"""Bounded multi-generation coordinator, reusing Generic Engine Match.

One explicit manual run executes the whole frozen plan. Standard GitHub CLI
run-watch waits for enrolled body IDs; no recurring scheduled polling task,
workflow_run privilege escalation or chains exceeding GitHub depth limits.
"""
from __future__ import annotations
import argparse
import base64
import copy
from datetime import datetime, timezone, timedelta
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.research.postgame_bridge import dump, verify_source, trajectory
from tools.research.postgame_cases import sha256
from tools.research.postgame_analyze import Analyzer, run_analysis
from tools.research.postgame_spiral import prepare
from tools.research.postgame_ranker import digest, require
from tools.research.postgame_eval_preflight import run as preflight
from tools.research.postgame_runtime import initialize, advance
from tools.research.postgame_progress import describe as describe_progress
from tools.research.postgame_knowledge import run as prepare_knowledge
from tools.research.postgame_followup import run as run_followup


def gh(*args, payload=None):
    command=['gh',*map(str,args)]
    if payload is not None: command+=['--input','-']
    return subprocess.check_output(command,input=json.dumps(payload) if payload is not None else None,text=True)


def api(path,payload=None):
    return json.loads(gh('api',path,payload=payload))


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def code_hash():
    files=sorted(ROOT.glob('tools/research/postgame_*.py'))+[Path(__file__),ROOT/'.github/workflows/postgame-spiral.yml',
          ROOT/'.github/workflows/postgame-cycle-pilot.yml',ROOT/'.github/scripts/run_postgame_knowledge_match.py']
    return digest({p.relative_to(ROOT).as_posix():sha256(p.read_bytes()) for p in files})



def algorithm_hash():
    # Audit/log/publication repairs may change, but not the frozen learning,
    # split rules, candidate gates or generation/selection semantics.
    names=('ranker','analyze','spiral','cycle','eval_preflight','runtime','candidates','cases','progress','knowledge','followup','knowledge_route')
    return digest({n:sha256((ROOT/f'tools/research/postgame_{n}.py').read_bytes()) for n in names})

def safe_extract(package,dest):
    with tarfile.open(package) as tar:
        members=tar.getmembers()
        require(sum(m.size for m in members)<=1024**3,'oversized unpacked research package')
        require(all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts
                    and (m.isfile() or m.isdir()) for m in members),'unsafe research package member')
        require(len({m.name for m in members})==len(members),'duplicate package paths')
        tar.extractall(dest,filter='data')


def runtime_statistics(paths):
    """Preserve compact observed Ponder/timing/search totals, not Raw PVs."""
    result=[]
    for path in sorted(paths):
        raw=Path(path).read_bytes();row=json.loads(raw)
        ponder=row.get('ponder')
        require(isinstance(ponder,dict) and set(ponder)=={'A','B'},'missing original Ponder observations')
        require(all(type(ponder[side].get(k)) is int and ponder[side][k]>=0
                    for side in ('A','B') for k in ('hits','misses')),'invalid Ponder observations')
        result.append(dict(shard=Path(path).name,source_sha256=sha256(raw),games=row['games'],
                           elapsed_seconds=row.get('elapsed_seconds'),ponder=ponder,
                           timing_ms=row.get('timing_ms'),search=row.get('search')))
    return result


def inherit_predecessor(env,previous):
    """New explicit budget, preserved research parent/data exposure history."""
    plan=env['state']['plan'];old=previous['state']
    require(old['stage']=='complete' and previous.get('blocked') is None,'predecessor is unfinished/blocked')
    require(previous.get('formal_adoption') is False and old.get('formal_adoption') is False,'not a research predecessor')
    require(old['parent']==plan['parent'] and previous['parent_options']==env['parent_options'],
            'new cycle reset/changed the actual research parent')
    require(old['plan'].get('algorithm_sha256')==plan.get('algorithm_sha256'),'reanalyze old features before changing learning algorithms')
    old_seeds=set(previous.get('experiment_seeds',[]))|{v for row in old['plan']['seeds'] for v in row.values()}
    new_seeds={v for row in plan['seeds'] for v in row.values()}
    require(not old_seeds & new_seeds,'new explicit cycle reused predecessor experimental seeds')
    require(digest(previous['prior_signatures'])==previous['trajectory_index_sha256'],'predecessor index hash mismatch')
    env['preparation_publication']=previous['preparation_publication']
    for key in ('parent_knowledge_publication','completed_research_tasks','source_publication'):
        if key in previous:env[key]=copy.deepcopy(previous[key])
    env['prior_signatures']=list(previous['prior_signatures'])
    env['predecessor_cycle']=old['plan']['cycle_id']
    env['experiment_seeds']=sorted(old_seeds|new_seeds)
    if 'progress_policy' in plan:
        require(old['plan'].get('progress_policy') == plan['progress_policy'],
                'predecessor progress policy differs; review the saved research queue')
        for key in ('progress_history','research_followup'):
            if key in old:env['state'][key]=copy.deepcopy(old[key])
    return env


class Backend:
    def __init__(self,repo,output):
        require(repo=='mtk-ctrl/shogi-ai','unexpected repository')
        self.repo=repo;self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.run_id=int(os.environ['GITHUB_RUN_ID']);self.attempt=os.environ.get('GITHUB_RUN_ATTEMPT','1')
        self.tag=datetime.now(timezone(timedelta(hours=9))).strftime('records-%Y-%m-01')
        self.latest_name=None;self.cache={};self.active=None

    def releases(self):
        pages=json.loads(gh('api','--paginate','--slurp',f'repos/{self.repo}/releases?per_page=100'))
        return [r for page in pages for r in page if re.fullmatch(r'records-\d{4}-\d{2}-01',r['tag_name'])]

    def release(self):
        matches=[r for r in self.releases() if r['tag_name']==self.tag]
        if not matches:
            gh('release','create',self.tag,'--repo',self.repo,'--target','main','--title',self.tag,
               '--notes','Played-move and selected own-engine research data; not a product engine release.')
            return api(f'repos/{self.repo}/releases/tags/{self.tag}')
        require(len(matches)==1,'duplicate monthly data release')
        return matches[0]

    def bytes(self,publication):
        require(re.fullmatch(r'records-\d{4}-\d{2}-01',publication.get('release',''))
                and re.fullmatch(r'[0-9a-f]{64}',publication.get('sha256',''))
                and type(publication.get('bytes')) is int and 0<publication['bytes']<=256*1024**2,
                'invalid immutable research publication')
        key=(publication['release'],publication['name'])
        if key in self.cache:return self.cache[key]
        dest=self.output/'downloads'/digest(key)[:16];dest.mkdir(parents=True,exist_ok=True)
        path=dest/publication['name']
        require(Path(publication['name']).name==publication['name'],'unsafe asset name')
        if not path.exists():gh('release','download',publication['release'],'--repo',self.repo,'--pattern',publication['name'],'--dir',dest)
        raw=path.read_bytes()
        require(len(raw)==publication['bytes'] and sha256(raw)==publication['sha256'],'Release readback hash/bytes mismatch')
        release=api(f"repos/{self.repo}/releases/tags/{publication['release']}")
        asset=next(a for a in release['assets'] if a['name']==publication['name'])
        require(asset['size']==len(raw) and asset.get('digest')=='sha256:'+sha256(raw),'Release API digest mismatch')
        self.cache[key]=path;return path

    def receipt(self,asset,tag):
        require(re.fullmatch(r'sha256:[0-9a-f]{64}',asset.get('digest','')),'missing Release API digest')
        return dict(release=tag,name=asset['name'],sha256=asset['digest'][7:],bytes=asset['size'],
                    readback_verified=True,api_digest_verified=True,url=asset['browser_download_url'])

    def upload(self,path):
        # No force/clobber and no deletion of an earlier result.
        release=self.release();require(len(release['assets'])<800,'monthly release capacity needs review')
        require(not any(a['name']==path.name for a in release['assets']),'immutable asset name already exists')
        gh('release','upload',self.tag,path,'--repo',self.repo)
        fresh=self.release();asset=next(a for a in fresh['assets'] if a['name']==path.name)
        receipt=self.receipt(asset,self.tag)
        require(receipt['sha256']==sha256(path.read_bytes()) and receipt['bytes']==path.stat().st_size,'uploaded bytes differ')
        self.bytes(receipt)
        return receipt

    def load(self,cycle_id=None):
        newest={}
        for release in self.releases():
            for a in release['assets']:
                m=re.fullmatch(r'spiral-([A-Za-z0-9-]+)-state-(\d{6})\.json',a['name'])
                if m and (cycle_id is None or m[1]==cycle_id):
                    old=newest.get(m[1]);item=(int(m[2]),a,release['tag_name'])
                    if old is None or item[0]>old[0]:newest[m[1]]=item
        states=[]
        for ident,(_,asset,tag) in newest.items():
            receipt=self.receipt(asset,tag);env=json.loads(self.bytes(receipt).read_bytes())
            require(env['state']['plan']['cycle_id']==ident and env['formal_adoption'] is False,'state identity/adoption mismatch')
            if cycle_id is not None or env['state']['stage']!='complete':states.append((env,asset['name'],tag))
        require(len(states)<=1,'multiple unfinished cycles; do not dispatch another')
        if not states:return None
        env,self.latest_name,self.tag=states[0];self.active=env
        return env

    def save(self,env):
        # Global workflow concurrency serializes controllers. A sequence-named,
        # append-only asset is a second collision guard across retries/clients.
        seq=env['sequence']+1
        env['sequence']=seq;env['previous_checkpoint']=self.latest_name
        if env.get('references_verified') is True:env['trajectory_index_sha256']=digest(env['prior_signatures'])
        name=f"spiral-{env['state']['plan']['cycle_id']}-state-{seq:06}.json"
        path=self.output/name;dump(path,env)
        require(path.stat().st_size<4*1024*1024,'checkpoint size requires review')
        self.upload(path);self.latest_name=name;self.active=env
        dump(self.output/'latest-state.json',env)
        print('SPIRAL_STATE '+json.dumps(dict(cycle=env['state']['plan']['cycle_id'],generation=env['state']['generation'],
                  stage=env['state']['stage'],used_games=env['state']['used_games'],body_run=(env.get('dispatch') or {}).get('body_run'),
                  sequence=seq,result=env['state']['result'],blocked=env['blocked']),ensure_ascii=False),flush=True)

    def free_runners(self,capacity):
        runs=[]
        for status in ('in_progress','queued'):
            pages=json.loads(gh('api','--paginate','--slurp',f'repos/{self.repo}/actions/runs?status={status}&per_page=100'))
            runs.extend(r for p in pages for r in p['workflow_runs'])
        occupied=0;observed=[]
        for r in runs:
            jobs=json.loads(gh('api','--paginate','--slurp',f"repos/{self.repo}/actions/runs/{r['id']}/jobs?per_page=100"))
            busy=[j for p in jobs for j in p['jobs'] if j['status'] in ('in_progress','queued')]
            occupied+=len(busy);observed.append(dict(run=r['id'],jobs=len(busy)))
        free=max(0,capacity-occupied)
        print('SPIRAL_RUNNERS '+json.dumps(dict(capacity=capacity,occupied=occupied,free=free,runs=observed)),flush=True)
        self.capacity_runs=[r['id'] for r in runs if r['id']!=self.run_id]
        return free

    def wait(self,env):
        body=(env.get('dispatch') or {}).get('body_run')
        if body is None:
            require(env.get('capacity_waiting') and self.capacity_runs,'no known capacity-release run to wait for')
            body=self.capacity_runs[0]
        # Standard CLI rate-aware wait; this is not a ChatGPT condition-watch.
        subprocess.run(['gh','run','watch',str(body),'--repo',self.repo,'--interval','60'],check=True)

    def dispatch(self,req):
        if req.get('execution_route')=='research_knowledge':
            release=self.release();asset=next(a for a in release['assets'] if a['name']==self.latest_name)
            checkpoint=self.receipt(asset,self.tag)
            response=api(f'repos/{self.repo}/actions/workflows/postgame-cycle-pilot.yml/dispatches',
                         dict(ref='main',return_run_details=True,inputs=dict(spiral_checkpoint=json.dumps(checkpoint),
                              request_id=self.active['state']['pending']['operation_id'],games=str(req['games']),shards=str(req['shards']))))
            body=response.get('workflow_run_id');require(type(body) is int and body>0,'research dispatch response lacks body ID; do not retry')
            print('SPIRAL_KNOWLEDGE_DISPATCH '+json.dumps(dict(body_run=body,request=req)),flush=True)
            return body
        # Official manual entry supports the nine evaluation options; this is
        # intentionally NOT an expansion/bypass of the narrower owner Issue API.
        k=api(f'repos/{self.repo}/contents/position-knowledge-v1.tsv?ref=main')
        require(sha256(base64.b64decode(k['content']))==self.active['state']['parent']['knowledge_sha256'],
                'current workflow snapshot differs from fixed research knowledge')
        from scripts.dispatch_match_request import validate
        validate(dict(req),issue_request=False)
        response=api(f'repos/{self.repo}/actions/workflows/engine-match.yml/dispatches',
                     dict(ref='main',inputs={k:str(v) for k,v in req.items()},return_run_details=True))
        body=response.get('workflow_run_id')
        require(type(body) is int and body>0,'manual dispatch response lacks run details; never blindly retry')
        print('SPIRAL_DISPATCH '+json.dumps(dict(body_run=body,request=req)),flush=True)
        return body

    def match_status(self,body):
        run=api(f'repos/{self.repo}/actions/runs/{body}')
        research=((self.active or {}).get('match_request') or {}).get('execution_route')=='research_knowledge'
        path='.github/workflows/postgame-cycle-pilot.yml' if research else '.github/workflows/engine-match.yml'
        require(run['event']=='workflow_dispatch' and run['path']==path,'wrong enrolled body')
        if run['status']!='completed':return 'waiting'
        return 'success' if run['conclusion']=='success' else 'failed'

    def folder(self,env):
        p=env['state']['pending'];folder=self.output/(env['state']['stage']+'-'+p['operation_id'][:16]);folder.mkdir(exist_ok=True)
        return folder

    def previous_stage(self,env):
        prefix=f"spiral-{env['state']['plan']['cycle_id']}-{env['state']['stage']}-{env['state']['pending']['operation_id'][:16]}-"
        matches=[a for a in self.release()['assets'] if a['name'].startswith(prefix) and a['name'].endswith('.tgz')]
        require(len(matches)<=1,'conflicting saved stage packages')
        if not matches:return None
        pub=self.receipt(matches[0],self.tag);folder=self.unpack(pub)
        binding=json.loads((folder/'binding.json').read_bytes())
        require(binding==env['state']['pending']['payload'],'saved result binding differs')
        return dict(json.loads((folder/'stage-result.json').read_bytes()),publication=pub)

    def package(self,env,data,files):
        folder=self.folder(env);dump(folder/'binding.json',env['state']['pending']['payload']);dump(folder/'stage-result.json',data)
        files=dict(files,**{'binding.json':folder/'binding.json','stage-result.json':folder/'stage-result.json'})
        name=f"spiral-{env['state']['plan']['cycle_id']}-{env['state']['stage']}-{env['state']['pending']['operation_id'][:16]}-{self.run_id}-a{self.attempt}.tgz"
        package=folder/name
        inspector=module('spiral_publish_inspector',ROOT/'.github/scripts/publish_postgame.py')
        with tarfile.open(package,'w:gz') as tar:
            for destination,path in sorted(files.items()):
                if path.suffix=='.json':inspector.no_pv(json.loads(path.read_bytes()))
                tar.add(path,arcname=destination,recursive=False)
        require(package.stat().st_size<=256*1024**2,'stage package must be split before upload')
        return self.upload(package)

    def unpack(self,pub):
        path=self.bytes(pub);dest=self.output/'unpacked'/pub['sha256'][:16]
        if not dest.exists():dest.mkdir(parents=True);safe_extract(path,dest)
        return dest

    def consume_match(self,env):
        existing=self.previous_stage(env)
        if existing:return existing
        if env['match_request'].get('execution_route')=='research_knowledge':return self.consume_knowledge_match(env)
        folder=self.folder(env);body=env['dispatch']['body_run'];req=env['match_request']
        restore=module('spiral_restore_match',ROOT/'.github/scripts/verify_selfplay_candidate.py');restore.OUT=folder
        source=restore.restore_match(body)
        jobs=api(f'repos/{self.repo}/actions/runs/{body}/jobs?per_page=100')['jobs']
        builds=[j for j in jobs if j['name']=='build' and j['conclusion']=='success']
        lanes=[j for j in jobs if j['name'].startswith('match (') and j['conclusion']=='success']
        require(len(builds)==1 and len(lanes)==req['shards'],'missing actual build/lane proof')
        require(all(any(s['name']=='Run shard' and s['conclusion']=='success' for s in j['steps']) for j in lanes),'actual match step was not started/completed')
        logger=module('spiral_safe_logs',ROOT/'.github/scripts/audit_postgame_pilot.py')
        log=logger.sanitized_job_log(self.repo,builds[0]['id'])
        candidate=env['candidate_options'] if env['state']['stage'] in ('screen','confirm') else None
        games,audit,result,binary,knowledge=verify_source(source,req,env['parent_options'],log,
                env['state']['parent']['knowledge_sha256'],candidate_options=candidate,prior_signatures=set(env['prior_signatures']))
        audit.update(match_run=body,build_job=builds[0]['id'],build_log_sha256=sha256(log.encode()),
                     actual_lane_jobs=[dict(id=j['id'],started_at=j['started_at'],completed_at=j['completed_at']) for j in lanes],
                     audit_code_sha256=code_hash())
        data=dict(audit=audit,result=result,started_lanes=len(lanes),
                  runtime_statistics=runtime_statistics((source/'shards').glob('shard-*.json')))
        files={f'played-archive/{name}':source/'verified-archive'/name for name in ('manifest.json','played-games.jsonl.gz')}
        files.update({f'build/{name}':source/'binaries/build'/name for name in ('engine-a','engine-b','position-knowledge-v1.tsv','position-knowledge-v1.manifest.json')})
        dump(folder/'match-request.json',req);files['match-request.json']=folder/'match-request.json'
        pub=self.package(env,data,files)
        return dict(data,publication=pub)

    def consume_knowledge_match(self,env):
        from tools.research.postgame_knowledge_route import materialize,audit
        folder=self.folder(env);body=env['dispatch']['body_run'];req=env['match_request']
        source=folder/'research-match';source.mkdir(exist_ok=True)
        subprocess.run(['gh','run','download',str(body),'--repo',self.repo,'--name',f'postgame-research-binaries-{body}','--dir',str(source)],check=True)
        safe_extract(source/'research-binaries.tgz',source)
        subprocess.run(['gh','run','download',str(body),'--repo',self.repo,'--pattern',f'postgame-research-shard-{body}-*','--dir',str(source/'raw')],check=True)
        shards=source/'shards';shards.mkdir()
        for path in (source/'raw').rglob('shard-*.json'):
            require(not (shards/path.name).exists(),'duplicate downloaded shard');shutil.copyfile(path,shards/path.name)
        checkenv=copy.deepcopy(env);checkenv['dispatch']['body_run']=None
        expected=materialize(checkenv,self.unpack,source/'expected-build')
        require(json.loads((source/'build/provenance.json').read_bytes())==expected,'actual research inputs differ from immutable intent')
        jobs=api(f'repos/{self.repo}/actions/runs/{body}/jobs?per_page=100')['jobs']
        builds=[j for j in jobs if j['name']=='research-build' and j['conclusion']=='success']
        lanes=[j for j in jobs if j['name'].startswith('research-match (') and j['conclusion']=='success']
        require(len(builds)==1 and len(lanes)==req['shards'],'missing research materialization/lane proof')
        require(all(any(x['name']=='Play research knowledge' and x['conclusion']=='success' for x in j['steps']) for j in lanes),
                'actual research match step did not complete')
        data=audit(source/'build',shards,req,body,source/'audit',set(env['prior_signatures']))
        data['audit'].update(match_run=body,build_job=builds[0]['id'],audit_code_sha256=code_hash(),
                 actual_lane_jobs=[dict(id=j['id'],started_at=j['started_at'],completed_at=j['completed_at']) for j in lanes])
        data['runtime_statistics']=runtime_statistics(shards.glob('shard-*.json'))
        files={f'played-archive/{p.name}':p for p in (source/'audit/played-archive').iterdir() if p.is_file()}
        files.update({f'build/{p.name}':p for p in (source/'build').iterdir() if p.is_file()})
        dump(folder/'match-request.json',req);files['match-request.json']=folder/'match-request.json'
        return dict(data,publication=self.package(env,data,files))

    def prepare(self,env):
        existing=self.previous_stage(env)
        if existing:return existing
        folder=self.folder(env);source=self.unpack(env['source_publication']);build=source/'build';binary=build/'engine-a';binary.chmod(0o755)
        knowledge=build/'position-knowledge-v1.tsv';params=env['parent_options'];context=env['state']['parent']
        previous={};old_cases={}
        if env['preparation_publication']:
            old=self.unpack(env['preparation_publication']);previous=json.loads((old/'preparation.json').read_bytes())
            old_cases={r['case_id']:r for r in json.loads((old/'eligible-cases.json').read_bytes())}
        bank=previous.get('example_bank');invalidated=0
        if bank and bank['parent_context']!=context:
            invalidated=len(bank['examples']);bank=None;old_cases={}
        count=sum(bool(s) and not s.startswith('#') for s in knowledge.read_text().splitlines())
        summary=run_analysis([source/'played-archive'],binary,knowledge,folder/'analysis',params,
                             expected_knowledge_sha256=context['knowledge_sha256'])
        diagnosis=json.loads((folder/'analysis/diagnosis.json').read_bytes())
        def probe(case):
            pairs=[]
            for _ in range(2):
                e=Analyzer(binary,knowledge,count,evaluation_options=params)
                try:pairs.append(e.search(case['start_sfen'],tuple(case['history_moves']),200))
                finally:e.close()
            return pairs
        e=Analyzer(binary,knowledge,count,evaluation_options=params)
        try:report=prepare(diagnosis,probe,e.static,'spiral-bridge-20261017-v1',registry=previous.get('split_registry'),
                           parent_options=params,example_bank=bank,parent_context=context,
                           track_decisions='progress_policy' in env['state']['plan'],
                           evaluation_enabled=env['state']['plan']['candidate_kind']!='knowledge')
        finally:e.close()
        current={r['case']['case_id']:dict(r['case'],research_move=r['research_move']) for r in diagnosis}
        all_cases=dict(old_cases,**current)
        cases=[all_cases[r['case_id']] for r in report['examples']]
        report['invalidated_old_parent_features']=invalidated
        if 'progress_policy' in env['state']['plan']:
            report['progress']=describe_progress(report,summary,diagnosis,context)
        followup=None
        if 'followup_policy' in env['state']['plan']:
            dump(folder/'original-preparation.json',report)
            followup=run_followup(binary,knowledge,report,diagnosis,context,folder/'followup',
                                  env.get('completed_research_tasks',[]))
            if followup['diagnosis_updates']:
                updates={r['case']['case_id']:r for r in followup['diagnosis_updates']}
                diagnosis=[updates.get(r['case']['case_id'],r) for r in diagnosis]
                e=Analyzer(binary,knowledge,count,evaluation_options=params)
                try:report=prepare(diagnosis,probe,e.static,'spiral-bridge-20261017-v1',registry=report['split_registry'],
                                    parent_options=params,example_bank=report['example_bank'],parent_context=context,track_decisions=True,
                                    evaluation_enabled=env['state']['plan']['candidate_kind']!='knowledge')
                finally:e.close()
                report['invalidated_old_parent_features']=invalidated
                from collections import Counter
                summary=dict(summary,routes=dict(Counter(r['route'] for r in diagnosis)),
                             verification_pairs=sum(r.get('followup') is not None for r in diagnosis),
                             seconds=summary['seconds']+followup['seconds'],followup_applied=True)
                report['progress']=describe_progress(report,summary,diagnosis,context)
                dump(folder/'effective-diagnosis.json',diagnosis)
        current={r['case']['case_id']:dict(r['case'],research_move=r['research_move']) for r in diagnosis}
        all_cases=dict(old_cases,**current)
        cases=[all_cases[r['case_id']] for r in report['examples']]
        dump(folder/'preparation.json',report);dump(folder/'eligible-cases.json',cases)
        data=dict(preparation=report,analysis_summary=summary)
        files={name:folder/name for name in ('preparation.json','eligible-cases.json')}
        files.update({f'analysis/{name}':folder/'analysis'/name for name in ('selected-cases.json','diagnosis.json','summary.json')})
        if followup is not None:
            data['followup']=followup;files['original-preparation.json']=folder/'original-preparation.json'
            if (folder/'effective-diagnosis.json').exists():files['effective-diagnosis.json']=folder/'effective-diagnosis.json'
            files.update({p.relative_to(folder).as_posix():p for p in (folder/'followup').rglob('*') if p.is_file()})
        if 'knowledge_policy' in env['state']['plan']:
            data['knowledge_stage']=prepare_knowledge(binary,knowledge,report,diagnosis,context,params,
                                                       env['state']['plan']['cycle_id'],folder/'knowledge-stage')
            files.update({p.relative_to(folder).as_posix():p for p in (folder/'knowledge-stage').rglob('*') if p.is_file()})
        return dict(data,publication=self.package(env,data,files))

    def preflight(self,env):
        existing=self.previous_stage(env)
        if existing:return existing
        source=self.unpack(env['source_publication']);folder=self.unpack(env['preparation_publication'])
        binary=source/'build/engine-a';binary.chmod(0o755)
        if env['state']['plan']['candidate_kind']=='knowledge':
            knowledge=json.loads((folder/'knowledge-stage/result.json').read_bytes())
            require(knowledge==env['knowledge_candidate'],'fixed knowledge proposal changed')
            result=knowledge['preflight']
            return dict(preflight=result,publication=self.package(env,dict(preflight=result),{}))
        result=preflight(binary,source/'build/position-knowledge-v1.tsv',env['parent_options'],env['candidate_options'],
                         json.loads((folder/'preparation.json').read_bytes()),json.loads((folder/'eligible-cases.json').read_bytes()))
        data=dict(preflight=result)
        return dict(data,publication=self.package(env,data,{}))

    def reference_index(self,plan):
        signatures=set()
        for pub in plan.get('reference_publications',[]):
            folder=self.unpack(pub)
            archives=list(folder.rglob('played-games.jsonl.gz'));require(len(archives)==1,'ambiguous reference archive')
            with gzip.open(archives[0],'rt') as stream:
                for line in stream:
                    game=json.loads(line)
                    signatures.add(trajectory(game.get('start_sfen') or __import__('shogi').STARTING_SFEN,[m['move'] for m in game['moves']]))
        return sorted(signatures)


def launch(repo):
    req=json.loads((ROOT/'.github/postgame-spiral-request.json').read_bytes())
    if req==dict(enabled=False):return
    require(set(req) in ({'cycle_id','plan_ref','repair'},{'cycle_id','plan_ref','repair','inspect_only'},
                        {'cycle_id','plan_ref','repair','publication_only'}),'launch request fields')
    require(type(req.get('inspect_only',False)) is bool,'invalid inspection flag')
    require(type(req.get('publication_only',False)) is bool,'invalid publication flag')
    require(re.fullmatch('[0-9a-f]{40}',req['plan_ref']),'fixed plan ref required')
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]{0,63}',req['cycle_id']) and type(req['repair']) is bool,'invalid start/resume request')
    response=api(f'repos/{repo}/actions/workflows/postgame-spiral.yml/dispatches',
                 dict(ref='main',return_run_details=True,inputs=dict(cycle_id=req['cycle_id'],plan_ref=req['plan_ref'],repair=str(req['repair']).lower(),inspect_only=str(req.get('inspect_only',False)).lower(),publication_only=str(req.get('publication_only',False)).lower())))
    require(type(response.get('workflow_run_id')) is int,'coordinator dispatch ID missing')
    print('SPIRAL_LAUNCH '+json.dumps(response),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--launch',action='store_true');args=parser.parse_args()
    repo=os.environ['GITHUB_REPOSITORY']
    require(repo=='mtk-ctrl/shogi-ai','unexpected repository')
    if args.launch:return launch(repo)
    backend=Backend(repo,ROOT/'build/postgame-spiral')
    event=os.environ['GITHUB_EVENT_NAME'];ident=os.environ.get('CYCLE_ID','')
    env=backend.load(ident or None)
    if env is None:
        require(event=='workflow_dispatch','only explicit manual entry may initialize a cycle')
        ref=os.environ.get('PLAN_REF','');require(re.fullmatch('[0-9a-f]{40}',ref),'fixed plan ref required')
        path=f'research/postgame-cycles/{ident}/PLAN.json'
        require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]{0,63}',ident),'invalid cycle identifier')
        raw=api(f'repos/{repo}/contents/{path}?ref={ref}')
        plan=json.loads(base64.b64decode(raw['content']))
        require(plan['cycle_id']==ident and plan['controller_sha256']==code_hash(),'frozen plan/controller mismatch')
        require('progress_policy' in plan,'new cycle plans must freeze research-yield and stagnation controls')
        require('knowledge_policy' in plan,'new cycle plans must freeze research-knowledge preparation policy')
        require('followup_policy' in plan,'new cycle plans must freeze bounded follow-up research policy')
        # New start must not overlap an already active cycle under another name.
        require(backend.load() is None,'another cycle is already active')
        env=initialize(plan,plan['parent_options'],code_hash());env['plan_ref']=ref
        env['experiment_seeds']=sorted(v for row in plan['seeds'] for v in row.values())
        if plan.get('predecessor_checkpoint'):
            prior=json.loads(backend.bytes(plan['predecessor_checkpoint']).read_bytes())
            env=inherit_predecessor(env,prior)
        backend.save(env)
    else:
        if event=='workflow_dispatch':require(os.environ.get('PLAN_REF')==env['plan_ref'],'resume changed frozen plan ref')
        changed=env['controller_sha256']!=code_hash()
        repair=os.environ.get('REPAIR')=='true' and event=='workflow_dispatch'
        if env['blocked'] is not None or changed:
            require(repair,'saved failure/code revision requires explicit investigated repair, never automatic replay')
            env.setdefault('repairs',[]).append(dict(previous_code=env['controller_sha256'],new_code=code_hash(),
                                                    blocked=env['blocked'],run=backend.run_id))
            env.update(blocked=None,controller_sha256=code_hash());backend.save(env)
    backend.active=env
    require(env['state']['plan'].get('algorithm_sha256')==algorithm_hash(),
            'frozen learning/split/gate algorithm changed; audit repair cannot retune it')
    try:
        if env.get('references_verified') is not True:
            env['prior_signatures']=sorted(set(env['prior_signatures'])|set(backend.reference_index(env['state']['plan'])))
            env['references_verified']=True
            env['reference_index_sha256']=digest(env['prior_signatures'])
            backend.save(env)
        require(digest(env['prior_signatures'])==env.get('trajectory_index_sha256',env['reference_index_sha256']),
                'saved trajectory index was edited')
        result=env
        while result['state']['stage']!='complete':
            result=advance(result,backend)
            if result['state']['stage']!='complete':backend.wait(result)
        report=dict(cycle_id=result['state']['plan']['cycle_id'],stage=result['state']['stage'],generation=result['state']['generation'],
                    used_games=result['state']['used_games'],result=result['state']['result'],research_parent=result['state']['parent'],
                    formal_adoption=False,checkpoint=backend.latest_name)
        if 'progress_policy' in result['state']['plan']:
            report.update(progress_history=result['state'].get('progress_history',[]),
                          research_followup=result['state'].get('research_followup'),
                          strength_improvement_demonstrated=False)
        dump(backend.output/'report.json',report)
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:out.write('## 自己対局の改善循環\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n')
        print('SPIRAL_RESULT '+json.dumps(report,ensure_ascii=False),flush=True)
    except Exception as exc:
        latest=backend.active or env
        latest['blocked']=dict(error_type=type(exc).__name__,message=str(exc)[:1000],run=backend.run_id)
        backend.save(latest)
        raise


if __name__=='__main__':main()
