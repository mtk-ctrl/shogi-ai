#!/usr/bin/env python3
"""Read back completed cycles and independently replay the saved stage ledger.

No dispatch, engine execution, analysis, learning, uploads or adoption. Raw
shards are read only to restore compact runtime observations omitted by schema1.
"""
from __future__ import annotations
import base64
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_postgame_spiral import Backend,api,dump,runtime_statistics,algorithm_hash
from tools.research import postgame_cycle as core
from tools.research.postgame_ranker import digest,require,OPTIONS
from tools.research.postgame_cases import load_archive,sha256
from tools.research.postgame_bridge import validate_shard,trajectory
from tools.records.archive_played_moves import archive
from tools.research.postgame_knowledge import validate_snapshot,staged_options
from tools.research.postgame_knowledge_route import materialize,verify_materialization
from tools.research.postgame_followup import verify_saved as verify_followup


def inspect(backend,env):
    saved=env['state']
    require(saved['stage']=='complete' and saved['pending'] is None and env['blocked'] is None,'cycle not complete')
    plan=saved['plan']
    require(plan['algorithm_sha256']==algorithm_hash(),'frozen learning/gate code differs')
    raw=api(f"repos/{backend.repo}/contents/research/postgame-cycles/{plan['cycle_id']}/PLAN.json?ref={env['plan_ref']}")
    require(json.loads(base64.b64decode(raw['content']))==plan,'immutable original plan differs from saved policy')
    previous={};reports=[];state=core.start(plan)
    source_publication=None;preparation_publication=None;parent_knowledge_publication=None;knowledge_candidate=None
    prior=set(backend.reference_index(plan))
    if plan.get('predecessor_checkpoint'):
        ancestor=json.loads(backend.bytes(plan['predecessor_checkpoint']).read_bytes())
        prior.update(ancestor['prior_signatures'])
        old=backend.unpack(ancestor['preparation_publication'])
        previous=json.loads((old/'preparation.json').read_bytes())
        parent_knowledge_publication=ancestor.get('parent_knowledge_publication')
    for record in saved['history']:
        pub=record['publication'];folder=backend.unpack(pub)
        binding=json.loads((folder/'binding.json').read_bytes())
        result=json.loads((folder/'stage-result.json').read_bytes())
        require(record['stage']==state['stage'] and digest(binding)==record['operation_id'],'stage order/operation mismatch')
        state=core.request(state,binding['inputs'],state['revision'])
        require(state['pending']['payload']==binding,'intent differs from frozen seeds/budget/parent')
        evidence=dict(input_sha256=digest(binding['inputs']),parent=state['parent'],publication=pub)
        stage=state['stage'];report=dict(stage=stage,generation=state['generation'],publication=pub)
        if stage in ('initial_source','collect_source','screen','confirm'):
            body=record['body_run'];req=json.loads((folder/'match-request.json').read_bytes())
            require(req['games']==binding['games'] and req['seed']==binding['seed']
                    and req['ref_a']==req['ref_b']==state['parent']['engine_ref'],'saved request differs from frozen match intent')
            for side in ('a','b'):
                options=json.loads(req['options_'+side]);params={k:options[k] for k in OPTIONS}
                expected=state['candidate'] if side=='a' and stage in ('screen','confirm') else state['parent']
                require(digest(params)==expected['parameters_sha256'],'actual evaluation options differ from intended parent/candidate')
            info=api(f'repos/{backend.repo}/actions/runs/{body}')
            research=req.get('execution_route')=='research_knowledge'
            expected_path='.github/workflows/postgame-cycle-pilot.yml' if research else '.github/workflows/engine-match.yml'
            require(info['status']=='completed' and info['conclusion']=='success' and info['path']==expected_path,'original body not successful')
            games=load_archive(folder/'played-archive')
            manifest=json.loads((folder/'played-archive/manifest.json').read_bytes())
            original_sources={r['source_id'] for r in manifest['sources']}
            actual_binaries={s:sha256((folder/f'build/engine-{s.lower()}').read_bytes()) for s in ('A','B')}
            require(actual_binaries==result['audit']['actual_binary_sha256'],'saved binary hash differs')
            require(sha256((folder/'build/position-knowledge-v1.tsv').read_bytes())==state['parent']['knowledge_sha256'],'snapshot hash differs')
            knowledge_specs=state['parent']['knowledge_sha256']
            if research:
                params={k:json.loads(req['options_b'])[k] for k in OPTIONS}
                checkenv=dict(state=state,formal_adoption=False,blocked=None,parent_options=params,
                              match_request=req,dispatch=dict(attempted=True,body_run=None),source_publication=source_publication,
                              preparation_publication=preparation_publication,parent_knowledge_publication=parent_knowledge_publication,
                              knowledge_candidate=knowledge_candidate)
                expected=materialize(checkenv,backend.unpack,backend.output/f'expected-research-{body}')
                require(json.loads((folder/'build/provenance.json').read_bytes())==expected,'saved research inputs differ from replayed intent')
                verify_materialization(folder/'build',expected,req);knowledge_specs=expected['snapshots']
            dest=backend.output/f'raw-runtime-{body}'
            for lane in range(req['shards']):
                name=f'postgame-research-shard-{body}-{lane}' if research else f'generic-engine-match-{body}-{lane}'
                subprocess.run(['gh','run','download',str(body),'--repo',backend.repo,'--name',name,'--dir',str(dest/str(lane))],check=True)
            rows=list(dest.rglob('shard-*.json'))
            require(len(rows)==req['shards'],'missing runtime original lane')
            for path in rows:
                require(sha256(path.read_bytes()) in original_sources,'runtime shard differs from archived source hash')
                row=json.loads(path.read_bytes())
                validate_shard(row,int(path.stem.split('-')[-1]),req,actual_binaries,knowledge_specs)
            rebuilt=dest/'reconstructed-archive'
            archive(sorted(rows),rebuilt,manifest['run_id'],manifest['requested_ref_a'],manifest['requested_ref_b'])
            replayed=load_archive(rebuilt)
            require([g.row for g in replayed]==[g.row for g in games],'restored all-move archive differs')
            expected=dict(wins=sum(g.row['winner']=='A' for g in games),losses=sum(g.row['winner']=='B' for g in games),draws=sum(g.row['winner'] is None for g in games))
            require(expected==result['result'],'observed results differ')
            if research:
                ids=set(json.loads((folder/'build/provenance.json').read_bytes())['candidate_research_ids'])
                uses=[m for g in games for m in g.row['moves'] if m['search'].get('research_id') in ids]
                require(all(m['engine']=='A' for m in uses) and len(uses)==result['audit']['candidate_knowledge_uses'],
                        'candidate knowledge use/leakage audit differs')
            unique={}
            signatures=[]
            for g in games:
                signature=trajectory(g.start_sfen,g.moves);signatures.append(signature)
                if signature not in prior:unique.setdefault(signature,g)
            counts=dict(wins=sum(g.row['winner']=='A' for g in unique.values()),losses=sum(g.row['winner']=='B' for g in unique.values()),draws=sum(g.row['winner'] is None for g in unique.values()))
            require(counts==result['audit']['prior_and_internal_duplicates_excluded'],'duplicate sensitivity differs')
            prior.update(signatures)
            match=re.search(r'-(\d+)-a\d+\.tgz$',pub['name']);require(match is not None,'controller run not bound in publication')
            controller=int(match[1]);origin=api(f'repos/{backend.repo}/actions/runs/{controller}')
            require(origin['conclusion']=='success' and origin['path']=='.github/workflows/postgame-spiral.yml','controller provenance differs')
            state=core.observe_start(state,record['operation_id'],controller,body,result['started_lanes'])
            evidence.update(body_run=body,seed=binding['seed'],result=result['result'],audit=result['audit'])
            if stage in ('screen','confirm'):evidence['candidate']=state['candidate']
            report.update(body_run=body,games=len(games),plies=sum(len(g.moves) for g in games),result=expected,
                          runtime_statistics=runtime_statistics(rows),audit=result['audit'])
        elif stage=='prepare':
            prep=result['preparation'];require(json.loads((folder/'preparation.json').read_bytes())==prep,'bank differs from stage receipt')
            old_registry=previous.get('split_registry',{});registry=prep['split_registry']
            require(set(old_registry)<=set(registry),'old split/exposure aliases were lost')
            for key,old in old_registry.items():
                new=registry[key]
                require(new['split'] in (old['split'],'quarantine'),'old test/validation group was reassigned')
                require(not old.get('heldout_consumed') or new.get('heldout_consumed'),'used heldout exposure was reset')
            if state['generation']>1:
                require(binding['inputs']['split_registry_sha256']==digest(old_registry)
                        and binding['inputs']['example_bank_sha256']==digest(previous.get('example_bank',{})),'bank/registry handoff hash differs')
            evidence['preparation']=prep
            report.update(analysis=result['analysis_summary'],learning_status=prep['learning']['status'],
                          parameter_updates=prep['learning']['parameter_updates'],eligible_pairs=len(prep['examples']),
                          split_aliases=len(registry),old_aliases_preserved=len(old_registry),bank_pairs_reused=prep['bank_pairs_reused'])
            if 'progress_policy' in plan:
                report['progress']=prep['progress']
            if 'knowledge_policy' in plan:
                knowledge=result['knowledge_stage']
                require(json.loads((folder/'knowledge-stage/result.json').read_bytes())==knowledge,'knowledge result differs')
                if 'staging' in knowledge:
                    target=folder/'knowledge-stage/staged'
                    require(knowledge['staging']['manifest_sha256']==digest(knowledge['manifest'])
                            and knowledge['staging']['preflight_sha256']==digest(knowledge['preflight']),
                            'staged knowledge evidence hash differs')
                    staged_options(target,knowledge['staging'])
                    validate_snapshot((target/'B.tsv').read_bytes(),(target/'A.tsv').read_bytes(),knowledge['manifest'])
                report['knowledge_stage']=knowledge
                knowledge_candidate=knowledge
                if 'knowledge_execution_policy' in plan:evidence['knowledge_stage']=knowledge
            if 'followup_policy' in plan:
                followup=result['followup']
                require(json.loads((folder/'followup/result.json').read_bytes())==followup,'follow-up result differs')
                original=json.loads((folder/'original-preparation.json').read_bytes())
                diagnosis=json.loads((folder/'analysis/diagnosis.json').read_bytes())
                verify_followup(original,diagnosis,state['parent'],followup)
                report['followup']=followup
                evidence['followup']=followup
            previous=prep
        elif stage=='preflight':
            evidence.update(candidate=binding['inputs']['candidate'],preflight=result['preflight'])
            report['preflight']=result['preflight']
        require(digest(evidence)==record['evidence_sha256'],'saved stage evidence hash differs')
        before=state['parent'];state=core.finish(state,record['operation_id'],evidence)
        if state['parent']!=before and plan['candidate_kind']=='knowledge':parent_knowledge_publication=preparation_publication
        if stage in ('initial_source','collect_source'):source_publication=pub
        if stage=='prepare':preparation_publication=pub
        reports.append(report)
    require(state==saved,'independent stage replay did not reproduce final cycle state')
    require(digest(sorted(prior))==env['trajectory_index_sha256'],'final duplicate index differs')
    return dict(schema='postgame-cycle-readback-v1',cycle_id=plan['cycle_id'],controller_ledger_replayed=True,
                all_publication_hash_bytes_api_verified=True,stage_reports=reports,
                generation=state['generation'],used_games=state['used_games'],stage=state['stage'],
                parent_retained=state['parent']==plan['parent'],parameter_updates=sum(r.get('parameter_updates',0) for r in reports),
                final_trajectory_signatures=len(prior),formal_adoption=False,
                scope='Actual bounded cycle; candidate screen/confirm branches are separately tested with synthetic fixtures, not live strength evidence.')


def main():
    backend=Backend(os.environ['GITHUB_REPOSITORY'],Path('build/postgame-spiral-inspection'))
    env=backend.load(os.environ['CYCLE_ID']);require(env is not None,'unknown cycle')
    require(env['plan_ref']==os.environ['PLAN_REF'],'inspected plan ref differs')
    report=inspect(backend,env);dump(backend.output/'readback.json',report)
    print('SPIRAL_READBACK '+json.dumps({k:v for k,v in report.items() if k!='stage_reports'}),flush=True)


if __name__=='__main__':main()
