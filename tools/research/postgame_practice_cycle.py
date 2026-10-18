#!/usr/bin/env python3
"""Budgeted training practice as a persisted stage of the ordinary research cycle.

Practice is not an independent match or a source of extra validation groups.
The original branch player, archive verifier and candidate gates are reused.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import time
from tools.research import postgame_practice as practice
from tools.research import postgame_horizon as horizon
from tools.research.postgame_ranker import digest, require
from tools.research.postgame_cases import sha256


def practice_signatures(folder):
    from tools.research.postgame_cases import load_archive
    from tools.research.postgame_bridge import trajectory
    folder=Path(folder)/'practice/played-archive'
    return sorted({trajectory(g.start_sfen,g.moves) for g in load_archive(folder)}) if folder.exists() else []

POLICY_PRACTICE_CYCLE=dict(schema='postgame-practice-cycle-policy-v1',max_roots_per_attempt=1,
    max_attempts=2,max_attempts_per_parent=2,max_practice_games=8,
    analysis_reservation_ms_per_attempt=600000,max_analysis_reservation_ms=1200000,
    practice_policy=practice.POLICY_PRACTICE,horizon_policy=horizon.POLICY_HORIZON,
    trigger='no_candidate_after_prepare',automatic_formal_adoption=False)


def validate_policy(policy):
    require(policy==POLICY_PRACTICE_CYCLE,'freeze the implemented practice-cycle limits')
    cases=policy['max_roots_per_attempt']*4*practice.POLICY_PRACTICE['max_selected_per_game']
    # Every fixed-depth search reserves its whole deadline, even if it normally
    # finishes much earlier. Only one of the two knowledge preflights can run.
    bound=cases*(50+500+2*(50+500)+2*5000+2*200+2*200+400+1000+4000+1000+20000)
    bound+=(12+cases)*(2*5000+2*200)
    require(policy['analysis_reservation_ms_per_attempt']>=bound,'practice analysis reservation is too small')


def make_offer(preparation,diagnosis,parent,seed,ledger=(),prior_ids=()):
    done=set(prior_ids)|{i for r in ledger if r['parent']==parent for i in r['practice_ids']}
    plan=practice.create_plan([(preparation,diagnosis)],parent,seed,done,for_cycle=True)
    extras=plan['roots'][POLICY_PRACTICE_CYCLE['max_roots_per_attempt']:]
    plan['excluded'].extend(dict(task_id=r['task']['task_id'],case_id=r['task']['case']['case_id'],
                                 reason='cycle_root_budget') for r in extras)
    plan['roots']=plan['roots'][:POLICY_PRACTICE_CYCLE['max_roots_per_attempt']]
    plan.pop('plan_sha256');plan['plan_sha256']=digest(plan);practice.verify_plan(plan)
    return dict(schema='postgame-practice-offer-v1',plan=plan,preparation_sha256=digest(preparation),
        diagnosis_sha256=digest(diagnosis),games=len(plan['roots'])*4,
        analysis_reservation_ms=POLICY_PRACTICE_CYCLE['analysis_reservation_ms_per_attempt'],
        unsupported_tasks_preserved=sum(t['kind']=='inspect_evaluation_representation'
                                       for t in preparation['progress']['work_items']),formal_adoption=False)


def available(state,offer):
    policy=state['plan']['practice_cycle_policy'];validate_policy(policy)
    require(offer['schema']=='postgame-practice-offer-v1' and offer['formal_adoption'] is False,
            'not a practice offer')
    plan=offer['plan'];practice.verify_plan(plan)
    require(plan['parent']==state['parent'] and plan['seed']==state['plan']['seeds'][state['generation']-1]['practice'],
            'practice offer changed parent/seed')
    require(len(plan['roots'])<=policy['max_roots_per_attempt'] and offer['games']==len(plan['roots'])*4
            and offer['analysis_reservation_ms']==policy['analysis_reservation_ms_per_attempt'],
            'practice offer changed reserved work')
    ledger=state.get('practice_ledger',[])
    completed=set(state.get('prior_practice_ids',[]))|{i for r in ledger if r['parent']==state['parent'] for i in r['practice_ids']}
    require(not completed & {r['practice_id'] for r in plan['roots']},'same parent practice was already executed')
    if not plan['roots']:return False,'no_eligible_training_branch'
    if len(ledger)>=policy['max_attempts']:return False,'practice_attempt_budget_exhausted'
    if sum(r['parent']==state['parent'] for r in ledger)>=policy['max_attempts_per_parent']:
        return False,'parent_practice_budget_exhausted'
    if state.get('practice_used_games',0)+offer['games']>policy['max_practice_games']:
        return False,'practice_game_budget_exhausted'
    if state.get('practice_analysis_reserved_ms',0)+offer['analysis_reservation_ms']>policy['max_analysis_reservation_ms']:
        return False,'practice_analysis_budget_exhausted'
    return True,None


def training_history(folder,spec,parent):
    """Import exposure/completion history only; never reuse old fitted features."""
    root=Path(folder)/'practice';old_plan=json.loads((root/'plan.json').read_bytes())
    result=json.loads((root/'result.json').read_bytes());prepared=json.loads((root/'handoff/preparation.json').read_bytes())
    practice.verify_plan(old_plan)
    require(spec['schema']=='postgame-training-history-v1' and old_plan['parent']==parent
            and prepared['example_bank']['parent_context']==parent,'training history parent differs')
    require(result['plan_sha256']==old_plan['plan_sha256'] and result['completed_practice_ids']==[r['practice_id'] for r in old_plan['roots']]
            and result['completed_practice_ids']==spec['completed_practice_ids']
            and digest(prepared)==spec['preparation_sha256'],'training history content differs from frozen input')
    return copy.deepcopy(prepared['split_registry'])


def accept(state,receipt):
    """Accept only a saved, audited execution of the previously frozen offer."""
    offer=state['practice_offer'];ok,reason=available(state,offer);require(ok,reason)
    plan=offer['plan'];ids=[r['practice_id'] for r in plan['roots']]
    require(receipt['schema']=='postgame-practice-cycle-receipt-v1' and receipt['parent']==state['parent']
            and receipt['plan_sha256']==plan['plan_sha256'] and receipt['practice_ids']==ids,
            'practice receipt differs from saved intent')
    require(receipt['games']==offer['games'] and type(receipt['new_plies']) is int
            and receipt['games']<=receipt['new_plies']<=receipt['games']*practice.POLICY_PRACTICE['max_new_plies'],
            'practice actual game/move budget differs')
    require(type(receipt['handoff_available']) is bool and type(receipt['selected_cases']) is int
            and 0<=receipt['selected_cases']<=receipt['games']*2,'practice handoff selection budget differs')
    signatures=receipt['trajectory_signatures']
    require(isinstance(signatures,list) and len(set(signatures))==len(signatures)<=receipt['games']
            and all(__import__('re').fullmatch('[0-9a-f]{64}',x) for x in signatures),'invalid practice trajectory index')
    require(receipt['analysis_reservation_ms']==offer['analysis_reservation_ms']
            and type(receipt['requested_analysis_ms']) is int
            and 0<=receipt['requested_analysis_ms']<=offer['analysis_reservation_ms'],
            'practice analysis budget exceeded')
    require(receipt['formal_adoption'] is False and receipt['strength_improvement_demonstrated'] is False,
            'practice is not a strength/adoption result')
    for key in ('all_moves_legal','all_terminations_verified','settings_verified','full_history_verified',
                'raw_archive_reproduced','handoff_reproduced'):
        require(receipt['verification'].get(key) is True,'missing practice verification: '+key)
    out=copy.deepcopy(state)
    out.setdefault('practice_ledger',[]).append(copy.deepcopy(receipt))
    out['practice_used_games']=out.get('practice_used_games',0)+receipt['games']
    out['practice_analysis_reserved_ms']=out.get('practice_analysis_reserved_ms',0)+receipt['analysis_reservation_ms']
    return out


def requested_ms(value):
    if isinstance(value,dict):
        if 'position_command' in value and 'requested_ms' in value:
            require(type(value['requested_ms']) is int and value['requested_ms']>=0,'invalid saved search budget')
            return value['requested_ms']
        return sum(requested_ms(v) for v in value.values())
    return sum(requested_ms(v) for v in value) if isinstance(value,list) else 0


def analysis_work(folder):
    """Count reserved USI search milliseconds; wall/handshake time is separate."""
    folder=Path(folder)
    files=['practice/handoff/analysis/diagnosis.json','practice/handoff/prepare-observations.json',
           'practice/handoff/knowledge-stage/result.json','knowledge-stage/observations.json']
    total=sum(requested_ms(json.loads((folder/p).read_bytes())) for p in files if (folder/p).exists())
    result=folder/'knowledge-stage/result.json'
    if result.exists() and (folder/'knowledge-stage/observations.json').exists():
        # The horizon manifest has no probes; its separate preflight does.
        total+=requested_ms(json.loads(result.read_bytes()).get('preflight',{}))
    return total


def run(offer,previous,source_games,binary,knowledge,cycle_id,folder,previous_cases=()):
    folder=Path(folder);plan=offer['plan'];started=time.monotonic()
    practice.verify_plan(plan)
    require(offer['preparation_sha256']==digest(previous),'practice input preparation changed')
    report=practice.run(plan,source_games,binary,knowledge,folder/'practice')
    audit=practice.verify_saved(plan,report,source_games,folder/'practice')
    handoff=practice.prepare_candidates(plan,report,folder/'practice',binary,knowledge,previous,evaluation_enabled=False)
    verify=practice.verify_handoff(plan,report,folder/'practice',previous,knowledge)
    data=dict(preparation=None,knowledge_stage=None,analysis_summary=None)
    if handoff['status']=='candidate_preparation_completed':
        hand=folder/'practice/handoff';preparation=json.loads((hand/'preparation.json').read_bytes())
        diagnosis=json.loads((hand/'analysis/diagnosis.json').read_bytes())
        generic=json.loads((hand/'knowledge-stage/result.json').read_bytes())
        frozen=horizon.selection(preparation,diagnosis,plan['parent'])
        if generic['manifest']['candidate_positions']==0 and frozen['roots']:
            knowledge_stage=horizon.run(binary,knowledge,preparation,diagnosis,frozen,plan['parent_options'],
                cycle_id[:48]+'-p'+plan['plan_sha256'][:8],folder/'knowledge-stage',plan['binary_sha256'])
        else:
            shutil.copytree(hand/'knowledge-stage',folder/'knowledge-stage');knowledge_stage=generic
        practice.dump(folder/'preparation.json',preparation)
        cases={c['case_id']:c for c in previous_cases}
        cases.update({r['case']['case_id']:dict(r['case'],research_move=r['research_move']) for r in diagnosis})
        practice.dump(folder/'eligible-cases.json',[cases[r['case_id']] for r in preparation['examples']])
        data.update(preparation=preparation,knowledge_stage=knowledge_stage,
                    analysis_summary=preparation['progress']['analysis'])
    receipt=dict(schema='postgame-practice-cycle-receipt-v1',parent=plan['parent'],plan_sha256=plan['plan_sha256'],
        practice_ids=report['completed_practice_ids'],games=report['games'],new_plies=report['new_plies'],
        replayed_prefix_plies=report['replayed_prefix_plies'],handoff_available=data['preparation'] is not None,
        selected_cases=handoff['selected_cases'],analysis_reservation_ms=offer['analysis_reservation_ms'],
        trajectory_signatures=practice_signatures(folder),
        requested_analysis_ms=analysis_work(folder),analysis_and_audit_seconds=round(time.monotonic()-started-report['seconds'],3),
        verification=dict(audit,handoff_reproduced=True),formal_adoption=False,strength_improvement_demonstrated=False)
    require(receipt['requested_analysis_ms']<=offer['analysis_reservation_ms'],'practice exceeded reserved analysis work')
    data['practice']=receipt;practice.dump(folder/'practice-receipt.json',receipt)
    verify_package(folder,offer,previous,source_games,knowledge,data,previous_cases)
    return data


def verify_package(folder,offer,previous,source_games,knowledge,data,previous_cases=()):
    folder=Path(folder);plan=offer['plan'];receipt=data['practice']
    require(digest(previous)==offer['preparation_sha256'],'saved practice ancestor differs')
    report=json.loads((folder/'practice/result.json').read_bytes())
    audit=practice.verify_saved(plan,report,source_games,folder/'practice')
    verify=practice.verify_handoff(plan,report,folder/'practice',previous,knowledge)
    require(receipt==json.loads((folder/'practice-receipt.json').read_bytes())
            and receipt['verification']==dict(audit,handoff_reproduced=True), 'saved practice verification differs')
    require(receipt['practice_ids']==report['completed_practice_ids'] and receipt['games']==report['games']
            and receipt['new_plies']==report['new_plies'] and receipt['replayed_prefix_plies']==report['replayed_prefix_plies']
            and receipt['requested_analysis_ms']==analysis_work(folder),'practice receipt counts differ from original data')
    require(receipt['trajectory_signatures']==practice_signatures(folder),'practice trajectory index differs')
    hand=folder/'practice/handoff'
    if receipt['handoff_available']:
        prepared=json.loads((hand/'preparation.json').read_bytes());diagnosis=json.loads((hand/'analysis/diagnosis.json').read_bytes())
        require(prepared==data['preparation']==json.loads((folder/'preparation.json').read_bytes())
                and data['analysis_summary']==prepared['progress']['analysis'],'practice preparation copy changed')
        cases={c['case_id']:c for c in previous_cases}
        cases.update({r['case']['case_id']:dict(r['case'],research_move=r['research_move']) for r in diagnosis})
        require(json.loads((folder/'eligible-cases.json').read_bytes())==[cases[r['case_id']] for r in prepared['examples']],
                'practice eligible-case history differs')
        result=json.loads((folder/'knowledge-stage/result.json').read_bytes())
        require(result==data['knowledge_stage'],'practice knowledge copy changed')
        if (folder/'knowledge-stage/observations.json').exists():
            frozen=horizon.selection(prepared,diagnosis,plan['parent'])
            horizon.verify_saved(folder/'knowledge-stage',Path(knowledge).read_bytes(),prepared,diagnosis,frozen,result)
            if 'preflight' in result:
                from tools.research.postgame_knowledge import preflight,validate_snapshot,staged_options
                queue=[]
                for row in result['preflight']['observations']:queue.extend(row['disabled']+[row['parent'],row['candidate']])
                it=iter(queue)
                def saved_probe(case,which,ms,depth,enabled):
                    frame=next(it);require(frame['requested_ms']==ms and frame['requested_depth']==depth,'horizon preflight budget differs')
                    return frame
                require(preflight(result['manifest'],saved_probe)==result['preflight'] and next(it,None) is None,
                        'horizon preflight does not reproduce')
                validate_snapshot(Path(knowledge).read_bytes(),(folder/'knowledge-stage/candidate.tsv').read_bytes(),result['manifest'])
                if 'staging' in result:staged_options(folder/'knowledge-stage/staged',result['staging'])
        else:
            require(result==json.loads((hand/'knowledge-stage/result.json').read_bytes()),'generic practice knowledge differs')
    else:require(data['preparation'] is None and data['knowledge_stage'] is None,'empty practice created candidates')
    return dict(practice_reproduced=True,handoff_reproduced=True,new_games=0,new_engine_runs=0,
                games=report['games'],new_plies=report['new_plies'],formal_adoption=False)
