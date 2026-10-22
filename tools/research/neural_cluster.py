#!/usr/bin/env python3
"""Portable map/reduce NNUE generations; one lane per available Actions runner.

Workers are isolated. Only a reducer changes the learning/parent state. Every
assignment and output is bound to the frozen plan and actual model hashes.
"""
import argparse
import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.research.nnue_cycle import atomic_json, verify_native
from tools.research.nnue_release_source import safely_extract


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def implementation():
    files = sorted((ROOT/'tools/research').glob('*.py')) + [ROOT/'benchmarks/arena.py']
    return identity({str(p.relative_to(ROOT)): sha(p) for p in files})


def parameters(request):
    defaults = dict(cycle_id='neural20', mode='standard', generations=3, runners=20,
        selfplay_games=100, screen_games=80, match_games=1000, cases=40,
        medium_ms=600000, long_ms=3000000, branch_ms=600000, epochs=20,
        width=128, simulations=512, samples_per_game=64, seed=20261022,
        split_seed=20261021, max_plies=400, threads=2)
    if request.get('mode') == 'smoke':
        defaults.update(generations=2, selfplay_games=40, screen_games=0, match_games=40,
            cases=20, medium_ms=100, long_ms=200, branch_ms=100, epochs=1,
            width=32, simulations=16, samples_per_game=8)
    if set(request)-set(defaults):
        raise ValueError('unknown request fields')
    p = dict(defaults, **request)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,60}', p['cycle_id']):
        raise ValueError('invalid cycle identifier')
    if p['mode'] not in ('standard', 'smoke'):
        raise ValueError('invalid mode')
    bounds = dict(generations=(1,3), runners=(1,20), selfplay_games=(2,10000),
        screen_games=(0,1000), match_games=(2,10000), cases=(1,96),
        medium_ms=(50,600000), long_ms=(50,3000000), branch_ms=(50,600000),
        epochs=(1,100), width=(16,256), simulations=(8,4096), samples_per_game=(8,128),
        seed=(1,1000000000), split_seed=(1,1000000000), max_plies=(100,1000), threads=(1,2))
    for k,(low,high) in bounds.items():
        if type(p[k]) is not int or not low <= p[k] <= high:
            raise ValueError('invalid budget: '+k)
    if any(p[k]%2 for k in ('selfplay_games','screen_games','match_games')):
        raise ValueError('games must form complete color pairs')
    if p['long_ms'] < p['medium_ms']:
        raise ValueError('long search shorter than medium search')
    if p['mode']=='standard' and (p['match_games']<200 or p['screen_games']<40):
        raise ValueError('standard profile needs independent screening and >=200 final games')
    return p


def partition(items, lanes):
    """Balanced contiguous partitions, never empty workers or split color pairs."""
    if lanes < 1 or not items:
        raise ValueError('nonempty work and positive runner allowance required')
    lanes = min(lanes, len(items))
    q,r = divmod(len(items),lanes)
    result,at = [],0
    for lane in range(lanes):
        n = q + (lane<r)
        result.append(items[at:at+n])
        at += n
    return result


def context(work):
    work = Path(work)
    plan,state = read(work/'plan.json'),read(work/'state.json')
    if state['plan_sha256'] != identity(plan) or plan['implementation_sha256'] != implementation():
        raise ValueError('plan or implementation changed; use a new research run')
    for file,expected in plan['fixed_assets'].items():
        if sha(work/file) != expected:
            raise ValueError('fixed engine/knowledge asset changed: '+file)
    if sha(work/'archives/source/manifest.json') != plan['source_manifest_sha256']:
        raise ValueError('original source manifest changed')
    (work/'engine/shogi-ai').chmod(0o755)
    return work,plan,state


def archives(work):
    return sorted(p.parent for p in (Path(work)/'archives').glob('*/manifest.json'))


def initialize(work, request, source, engine, knowledge, commit):
    from tools.research.neural_loop import freeze_archives
    work = Path(work)
    if (work/'plan.json').exists():
        raise ValueError('initial run directory already exists')
    if not re.fullmatch('[0-9a-f]{40}',commit):
        raise ValueError('source build commit must be immutable')
    p = parameters(request)
    (work/'engine').mkdir(parents=True,exist_ok=True)
    shutil.copy2(engine,work/'engine/shogi-ai')
    shutil.copy2(knowledge,work/'knowledge.tsv')
    pinned,_ = freeze_archives([Path(source)],work/'source-check')
    (work/'archives').mkdir()
    shutil.move(str(pinned[0]),work/'archives/source')
    shutil.rmtree(work/'source-check')
    plan = dict(schema='neural-cluster-v1',parameters=p,source_commit=commit,
        implementation_sha256=implementation(),
        source_manifest_sha256=sha(work/'archives/source/manifest.json'),
        fixed_assets={file:sha(work/file) for file in ('engine/shogi-ai','knowledge.tsv')},
        gate='fixed independent paired Hoeffding, Bonferroni across planned generations',
        formal_adoption=False)
    atomic_json(work/'plan.json',plan)
    atomic_json(work/'state.json',dict(plan_sha256=identity(plan),next_generation=0,
        accepted=0,parent=None,seen_positions=[],completed=[],formal_engine_adopted=False))
    atomic_json(work/'research-replay.json',[])


def make_tasks(work,stage,items,lanes):
    work,plan,state = context(work)
    groups = partition(items,lanes)
    assets = {}
    for file in ('parent.nnue','current/candidate.nnue','current/teacher/model.pt'):
        if (work/file).exists():
            assets[file]=sha(work/file)
    tasks = dict(stage=stage,generation=state['next_generation'],plan_sha256=identity(plan),
        assets=assets,assignments=[dict(lane=i,items=x) for i,x in enumerate(groups)])
    tasks['key']=identity(tasks)
    atomic_json(work/'tasks.json',tasks)
    return tasks


def game_items(games,seed,opponent='parent'):
    return [dict(pair=i,seed=seed,opponent=opponent) for i in range(games//2)]


def begin(work,lanes):
    work,plan,state=context(work)
    p=plan['parameters']
    if state['next_generation']>=p['generations']:
        raise ValueError('bounded generation plan already completed')
    if (work/'current').exists():
        raise ValueError('unfinished current generation; resume its stage')
    (work/'current').mkdir()
    state['lanes']=min(lanes,p['runners'])
    atomic_json(work/'state.json',state)
    return make_tasks(work,'selfplay',game_items(p['selfplay_games'],
        p['seed']+state['next_generation']*1000000),state['lanes'])


def file_manifest(directory):
    return {str(p.relative_to(directory)):sha(p) for p in sorted(Path(directory).rglob('*'))
            if p.is_file() and p.name not in ('receipt.json',) and not p.name.endswith('.part')}


def checked_receipt(directory,task_key,lane,require_complete=True):
    directory=Path(directory)
    r=read(directory/'receipt.json')
    if r['task_key']!=task_key or r['lane']!=lane:
        raise ValueError('worker output belongs to a different task/model/generation')
    if require_complete and r['status']!='completed':
        raise ValueError('worker did not complete')
    if r['files']!=file_manifest(directory):
        raise ValueError('worker files changed, missing, or unexpected')
    return r


def worker(work,output,lane):
    from tools.research import neural_model as nm
    from tools.research.neural_arena import paired_match,options
    from tools.research.nnue_deep_study import analyze
    from tools.research.neural_loop import mcts_labels
    work,plan,state=context(work)
    tasks=read(work/'tasks.json')
    key=tasks.pop('key')
    if identity(tasks)!=key or tasks['plan_sha256']!=identity(plan):
        raise ValueError('assignment plan changed')
    if tasks['generation']!=state['next_generation']:
        raise ValueError('worker generation differs from state')
    task=tasks['assignments'][lane]
    if task['lane']!=lane:
        raise ValueError('invalid worker lane')
    for file,expected in tasks['assets'].items():
        if sha(work/file)!=expected:
            raise ValueError('worker neural model changed')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    before=0
    if (output/'receipt.json').exists():
        old=checked_receipt(output,key,lane,False)
        if old['status']=='completed':
            return old
        before=old['elapsed_seconds']
    p=plan['parameters']; stage=tasks['stage']
    engine,knowledge=work/'engine/shogi-ai',work/'knowledge.tsv'
    parent=work/state['parent'] if state['parent'] else None
    started=time.monotonic()
    receipt=dict(task_key=key,lane=lane,stage=stage,generation=tasks['generation'])
    try:
        nm.torch.set_num_threads(p['threads'])
        if stage in ('selfplay','screen','evaluate'):
            # One pair is the atomic resume unit. Preserve the exact global
            # black/white seeds regardless of how many lanes are available.
            for item in task['items']:
                opponent=item['opponent']
                paired_match(engine,knowledge,output/opponent/f"p{item['pair']:05d}",
                    2,item['seed'],candidate=parent if stage=='selfplay' else work/'current/candidate.nnue',
                    parent=parent if opponent=='parent' else None,
                    max_plies=p['max_plies'],movetime=200,pair_offset=item['pair'])
        elif stage=='study':
            neural={k:v for k,v in options(knowledge,parent).items() if k.startswith('EvalNeural')}
            for case in task['items']:
                path=output/(case['case_id']+'.json')
                saved=read(path) if path.exists() else dict(case=case,partial={})
                if saved['case']!=case:
                    raise ValueError('study checkpoint changed case')
                if 'result' in saved:
                    continue
                saved['result']=analyze(engine,knowledge,case,50,p['medium_ms'],p['long_ms'],
                    p['branch_ms'],163,checkpoint=saved['partial'],
                    persist=lambda:atomic_json(path,saved),force_long=True,
                    neural_options=neural or None)
                saved.pop('partial')
                atomic_json(path,saved)
        elif stage=='mcts':
            rows=mcts_labels(work/'current/teacher/model.pt',engine,
                {'results':task['items']},output/'mcts-checkpoint.json',p['simulations'],p['split_seed'])
            atomic_json(output/'labels.json',rows)
        else:
            raise ValueError('unknown worker stage')
        receipt['status']='completed'
    except BaseException as error:
        receipt.update(status='interrupted_resumable',error=str(error))
        raise
    finally:
        receipt.update(elapsed_seconds=before+time.monotonic()-started,files=file_manifest(output))
        atomic_json(output/'receipt.json',receipt)
    return receipt


def collect_outputs(work,outputs):
    tasks=read(Path(work)/'tasks.json')
    expected={a['lane'] for a in tasks['assignments']}
    found={}
    for path in sorted(Path(outputs).glob('lane-*/receipt.json')):
        lane=read(path)['lane']
        if lane not in expected or lane in found:
            raise ValueError('unexpected or duplicated worker')
        found[lane]=(path.parent,checked_receipt(path.parent,tasks['key'],lane))
    if set(found)!=expected:
        raise ValueError('missing worker outputs: '+str(sorted(expected-set(found))))
    return tasks,found


def collect_matches(work,tasks,found):
    from tools.research.neural_arena import summarize_records
    work,plan,state=context(work)
    by_opponent={}
    for assignment in tasks['assignments']:
        directory,_=found[assignment['lane']]
        for item in assignment['items']:
            path=directory/item['opponent']/f"p{item['pair']:05d}"/f"pair-{item['pair']:05d}.json"
            record=read(path)
            ident=record['identity']
            parent_sha=sha(work/state['parent']) if state['parent'] else None
            candidate_sha=parent_sha if tasks['stage']=='selfplay' else sha(work/'current/candidate.nnue')
            if (ident['seed']!=item['seed'] or ident.get('pair_offset',0)!=item['pair'] or
                ident['games']!=2 or ident['movetime']!=200 or ident['max_plies']!=plan['parameters']['max_plies'] or
                ident['binary_sha256']!=plan['fixed_assets']['engine/shogi-ai'] or
                ident['knowledge_sha256']!=plan['fixed_assets']['knowledge.tsv'] or
                ident['candidate_sha256']!=candidate_sha or
                ident['parent_sha256']!=(parent_sha if item['opponent']=='parent' else None)):
                raise ValueError('paired game identity/conditions mismatch')
            details=record['details']
            if len(details)!=2 or [g['a_black'] for g in details]!=[True,False]:
                raise ValueError('missing color-swapped game')
            for field,winner in (('wins_a','A'),('wins_b','B'),('draws',None)):
                if record[field]!=sum(g['winner']==winner for g in details):
                    raise ValueError('recorded outcomes disagree with actual games')
            by_opponent.setdefault(item['opponent'],[]).append((path,record))
    return {opponent:(summarize_records([r for _,r in rows],[p for p,_ in rows]),
                       [p for p,_ in rows]) for opponent,rows in by_opponent.items()}


def replay_merge(old,new):
    # Keep a bounded derivative per source-position/origin. Source game IDs and
    # the original full histories are still checked by neural_model.prepare.
    rows={(r['root'],r['sfen'],r['origin']):r for r in old}
    for r in new:
        rows[(r['root'],r['sfen'],r['origin'])]=r
    return [rows[k] for k in sorted(rows)]


def train_stage(work,kind):
    from tools.research import neural_model as nm
    from tools.research.neural_loop import distill
    work,plan,state=context(work); p=plan['parameters']
    _,parts,_=nm.prepare(archives(work),p['split_seed'],per_game=p['samples_per_game'],
                       extra=read(work/'research-replay.json'))
    if kind=='student':
        parts=distill(nm.load_network(work/'current/teacher/model.pt'),parts)
    warm=work/'learner'/kind/'model.pt'
    net,report=nm.train(parts,work/'current'/kind,width=p['width'],residual=2 if kind=='teacher' else 0,
        epochs=p['epochs'],seed=p['seed']+state['next_generation'],
        warmstart=warm if warm.exists() else None,threads=p['threads'])
    if kind=='student':
        candidate=work/'current/candidate.nnue'
        nm.export_nnue(net,candidate)
        probe=parts['validation'][0]['sfen']
        proof=verify_native(work/'engine/shogi-ai',candidate,probe,nm.quantized_cp(candidate,probe),work/'knowledge.tsv')
        atomic_json(work/'current/native-verification.json',proof)
    return report


def reduce_stage(work,outputs):
    from tools.research import neural_model as nm
    from tools.research.neural_loop import deep_labels
    from tools.research.nnue_deep_study import choose
    from tools.records.archive_played_moves import archive
    work,plan,state=context(work); p=plan['parameters']
    tasks,found=collect_outputs(work,outputs)
    stage=tasks['stage']; generation=state['next_generation']; current=work/'current'
    started=time.monotonic()
    timing=dict(workers=len(found),worker_seconds=sum(r['elapsed_seconds'] for _,r in found.values()),
        longest_worker_seconds=max(r['elapsed_seconds'] for _,r in found.values()))
    if stage in ('selfplay','screen','evaluate'):
        matches=collect_matches(work,tasks,found)
        for opponent,(summary,paths) in matches.items():
            destination=(work/'archives'/f'g{generation:03d}' if stage=='selfplay' else
                         current/'evaluation-archives'/f'{stage}-{opponent}')
            if not (destination/'manifest.json').exists():
                archive(paths,destination,run_id=f"{p['cycle_id']}-g{generation}-{stage}-{opponent}",
                        ref_a=plan['source_commit'],ref_b=plan['source_commit'])
            summary['files']=[str(destination.relative_to(work))]
            atomic_json(current/f'{stage}-{opponent}.json',summary)
    if stage=='selfplay':
        _,_,games=nm.prepare(archives(work),p['split_seed'],per_game=p['samples_per_game'])
        roots={g.row['game_id'] for g in games if nm.split_root(g.row['game_id'],p['split_seed'])=='train'}
        cases=choose(games,p['cases'],2,roots,excluded_positions=state['seen_positions'],
                     selection_seed=p['seed']+generation)
        if len(cases)!=p['cases']:
            raise ValueError(f"need {p['cases']} fresh train cases; found {len(cases)}")
        atomic_json(current/'cases.json',cases)
        make_tasks(work,'study',cases,state['lanes'])
    elif stage=='study':
        observations=[]
        for task in tasks['assignments']:
            directory,_=found[task['lane']]
            for case in task['items']:
                saved=read(directory/(case['case_id']+'.json'))
                if saved['case']!=case or saved['result']['case']!=case:
                    raise ValueError('study output case changed')
                observations.append(saved['result'])
        study={'results':observations}
        atomic_json(current/'deep-study.json',study)
        _,_,games=nm.prepare(archives(work),p['split_seed'],per_game=p['samples_per_game'])
        extra=deep_labels(study,games)
        atomic_json(work/'research-replay.json',replay_merge(read(work/'research-replay.json'),extra))
        timing['new_deep_labels']=len(extra)
        train_stage(work,'teacher')
        make_tasks(work,'mcts',observations,state['lanes'])
    elif stage=='mcts':
        extra=[]
        for directory,_ in found.values():
            extra.extend(read(directory/'labels.json'))
        if len(extra)!=sum(len(t['items']) for t in tasks['assignments']):
            raise ValueError('missing MCTS labels')
        atomic_json(work/'research-replay.json',replay_merge(read(work/'research-replay.json'),extra))
        train_stage(work,'student')
        if p['screen_games']:
            make_tasks(work,'screen',game_items(p['screen_games'],p['seed']+generation*1000000+200000),state['lanes'])
        else:
            atomic_json(current/'screen-decision.json',dict(pass_screen=True,reason='smoke_only_skips_screen'))
            evaluation_tasks(work)
    elif stage=='screen':
        match=read(current/'screen-parent.json')
        passed=match['invalid_games']==0 and match['score']>=.5
        atomic_json(current/'screen-decision.json',dict(pass_screen=passed,
            reason='predeclared_screen_passed' if passed else 'rejected_before_full_match',
            score=match['score'],games=match['games'],used_for_promotion=False))
        if passed:
            evaluation_tasks(work)
    elif stage!='evaluate':
        raise ValueError('unknown reducer stage')
    timing['reduce_and_learning_seconds']=time.monotonic()-started
    atomic_json(current/(stage+'-timing.json'),timing)


def evaluation_tasks(work):
    work,plan,state=context(work); p=plan['parameters']; generation=state['next_generation']
    # Screening and final evaluation use disjoint, preregistered seed regions.
    items=game_items(p['match_games'],p['seed']+generation*1000000+400000)
    if state['parent']:
        items+=game_items(p['match_games'],p['seed']+generation*1000000+600000,'baseline')
    return make_tasks(work,'evaluate',items,state['lanes'])


def finish(work):
    from tools.research.neural_arena import gate
    work,plan,state=context(work); p=plan['parameters']; current=work/'current'
    pending=work/'finalization.json'
    if pending.exists():
        transaction=read(pending)
        if (transaction['plan_sha256']!=identity(plan) or
            identity(state) not in (transaction['before_state_sha256'],identity(transaction['state']))):
            raise ValueError('finalization belongs to a different generation state')
        result=transaction['result']
    else:
        decision=read(current/'screen-decision.json')
        result=dict(generation=state['next_generation'],screen=decision,formal_engine_adopted=False,
            candidate_sha256=sha(current/'candidate.nnue'),
            teacher=read(current/'teacher/report.json'),student=read(current/'student/report.json'),
            case_count=len(read(current/'cases.json')),replay_rows=len(read(work/'research-replay.json')),
            stage_timings={f.stem:read(f) for f in current.glob('*-timing.json')})
        if decision['pass_screen']:
            parent=read(current/'evaluate-parent.json')
            baseline=read(current/'evaluate-baseline.json') if state['parent'] else parent
            result.update(parent_match=parent,baseline_match=baseline,
                decision=gate(parent,baseline,state['next_generation'],p['generations']))
        else:
            result['decision']=dict(accepted=False,reason='screen_rejected',formal_engine_adopted=False)
        if p['mode']=='smoke':
            result['decision'].update(accepted=False,reason='integration_only_not_a_strength_test')
        next_state=copy.deepcopy(state)
        if result['decision']['accepted']:
            next_state['parent']='parent.nnue'
            next_state['accepted']+=1
        next_state['seen_positions']=sorted(set(state['seen_positions'])|
            {c['position_key'] for c in read(current/'cases.json')})
        next_state['completed'].append(dict(generation=state['next_generation'],
            accepted=result['decision']['accepted'],candidate_sha256=result['candidate_sha256']))
        next_state['next_generation']+=1
        next_state['status']='completed' if next_state['next_generation']>=p['generations'] else 'ready_for_next_generation'
        transaction=dict(plan_sha256=identity(plan),before_state_sha256=identity(state),
            state=next_state,result=result,
            learner_files={kind:file_manifest(current/kind) for kind in ('teacher','student')})
        # Persist the entire transition BEFORE removing or moving any input.
        # A retry can finish it even after current was renamed or state saved.
        atomic_json(pending,transaction)
    history=work/'history'/f"g{result['generation']:03d}"
    record=current if current.exists() else history
    if sha(record/'candidate.nnue')!=result['candidate_sha256']:
        raise ValueError('finalization candidate changed')
    if result['decision']['accepted']:
        shutil.copy2(record/'candidate.nnue',work/'parent.nnue')
    for kind in ('teacher','student'):
        source=current/kind
        destination=work/'learner'/kind
        expected=transaction['learner_files'][kind]
        if source.exists():
            if file_manifest(source)!=expected:
                raise ValueError('finalization source learner changed')
            if file_manifest(destination)!=expected:
                if destination.exists():shutil.rmtree(destination)
                shutil.copytree(source,destination)
        if file_manifest(destination)!=expected:
            raise ValueError('finalization learner missing or changed')
    atomic_json(record/'result.json',result)
    if current.exists():
        for kind in ('teacher','student'):
            if (current/kind).exists():shutil.rmtree(current/kind)
        history.parent.mkdir(exist_ok=True)
        if history.exists():raise ValueError('duplicate generation history')
        shutil.move(str(current),history)
    (work/'tasks.json').unlink(missing_ok=True)
    atomic_json(work/'state.json',transaction['state'])
    pending.unlink()
    return result


def clean_research(value):
    if isinstance(value,dict):
        return {k:clean_research(v) for k,v in value.items()
                if k not in ('pv','ponder_pv','pv_moves','principal_variation')}
    if isinstance(value,list):
        return [clean_research(v) for v in value]
    if isinstance(value,str) and value.startswith('info ') and ' pv ' in value:
        return value.split(' pv ',1)[0]
    return value


def pack(directory,bundle,workers=False,durable=False):
    """Deterministic archive with file hashes; preserve executable mode via tar."""
    directory,bundle=Path(directory),Path(bundle)
    bundle.parent.mkdir(parents=True,exist_ok=True)
    files=[]
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or path.is_symlink() or path.name.endswith('.part'):
            continue
        rel=path.relative_to(directory).as_posix()
        if workers:
            if rel.startswith(('history/','learner/')) or rel=='research-replay.json':
                continue
            if rel.startswith('current/') and rel not in ('current/teacher/model.pt','current/candidate.nnue'):
                continue
        files.append((path,rel))
    import io
    manifest={}
    with bundle.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as gz,tarfile.open(fileobj=gz,mode='w|') as out:
        for path,rel in files:
            data=path.read_bytes()
            if durable and path.suffix=='.json':
                original=json.loads(data)
                cleaned=clean_research(original)
                if cleaned != original:
                    data=(json.dumps(cleaned,sort_keys=True,indent=2)+'\n').encode()
            manifest[rel]=hashlib.sha256(data).hexdigest()
            info=tarfile.TarInfo(rel);info.size=len(data);info.mode=0o755 if os.access(path,os.X_OK) else 0o644
            out.addfile(info,io.BytesIO(data))
        data=(json.dumps(manifest,sort_keys=True)+'\n').encode()
        info=tarfile.TarInfo('BUNDLE-MANIFEST.json');info.size=len(data)
        out.addfile(info,io.BytesIO(data))
    return sha(bundle)


def unpack(bundle,directory):
    directory=Path(directory)
    safely_extract(bundle,directory,max_bytes=2*1024**3)
    manifest=read(directory/'BUNDLE-MANIFEST.json')
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*')
            if p.is_file() and p.name!='BUNDLE-MANIFEST.json'}
    if actual!=set(manifest) or any(sha(directory/name)!=value for name,value in manifest.items()):
        raise ValueError('bundle content failed checksum verification')
    (directory/'BUNDLE-MANIFEST.json').unlink()
    if (directory/'engine/shogi-ai').exists():
        (directory/'engine/shogi-ai').chmod(0o755)


def workflow_outputs(work):
    work,plan,state=context(work)
    values=dict(more=str(state['next_generation']<plan['parameters']['generations']).lower(),
                generation=state['next_generation'])
    if (work/'tasks.json').exists():
        task=read(work/'tasks.json')
        values.update(matrix=json.dumps({'lane':[a['lane'] for a in task['assignments']]}),stage=task['stage'])
    if (work/'current/screen-decision.json').exists():
        values['evaluate']=str(read(work/'current/screen-decision.json')['pass_screen']).lower()
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for k,v in values.items():print(f'{k}={v}',file=f)
    print(json.dumps(values))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('init','begin','worker','reduce','finish','pack','unpack','outputs'))
    p.add_argument('--work',type=Path,default=Path('run'))
    p.add_argument('--request',type=Path)
    p.add_argument('--source',type=Path)
    p.add_argument('--engine',type=Path)
    p.add_argument('--knowledge',type=Path,default=ROOT/'position-knowledge-v1.tsv')
    p.add_argument('--commit')
    p.add_argument('--lanes',type=int,default=20)
    p.add_argument('--lane',type=int)
    p.add_argument('--output',type=Path,default=Path('task'))
    p.add_argument('--inputs',type=Path,default=Path('results'))
    p.add_argument('--bundle',type=Path,default=Path('state.tgz'))
    p.add_argument('--workers',action='store_true')
    p.add_argument('--durable',action='store_true')
    args=p.parse_args()
    if args.command=='init':initialize(args.work,read(args.request),args.source,args.engine,args.knowledge,args.commit)
    elif args.command=='begin':begin(args.work,args.lanes)
    elif args.command=='worker':worker(args.work,args.output,args.lane)
    elif args.command=='reduce':reduce_stage(args.work,args.inputs)
    elif args.command=='finish':finish(args.work)
    elif args.command=='pack':print(pack(args.work,args.bundle,args.workers,args.durable))
    elif args.command=='unpack':unpack(args.bundle,args.work)
    elif args.command=='outputs':workflow_outputs(args.work)


if __name__=='__main__':
    main()
