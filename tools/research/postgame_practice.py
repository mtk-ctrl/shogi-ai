#!/usr/bin/env python3
"""Training-only full-history branch practice; results are observations, not teachers.

Uses the existing own-engine Analyzer and independent arena adjudicator. The
production arena, formal engine and knowledge are unchanged. Every lineage is
kept in its original split; practice cannot manufacture independent groups.
"""
from __future__ import annotations
from collections import Counter
import copy
import json
from pathlib import Path
import time
import shogi
from benchmarks.arena import Adjudicator, can_declare_win
from tools.records.archive_played_moves import archive, clean_search
from tools.research.postgame_analyze import Analyzer, OPTIONS, exact_cp
from tools.research.postgame_cases import load_archive, make_case, position_command, sha256, verify_game
from tools.research.postgame_candidates import replay
from tools.research.postgame_followup import tasks_from
from tools.research.postgame_ranker import digest, require, parent_values
from tools.research.postgame_spiral import leakage_keys, prepare, group_rows

POLICY_PRACTICE=dict(schema='postgame-practice-policy-v1',max_roots=4,max_roots_per_game=2,
    max_new_plies=16,max_selected_per_game=2,attempts_per_parent_task=1,
    scenarios=[dict(name='balanced',actor_ms=50,reply_ms=50),dict(name='reply_deeper',actor_ms=50,reply_ms=200)],
    automatic_formal_adoption=False)


def dump(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def create_plan(inputs,parent,seed,completed=()):
    """Select once from original observations, before any new practice results."""
    require(type(seed) is int and 1<=seed<=2_100_000_000,'bounded practice seed required')
    candidates=[];excluded=[];seen=set();last=None
    for preparation,diagnosis in inputs:
        require(preparation['example_bank']['parent_context']==parent,'practice parent differs')
        require(preparation['progress']['analysis']['analyzer_binary_sha256']==inputs[0][0]['progress']['analysis']['analyzer_binary_sha256'],
                'practice inputs need the same archived analyzer')
        last=preparation
        for task,row in tasks_from(preparation,diagnosis,parent):
            require(task['task_id'] not in seen,'duplicate practice input task');seen.add(task['task_id'])
            base=dict(task_id=task['task_id'],case_id=task['case']['case_id'])
            if task['kind']=='verify_mate_research':
                excluded.append(dict(base,reason='mate_requires_separate_path'));continue
            board,_=replay(task['case']);actual=task['case']['actual_move'];alternatives=[]
            for key in ('root_short','root_deep'):
                move=row[key]['bestmove']
                if move not in ('resign','win',actual) and move not in alternatives:
                    require(shogi.Move.from_usi(move) in board.legal_moves,'illegal original practice alternative')
                    alternatives.append(move)
            if not alternatives:
                excluded.append(dict(base,reason='no_distinct_original_branch'));continue
            identity=dict(parent=parent,task_id=task['task_id'],policy=POLICY_PRACTICE)
            root=dict(practice_id=digest(identity),task=task,actual_move=actual,alternative_move=alternatives[0],
                      original_row_sha256=digest(row),preparation_sha256=digest(preparation))
            if root['practice_id'] in completed:
                excluded.append(dict(base,reason='already_practiced_same_parent'));continue
            candidates.append(root)
    require(last is not None,'practice needs original training evidence')
    registry=last['split_registry'];roots=[];counts=Counter()
    for root in sorted(candidates,key=lambda r:(r['task']['priority'],r['task']['task_id'])):
        case=root['task']['case'];key='game:'+str(case['source']['run_id'])+':'+case['source']['game_id']
        require(key in registry and registry[key]['split']=='train' and not registry[key].get('heldout_consumed'),
                'practice source is no longer unexposed training data')
        if len(roots)>=POLICY_PRACTICE['max_roots'] or counts[key]>=POLICY_PRACTICE['max_roots_per_game']:
            excluded.append(dict(task_id=root['task']['task_id'],case_id=case['case_id'],reason='frozen_root_budget'));continue
        root['lineage']=copy.deepcopy(registry[key]);roots.append(root);counts[key]+=1
    plan=dict(schema='postgame-practice-plan-v1',parent=copy.deepcopy(parent),policy=copy.deepcopy(POLICY_PRACTICE),
              seed=seed,roots=roots,excluded=excluded,source_tasks=len(seen),split_registry=copy.deepcopy(registry),
              parent_options=copy.deepcopy(last['learning']['parent_options']),
              binary_sha256=last['progress']['analysis']['analyzer_binary_sha256'],
              purpose='training_practice',formal_adoption=False,strength_measurement=False)
    plan['plan_sha256']=digest(plan)
    return plan


def verify_plan(plan):
    bare={k:v for k,v in plan.items() if k!='plan_sha256'}
    require(plan['plan_sha256']==digest(bare) and plan['policy']==POLICY_PRACTICE,'practice frozen plan changed')
    require(plan['purpose']=='training_practice' and plan['formal_adoption'] is False
            and plan['strength_measurement'] is False,'practice purpose differs')
    parent_values(plan['parent_options'])
    require(digest(plan['parent_options'])==plan['parent']['parameters_sha256'],'practice parameters differ')
    require(len(plan['roots'])<=POLICY_PRACTICE['max_roots'] and len({r['practice_id'] for r in plan['roots']})==len(plan['roots']),
            'practice root budget or duplicate')
    for root in plan['roots']:
        task=root['task'];case=task['case'];board,_=replay(case)
        require(task['parent']==plan['parent'] and task['split']=='train'
                and case.get('evidence_purpose')!='synthetic_fixture','practice source is not real training evidence')
        require(root['practice_id']==digest(dict(parent=plan['parent'],task_id=task['task_id'],policy=POLICY_PRACTICE)),
                'practice identity differs')
        command=position_command(case['start_sfen'],tuple(case['history_moves']))
        require(sha256(command.encode())==case['history_key'],'practice lost full source history')
        require(root['actual_move']==case['actual_move'] and root['alternative_move']!=root['actual_move'],
                'practice branches differ from source')
        require(all(shogi.Move.from_usi(m) in board.legal_moves for m in (root['actual_move'],root['alternative_move'])),
                'illegal practice branch')
        key='game:'+str(case['source']['run_id'])+':'+case['source']['game_id']
        require(plan['split_registry'][key]==root['lineage'] and root['lineage']['split']=='train'
                and not root['lineage'].get('heldout_consumed'),'practice lineage changed or exposed')
    return True


def replay_prefix(case):
    board=shogi.Board(case['start_sfen']);judge=Adjudicator(board)
    for token in case['history_moves']:
        move=shogi.Move.from_usi(token);require(move in board.legal_moves,'illegal practice history')
        board.push(move);require(judge.after_move(board) is None,'practice source is already terminal')
    return board,judge


def play_branch(root,scenario,branch,source_game,search):
    """search(case, history, ms) returns a fresh own-engine observation."""
    case=root['task']['case'];prefix=case['history_moves'];board,judge=replay_prefix(case);actor_color=board.turn
    require(source_game.start_sfen==case['start_sfen'] and list(source_game.moves[:len(prefix)])==prefix
            and source_game.moves[len(prefix)]==case['actual_move'],'practice source game differs')
    rows=copy.deepcopy(source_game.row['moves'][:len(prefix)]);records=[];reason='move_limit';winner=None
    branch_move=root[branch+'_move'];termination=None
    for step in range(POLICY_PRACTICE['max_new_plies']):
        color=board.turn;actor='A' if (color==shogi.BLACK)==source_game.row['a_black'] else 'B'
        if step==0:
            token=branch_move;telemetry=dict(score_status='not_recorded',decision_source='practice_forced_branch')
        else:
            ms=scenario['actor_ms'] if color==actor_color else scenario['reply_ms']
            history=tuple(prefix)+tuple(r['move'] for r in records)
            observed=search(case,history,ms);command=position_command(case['start_sfen'],history)
            require(observed['position_command']==command and observed['history_key']==sha256(command.encode())
                    and observed['requested_ms']==ms and observed['requested_depth'] is None,'practice search binding differs')
            token=observed['bestmove']
            telemetry=dict(observed.get('played_telemetry',{}),score_status='not_recorded',
                           elapsed_ms=observed['elapsed_ms'])
            telemetry.setdefault('decision_source','own_practice_search')
            if exact_cp(observed):telemetry.update(score_cp_stm=observed['value_stm'],depth=observed['depth'])
            elif observed['status']=='recorded' and observed['kind']=='mate' and observed['pv_head_matches']:
                telemetry.update(score_mate_stm=observed['value_stm'],depth=observed['depth'],
                    score_lowerbound=observed['bound']=='lower',score_upperbound=observed['bound']=='upper')
            if observed.get('research_decision_id'):
                telemetry.update(decision_source='research_decision',research_id=observed['research_decision_id'])
            telemetry=clean_search(telemetry)
            if token=='resign':
                reason='practice_resign_unverified';termination=dict(actor=actor,search=telemetry,requested_ms=ms);break
            if token=='win':
                require(can_declare_win(board),'invalid practice declaration');reason='declare_win';winner=actor
                termination=dict(actor=actor,search=telemetry,requested_ms=ms);break
        move=shogi.Move.from_usi(token);require(move in board.legal_moves,'illegal practice continuation')
        record=dict(ply=len(rows)+1,move=token,engine=actor,side_to_move='black' if color==shogi.BLACK else 'white',search=telemetry)
        if step>0:record['practice_requested_ms']=ms
        board.push(move);rows.append(record);records.append(record)
        terminal=judge.after_move(board)
        if terminal is not None:
            end_color,reason=terminal
            winner=None if end_color is None else ('A' if (end_color==shogi.BLACK)==source_game.row['a_black'] else 'B')
            break
    game=dict(start_sfen=case['start_sfen'],a_black=source_game.row['a_black'],moves=rows,
              plies=len(rows),winner=winner,reason=reason,final_sfen=board.sfen())
    info=dict(practice_id=root['practice_id'],source=case['source'],source_case_id=case['case_id'],
              prefix_plies=len(prefix),new_plies=len(records),branch=branch,forced_move=branch_move,
              scenario=copy.deepcopy(scenario),split='train',lineage=root['lineage'],terminal_observation=termination)
    if reason=='practice_resign_unverified':
        # Custom verifier below keeps this unresolved. Never feed a resignation
        # into verify_game as a proved win/loss.
        require(winner is None,'unverified resignation supplied a teacher')
    else:verify_game(game,dict(max_plies=len(prefix)+POLICY_PRACTICE['max_new_plies']))
    return game,info


def validate_game(game,info,root,scenario,source_game):
    case=root['task']['case'];prefix=case['history_moves']
    require(info['practice_id']==root['practice_id'] and info['source']==case['source'] and info['source_case_id']==case['case_id']
            and info['scenario']==scenario and info['lineage']==root['lineage'] and info['split']=='train','practice provenance differs')
    require(info['branch'] in ('actual','alternative') and info['forced_move']==root[info['branch']+'_move'],'practice branch differs')
    require(game['start_sfen']==case['start_sfen'] and game['a_black']==source_game.row['a_black']
            and game['moves'][:len(prefix)]==source_game.row['moves'][:len(prefix)],'practice replayed prefix differs')
    new=game['moves'][len(prefix):]
    require(1<=len(new)<=POLICY_PRACTICE['max_new_plies'] and info['prefix_plies']==len(prefix)
            and info['new_plies']==len(new) and new[0]['move']==info['forced_move'],'practice continuation length/first move differs')
    require(new[0]['search']==dict(score_status='not_recorded',decision_source='practice_forced_branch'),
            'forced branch has a fabricated search score')
    if game['reason']=='practice_resign_unverified':
        require(info['terminal_observation'] is not None,'unresolved resignation lacks its observation')
        verify_game(dict(game,reason='move_limit'),dict(max_plies=len(game['moves'])))
        status='unresolved'
    else:_,status=verify_game(game,dict(max_plies=len(prefix)+POLICY_PRACTICE['max_new_plies']))
    # Recorded per-move budgets describe the fixed scenario, not formal match
    # time or hindsight values for the forced branch.
    actor_color=0 if case['side_to_move']=='black' else 1
    for i,r in enumerate(new[1:],1):
        expected=scenario['actor_ms'] if (actor_color^(i%2))==actor_color else scenario['reply_ms']
        require(r.get('practice_requested_ms')==expected,'practice per-move budget differs')
    if info['terminal_observation'] is not None:
        expected=scenario['actor_ms'] if len(new)%2==0 else scenario['reply_ms']
        require(info['terminal_observation']['requested_ms']==expected,'practice terminal search budget differs')
    return status


def run(plan,source_games,binary,knowledge,output):
    verify_plan(plan);binary=Path(binary);knowledge=Path(knowledge);output=Path(output)
    require(not output.exists(),'preserve existing practice intent/results; reconcile instead of replaying')
    require(sha256(knowledge.read_bytes())==plan['parent']['knowledge_sha256'],'practice knowledge differs')
    require(sha256(binary.read_bytes())==plan['binary_sha256'],'practice binary differs from original analyzer')
    games_by_source={(str(g.run_id),g.row['game_id']):g for g in source_games}
    require(len(games_by_source)==len(source_games),'duplicate practice source game')
    output.mkdir(parents=True);dump(output/'plan.json',plan)
    dump(output/'intent.json',dict(plan_sha256=plan['plan_sha256'],status='execution_started',automatic_retry=False))
    count=sum(bool(s) and not s.startswith('#') for s in knowledge.read_text().splitlines());results=[];started=time.monotonic()
    raw=output/'games';raw.mkdir();searches=0
    for index,root in enumerate(plan['roots']):
        case=root['task']['case'];source=games_by_source[(str(case['source']['run_id']),case['source']['game_id'])]
        require(source.archive_sha256==case['source']['archive_sha256']
                and source.manifest_sha256==case['source']['manifest_sha256'],'practice original archive differs')
        for scenario in POLICY_PRACTICE['scenarios']:
            for branch in ('actual','alternative'):
                engine=Analyzer(binary,knowledge,count,evaluation_options=plan['parent_options'])
                try:
                    engine.send('setoption name RandomSeed value '+str(plan['seed']+index))
                    def search(c,history,ms):
                        nonlocal searches
                        searches+=1;frame=engine.search(c['start_sfen'],history,ms,include_telemetry=True)
                        require('phase_maturity' in frame.get('played_telemetry',{}),'practice engine omitted actual phase telemetry')
                        return frame
                    game,info=play_branch(root,scenario,branch,source,search)
                finally:engine.close()
                status=validate_game(game,info,root,scenario,source)
                raw_game=dict(game,moves=[r['move'] for r in game['moves']],move_records=game['moves'])
                name='game-'+str(len(results))+'.json';path=raw/name
                metadata=dict(telemetry_schema_version=1,engine_a='KUMOJI v2.0.21',engine_b='KUMOJI v2.0.21',
                    sha256_a=sha256(binary.read_bytes()),sha256_b=sha256(binary.read_bytes()),
                    options_a=dict(OPTIONS,**plan['parent_options'],PositionKnowledgeFile=str(knowledge.resolve()),RandomSeed=plan['seed']+index),
                    options_b=dict(OPTIONS,**plan['parent_options'],PositionKnowledgeFile=str(knowledge.resolve()),RandomSeed=plan['seed']+index),
                    seed=plan['seed']+index,max_plies=len(case['history_moves'])+POLICY_PRACTICE['max_new_plies'],
                    start_sfen=case['start_sfen'],games=1,go_command='per_side_frozen_practice_budget',
                    position_knowledge={s:dict(enabled=True,available=True,sha256=plan['parent']['knowledge_sha256'],positions=count) for s in ('A','B')},
                    details=[raw_game])
                dump(path,metadata)
                results.append(dict(file='games/'+name,sha256=sha256(path.read_bytes()),outcome_status=status,info=info))
                dump(output/'checkpoint.json',dict(completed_games=len(results),results=results))
                print('PRACTICE '+str(len(results))+' '+branch+' '+scenario['name']+' '+game['reason'],flush=True)
    # The normal archive verifier deliberately rejects unverified resignations.
    # Preserve those raw observations, and keep them out of the learning archive.
    verified=[output/r['file'] for r in results if r['info']['terminal_observation'] is None or r['outcome_status']!='unresolved']
    manifest=archive(verified,output/'played-archive','practice-'+plan['plan_sha256'][:16],
                     plan['parent']['engine_ref'],plan['parent']['engine_ref']) if verified else None
    report=dict(schema='postgame-practice-result-v1',plan_sha256=plan['plan_sha256'],parent=plan['parent'],
        binary_sha256=sha256(binary.read_bytes()),knowledge_sha256=sha256(knowledge.read_bytes()),
        games=len(results),new_plies=sum(r['info']['new_plies'] for r in results),
        replayed_prefix_plies=sum(r['info']['prefix_plies'] for r in results),searches=searches,results=results,
        completed_practice_ids=[r['practice_id'] for r in plan['roots']],manifest=manifest,
        outcome_status=dict(Counter(r['outcome_status'] for r in results)),seconds=round(time.monotonic()-started,3),
        formal_adoption=False,strength_improvement_demonstrated=False)
    dump(output/'result.json',report);return report


def verify_saved(plan,report,source_games,directory):
    """Read-only full replay. No engine calls, learning or new games."""
    import tempfile
    verify_plan(plan);directory=Path(directory)
    require(json.loads((directory/'plan.json').read_bytes())==plan,'saved practice plan differs')
    require(report['plan_sha256']==plan['plan_sha256'] and report['parent']==plan['parent']
            and report['binary_sha256']==plan['binary_sha256'] and report['knowledge_sha256']==plan['parent']['knowledge_sha256']
            and report['formal_adoption'] is False and report['strength_improvement_demonstrated'] is False,'practice result binding differs')
    sources={(str(g.run_id),g.row['game_id']):g for g in source_games};expected=[];verified=[];statuses=[]
    for index,root in enumerate(plan['roots']):
        c=root['task']['case'];source=sources[(str(c['source']['run_id']),c['source']['game_id'])]
        require(source.archive_sha256==c['source']['archive_sha256'] and source.manifest_sha256==c['source']['manifest_sha256'],
                'practice saved source archive differs')
        for scenario in POLICY_PRACTICE['scenarios']:
            for branch in ('actual','alternative'):expected.append((index,root,scenario,branch,source))
    require(report['games']==len(expected)==len(report['results']),'practice missing or repeated branch/scenario')
    require(report['completed_practice_ids']==[r['practice_id'] for r in plan['roots']],'practice completion list differs')
    for n,(saved,(index,root,scenario,branch,source)) in enumerate(zip(report['results'],expected)):
        require(saved['file']=='games/game-'+str(n)+'.json' and saved['info']['branch']==branch,'practice result order differs')
        path=directory/saved['file'];raw=path.read_bytes();require(sha256(raw)==saved['sha256'],'practice raw game hash differs')
        row=json.loads(raw);raw_game=row['details'][0];game=dict(raw_game,moves=raw_game['move_records'])
        require(row['games']==len(row['details'])==1 and raw_game['moves']==[r['move'] for r in game['moves']],
                'practice raw move/telemetry count differs')
        require(row['sha256_a']==row['sha256_b']==plan['binary_sha256'] and row['seed']==plan['seed']+index,
                'practice runtime binary or seed differs')
        require(row['engine_a']==row['engine_b']=='KUMOJI v2.0.21','practice actual identity differs')
        require(row['max_plies']==len(root['task']['case']['history_moves'])+POLICY_PRACTICE['max_new_plies']
                and row['go_command']=='per_side_frozen_practice_budget','practice time/limit metadata differs')
        for side in ('a','b'):
            opts=row['options_'+side]
            require({k:v for k,v in opts.items() if k!='PositionKnowledgeFile'}==dict(OPTIONS,**plan['parent_options'],RandomSeed=plan['seed']+index),
                    'practice actual options differ')
            k=row['position_knowledge'][side.upper()]
            require(k['enabled'] is True and k['available'] is True and k['sha256']==plan['parent']['knowledge_sha256']
                    and type(k['positions']) is int and k['positions']>0,'practice actual knowledge metadata differs')
        status=validate_game(game,saved['info'],root,scenario,source)
        require(status==saved['outcome_status'],'practice outcome status differs');statuses.append(status)
        if game['reason']!='practice_resign_unverified':verified.append(path)
    require(report['new_plies']==sum(r['info']['new_plies'] for r in report['results'])
            and report['replayed_prefix_plies']==sum(r['info']['prefix_plies'] for r in report['results'])
            and report['outcome_status']==dict(Counter(statuses)),'practice summary counts differ')
    require(report['searches']==sum(r['info']['new_plies']-1+int(r['info']['terminal_observation'] is not None)
                                    for r in report['results']),'practice search count differs')
    # Rebuild from raw observations, not only a self-reported saved manifest.
    if verified:
        with tempfile.TemporaryDirectory() as temp:
            actual=archive(verified,Path(temp),'practice-'+plan['plan_sha256'][:16],plan['parent']['engine_ref'],plan['parent']['engine_ref'])
            require(actual==report['manifest']==json.loads((directory/'played-archive/manifest.json').read_bytes()),
                    'practice archive does not reproduce from raw played moves')
            require((Path(temp)/'played-games.jsonl.gz').read_bytes()==(directory/'played-archive/played-games.jsonl.gz').read_bytes(),
                    'practice archived moves differ from raw')
        load_archive(directory/'played-archive')
    else:require(report['manifest'] is None,'empty practice archive has a manifest')
    return dict(all_moves_legal=True,all_terminations_verified=True,settings_verified=True,full_history_verified=True,
                raw_archive_reproduced=True,games=report['games'],new_plies=report['new_plies'],new_engine_runs=0,
                formal_adoption=False,strength_improvement_demonstrated=False)


def learning_inputs(plan,report,directory):
    """Join ALL descendant positions before any new diagnosis/teaching label.

    The ancestor game alias connects every sibling and descendant to its prior
    group. Contact with validation/heldout/exposed positions quarantines the
    entire component. It can never create new independent training groups.
    """
    directory=Path(directory);registry=copy.deepcopy(plan['split_registry']);descriptors=[];by_source={}
    if report['manifest'] is None:return dict(selection=[],split_registry=registry,game_splits=[],selected_cases=0)
    games=load_archive(directory/'played-archive')
    for r in report['results']:by_source[r['sha256']]=r['info']
    for g in games:
        info=by_source[g.row['source_id']];prefix=info['prefix_plies'];board=shogi.Board(g.start_sfen);keys=[]
        for ply,move in enumerate(g.moves):
            if ply>=prefix:keys.extend(leakage_keys(board))
            board.push_usi(move)
        keys.extend(leakage_keys(board))
        ancestor='game:'+str(info['source']['run_id'])+':'+info['source']['game_id']
        require(ancestor in registry and registry[ancestor]['split']=='train','practice ancestor is not training')
        keys.append(ancestor)
        descriptors.append(dict(case_id=g.row['game_id'],game=str(g.run_id)+':'+g.row['game_id'],
                                leakage_keys=sorted(set(keys)),prefix_plies=prefix))
    group_rows(descriptors,'spiral-bridge-20261017-v1',registry)
    selection=[]
    for g,d in zip(games,descriptors):
        if d['split']!='train':continue
        # Forced branch and the next choice by the same actor. These positions
        # are fixed before inspecting any new analysis, score or winner.
        for ply in (d['prefix_plies']+1,d['prefix_plies']+3):
            if ply<=len(g.moves):selection.append(dict(game_id=g.row['game_id'],ply=ply))
    require(len(selection)<=len(games)*POLICY_PRACTICE['max_selected_per_game'],'practice selection exceeds frozen budget')
    return dict(selection=selection,split_registry=registry,game_splits=descriptors,selected_cases=len(selection),
                training_games=sum(d['split']=='train' for d in descriptors),quarantined_games=sum(d['split']!='train' for d in descriptors),
                limitation='Descendants of existing training groups; not new independent games/groups or strength evidence.')


def prepare_candidates(plan,report,directory,binary,knowledge,previous):
    """Feed verified practice positions through existing diagnosis and gates."""
    from tools.research.postgame_analyze import run_analysis
    from tools.research.postgame_progress import describe
    from tools.research.postgame_knowledge import run as prepare_knowledge
    directory=Path(directory);output=directory/'handoff';require(not output.exists(),'preserve practice handoff');output.mkdir()
    transfer=learning_inputs(plan,report,directory);dump(output/'transfer.json',transfer)
    if not transfer['selection']:
        result=dict(status='no_unexposed_training_positions',selected_cases=0,parameter_updates=0,knowledge_positions=0)
        dump(output/'result.json',result);return result
    params=plan['parent_options'];count=sum(bool(s) and not s.startswith('#') for s in Path(knowledge).read_text().splitlines())
    summary=run_analysis([directory/'played-archive'],binary,knowledge,output/'analysis',params,
                         expected_knowledge_sha256=plan['parent']['knowledge_sha256'],selection=transfer['selection'])
    diagnosis=json.loads((output/'analysis/diagnosis.json').read_bytes());observations=dict(parent_probes={},static={})
    def probe(case):
        result=[]
        for _ in range(2):
            engine=Analyzer(binary,knowledge,count,evaluation_options=params)
            try:result.append(engine.search(case['start_sfen'],tuple(case['history_moves']),200))
            finally:engine.close()
        observations['parent_probes'][case['case_id']]=result;return result
    engine=Analyzer(binary,knowledge,count,evaluation_options=params)
    def static(sfen):
        terms=engine.static(sfen);observations['static'][sfen]=terms;return terms
    try:
        prepared=prepare(diagnosis,probe,static,'spiral-bridge-20261017-v1',registry=transfer['split_registry'],
            parent_options=params,example_bank=previous['example_bank'],parent_context=plan['parent'],track_decisions=True)
    finally:engine.close()
    prepared['progress']=describe(prepared,summary,diagnosis,plan['parent'])
    dump(output/'preparation.json',prepared);dump(output/'prepare-observations.json',observations)
    knowledge_result=prepare_knowledge(binary,knowledge,prepared,diagnosis,plan['parent'],params,
                                     'practice-'+plan['plan_sha256'][:16],output/'knowledge-stage')
    result=dict(status='candidate_preparation_completed',selected_cases=len(diagnosis),
        parameter_updates=prepared['learning']['parameter_updates'],evaluation_status=prepared['learning']['status'],
        knowledge_positions=knowledge_result['manifest']['candidate_positions'],
        independent_groups=prepared['learning']['split_groups'],routes=summary['routes'],
        formal_adoption=False,strength_improvement_demonstrated=False)
    dump(output/'result.json',result);return result


def verify_handoff(plan,report,directory,previous,base_file):
    """Reproduce split and candidate preparation from saved observations only."""
    directory=Path(directory);output=directory/'handoff'
    transfer=learning_inputs(plan,report,directory)
    require(transfer==json.loads((output/'transfer.json').read_bytes()),'practice lineage/selection handoff differs')
    if not transfer['selection']:
        require(json.loads((output/'result.json').read_bytes())['status']=='no_unexposed_training_positions','empty handoff differs')
        return dict(training_selected_cases=0,all_lineages_preserved=True,new_engine_runs=0)
    diagnosis=json.loads((output/'analysis/diagnosis.json').read_bytes())
    games={g.row['game_id']:g for g in load_archive(directory/'played-archive')}
    expected=[make_case(games[s['game_id']],s['ply']) for s in transfer['selection']]
    require(expected==[r['case'] for r in diagnosis],'practice diagnosis selected another position')
    summary=json.loads((output/'analysis/summary.json').read_bytes())
    require(summary['analyzer_binary_sha256']==plan['binary_sha256'] and summary['knowledge_sha256']==plan['parent']['knowledge_sha256']
            and summary['evaluation_options']==plan['parent_options'] and summary['options']==OPTIONS,'practice analyzer conditions differ')
    def check_frame(case,history,frame,ms,depth=None):
        command=position_command(case['start_sfen'],tuple(history));board=shogi.Board(case['start_sfen'])
        for move in history:board.push_usi(move)
        require(frame['position_command']==command and frame['history_key']==sha256(command.encode())
                and frame['requested_ms']==ms and frame['requested_depth']==depth,'practice diagnosis lost history/time')
        require(frame['bestmove'] in ('win','resign') or shogi.Move.from_usi(frame['bestmove']) in board.legal_moves,'illegal saved analysis move')
    from tools.research.postgame_analyze import route_result,compare_children
    for row in diagnosis:
        case=row['case'];history=case['history_moves']
        check_frame(case,history,row['root_short'],50);check_frame(case,history,row['root_deep'],500)
        require(row['research_move']==row['root_deep']['bestmove'] and row['route']==route_result(row),'practice diagnostic route differs')
        for ms,pair in row.get('child_pairs',{}).items():
            for side,move in (('actual',case['actual_move']),('research',row['research_move'])):
                check_frame(case,history+[move],pair[side],int(ms))
            require(pair['comparison']==compare_children(pair['actual'],pair['research']),'practice child comparison differs')
        if row.get('followup'):
            fixed=row['followup'];depth=fixed['requested_depth']
            for side,move in (('actual',case['actual_move']),('research',row['research_move'])):
                check_frame(case,history+[move],fixed[side],5000,depth)
            comparison=compare_children(fixed['actual'],fixed['research'])
            if any(fixed[s].get('depth')!=depth for s in ('actual','research')):comparison['status']='fixed_depth_incomplete'
            require(fixed['comparison']==comparison,'practice fixed-depth comparison differs')
    obs=json.loads((output/'prepare-observations.json').read_bytes())
    def probe(case):return obs['parent_probes'][case['case_id']]
    result=prepare(diagnosis,probe,lambda s:obs['static'][s],'spiral-bridge-20261017-v1',
        registry=transfer['split_registry'],parent_options=plan['parent_options'],example_bank=previous['example_bank'],
        parent_context=plan['parent'],track_decisions=True)
    from tools.research.postgame_progress import describe
    result['progress']=describe(result,summary,diagnosis,plan['parent'])
    require(result==json.loads((output/'preparation.json').read_bytes()),'practice learning preparation did not reproduce')
    require(all(d['split']=='train' or d['reason']!='evaluation_eligible' for d in result['case_decisions']),
            'practice preparation learned outside training split')
    from tools.research.postgame_knowledge import propose,validate_snapshot,preflight,staged_options
    knowledge=json.loads((output/'knowledge-stage/result.json').read_bytes());manifest=knowledge['manifest']
    frames={r['case_id']:iter(copy.deepcopy(r['parent_observations']))
            for r in manifest['accepted']+manifest['rejected'] if 'parent_observations' in r}
    candidate,expected_manifest=propose(Path(base_file).read_bytes(),result,diagnosis,plan['parent'],
        'practice-'+plan['plan_sha256'][:16],lambda case:next(frames[case['case_id']]))
    require(manifest==expected_manifest and knowledge['binary_sha256']==plan['binary_sha256'],
            'practice knowledge proposal did not reproduce')
    require(all(next(frames[c],None) is None for c in frames),'unused knowledge parent observations')
    if candidate is not None:
        require(candidate==(output/'knowledge-stage/candidate.tsv').read_bytes(),'practice candidate knowledge bytes differ')
        validate_snapshot(Path(base_file).read_bytes(),candidate,manifest)
        checks={r['case_id']:r for r in knowledge['preflight']['observations']}
        def saved_probe(case,which,ms,depth,enabled):
            r=checks[case['case_id']]
            return r['disabled'][int(which=='candidate')] if not enabled else r['candidate' if which=='candidate' else 'parent']
        require(preflight(manifest,saved_probe)==knowledge['preflight'],'practice knowledge preflight did not reproduce')
        if 'staging' in knowledge:staged_options(output/'knowledge-stage/staged',knowledge['staging'])
    final=json.loads((output/'result.json').read_bytes())
    require(final['selected_cases']==len(diagnosis) and final['parameter_updates']==result['learning']['parameter_updates']
            and final['knowledge_positions']==manifest['candidate_positions'],'practice candidate summary differs')
    return dict(training_selected_cases=len(diagnosis),all_lineages_preserved=True,preparation_reproduced=True,
                knowledge_proposal_reproduced=True,
                new_engine_runs=0,formal_adoption=False,strength_improvement_demonstrated=False)
