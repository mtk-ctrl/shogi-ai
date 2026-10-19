"""Two explicitly authorized rounds; fixed own engine, append-only checkpoints.

The controller owns all dispatches. The ChatGPT ETA task only reconciles this
controller and its saved results. It never independently starts the next round.
"""
import base64
import copy
from datetime import datetime, timedelta, timezone
import gzip
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
import shogi
import selfplay_trial_transport as transport
from run_postgame_spiral import Backend, api
from run_selfplay_value import probe_module
from tools.research.postgame_cases import load_archive,sha256,require
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.postgame_ranker import OPTIONS
from tools.research.train_selfplay_value import fit

REPO=transport.REPO
OUT=ROOT/'build/value-loop'
save=transport.save

def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode())

def same_model(a,b):
    # BLAS reductions can differ in the final binary digit across CPUs. Input
    # hashes, split membership and the integer candidate settings stay exact.
    if isinstance(a,float) and isinstance(b,float):return math.isclose(a,b,rel_tol=0,abs_tol=1e-12)
    if type(a) is not type(b):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(same_model(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(same_model(x,y) for x,y in zip(a,b))
    return a==b

def decide(screens,confirmation=None):
    eligible=[r for r in screens if r['report']['raw']['score']>=.5]
    if not eligible:return None,False
    selected=max(eligible,key=lambda r:(r['report']['raw']['score'],-r['candidate']['fraction']))['candidate']
    passed=bool(confirmation and confirmation['raw']['lower']>.5 and confirmation['unique']['lower']>.5)
    return selected,passed

def requests(parent,candidate,games,shards,seed,new_parent=False):
    require(set(parent)==set(OPTIONS),'complete current parent required')
    a=dict(transport.BASE,**candidate)
    b=dict(transport.BASE,**(candidate if new_parent else parent))
    return dict(ref_a=transport.BASE_REF,ref_b=transport.BASE_REF,games=games,
                shards=min(games,shards),seed=seed,go_command='go movetime 200',max_plies=300,
                options_a=json.dumps(a,sort_keys=True),options_b=json.dumps(b,sort_keys=True))

def validate_plan(plan):
    require(plan['schema']=='selfplay-value-loop-v1' and plan['rounds']==2 and plan['max_games']==3200,'fixed two-round budget required')
    require(plan['engine_ref']==transport.BASE_REF and plan['formal_adoption'] is False,'research engine boundary differs')
    require(re.fullmatch(r'[a-z0-9-]{1,64}',plan['cycle_id']) is not None,'invalid cycle identifier')
    require(len(plan['seeds'])==2 and all(len(r)==5 for r in plan['seeds']),'fixed screen/confirm/source seeds required')
    seeds=[s for row in plan['seeds'] for s in row]
    require(len(seeds)==len(set(seeds)) and all(type(s)is int and 0<=s<=2147483647-2000000 for s in seeds),'invalid/repeated seed')

def exposure(directory):
    """Index immutable previously audited originals; no outcome relabeling."""
    root=Path(directory);m=json.loads((root/'manifest.json').read_text())
    name=m['archive'];require(Path(name).name==name,'unsafe archive path')
    data=(root/name).read_bytes()
    require(sha256(data)==m['archive_sha256'] and len(data)==m['archive_bytes'],'historical original differs')
    sources={r['source_id']:r['metadata'] for r in m['sources']};games=set();positions=set();count=0
    for line in gzip.decompress(data).splitlines():
        g=json.loads(line);moves=g['moves'];count+=1
        games.add(sha256(' '.join(r['move'] for r in moves).encode()))
        b=shogi.Board(g.get('start_sfen') or sources[g['source_id']].get('start_sfen') or shogi.STARTING_SFEN)
        for ply,r in enumerate(moves,1):
            if ply>=16:positions.add(sha256(' '.join(b.sfen().split()[:3]).encode()))
            b.push_usi(r['move'])
    require(count==m['games'],'historical game count differs')
    return dict(games=games,positions=positions)

def candidate_preflight(binary,rows,parent,candidates):
    probe=probe_module().probe
    require(len(rows)>=16 and len(candidates)==3,'fixed preflight materials required')
    controls=[];speed=[];options=[parent]+[c['options'] for c in candidates]
    for case in tactical_cases():
        frames=[probe(binary,case['start_sfen'],extra_options=o) for o in options]
        controls.append(dict(case_id=case['case_id'],correct=[r['move'].startswith(case['expected_prefix']) for r in frames],observations=frames))
    for row in rows[:16]:
        frames=[probe(binary,row['sfen'],extra_options=o) for o in options]
        speed.append(dict(game_hash=row['game_hash'],ply=row['ply'],observations=frames))
    depths=[sum(r['observations'][i].get('depth',0) for r in speed) for i in range(4)]
    ratios=[d/depths[0] if depths[0] else 0 for d in depths[1:]]
    passed=[c['options']!=parent and all(r['correct'][0] and r['correct'][i+1] for r in controls)
            and ratios[i]>=.9 for i,c in enumerate(candidates)]
    return dict(parent_options=parent,controls=controls,speed=speed,depth_ratios=ratios,candidates_passed=passed)

class Loop:
    def __init__(self,plan,backend):
        validate_plan(plan);self.plan=plan;self.backend=backend;self.root=OUT
        self.prefix='value-loop-'+plan['cycle_id'];self.state=None;self.cache={}

    def asset(self,name):
        return next((a for a in self.backend.release()['assets'] if a['name']==name),None)

    def existing(self,name):
        asset=self.asset(name)
        return self.backend.receipt(asset,self.backend.tag) if asset else None

    def latest(self):
        matches=[a for a in self.backend.release()['assets'] if re.fullmatch(re.escape(self.prefix)+r'-state-\d{6}\.json',a['name'])]
        if not matches:return None
        asset=max(matches,key=lambda a:a['name'])
        return json.loads(self.backend.bytes(self.backend.receipt(asset,self.backend.tag)).read_bytes())

    def checkpoint(self,phase):
        previous=self.latest()
        require((previous or {}).get('revision',0)==self.state['revision'],'checkpoint revision collision')
        self.state.update(revision=self.state['revision']+1,phase=phase,updated_at=datetime.now(timezone.utc).isoformat())
        path=self.root/(self.prefix+f"-state-{self.state['revision']:06}.json")
        save(path,self.state);receipt=self.backend.upload(path)
        require(json.loads(self.backend.bytes(receipt).read_bytes())==self.state,'checkpoint readback differs')
        save(self.root/'latest-state.json',self.state)
        print('VALUE_LOOP_STATE '+json.dumps(dict(phase=phase,round=self.state['round'],revision=self.state['revision'],
            used_games=self.state['used_games'],parent_generation=self.state['parent_generation'],
            active_operation=self.state.get('active_operation')),ensure_ascii=False),flush=True)

    def guard(self):
        raw=api(f'repos/{REPO}/contents/.github/selfplay-value-loop-control.json?ref=research/value-learning-20261018')
        control=json.loads(base64.b64decode(raw['content']))
        require(control['cycle_id']==self.plan['cycle_id'] and control['stop_requested'] is False,'owner requested stop or control identity differs')

    def package(self,label,files):
        name=self.prefix+'-'+label+'.tgz';old=self.existing(name)
        if old:
            folder=self.backend.unpack(old)
            require(all((folder/n).read_bytes()==p.read_bytes() for n,p in files.items()),'existing stage content differs')
            return old
        path=self.root/name
        with tarfile.open(path,'w:gz') as tar:
            for name,p in sorted(files.items()):tar.add(p,arcname=name,recursive=False)
        return self.backend.upload(path)

    def historical(self):
        pubs=list(self.plan['history'])
        pubs.extend(op['publication'] for op in self.state['operations'].values() if op.get('publication'))
        return {p['sha256']:p for p in pubs}

    def exclusions(self,omit=None):
        result=dict(games=set(),positions=set())
        for ident,pub in self.historical().items():
            if ident==omit:continue
            if ident not in self.cache:self.cache[ident]=exposure(self.backend.unpack(pub))
            for key in result:result[key].update(self.cache[ident][key])
        return result

    def match(self,label,parent,candidate,games,seed,new_parent=False):
        self.guard();op=self.state['operations'].get(label)
        if op is None:
            while not (free:=self.backend.free_runners(20)):
                self.guard();time.sleep(30)
            req=requests(parent,candidate,games,free,seed,new_parent)
            require(self.state['used_games']+games<=self.plan['max_games'],'round budget exceeded')
            self.state['used_games']+=games
            op=dict(operation_id=digest([self.plan['cycle_id'],label,req]),request=req,status='intent_saved')
            self.state['operations'][label]=op;self.state['active_operation']=label
            self.checkpoint(label+'-intent')
            response=api(f'repos/{REPO}/actions/workflows/engine-match.yml/dispatches',dict(
                ref=os.environ['GITHUB_REF_NAME'],return_run_details=True,
                inputs={k:str(v) if type(v)is int else v for k,v in req.items()}))
            require(type(response.get('workflow_run_id')) is int,'ambiguous dispatch; reconcile saved intent, never blindly repeat')
            op.update(run_id=response['workflow_run_id'],dispatch=response,status='running')
            self.checkpoint(label+'-running')
            print('VALUE_LOOP_MATCH '+json.dumps(dict(label=label,run_id=op['run_id'],request=req)),flush=True)
        require(type(op.get('run_id')) is int,'saved dispatch intent has no response ID; explicit reconciliation required')
        req=op['request']
        require(req['games']==games and req['seed']==seed and
                json.loads(req['options_a'])==dict(transport.BASE,**candidate) and
                json.loads(req['options_b'])==dict(transport.BASE,**(candidate if new_parent else parent)),
                'resume request changed frozen parent or candidate')
        if op.get('publication'):
            folder=self.backend.unpack(op['publication']);return op['report'],folder
        # If a publication succeeded immediately before a checkpoint failure,
        # recover that immutable result instead of dispatching another match.
        old=self.existing(self.prefix+'-'+label+'.tgz')
        if old:
            folder=self.backend.unpack(old);report=json.loads((folder/'audit.json').read_text())
            require(report['run_id']==op['run_id'] and report['request']==req,'published operation differs')
        else:
            transport.wait_body(op['run_id']);folder=self.root/label
            folder.mkdir(parents=True,exist_ok=True)
            source=folder/'source'
            if not source.exists():source=transport.restore(op['run_id'],folder)
            _,report=transport.audit(source,req,op['run_id'],self.exclusions()['games'],require_order_usage=False)
            require(not any(report['model_order_calls'].values()),'unrelated ordering model enabled')
            save(folder/'audit.json',report)
            old=self.package(label,{**{n:source/n for n in ('manifest.json','played-games.jsonl.gz','engine-binaries.tgz','aggregate.json')},
                                    'audit.json':folder/'audit.json'})
            folder=self.backend.unpack(old)
            # Re-verify legal original and settings archive on the saved bytes.
            load_archive(folder)
        op.update(publication=old,report=report,status='complete')
        self.state['active_operation']=None;self.checkpoint(label+'-saved')
        return report,folder

    def binary(self,source):
        dest=source/'binaries'
        if not dest.exists():
            from run_postgame_spiral import safe_extract
            dest.mkdir();safe_extract(source/'engine-binaries.tgz',dest)
        p=dest/'build/engine-b';p.chmod(0o755)
        require(sha256(p.read_bytes())==self.plan['binary_sha256'],'frozen feature binary differs')
        require(sha256((dest/'build/position-knowledge-v1.tsv').read_bytes())==self.plan['knowledge_sha256'],'knowledge differs')
        return p

    def learning(self,label,source_pub,parent,initial_model=None):
        saved=self.existing(self.prefix+'-'+label+'.tgz')
        if saved:return saved,json.loads((self.backend.unpack(saved)/'model.json').read_text())
        self.guard();source=self.backend.unpack(source_pub);binary=self.binary(source)
        folder=self.root/label;folder.mkdir(parents=True,exist_ok=True)
        target=folder/'fit'
        if target.exists():
            # A locally completed fit is immutable and can be recovered in the
            # same run. A new controller restores only verified publications.
            model=json.loads((target/'model.json').read_text())
        else:
            exclusions=None if initial_model is not None else self.exclusions(omit=source_pub['sha256'])
            if exclusions is not None:
                (folder/'exclusions.json.gz').write_bytes(gzip.compress(json.dumps({k:sorted(v) for k,v in exclusions.items()},sort_keys=True).encode(),mtime=0))
            try:
                fit([source],binary,target,parent_options=parent,exclusions=exclusions)
                model=json.loads((target/'model.json').read_text())
            except ValueError as error:
                if str(error)!='insufficient independent split':raise
                target.mkdir(exist_ok=True);model=dict(eligible=False,candidates=[],base_options=parent,
                    status='insufficient_new_independent_data',formal_adoption=False)
                save(target/'model.json',model)
        reproduced=None
        if initial_model is not None:
            require(same_model(model,initial_model),'saved model inputs, splits or candidate settings did not reproduce')
            reproduced=target/'model.json';model=copy.deepcopy(initial_model)
            save(folder/'frozen-model.json',model)
        positions=[]
        if initial_model is None:
            probe=probe_module().probe
            for game in load_archive(source)[:8]:
                ply=min(30,len(game.moves)-1)
                positions.append(dict(game_id=game.row['game_id'],ply=ply,start_sfen=game.start_sfen,
                    history_moves=game.moves[:ply],observation=probe(binary,game.start_sfen,history=game.moves[:ply],extra_options=parent)))
        save(folder/'diagnostics.json',dict(observations=positions,used_as_training_labels=False))
        files={'model.json':folder/'frozen-model.json' if initial_model is not None else target/'model.json',
               'diagnostics.json':folder/'diagnostics.json'}
        if reproduced is not None:files['reproduced-model.json']=reproduced
        if (target/'selected-actual-positions.jsonl').exists():files['selected-actual-positions.jsonl']=target/'selected-actual-positions.jsonl'
        if (folder/'exclusions.json.gz').exists():files['exclusions.json.gz']=folder/'exclusions.json.gz'
        return self.package(label,files),model

    def run(self,repair=False):
        self.guard();previous=self.latest()
        if previous:
            require(previous['plan_sha256']==digest(self.plan),'plan changed across resume')
            if previous['phase']=='complete':self.state=previous;return
            require(repair,'unfinished loop exists; use explicit repair after investigation')
            self.state=previous;self.state.pop('error',None)
            self.state.setdefault('repair_runs',[]).append(self.backend.run_id)
        else:
            require(not repair,'no previous loop to repair')
            source=self.backend.unpack(self.plan['initial_result'])
            initial=json.loads((source/'result.json').read_text())
            require(initial['research_parent_updated'] and initial['next_selfplay_completed'],'predecessor incomplete')
            self.state=dict(schema=self.plan['schema'],cycle_id=self.plan['cycle_id'],plan_sha256=digest(self.plan),
                plan_ref=os.environ['PLAN_REF'],controller_run=self.backend.run_id,revision=0,round=1,used_games=0,
                parent=initial['selected']['options'],initial_parent=initial['selected']['options'],parent_generation=1,
                operations={},rounds={},formal_adoption=False)
            self.checkpoint('initialized')
        result_root=self.backend.unpack(self.plan['initial_result'])
        initial=json.loads((result_root/'result.json').read_text())
        for number in range(1,3):
            self.state['round']=number
            r=self.state['rounds'].get(str(number))
            if r and r.get('complete'):continue
            if r is None:
                if number==1:
                    source_pub=initial['next_publication']
                    publication,model=self.learning('initial-learning',source_pub,self.state['parent'],initial['next_learning'])
                else:
                    prior=self.state['rounds'][str(number-1)]
                    publication=prior['next_learning_publication'];model=prior['next_model'];source_pub=prior['next_source_publication']
                require(model['base_options']==self.state['parent'],'new round reset its learned parent')
                r=dict(parent=copy.deepcopy(self.state['parent']),model=model,learning_publication=publication,
                       source_publication=source_pub,screens=[])
                self.state['rounds'][str(number)]=r;self.checkpoint(f'round-{number}-prepared')
            if 'preflight' not in r:
                folder=self.backend.unpack(r['learning_publication']);rows=[]
                if r['model']['eligible']:
                    rows=[json.loads(s) for s in (folder/'selected-actual-positions.jsonl').read_text().splitlines()]
                    checks=candidate_preflight(self.binary(self.backend.unpack(r['source_publication'])),
                        [x for x in rows if x['split']=='train'],r['parent'],r['model']['candidates'])
                else:checks=dict(candidates_passed=[False,False,False],reason=r['model'].get('status','proposal_gate_rejected'))
                path=self.root/f'round-{number}-preflight.json';save(path,checks)
                r.update(preflight=checks,preflight_publication=self.package(f'round-{number}-preflight',{'preflight.json':path}))
                self.checkpoint(f'round-{number}-preflight-saved')
            seeds=self.plan['seeds'][number-1]
            for i,c in enumerate(r['model']['candidates']):
                if not r['preflight']['candidates_passed'][i] or any(x['candidate']==c for x in r['screens']):continue
                report,_=self.match(f'r{number}-screen-{int(c["fraction"]*100)}',r['parent'],c['options'],100,seeds[i])
                r['screens'].append(dict(candidate=c,report=report));self.checkpoint(f'round-{number}-screen-recorded')
            if 'verdict' not in r:
                selected,_=decide(r['screens']);confirmation=None
                if selected:
                    confirmation,_=self.match(f'r{number}-confirmation',r['parent'],selected['options'],1000,seeds[3])
                _,promoted=decide(r['screens'],confirmation)
                r.update(selected=selected,confirmation=confirmation,promoted=promoted,
                         verdict='parent_updated' if promoted else 'parent_retained')
                if promoted:
                    self.state['parent']=selected['options'];self.state['parent_generation']+=1
                self.checkpoint(f'round-{number}-judged')
            failures=sum(not value.get('promoted',False) for value in self.state['rounds'].values() if 'verdict' in value)
            if number==2 and failures==2:
                r.update(complete=True,next_source_skipped='two unsuccessful rounds; no extra selfplay')
                self.checkpoint('round-2-complete');break
            if 'next_model' not in r:
                _,_=self.match(f'r{number}-next-source',self.state['parent'],self.state['parent'],300,seeds[4],new_parent=True)
                pub=self.state['operations'][f'r{number}-next-source']['publication']
                learning,model=self.learning(f'r{number}-next-learning',pub,self.state['parent'])
                r.update(next_source_publication=pub,next_learning_publication=learning,next_model=model)
            r['complete']=True;self.checkpoint(f'round-{number}-complete')
        require(len(self.state['rounds'])==2 and all(r['complete'] for r in self.state['rounds'].values()),'two rounds unfinished')
        # Read every enrolled publication and the final current parent back.
        for op in self.state['operations'].values():
            require(op.get('status')=='complete','unfinished enrolled match')
            self.backend.bytes(op['publication'])
        self.state['result']=dict(rounds=2,parent_updates=sum(r['promoted'] for r in self.state['rounds'].values()),
            initial_parent=self.state['initial_parent'],final_parent=self.state['parent'],used_games=self.state['used_games'],
            formal_adoption=False,limitation='Per-round approximate intervals; no repeated-testing or independent-opening guarantee.')
        self.checkpoint('complete')

def main():
    require(os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('GITHUB_RUN_ATTEMPT','1')=='1','wrong repository or blind attempt retry')
    ref=os.environ['PLAN_REF'];require(subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==ref,'frozen code checkout differs')
    plan=json.loads((ROOT/'research/selfplay-value-20261019/PLAN.json').read_text())
    require(os.environ['CYCLE_ID']==plan['cycle_id'],'workflow cycle differs')
    backend=Backend(REPO,OUT/'transport');loop=Loop(plan,backend)
    try:loop.run(repair=os.environ.get('REPAIR')=='true')
    except Exception as error:
        if loop.state:
            loop.state['error']=str(error)
            try:loop.checkpoint('blocked')
            except Exception as save_error:print('VALUE_LOOP_CHECKPOINT_ERROR '+str(save_error),flush=True)
        raise

if __name__=='__main__':main()
