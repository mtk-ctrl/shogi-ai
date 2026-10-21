#!/usr/bin/env python3
"""Bounded own-engine execution of training-only saved research requests.

Original observations are never edited. A successful repeat is research
information, not automatically a teacher, candidate or strength improvement.
"""
from __future__ import annotations
import copy
from collections import Counter
from pathlib import Path
import time
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp, compare_children, route_result, OPTIONS
from tools.research.postgame_cases import position_command, sha256
from tools.research.postgame_candidates import replay
from tools.research.postgame_progress import describe
from tools.research.postgame_ranker import digest, require, parent_values

POLICY_FOLLOWUP=dict(schema='postgame-followup-policy-v1',max_tasks=8,root_ms=[50,500],repeats=2,
                     child_ms=500,fixed_timeout_ms=5000,max_fixed_depth=4,mate_ms=1000,attempts_per_parent_task=1)
SUPPORTED_KINDS=frozenset(('verify_mate_research','repeat_missing_observation','review_search_stability',
                            'verify_same_depth','resolve_parent_instability','extend_own_analysis'))


def tasks_from(preparation,diagnosis,parent,for_practice=False):
    progress=preparation['progress'];bare={k:v for k,v in preparation.items() if k!='progress'}
    require(progress==describe(bare,progress['analysis'],diagnosis,parent),'follow-up evidence/queue differs')
    params=preparation['learning']['parent_options'];parent_values(params)
    require(preparation['example_bank']['parent_context']==parent and digest(params)==parent['parameters_sha256']
            and progress['analysis']['evaluation_options']==params and progress['analysis']['options']==OPTIONS,
            'follow-up parent/search/evaluation differs')
    rows={r['case']['case_id']:r for r in diagnosis};tasks=[]
    for task in progress['work_items']:
        if task['kind']=='validate_research_knowledge':continue
        supported=task['kind'] in SUPPORTED_KINDS
        if for_practice and not supported:continue  # Keep representation tasks in the original queue.
        # Unsupported kinds remain in the audited queue, but are not executed
        # as a different kind of research.
        row=rows[task['case']['case_id']]
        require(task['split']=='train' and task['parent']==parent and task['case']==row['case']
                and task['evidence']['row_sha256']==digest(row),'follow-up leaked split or changed evidence')
        case=task['case'];command=position_command(case['start_sfen'],tuple(case['history_moves']))
        require(sha256(command.encode())==case['history_key'],'follow-up lost actual history')
        replay(case)
        require(case.get('evidence_purpose')!='synthetic_fixture','synthetic fixture is not follow-up training research')
        tasks.append((copy.deepcopy(task),copy.deepcopy(row)))
    require(len(tasks)<=96, 'follow-up queue exceeds selected-case budget')
    return sorted(tasks,key=lambda pair:(pair[0]['priority'],pair[0]['task_id']))


def stable(results):
    return all(exact_cp(r) for r in results) and len({r['bestmove'] for r in results})==1


def execute(task,row,search,mate):
    """Search accepts (case, full_history, ms, depth); every call is fresh."""
    case=task['case'];history=tuple(case['history_moves'])
    def checked(history,ms,depth=None):
        result=search(case,history,ms,depth);command=position_command(case['start_sfen'],history)
        require(result['position_command']==command and result['history_key']==sha256(command.encode())
                and result['requested_ms']==ms and result['requested_depth']==depth,
                'follow-up observation lost command/time/history')
        return result
    repeats={str(ms):[checked(history,ms) for _ in range(POLICY_FOLLOWUP['repeats'])]
             for ms in POLICY_FOLLOWUP['root_ms']}
    command=position_command(case['start_sfen'],history)
    require(all(r['position_command']==command and r['history_key']==case['history_key']
                and r['requested_ms']==int(ms) and r['requested_depth'] is None
                for ms,observations in repeats.items() for r in observations),'follow-up observation lost command/time/history')
    result=dict(task_id=task['task_id'],kind=task['kind'],case_id=case['case_id'],parent=task['parent'],
                split='train',original_row_sha256=digest(row),root_observations=repeats,
                formal_adoption=False,knowledge_ready=False,completed=True)
    if any(r.get('kind')=='mate' for obs in repeats.values() for r in obs):
        result.update(status='mate_requires_separate_learning_path',mate_verification=mate(case))
        return result,None
    if not stable(repeats['500']):
        result['status']='deep_observation_incomplete' if not all(exact_cp(r) for r in repeats['500']) else 'deep_preference_unstable'
        return result,None
    alt=repeats['500'][0]['bestmove']
    if alt==case['actual_move']:
        result['status']='actual_move_supported' if stable(repeats['50']) and repeats['50'][0]['bestmove']==alt else 'actual_supported_short_search_varies'
        return result,None
    if not stable(repeats['50']) or repeats['50'][0]['bestmove']!=alt:
        result.update(status='deep_only_or_short_unstable_preference',research_move=alt)
        return result,None
    children={side:checked(history+(move,),POLICY_FOLLOWUP['child_ms'])
              for side,move in (('actual',case['actual_move']),('research',alt))}
    result['children']=children
    if not all(exact_cp(r) for r in children.values()):
        result['status']='child_observation_incomplete';return result,None
    depth=min(POLICY_FOLLOWUP['max_fixed_depth'],*(r['depth'] for r in children.values()))
    fixed={side:checked(history+(move,),POLICY_FOLLOWUP['fixed_timeout_ms'],depth)
           for side,move in (('actual',case['actual_move']),('research',alt))}
    comparison=compare_children(fixed['actual'],fixed['research'])
    if any(r.get('depth')!=depth for r in fixed.values()):comparison['status']='fixed_depth_incomplete'
    follow=dict(requested_depth=depth,**fixed,comparison=comparison)
    result['fixed_comparison']=follow
    new=dict(case=copy.deepcopy(case),root_short=repeats['50'][0],root_deep=repeats['500'][0],
             research_move=alt,same_as_actual=False,followup=follow)
    new['route']=route_result(new)
    if new['route']=='stable_research_move_candidate':
        from tools.research.postgame_spiral import check_result
        check_result(new)
    result.update(status='stable_research_preference' if new['route']=='stable_research_move_candidate' else 'comparison_did_not_confirm',
                  knowledge_ready=new['route']=='stable_research_move_candidate',research_move=alt)
    return result,new if result['knowledge_ready'] else None


def mate_probe(binary,knowledge,count,params,case):
    engine=Analyzer(binary,knowledge,count,evaluation_options=params)
    try:
        history=tuple(case['history_moves']);command=position_command(case['start_sfen'],history)
        engine.send('usinewgame');engine.send(command);engine.send('go mate '+str(POLICY_FOLLOWUP['mate_ms']))
        lines=engine.until('checkmate',15);tokens=lines[-1].split()[1:]
        proof=[] if tokens==['timeout'] else tokens
        terminal=False
        if proof:
            board,_=replay(case);attacker=board.turn
            for i,token in enumerate(proof):
                move=shogi.Move.from_usi(token)
                require(move in board.legal_moves,'illegal own-engine mate proof')
                board.push(move)
                if i%2==0:require(board.is_check(),'mate proof contains a nonchecking attack')
            terminal=board.turn!=attacker and board.is_checkmate()
            require(terminal,'reported mate line does not end in mate')
        return dict(status='own_engine_mate_proven' if terminal else 'not_proven_within_budget',
                    requested_ms=POLICY_FOLLOWUP['mate_ms'],position_command=command,history_key=case['history_key'],
                    proof_moves=proof,terminal_checkmate_verified=terminal,
                    limitation='Own bounded solver claim with legal terminal replay; not a generic cp teacher or a no-mate proof.')
    finally:engine.close()


def run(binary,knowledge,preparation,diagnosis,parent,output,completed_task_ids=()):
    tasks=tasks_from(preparation,diagnosis,parent)
    all_tasks=tasks
    completed=set(completed_task_ids)
    require(len(completed)==len(tuple(completed_task_ids)), 'duplicate previously completed task')
    require(completed <= {t['task_id'] for t,_ in all_tasks}, 'completed task not in audited current queue')
    skipped=[t['task_id'] for t,_ in all_tasks if t['task_id'] in completed]
    eligible=[(t,r) for t,r in all_tasks if t['task_id'] not in completed and t['kind'] in SUPPORTED_KINDS]
    tasks=eligible[:POLICY_FOLLOWUP['max_tasks']]
    deferred=[t['task_id'] for t,_ in eligible[POLICY_FOLLOWUP['max_tasks']:]]
    unsupported=[t['task_id'] for t,_ in all_tasks if t['task_id'] not in completed and t['kind'] not in SUPPORTED_KINDS]
    params=preparation['learning']['parent_options'];binary=Path(binary);knowledge=Path(knowledge)
    require(sha256(binary.read_bytes())==preparation['progress']['analysis']['analyzer_binary_sha256'],
            'follow-up binary differs from original analyzer')
    require(sha256(knowledge.read_bytes())==parent['knowledge_sha256'],'follow-up knowledge differs')
    count=sum(bool(s) and not s.startswith('#') for s in knowledge.read_text().splitlines())
    output=Path(output);require(not output.exists(),'preserve previous follow-up observations');output.mkdir(parents=True)
    started=time.monotonic();results=[];updates=[];calls=0
    def probe(case,history,ms,depth):
        nonlocal calls
        calls+=1;engine=Analyzer(binary,knowledge,count,evaluation_options=params)
        try:return engine.search(case['start_sfen'],history,ms,depth)
        finally:engine.close()
    from tools.research.postgame_bridge import dump
    for task,row in tasks:
        observation,new=execute(task,row,probe,lambda case:mate_probe(binary,knowledge,count,params,case))
        results.append(observation)
        if new is not None:updates.append(new)
        dump(output/'checkpoint.json',dict(completed=len(results),total=len(tasks),results=results,diagnosis_updates=updates))
        print('FOLLOWUP '+str(len(results))+'/'+str(len(tasks))+' '+observation['status'],flush=True)
    report=dict(schema='postgame-followup-v1',policy=POLICY_FOLLOWUP,parent=parent,
                preparation_sha256=digest(preparation),diagnosis_sha256=digest(diagnosis),binary_sha256=sha256(binary.read_bytes()),
                tasks=len(tasks),total_queued_tasks=len(all_tasks),deferred_task_ids=deferred,
                unsupported_task_ids=unsupported,
                completed_task_ids=[r['task_id'] for r in results],previously_completed_task_ids=skipped,
                results=results,diagnosis_updates=updates,
                status_counts=dict(Counter(r['status'] for r in results)),search_probes=calls,
                mate_probes=sum('mate_verification' in r for r in results),seconds=round(time.monotonic()-started,3),
                formal_adoption=False,strength_improvement_demonstrated=False,new_games=0)
    dump(output/'result.json',report)
    return report


def verify_saved(preparation,diagnosis,parent,report):
    """Recompute decisions from saved observations only; never executes an engine."""
    tasks={t['task_id']:(t,r) for t,r in tasks_from(preparation,diagnosis,parent)}
    require(report['policy']==POLICY_FOLLOWUP and report['parent']==parent
            and report['preparation_sha256']==digest(preparation) and report['diagnosis_sha256']==digest(diagnosis),
            'saved follow-up binding differs')
    require(report['binary_sha256']==preparation['progress']['analysis']['analyzer_binary_sha256']
            and report['formal_adoption'] is False,'saved follow-up binary/adoption differs')
    require(report['tasks']==len(report['results']) and report['completed_task_ids']==[r['task_id'] for r in report['results']],
            'saved follow-up task counts differ')
    ordered=list(tasks.values())
    previous=set(report.get('previously_completed_task_ids',[]))
    require(len(previous)==len(report.get('previously_completed_task_ids',[])) and previous <= set(tasks),
            'previously completed task IDs are invalid')
    eligible=[t['task_id'] for t,r in ordered if t['task_id'] not in previous and t['kind'] in SUPPORTED_KINDS]
    unsupported=[t['task_id'] for t,r in ordered if t['task_id'] not in previous and t['kind'] not in SUPPORTED_KINDS]
    require(report['completed_task_ids']==eligible[:POLICY_FOLLOWUP['max_tasks']]
            and report.get('deferred_task_ids')==eligible[POLICY_FOLLOWUP['max_tasks']:]
            and report.get('unsupported_task_ids')==unsupported
            and report.get('total_queued_tasks')==len(tasks),
            'saved follow-up selection/deferred queue differs')
    require(len(set(report['completed_task_ids']))==len(report['completed_task_ids']),'repeated follow-up task result')
    updates=[];calls=0
    for saved in report['results']:
        require(saved['task_id'] in tasks,'saved follow-up was not an original training task')
        task,row=tasks[saved['task_id']]
        frames=[r for ms in ('50','500') for r in saved['root_observations'][ms]]
        if 'children' in saved:frames.extend(saved['children'][side] for side in ('actual','research'))
        if 'fixed_comparison' in saved:frames.extend(saved['fixed_comparison'][side] for side in ('actual','research'))
        observations=iter(copy.deepcopy(frames))
        def probe(*_):return next(observations)
        actual,new=execute(task,row,probe,lambda _:saved['mate_verification'])
        if 'mate_verification' in saved:
            proof=saved['mate_verification'];case=task['case'];command=position_command(case['start_sfen'],tuple(case['history_moves']))
            require(proof['requested_ms']==POLICY_FOLLOWUP['mate_ms'] and proof['position_command']==command
                    and proof['history_key']==case['history_key'],'saved mate request differs')
            if proof['status']=='own_engine_mate_proven':
                board,_=replay(case);attacker=board.turn
                for i,token in enumerate(proof['proof_moves']):
                    move=shogi.Move.from_usi(token);require(move in board.legal_moves,'saved mate proof is illegal');board.push(move)
                    if i%2==0:require(board.is_check(),'saved attack is not checking')
                require(board.turn!=attacker and board.is_checkmate() and proof['terminal_checkmate_verified'] is True,
                        'saved mate terminal not proved')
            else:require(proof['status']=='not_proven_within_budget' and not proof['proof_moves']
                         and proof['terminal_checkmate_verified'] is False,'unknown mate result')
        require(next(observations,None) is None and actual==saved,'saved follow-up decisions differ from recorded probes')
        calls+=len(frames)
        if new is not None:updates.append(new)
    require(calls==report['search_probes'] and updates==report['diagnosis_updates'],'saved follow-up totals/updates differ')
    require(report['status_counts']==dict(Counter(r['status'] for r in report['results']))
            and report['mate_probes']==sum('mate_verification' in r for r in report['results']),
            'saved follow-up status totals differ')
    require(set(report['completed_task_ids'])|set(report.get('previously_completed_task_ids',[]))
            |set(report.get('deferred_task_ids',[]))|set(report.get('unsupported_task_ids',[]))==set(tasks),
            'follow-up task was silently lost')
    return True
