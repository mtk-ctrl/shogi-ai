#!/usr/bin/env python3
"""Effect adapter for bounded evaluation-learning or research-knowledge spirals.

All side effects are delegated to a persisted backend. No formal adoption or
repository engine/knowledge edits. A dispatch of uncertain outcome is never
retried automatically; a known body is reconciled instead of launched twice.
"""
from __future__ import annotations
import copy
import re
from tools.research import postgame_cycle as core
from tools.research.postgame_bridge import FORMAL_DEFAULTS
from tools.research.postgame_ranker import POLICY, digest, parent_values, require
from tools.research.postgame_eval_preflight import POLICY_LIVE
from tools.research.postgame_knowledge import POLICY_KNOWLEDGE
from tools.research.postgame_followup import POLICY_FOLLOWUP
import json

POLICY_KNOWLEDGE_EXECUTION=dict(schema='postgame-knowledge-execution-v1',screen_games=100,confirm_games=200,
                              require_actual_use=True,automatic_formal_adoption=False)


def initialize(plan, parent_options, controller_sha256):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,63}',plan['cycle_id']), 'unsafe cycle identifier')
    require(plan['candidate_kind'] in ('evaluation','knowledge'), 'combined candidates require a separate frozen experiment')
    if 'knowledge_execution_policy' in plan:
        require(plan['candidate_kind']=='knowledge','knowledge execution policy requires a knowledge-only cycle')
    if plan['candidate_kind']=='knowledge':
        require(plan.get('knowledge_execution_policy')==POLICY_KNOWLEDGE_EXECUTION
                and plan.get('knowledge_policy')==POLICY_KNOWLEDGE,'freeze actual knowledge execution policy')
    if 'followup_policy' in plan:
        require(plan['followup_policy']==POLICY_FOLLOWUP and 'progress_policy' in plan,
                'freeze bounded follow-up with its original decision ledger')
    require(plan.get('generate_initial_source') is True, 'automatic cycle starts from fresh selfplay')
    require(plan.get('learning_policy')==POLICY and plan.get('live_policy')==POLICY_LIVE, 'freeze actual implemented learning/live policy')
    if 'knowledge_policy' in plan:
        require(plan['knowledge_policy']==POLICY_KNOWLEDGE,'freeze actual research-knowledge policy')
        require('progress_policy' in plan,'knowledge preparation requires the decision/progress ledger')
    require(type(plan.get('runner_capacity')) is int and 1<=plan['runner_capacity']<=20, 'freeze available hosted runner capacity')
    parent_values(parent_options)
    require(digest(parent_options)==plan['parent']['parameters_sha256'], 'initial parent parameters differ')
    return dict(schema='postgame-runtime-v1',state=core.start(plan),parent_options=copy.deepcopy(parent_options),
                controller_sha256=controller_sha256,sequence=0,prior_signatures=[],source_publication=None,
                preparation_publication=None,candidate_options=None,match_request=None,dispatch=None,
                blocked=None,formal_adoption=False,receipts=[],parent_knowledge_publication=None,
                completed_research_tasks=[])


def inputs(env):
    s=env['state']; result=dict(parent=s['parent'])
    if s['stage']=='prepare' and s['generation']>1:
        result.update(split_registry_sha256=s['split_registry_sha256'],example_bank_sha256=s['example_bank_sha256'])
    if s['stage'] in ('preflight','screen','confirm'):
        result['candidate']=dict(s['parent'],parameters_sha256=digest(env['candidate_options']))
        if s['plan']['candidate_kind']=='knowledge':
            result['candidate']['knowledge_sha256']=env['knowledge_candidate']['manifest']['candidate_sha256']
    return result


def comparison_request(env,free_runners):
    s=env['state']; p=s['pending']; require(p is not None,'missing persisted intent')
    require(type(free_runners) is int and 1<=free_runners<=20,'no available runners')
    options=dict(FORMAL_DEFAULTS,PositionKnowledgeFile='build/position-knowledge-v1.tsv')
    a=dict(options,**(env['candidate_options'] if s['stage'] in ('screen','confirm') else env['parent_options']))
    b=dict(options,**env['parent_options'])
    result=dict(ref_a=s['parent']['engine_ref'],ref_b=s['parent']['engine_ref'],games=p['payload']['games'],
                shards=min(free_runners,p['payload']['games']),go_command='go movetime 200',max_plies=300,
                seed=p['payload']['seed'],options_a=json.dumps(a,sort_keys=True),options_b=json.dumps(b,sort_keys=True))
    if (s['plan']['candidate_kind']=='knowledge' and s['stage'] in ('screen','confirm')) or env.get('parent_knowledge_publication'):
        result.update(execution_route='research_knowledge')
        for side,opts in (('a',a),('b',b)):
            opts['PositionKnowledgeFile']='build/knowledge-'+side.upper()+'.tsv'
            result['options_'+side]=json.dumps(opts,sort_keys=True)
    return result


def advance(env, backend):
    """Advance synchronous stages, then yield to a known child workflow/event.

    backend: save, free_runners, dispatch, match_status, consume_match, prepare,
    preflight. Durable stage publication must be retrieved before core.finish.
    """
    env=copy.deepcopy(env)
    require(env['blocked'] is None, 'cycle blocked; investigate and explicitly resume the saved operation')
    for _ in range(16):
        s=env['state']; stage=s['stage']
        if stage=='complete':
            backend.save(env); return env
        if s['pending'] is None:
            env['state']=core.request(s,inputs(env),s['revision']); s=env['state']
            env['dispatch']=None; env['match_request']=None
            backend.save(env)  # Intent ALWAYS precedes any execution/dispatch.
        p=s['pending']; op=p['operation_id']
        if stage in ('initial_source','collect_source','screen','confirm'):
            if env['dispatch'] is None:
                free=backend.free_runners(s['plan']['runner_capacity'])
                if free<=0:
                    env['capacity_waiting']=True; backend.save(env); return env
                env['capacity_waiting']=False
                req=comparison_request(env,free)
                env['match_request']=req
                # Persist the attempt BEFORE sending. A lost response cannot
                # make a resume accidentally repeat the same game operation.
                env['dispatch']=dict(attempted=True,body_run=None,launcher_run=backend.run_id)
                backend.save(env)
                body=backend.dispatch(req)
                require(type(body) is int and body>0,'dispatch did not return a body run ID; do not retry')
                env['dispatch']['body_run']=body; backend.save(env)
                return env
            body=env['dispatch']['body_run']
            require(body is not None,'uncertain dispatch response; reconcile the existing run before continuing')
            status=backend.match_status(body)
            if status=='waiting': return env
            require(status=='success','child match failed; preserve raw records and repair/audit without duplicate launch')
            data=backend.consume_match(env)
            env['state']=core.observe_start(s,op,env['dispatch']['launcher_run'],body,data['started_lanes'])
            evidence=dict(input_sha256=p['input_sha256'],parent=s['parent'],body_run=body,seed=p['payload']['seed'],
                          result=data['result'],audit=data['audit'],publication=data['publication'])
            if stage in ('screen','confirm'): evidence['candidate']=s['candidate']
            env['state']=core.finish(env['state'],op,evidence)
            env['prior_signatures']=sorted(set(env['prior_signatures'])|{r['sha256'] for r in data['audit']['trajectory_outcomes']})
            if stage in ('initial_source','collect_source'): env['source_publication']=data['publication']
            if env['state']['parent'] != s['parent']:
                env['parent_options']=copy.deepcopy(env['candidate_options'])
                if s['plan']['candidate_kind']=='knowledge':
                    env['parent_knowledge_publication']=copy.deepcopy(env['preparation_publication'])
            env['receipts'].append(dict(stage=stage,generation=s['generation'],body_run=body,publication=data['publication']))
            backend.save(env)
        elif stage=='prepare':
            data=backend.prepare(env)
            evidence=dict(input_sha256=p['input_sha256'],parent=s['parent'],publication=data['publication'],preparation=data['preparation'])
            if 'knowledge_execution_policy' in s['plan']:
                evidence['knowledge_stage']=data['knowledge_stage']
            if 'followup_policy' in s['plan']:evidence['followup']=data['followup']
            env['state']=core.finish(s,op,evidence)
            env['preparation_publication']=data['publication']
            env['candidate_options']=(copy.deepcopy(env['parent_options']) if s['plan']['candidate_kind']=='knowledge'
                                      else data['preparation']['learning'].get('options'))
            env['knowledge_candidate']=data.get('knowledge_stage')
            if data.get('followup'):
                env['completed_research_tasks']=sorted(set(env.get('completed_research_tasks',[]))|set(data['followup']['completed_task_ids']))
            env['receipts'].append(dict(stage=stage,generation=s['generation'],publication=data['publication']))
            backend.save(env)
        elif stage=='preflight':
            data=backend.preflight(env)
            evidence=dict(input_sha256=p['input_sha256'],parent=s['parent'],publication=data['publication'],
                          candidate=p['payload']['inputs']['candidate'],preflight=data['preflight'])
            env['state']=core.finish(s,op,evidence)
            env['receipts'].append(dict(stage=stage,generation=s['generation'],publication=data['publication']))
            backend.save(env)
        else: raise ValueError('unsupported execution stage')
    raise ValueError('unexpected synchronous transition count')
