"""Frozen phase/side coverage, own research opponents, and retained controls.

This bounded training experiment reuses the branch player, all-move archive and
candidate handoff. It never treats opponent variants or unfinished games as
independent strength tests. The v1 practice and ordinary cycle remain unchanged.
"""
from __future__ import annotations
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import time
import shogi
from tools.research import postgame_practice as practice
from tools.research.postgame_analyze import Analyzer, OPTIONS
from tools.research.postgame_cases import load_archive, make_case, position_command, sha256
from tools.research.postgame_candidates import replay
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.postgame_ranker import digest, require
from tools.research.postgame_spiral import leakage_keys
from tools.records.archive_played_moves import archive

POLICY = dict(schema='postgame-curriculum-policy-v1', max_roots=6, max_per_game=4,
    phases=['opening','middle','end'], sides=['black','white'], root_probe_ms=[50,500],
    max_new_plies=16, move_ms=50, max_games=36, max_handoff_cases=8,
    analysis_reservation_ms=600000, retention_ms=200, retention_cases=12,
    automatic_formal_adoption=False)
HANDOFF = dict(schema='postgame-curriculum-handoff-v1', max_cases=8)


def opponents(options):
    return [dict(id='parent', options=copy.deepcopy(options)),
            dict(id='pressure', options=dict(options, EvalSafety=options['EvalSafety']*9//10,
                 EvalPressure=options['EvalPressure']*6//5)),
            dict(id='safety', options=dict(options, EvalSafety=options['EvalSafety']*6//5,
                 EvalPressure=options['EvalPressure']*9//10))]


def protected_registry(games, previous):
    """Use heldout source boards only as exclusions, before any root probing."""
    registry=copy.deepcopy(previous['split_registry']);blocked=set()
    for key,value in registry.items():
        if value['split']!='train' or value.get('heldout_consumed'):blocked.add(key)
    for game in games:
        alias='game:'+str(game.run_id)+':'+game.row['game_id']
        require(alias in registry, 'source game lacks inherited split')
        if registry[alias]['split']=='train' and not registry[alias].get('heldout_consumed'):continue
        board=shogi.Board(game.start_sfen)
        for token in game.moves:
            blocked.update(leakage_keys(board));board.push_usi(token)
        blocked.update(leakage_keys(board))
    contaminated={registry[k]['group'] for k in blocked if k in registry and registry[k]['split']=='train'}
    for value in registry.values():
        if value['group'] in contaminated:value['split']='quarantine'
    for key in blocked:
        registry.setdefault(key,dict(group=digest(['protected-source',key]),split='heldout',heldout_consumed=False))
    return registry,blocked


def build_plan(games,previous,parent,binary_sha256,completed_histories,seed):
    require(type(seed) is int and 1<=seed<=2_000_000_000,'bounded curriculum seed')
    require(previous['example_bank']['parent_context']==parent,'curriculum parent differs')
    options=previous['learning']['parent_options']
    require(digest(options)==parent['parameters_sha256'],'curriculum parent options differ')
    registry,blocked=protected_registry(games,previous)
    candidates=[];excluded=Counter();seen=set()
    for game in games:
        alias='game:'+str(game.run_id)+':'+game.row['game_id'];lineage=registry[alias]
        if lineage['split']!='train' or lineage.get('heldout_consumed'):
            excluded['protected_source_game']+=len(game.moves);continue
        board=shogi.Board(game.start_sfen)
        for index,move in enumerate(game.moves):
            observed=game.row['moves'][index].get('search',{});phase=observed.get('phase_stage')
            command=position_command(game.start_sfen,game.moves[:index]);history=sha256(command.encode())
            reason=('missing_phase' if phase not in POLICY['phases'] else
                    'previously_practiced_history' if history in completed_histories else
                    'protected_position_or_formation' if set(leakage_keys(board))&blocked else
                    'too_close_to_end_or_single_move' if len(game.moves)-index<4 or len(list(board.legal_moves))<2 else None)
            if reason:excluded[reason]+=1
            elif history not in seen:
                case=make_case(game,index+1);seen.add(history)
                cp=observed.get('score_cp_stm') if observed.get('score_status')=='recorded' else None
                bucket='missing_or_mate' if type(cp) is not int else 'disadvantage' if cp<0 else 'convert_advantage' if cp>=600 else 'balanced'
                candidates.append(dict(case=case,phase=phase,score_bucket=bucket,lineage=copy.deepcopy(lineage)))
            board.push_usi(move)
    selected=[];used_games=Counter();used_buckets=Counter();availability=Counter((r['phase'],r['case']['side_to_move']) for r in candidates)
    for phase in POLICY['phases']:
        for side in POLICY['sides']:
            rows=[r for r in candidates if r['phase']==phase and r['case']['side_to_move']==side
                  and used_games[str(r['case']['source']['run_id'])+':'+r['case']['source']['game_id']]<POLICY['max_per_game']]
            if not rows:continue
            def rank(row):
                game=str(row['case']['source']['run_id'])+':'+row['case']['source']['game_id']
                return used_games[game],used_buckets[row['score_bucket']],digest([seed,row['case']['history_key']])
            row=copy.deepcopy(min(rows,key=rank));selected.append(row)
            used_games[str(row['case']['source']['run_id'])+':'+row['case']['source']['game_id']]+=1
            used_buckets[row['score_bucket']]+=1
    plan=dict(schema='postgame-curriculum-plan-v1',policy=copy.deepcopy(POLICY),seed=seed,parent=parent,
        parent_options=options,binary_sha256=binary_sha256,opponents=opponents(options),selected=selected,
        split_registry_sha256=digest(registry),previous_preparation_sha256=digest(previous),
        completed_histories_sha256=digest(sorted(completed_histories)),
        available_cells={p+':'+s:availability[p,s] for p in POLICY['phases'] for s in POLICY['sides']},
        excluded=dict(excluded),retained_controls_sha256=digest(tactical_cases()),
        purpose='training_coverage',formal_adoption=False,strength_measurement=False)
    plan['plan_sha256']=digest(plan);return plan


def check_frame(case,frame,ms):
    board,_=replay(case)
    require(frame['position_command']==case['analysis_position_command'] and frame['history_key']==case['history_key']
            and frame['requested_ms']==ms and frame['requested_depth'] is None,'curriculum probe binding differs')
    require(frame['bestmove'] in ('resign','win') or shogi.Move.from_usi(frame['bestmove']) in board.legal_moves,
            'illegal curriculum observation')


def branch_roots(plan,observations,registry):
    require(len(observations)==len(plan['selected']),'missing curriculum root observations')
    roots=[]
    for selected,frames in zip(plan['selected'],observations):
        case=selected['case'];require(len(frames)==2,'curriculum probe count differs')
        for frame,ms in zip(frames,POLICY['root_probe_ms']):check_frame(case,frame,ms)
        alternatives=[r['bestmove'] for r in reversed(frames) if r['bestmove'] not in ('resign','win',case['actual_move'])]
        identity=dict(parent=plan['parent'],history_key=case['history_key'],policy=POLICY,opponents=plan['opponents'])
        root=dict(practice_id=digest(identity),task=dict(case=case,parent=plan['parent'],split='train'),
            actual_move=case['actual_move'],alternative_move=alternatives[0] if alternatives else None,
            lineage=selected['lineage'],phase=selected['phase'],score_bucket=selected['score_bucket'])
        alias='game:'+str(case['source']['run_id'])+':'+case['source']['game_id']
        require(registry[alias]==root['lineage'] and root['lineage']['split']=='train','curriculum lineage differs')
        roots.append(root)
    return roots


def bounded_handoff(selection,games,info_by_source):
    """Choose at most eight before looking at diagnosis, after ALL group joins."""
    chosen=[];counts=Counter()
    lookup={g.row['game_id']:g for g in games}
    pool=list(selection)
    while pool and len(chosen)<HANDOFF['max_cases']:
        def rank(row):
            info=info_by_source[lookup[row['game_id']].row['source_id']]
            return counts[info['practice_id']],counts[info['scenario']['name']],digest(row)
        row=min(pool,key=rank);pool.remove(row);chosen.append(row)
        info=info_by_source[lookup[row['game_id']].row['source_id']]
        counts[info['practice_id']]+=1;counts[info['scenario']['name']]+=1
    return chosen


def retention(frames):
    cases=tactical_cases();require(len(frames)==len(cases)==POLICY['retention_cases'],'retained suite count differs')
    rows=[]
    for case,frame in zip(cases,frames):
        command=position_command(case['start_sfen'],())
        require(frame['position_command']==command and frame['history_key']==sha256(command.encode())
                and frame['requested_ms']==200 and frame['requested_depth'] is None,'retained control binding differs')
        require(frame['bestmove'] in ('resign','win') or shogi.Move.from_usi(frame['bestmove']) in shogi.Board(case['start_sfen']).legal_moves,
                'illegal retained control observation')
        rows.append(dict(case_id=case['case_id'],correct=frame['bestmove'].startswith(case['expected_prefix'])))
    return dict(cases=12,passed=all(r['correct'] for r in rows),rows=rows,
        limitation='Own-authored capture controls; no general strength inference.')


def verify_plan(plan,previous,registry):
    require(plan['plan_sha256']==digest({k:v for k,v in plan.items() if k!='plan_sha256'})
        and plan['policy']==POLICY and len(plan['selected'])<=6 and plan['opponents']==opponents(plan['parent_options'])
        and plan['purpose']=='training_coverage' and plan['formal_adoption'] is False and plan['strength_measurement'] is False,
        'curriculum frozen plan changed')
    require(plan['previous_preparation_sha256']==digest(previous) and plan['split_registry_sha256']==digest(registry)
        and digest(plan['parent_options'])==plan['parent']['parameters_sha256']
        and plan['retained_controls_sha256']==digest(tactical_cases()),'curriculum parent/registry/controls differ')


def run(plan,games,previous,registry,binary,knowledge,output):
    output=Path(output);require(not output.exists(),'preserve curriculum execution; no automatic retry')
    require(sha256(Path(binary).read_bytes())==plan['binary_sha256'] and sha256(Path(knowledge).read_bytes())==plan['parent']['knowledge_sha256'],
            'curriculum actual assets differ')
    verify_plan(plan,previous,registry)
    require(plan['policy']==POLICY and plan['opponents']==opponents(plan['parent_options'])
            and plan['retained_controls_sha256']==digest(tactical_cases()),'curriculum fixed policy changed')
    output.mkdir(parents=True);practice.dump(output/'plan.json',plan)
    practice.dump(output/'intent.json',dict(plan_sha256=plan['plan_sha256'],status='started',automatic_retry=False))
    count=sum(bool(s) and not s.startswith('#') for s in Path(knowledge).read_text().splitlines())
    def probe(case,options,ms,history=None,seed=None,telemetry=False):
        engine=Analyzer(binary,knowledge,count,evaluation_options=options)
        try:
            if seed is not None:engine.send('setoption name RandomSeed value '+str(seed))
            return engine.search(case['start_sfen'],tuple(case['history_moves'] if history is None else history),ms,include_telemetry=telemetry)
        finally:engine.close()
    retained_before=[probe(c,plan['parent_options'],200) for c in tactical_cases()]
    require(retention(retained_before)['passed'],'parent retained controls failed; stop before practice')
    practice.dump(output/'retention-before.json',retained_before)
    observations=[]
    practice.dump(output/'root-observations.json',observations)
    for row in plan['selected']:
        observations.append([probe(row['case'],plan['parent_options'],ms) for ms in POLICY['root_probe_ms']])
        practice.dump(output/'root-observations.json',observations)
    roots=branch_roots(plan,observations,registry)
    wrapper=dict(plan,parent_options=plan['parent_options'],split_registry=registry,roots=roots,curriculum_handoff_policy=HANDOFF)
    raw=output/'games';raw.mkdir();results=[];started=time.monotonic();sources={(str(g.run_id),g.row['game_id']):g for g in games}
    for index,root in enumerate(roots):
        case=root['task']['case'];source=sources[(str(case['source']['run_id']),case['source']['game_id'])]
        for opponent in plan['opponents']:
            scenario=dict(name=opponent['id'],actor_ms=50,reply_ms=50)
            for branch in ('actual','alternative') if root['alternative_move'] else ('actual',):
                def search(c,history,ms):
                    opts=plan['parent_options'] if len(history)%2==len(c['history_moves'])%2 else opponent['options']
                    frame=probe(c,opts,ms,history,plan['seed']+index,True)
                    require('phase_maturity' in frame.get('played_telemetry',{}),'curriculum actual phase telemetry missing')
                    return frame
                game,info=practice.play_branch(root,scenario,branch,source,search)
                status=practice.validate_game(game,info,root,scenario,source)
                actor=case['actor'];actual_options={s:dict(OPTIONS,**(plan['parent_options'] if s==actor else opponent['options']),RandomSeed=plan['seed']+index,
                    PositionKnowledgeFile=str(Path(knowledge).resolve())) for s in ('A','B')}
                row=dict(game,moves=[r['move'] for r in game['moves']],move_records=game['moves'])
                name='game-'+str(len(results))+'.json';path=raw/name
                practice.dump(path,dict(games=1,max_plies=len(case['history_moves'])+16,start_sfen=case['start_sfen'],
                    engine_a='KUMOJI v2.0.21',engine_b='KUMOJI v2.0.21',sha256_a=plan['binary_sha256'],sha256_b=plan['binary_sha256'],
                    options_a=actual_options['A'],options_b=actual_options['B'],seed=plan['seed']+index,
                    options_effective_from_ply=len(case['history_moves'])+1,
                    replayed_prefix_source=case['source'],
                    position_knowledge={s:dict(enabled=True,available=True,sha256=plan['parent']['knowledge_sha256'],positions=count) for s in ('A','B')},
                    go_command='per_side_frozen_practice_budget',details=[row]))
                results.append(dict(file='games/'+name,sha256=sha256(path.read_bytes()),info=info,outcome_status=status))
                practice.dump(output/'checkpoint.json',dict(completed_games=len(results),results=results))
                print('CURRICULUM_GAME',len(results),root['phase'],case['side_to_move'],opponent['id'],branch,game['reason'],flush=True)
    verified=[output/r['file'] for r in results if json.loads((output/r['file']).read_bytes())['details'][0]['reason']!='practice_resign_unverified']
    manifest=archive(verified,output/'played-archive','practice-'+plan['plan_sha256'][:16],plan['parent']['engine_ref'],plan['parent']['engine_ref']) if verified else None
    report=dict(schema='postgame-curriculum-result-v1',plan_sha256=plan['plan_sha256'],games=len(results),results=results,manifest=manifest,
        new_plies=sum(r['info']['new_plies'] for r in results),replayed_prefix_plies=sum(r['info']['prefix_plies'] for r in results),
        completed_practice_ids=[r['practice_id'] for r in roots],play_seconds=round(time.monotonic()-started,3),formal_adoption=False,strength_improvement_demonstrated=False)
    require(report['games']<=36 and report['new_plies']<=576,'curriculum game budget exceeded')
    practice.dump(output/'result.json',report)
    practice.prepare_candidates(wrapper,report,output,binary,knowledge,previous,evaluation_enabled=False)
    knowledge_dir=output/'handoff/knowledge-stage'
    if (knowledge_dir/'result.json').exists():
        from tools.research import postgame_horizon as horizon
        prepared=json.loads((output/'handoff/preparation.json').read_bytes())
        diagnosis=json.loads((output/'handoff/analysis/diagnosis.json').read_bytes())
        generic=json.loads((knowledge_dir/'result.json').read_bytes())
        selection=horizon.selection(prepared,diagnosis,plan['parent'])
        if generic['manifest']['candidate_positions']==0 and selection['roots']:
            knowledge_dir=output/'knowledge-stage'
            horizon.run(binary,knowledge,prepared,diagnosis,selection,plan['parent_options'],
                'curriculum-'+plan['plan_sha256'][:16],knowledge_dir,plan['binary_sha256'])
    # No weight fitting. Any knowledge candidate remains research-only; the
    # retained controls must pass before it is even described as ready.
    candidate=knowledge_dir/'candidate.tsv'
    after_file=candidate if candidate.exists() else Path(knowledge)
    after_count=sum(bool(s) and not s.startswith('#') for s in after_file.read_text().splitlines())
    after=[]
    for case in tactical_cases():
        engine=Analyzer(binary,after_file,after_count,evaluation_options=plan['parent_options'])
        try:after.append(engine.search(case['start_sfen'],(),200))
        finally:engine.close()
    practice.dump(output/'retention-after.json',after)
    practice.dump(output/'retention-context.json',dict(binary_sha256=plan['binary_sha256'],parameters_sha256=plan['parent']['parameters_sha256'],
        before_knowledge_sha256=sha256(Path(knowledge).read_bytes()),after_knowledge_sha256=sha256(after_file.read_bytes()),
        after_positions=after_count,after_is_candidate=candidate.exists()))
    return verify_saved(plan,games,previous,registry,knowledge,output)


def verify_saved(plan,games,previous,registry,knowledge,output):
    verify_plan(plan,previous,registry)
    output=Path(output);require(json.loads((output/'plan.json').read_bytes())==plan,'saved curriculum plan differs')
    observations=json.loads((output/'root-observations.json').read_bytes());roots=branch_roots(plan,observations,registry)
    wrapper=dict(plan,split_registry=registry,roots=roots,curriculum_handoff_policy=HANDOFF)
    report=json.loads((output/'result.json').read_bytes());require(report['plan_sha256']==plan['plan_sha256']
        and report['formal_adoption'] is False and report['strength_improvement_demonstrated'] is False,'curriculum result differs')
    sources={(str(g.run_id),g.row['game_id']):g for g in games};expected=[];verified=[]
    for index,root in enumerate(roots):
        c=root['task']['case'];source=sources[(str(c['source']['run_id']),c['source']['game_id'])]
        require(c==make_case(source,c['source']['ply']),'curriculum source history/observation differs')
        for opp in plan['opponents']:
            for branch in ('actual','alternative') if root['alternative_move'] else ('actual',):expected.append((index,root,source,opp,branch))
    require(report['games']==len(expected)==len(report['results'])<=36,'curriculum branch/profile count differs')
    trajectories={}
    for n,(saved,(index,root,source,opp,branch)) in enumerate(zip(report['results'],expected)):
        path=output/saved['file'];require(saved['file']=='games/game-'+str(n)+'.json' and sha256(path.read_bytes())==saved['sha256'],'curriculum raw hash/order differs')
        row=json.loads(path.read_bytes());raw=row['details'][0];game=dict(raw,moves=raw['move_records']);case=root['task']['case']
        require(raw['moves']==[m['move'] for m in game['moves']] and saved['info']['branch']==branch,'curriculum branch/moves differ')
        require(row['sha256_a']==row['sha256_b']==plan['binary_sha256'] and row['seed']==plan['seed']+index
            and row['engine_a']==row['engine_b']=='KUMOJI v2.0.21' and row['max_plies']==len(case['history_moves'])+16
            and row['go_command']=='per_side_frozen_practice_budget','curriculum runtime assets/limits differ')
        require(row['options_effective_from_ply']==len(case['history_moves'])+1 and row['replayed_prefix_source']==case['source'],
            'curriculum options incorrectly attributed to replayed prefix')
        for side in ('A','B'):
            opts=row['options_'+side.lower()];actual={k:v for k,v in opts.items() if k!='PositionKnowledgeFile'}
            require(actual==dict(OPTIONS,**(plan['parent_options'] if side==case['actor'] else opp['options']),RandomSeed=plan['seed']+index),
                'curriculum opponent applied to wrong side/options')
            k=row['position_knowledge'][side];require(k['enabled'] is True and k['available'] is True
                and k['sha256']==plan['parent']['knowledge_sha256'] and k['positions']>0,'curriculum knowledge differs')
        status=practice.validate_game(game,saved['info'],root,dict(name=opp['id'],actor_ms=50,reply_ms=50),source)
        require(status==saved['outcome_status'],'curriculum outcome differs')
        trajectories[index,branch,opp['id']]=[m['move'] for m in game['moves'][len(case['history_moves']):]]
        if game['reason']!='practice_resign_unverified':verified.append(path)
    require(report['completed_practice_ids']==[r['practice_id'] for r in roots]
        and report['new_plies']==sum(r['info']['new_plies'] for r in report['results'])
        and report['replayed_prefix_plies']==sum(r['info']['prefix_plies'] for r in report['results']),'curriculum actual counts differ')
    if verified:
        with tempfile.TemporaryDirectory() as tmp:
            manifest=archive(verified,Path(tmp),'practice-'+plan['plan_sha256'][:16],plan['parent']['engine_ref'],plan['parent']['engine_ref'])
            require(manifest==report['manifest']==json.loads((output/'played-archive/manifest.json').read_bytes())
                and (Path(tmp)/'played-games.jsonl.gz').read_bytes()==(output/'played-archive/played-games.jsonl.gz').read_bytes(),'curriculum archive replay differs')
        load_archive(output/'played-archive')
    else:require(report['manifest'] is None,'empty curriculum fabricated an archive')
    handoff=practice.verify_handoff(wrapper,report,output,previous,knowledge)
    if (output/'knowledge-stage/observations.json').exists():
        from tools.research import postgame_horizon as horizon
        from tools.research.postgame_knowledge import preflight,validate_snapshot,staged_options
        prepared=json.loads((output/'handoff/preparation.json').read_bytes())
        diagnosis=json.loads((output/'handoff/analysis/diagnosis.json').read_bytes())
        result=json.loads((output/'knowledge-stage/result.json').read_bytes())
        horizon.verify_saved(output/'knowledge-stage',Path(knowledge).read_bytes(),prepared,diagnosis,
            horizon.selection(prepared,diagnosis,plan['parent']),result)
        if 'preflight' in result:
            frames=[]
            for row in result['preflight']['observations']:frames.extend(row['disabled']+[row['parent'],row['candidate']])
            iterator=iter(frames)
            def saved_probe(case,which,ms,depth,enabled):
                frame=next(iterator)
                require(frame['requested_ms']==ms and frame['requested_depth']==depth,'curriculum candidate preflight budget differs')
                return frame
            require(preflight(result['manifest'],saved_probe)==result['preflight'] and next(iterator,None) is None,
                'curriculum horizon preflight did not reproduce')
            validate_snapshot(Path(knowledge).read_bytes(),(output/'knowledge-stage/candidate.tsv').read_bytes(),result['manifest'])
            if 'staging' in result:staged_options(output/'knowledge-stage/staged',result['staging'])
    controls={s:retention(json.loads((output/('retention-'+s+'.json')).read_bytes())) for s in ('before','after')}
    after_file=output/('knowledge-stage/candidate.tsv' if (output/'knowledge-stage').exists() else 'handoff/knowledge-stage/candidate.tsv')
    after_is_candidate=after_file.exists()
    if not after_is_candidate:after_file=Path(knowledge)
    require(json.loads((output/'retention-context.json').read_bytes())==dict(binary_sha256=plan['binary_sha256'],
        parameters_sha256=plan['parent']['parameters_sha256'],before_knowledge_sha256=sha256(Path(knowledge).read_bytes()),
        after_knowledge_sha256=sha256(after_file.read_bytes()),after_positions=sum(bool(s) and not s.startswith('#') for s in after_file.read_text().splitlines()),
        after_is_candidate=after_is_candidate),'curriculum retained candidate assets differ')
    require(controls['before']['passed'],'retained parent controls invalid')
    from tools.research.postgame_practice_cycle import requested_ms
    work=sum(requested_ms(json.loads((output/p).read_bytes())) for p in
        ['root-observations.json','retention-before.json','retention-after.json','handoff/analysis/diagnosis.json',
         'handoff/prepare-observations.json','handoff/knowledge-stage/result.json','knowledge-stage/observations.json',
         'knowledge-stage/result.json'] if (output/p).exists())
    require(work<=POLICY['analysis_reservation_ms'],'curriculum analysis budget exceeded')
    pairs=[sequence!=trajectories[index,branch,'parent'] for (index,branch,profile),sequence in trajectories.items() if profile!='parent']
    transfer=json.loads((output/'handoff/transfer.json').read_bytes()) if (output/'handoff/transfer.json').exists() else {}
    return dict(schema='postgame-curriculum-verification-v1',plan_sha256=plan['plan_sha256'],games=report['games'],new_plies=report['new_plies'],
        roots=len(roots),alternative_roots=sum(r['alternative_move'] is not None for r in roots),
        root_cells=[r['phase']+':'+r['task']['case']['side_to_move'] for r in roots],profiles=[r['id'] for r in plan['opponents']],
        opponent_branch_pairs=len(pairs),observed_sequences_differing_from_parent=sum(pairs),
        inherited_source_groups=len({r['lineage']['group'] for r in roots}),
        training_practice_games=transfer.get('training_games',0),quarantined_practice_games=transfer.get('quarantined_games',0),
        raw_archive_reproduced=True,all_histories_moves_terminations_settings_verified=True,handoff=handoff,
        retention=controls,research_candidate_retention_passed=controls['after']['passed'],requested_analysis_ms=work,
        analysis_reservation_ms=POLICY['analysis_reservation_ms'],new_games_for_readback=0,new_engine_runs_for_readback=0,
        formal_adoption=False,strength_improvement_demonstrated=False)
