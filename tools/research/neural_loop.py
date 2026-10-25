#!/usr/bin/env python3
"""Bounded, resumable selfplay -> research -> distillation -> independent gates.

Research parent promotion is automatic only after preregistered tests pass.
Formal engine adoption is never automatic. Evaluation games never become data.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
import torch
from tools.research import neural_model as model
from tools.research.neural_mcts import RulesOracle, research
from tools.research.neural_arena import paired_match, gate, options
from tools.research.nnue_cycle import atomic_json, immutable_file, verify_native
from tools.research.nnue_deep_study import execute as deep_study
from tools.research.nnue_labels import labels_from_diagnosis
from tools.records.archive_played_moves import archive


def freeze_archives(sources, output):
    """Pin verified inputs under the run, surviving deletion of an import dir."""
    from tools.research.postgame_cases import load_archive
    pinned=[]
    records=[]
    for index,source in enumerate(sources):
        source=Path(source).resolve()
        target=Path(output)/'inputs'/f'archive-{index:03d}'
        if (target/'manifest.json').exists() and (target/'played-games.jsonl.gz').exists():
            load_archive(target)
            if source.exists() and model.digest(source/'manifest.json')!=model.digest(target/'manifest.json'):
                raise ValueError('source archive changed after pinning')
        else:
            load_archive(source)
            target.mkdir(parents=True,exist_ok=True)
            for name in ('played-games.jsonl.gz','manifest.json'):
                payload=(source/name).read_bytes()
                part=target/(name+'.part')
                part.write_bytes(payload)
                part.replace(target/name)
            load_archive(target)
        pinned.append(target)
        records.append(dict(path=str(source),manifest_sha256=model.digest(target/'manifest.json')))
    return pinned,records


def deep_labels(study,games):
    observations=study['results']
    labels,rejected=labels_from_diagnosis(observations,{g.row['game_id']:g for g in games})
    study['teacher_admission'] = dict(accepted=len(labels), rejected=rejected)
    rows=[]
    for label in labels:
        rows.append(dict(root=label['root_game_id'],sfen=label['sfen'],origin='own_deep_search',
            target=max(-6,min(6,label['cp_black']/1000)),weight=4*label['confidence'],
            policy={str(model.action_id(label['evidence']['studied_move'])):1.0},
            policy_weight=label['confidence'],evidence=label['evidence']))
    return rows


def mcts_labels(teacher,engine,study,output,simulations,seed):
    path=Path(output)
    key=hashlib.sha256(json.dumps(study,sort_keys=True).encode()+model.digest(teacher).encode()
                       +str(simulations).encode()).hexdigest()
    state=json.loads(path.read_text()) if path.exists() else dict(identity=key,completed={})
    if state['identity']!=key:
        raise ValueError('MCTS resume inputs changed')
    net=model.load_network(teacher)
    oracle=RulesOracle(engine)
    try:
        for observation in study['results']:
            case=observation['case']
            cid=case['case_id']
            if cid in state['completed']:
                continue
            if model.split_root(case['source']['game_id'],seed)!='train':
                raise ValueError('MCTS leaked into holdout')
            def progress(value):
                state['active']=dict(case_id=cid,**value)
                atomic_json(path,state)
            result=research(net,oracle,case['start_sfen'],case['history_moves'],
                            simulations=simulations,on_progress=progress)
            state['completed'][cid]=dict(case=case,result=result)
            state.pop('active',None)
            atomic_json(path,state)
    finally:
        oracle.close()
    rows=[]
    import shogi
    for record in state['completed'].values():
        case,result=record['case'],record['result']
        board=shogi.Board(case['start_sfen'])
        for move in case['history_moves']:
            board.push_usi(move)
        rows.append(dict(root=case['source']['game_id'],sfen=board.sfen(),origin='own_mcts',
            target=math.atanh(max(-.999,min(.999,result['value_black'])))*.6,
            weight=.4,policy=result['policy'],policy_weight=1.0,
            evidence=dict(case_id=case['case_id'],teacher_sha256=model.digest(teacher),
                          completed_simulations=result['completed_simulations'])))
    return rows


@torch.no_grad()
def distill(teacher,parts):
    result=copy.deepcopy(parts)
    # Retain original labels as the main signal. This teacher is a learned
    # hypothesis, so it cannot overwrite the underlying games or heldouts.
    for at in range(0,len(result['train']),128):
        rows=result['train'][at:at+128]
        values,logits=teacher(*model.tensors(rows,'cpu'))
        for i,row in enumerate(rows):
            if row['origin'] in ('own_mcts','own_deep_search'):
                continue
            row['target']=.85*row['target']+.15*float(values[i].clamp(-6,6))
            legal=row['legal']
            probabilities=torch.softmax(logits[i,legal],0).tolist()
            original=row.get('policy',{})
            row['policy']={str(a):.8*original.get(str(a),0)+.2*p for a,p in zip(legal,probabilities)}
            if not original:
                row['policy']={str(a):p for a,p in zip(legal,probabilities)}
            row['policy_weight']=.15
    return result


def execute(args):
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    # OS releases this lock even after SIGKILL. A stale lock file is harmless.
    with (output/'writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError('another worker owns this generation directory') from e
        try:
            return run_locked(args,output)
        except BaseException as error:
            path=output/'state.json'
            state=json.loads(path.read_text()) if path.exists() else {}
            state.update(status='interrupted_resumable',last_error=str(error),
                         formal_engine_adopted=False)
            atomic_json(path,state)
            raise


def run_locked(args,output):
    if not re.fullmatch('[0-9a-f]{40}',args.source_commit):
        raise ValueError('immutable source commit required')
    if not 1<=args.generations<=100 or args.match_games<2 or args.match_games%2:
        raise ValueError('invalid bounded generation/match budget')
    if not 2<=args.selfplay_games<=10000 or args.selfplay_games%2 or not 1<=args.retries<=3:
        raise ValueError('invalid selfplay/retry budget')
    torch.set_num_threads(args.threads)
    archives=[p.resolve() for p in args.archive_dir]
    old_plan=json.loads((output/'plan.json').read_text()) if (output/'plan.json').exists() else None
    legacy=old_plan and old_plan.get('schema')=='neural-loop-v1'
    if legacy:
        sources=[dict(path=str(p),manifest_sha256=model.digest(p/'manifest.json')) for p in archives]
    else:
        archives,sources=freeze_archives(archives,output)
    plan=dict(schema='neural-loop-v1' if legacy else 'neural-loop-v2',parameters={k:str(v) if isinstance(v,Path) else
        [str(x) for x in v] if isinstance(v,list) else v for k,v in vars(args).items()},
        engine_sha256=model.digest(args.engine),knowledge_sha256=model.digest(args.knowledge),
        sources=sources,
        initial_parent_sha256=model.digest(args.parent_model) if args.parent_model else None,
        gate='paired Hoeffding; Bonferroni over all planned generations; fixed N; no peeking',
        normal_movetime_ms=200,formal_adoption=False)
    immutable_file(output/'plan.json',(json.dumps(plan,sort_keys=True,indent=2)+'\n').encode())
    state_path=output/'state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(
        completed=[],research_parent=str(args.parent_model.resolve()) if args.parent_model else None,
        accepted=0,status='running',formal_engine_adopted=False)
    if state.get('plan_sha256',model.digest(output/'plan.json'))!=model.digest(output/'plan.json'):
        raise ValueError('loop resume plan changed')
    state['plan_sha256']=model.digest(output/'plan.json')
    for generation in range(args.generations):
        directory=output/f'g{generation:03d}'
        directory.mkdir(exist_ok=True)
        selfplay_archive=directory/'selfplay-archive'
        if generation<len(state['completed']):
            saved=state['completed'][generation]
            if model.digest(directory/'candidate.nnue')!=saved['candidate_sha256']:
                raise ValueError('completed candidate was altered')
            archives.append(selfplay_archive)
            continue
        parent=Path(state['research_parent']) if state['research_parent'] else None
        timings=directory/'timings.json'
        stages=json.loads(timings.read_text()) if timings.exists() else {}
        def timed(name,fn):
            state.update(status='running',generation=generation,stage=name)
            atomic_json(state_path,state)
            start=time.monotonic()
            for attempt in range(args.retries):
                try:
                    value=fn()
                    stages[name]=stages.get(name,0)+time.monotonic()-start
                    atomic_json(timings,stages)
                    return value
                except (TimeoutError,RuntimeError,ConnectionError) as error:
                    state['last_error']=dict(stage=name,attempt=attempt+1,error=str(error))
                    atomic_json(state_path,state)
                    if attempt+1==args.retries:
                        state['status']='interrupted_resumable'
                        atomic_json(state_path,state)
                        raise
        matches=timed('selfplay',lambda:paired_match(args.engine,args.knowledge,directory/'selfplay',
            args.selfplay_games,args.seed+generation*100000,candidate=parent,parent=parent,
            max_plies=args.max_plies,movetime=args.movetime))
        if not (selfplay_archive/'manifest.json').exists():
            archive([Path(p) for p in matches['files']],selfplay_archive,
                    run_id=f'neural-{args.seed}-g{generation}',ref_a=args.source_commit,ref_b=args.source_commit)
        archives.append(selfplay_archive)
        rows,parts,games=model.prepare(archives,args.split_seed,per_game=args.samples_per_game)
        roots={g.row['game_id'] for g in games if model.split_root(g.row['game_id'],args.split_seed)=='train'}
        neural={k:v for k,v in options(args.knowledge,parent).items() if k.startswith('EvalNeural')}
        studied=timed('deep_analysis',lambda:deep_study(archives,args.engine,args.knowledge,
            directory/'deep-study.json',max_cases=args.cases,per_game=2,
            short_ms=50,medium_ms=args.medium_ms,long_ms=args.long_ms,branch_ms=args.branch_ms,
            force_long_cases=args.force_long_cases,eligible_roots=roots,neural_options=neural or None))
        extra=deep_labels(studied,games)
        _,parts,_=model.prepare(archives,args.split_seed,per_game=args.samples_per_game,extra=extra)
        previous_teacher=output/f'g{generation-1:03d}'/'teacher'/'model.pt' if generation else None
        teacher,teacher_report=timed('teacher_training',lambda:model.train(parts,directory/'teacher',
            width=args.width,residual=2,epochs=args.epochs,seed=args.seed+generation,
            warmstart=previous_teacher,threads=args.threads))
        extra+=timed('mcts_analysis',lambda:mcts_labels(directory/'teacher'/'model.pt',args.engine,
            studied,directory/'mcts.json',args.simulations,args.split_seed))
        _,parts,_=model.prepare(archives,args.split_seed,per_game=args.samples_per_game,extra=extra)
        distilled=distill(teacher,parts)
        # Keep learning from the previous learner even after a failed gate.
        # Only a passed candidate is used as the deployed selfplay parent.
        warmstart=(output/f'g{generation-1:03d}'/'student'/'model.pt') if generation else (
            parent.parent/'student'/'model.pt' if parent else None)
        if warmstart and not warmstart.exists():
            raise ValueError('parent training checkpoint missing')
        student,student_report=timed('student_training',lambda:model.train(distilled,directory/'student',
            width=args.width,epochs=args.epochs,seed=args.seed+generation,
            warmstart=warmstart,threads=args.threads))
        candidate=directory/'candidate.nnue'
        model.export_nnue(student,candidate)
        probe=parts['test'][0]['sfen']
        timed('native_verification',lambda:verify_native(args.engine,candidate,probe,
            model.quantized_cp(candidate,probe),args.knowledge))
        # Keep only compact selected derivatives; all played games have their
        # own complete archive. Evaluation archives are NEVER added to archives.
        atomic_json(directory/'research-labels.json',extra)
        comparison=timed('independent_parent_match',lambda:paired_match(args.engine,args.knowledge,
            directory/'parent-evaluation',args.match_games,args.seed+50000000+generation*100000,
            candidate=candidate,parent=parent,max_plies=args.max_plies,movetime=args.movetime))
        baseline=comparison if parent is None else timed('independent_fixed_baseline_match',
            lambda:paired_match(args.engine,args.knowledge,directory/'baseline-evaluation',
                args.match_games,args.seed+100000000+generation*100000,candidate=candidate,
                max_plies=args.max_plies,movetime=args.movetime))
        decision=gate(comparison,baseline,generation,args.generations)
        if decision['accepted']:
            state['research_parent']=str(candidate.resolve())
            state['accepted']+=1
        result=dict(generation=generation,decision=decision,parent_match=comparison,
            baseline_match=baseline,teacher=teacher_report,student=student_report,
            completed_stage_seconds=stages,
            timing_note='completed attempts accumulated; interrupted-stage time is not fully accounted',
            candidate_sha256=model.digest(candidate),
            research_parent=state['research_parent'],formal_engine_adopted=False)
        atomic_json(directory/'result.json',result)
        state['completed'].append(dict(generation=generation,accepted=decision['accepted'],
            candidate_sha256=result['candidate_sha256'],result=str(directory/'result.json')))
        state.pop('last_error',None)
        atomic_json(state_path,state)
    state.update(status='completed',stage='finished')
    atomic_json(state_path,state)
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive-dir',type=Path,action='append',required=True)
    p.add_argument('--engine',type=Path,required=True)
    p.add_argument('--knowledge',type=Path,default=ROOT/'position-knowledge-v1.tsv')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-commit',required=True)
    p.add_argument('--parent-model',type=Path)
    for name,default in [('generations',3),('selfplay-games',100),('match-games',1000),
        ('max-plies',400),('movetime',200),('cases',4),('medium-ms',600000),
        ('long-ms',3000000),('branch-ms',600000),('force-long-cases',1),
        ('epochs',20),('width',128),('simulations',512),('samples-per-game',64),
        ('seed',20261021),('split-seed',20261021),('threads',2),('retries',2)]:
        p.add_argument('--'+name,type=int,default=default)
    print(json.dumps(execute(p.parse_args()),indent=2))


if __name__=='__main__':
    main()
