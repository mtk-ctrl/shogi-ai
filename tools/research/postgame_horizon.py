#!/usr/bin/env python3
"""Separate, bounded deeper-search memory route. No evaluation training/adoption.

Old 50/500ms evaluation evidence is immutable. This route explicitly compares
against today's 200ms choice, with full history and repeatable deeper evidence.
"""
from __future__ import annotations
from collections import Counter
import copy
import json
from pathlib import Path
import re
import time
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp, compare_children
from tools.research.postgame_candidates import replay
from tools.research.postgame_cases import position_command, sha256
from tools.research.postgame_ranker import digest, require, parent_values
from tools.research.postgame_spiral import leakage_keys

POLICY_HORIZON=dict(schema='postgame-horizon-policy-v1',max_roots=9,parent_ms=200,parent_repeats=2,
    deeper_ms=[500,2000],deeper_repeats=2,child_ms=500,min_fixed_depth=2,max_fixed_depth=4,
    fixed_timeout_ms=5000,fixed_repeats=2,min_improvement_cp=150,attempts_per_parent_root=1,
    automatic_formal_adoption=False)


def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def selection(preparation,diagnosis,parent):
    """Freeze ALL eligible saved horizon roots; never rank by new results."""
    require(preparation['example_bank']['parent_context']==parent,'horizon input parent differs')
    decisions={r['case_id']:r for r in preparation['case_decisions']}
    registry=preparation['split_registry'];groups={};excluded=[]
    for row in diagnosis:
        if row['route']!='search_horizon_candidate':continue
        case=row['case'];board,_=replay(case)
        require(case['start_sfen']==shogi.STARTING_SFEN,'horizon loader needs standard-start history')
        require(case.get('evidence_purpose')!='synthetic_fixture','synthetic observation is not real horizon research')
        command=position_command(case['start_sfen'],tuple(case['history_moves']))
        require(sha256(command.encode())==case['history_key'],'horizon full history differs')
        game='game:'+str(case['source']['run_id'])+':'+case['source']['game_id']
        keys=[game,*leakage_keys(board)]
        require(all(k in registry for k in keys),'missing preserved horizon split aliases')
        eligible=decisions[case['case_id']]['split']=='train' and all(
            registry[k]['split']=='train' and not registry[k].get('heldout_consumed') for k in keys)
        if not eligible:
            excluded.append(dict(case_id=case['case_id'],reason='not_unexposed_training'));continue
        require(shogi.Move.from_usi(row['research_move']) in board.legal_moves,'illegal frozen horizon target')
        groups.setdefault(case['history_key'],[]).append(row)
    roots=[]
    for history,rows in sorted(groups.items()):
        rows=sorted(rows,key=lambda r:r['case']['case_id']);targets={r['research_move'] for r in rows}
        if len(targets)!=1:
            excluded.append(dict(history_key=history,reason='conflicting_frozen_targets'));continue
        roots.append(dict(case=copy.deepcopy(rows[0]['case']),target=rows[0]['research_move'],
            aliases=[dict(case_id=r['case']['case_id'],row_sha256=digest(r)) for r in rows]))
    require(len(roots)<=POLICY_HORIZON['max_roots'],'horizon root cap exceeded; do not truncate after looking')
    # Different arrival histories at one board cannot silently select different memories.
    by_position={}
    for root in roots:by_position.setdefault(root['case']['position_key'],set()).add(root['target'])
    conflicts={k for k,v in by_position.items() if len(v)>1}
    for root in roots:
        if root['case']['position_key'] in conflicts:
            excluded.append(dict(history_key=root['case']['history_key'],reason='conflicting_position_targets'))
    return dict(schema='postgame-horizon-selection-v1',parent=copy.deepcopy(parent),policy=copy.deepcopy(POLICY_HORIZON),
        preparation_sha256=digest(preparation),diagnosis_sha256=digest(diagnosis),
        roots=[r for r in roots if r['case']['position_key'] not in conflicts],excluded=excluded,
        split_registry_sha256=digest(registry),restricted_leakage_keys=sorted(k for k,v in registry.items()
            if v['split']!='train' or v.get('heldout_consumed')),formal_adoption=False)


def checked_frame(frame,case,ms,depth=None,move=None):
    history=tuple(case['history_moves'])+((move,) if move else ())
    command=position_command(case['start_sfen'],history)
    require(frame['position_command']==command and frame['history_key']==sha256(command.encode())
            and frame['requested_ms']==ms and frame.get('requested_depth')==depth,'horizon probe timing/history differs')
    return exact_cp(frame) and (depth is None or frame['depth']==depth)


def evaluate(root,probe):
    """probe(case, ms, depth=None, child_move=None); observations retain heads only."""
    case=root['case'];target=root['target'];board,occurrences=replay(case)
    result=dict(root=copy.deepcopy(root),status='pending',parent=[],deeper=[],child_time=[],fixed=[])
    if occurrences!=1:result['status']='repeated_root';return result
    result['parent']=[probe(case,200) for _ in range(2)]
    if not all(checked_frame(p,case,200) for p in result['parent']):
        result['status']='parent_score_incomplete';return result
    moves={p['bestmove'] for p in result['parent']}
    if len(moves)!=1:result['status']='parent_unstable';return result
    current=next(iter(moves));result['compared_parent_move']=current
    require(shogi.Move.from_usi(current) in board.legal_moves,'illegal current parent move')
    if current==target:result['status']='already_correct';return result
    for ms in POLICY_HORIZON['deeper_ms']:
        for _ in range(POLICY_HORIZON['deeper_repeats']):
            result['deeper'].append(probe(case,ms))
    if not all(checked_frame(p,case,ms) and p['bestmove']==target
               for p,ms in zip(result['deeper'],[500,500,2000,2000])):
        result['status']='deeper_target_unstable_or_incomplete';return result
    result['child_time']=[probe(case,500,move=m) for m in (current,target)]
    if not all(checked_frame(p,case,500,move=m) for p,m in zip(result['child_time'],(current,target))):
        result['status']='child_score_incomplete';return result
    depth=min(POLICY_HORIZON['max_fixed_depth'],*(p['depth'] for p in result['child_time']))
    result['fixed_depth']=depth
    if depth<POLICY_HORIZON['min_fixed_depth']:result['status']='child_depth_insufficient';return result
    for _ in range(POLICY_HORIZON['fixed_repeats']):
        pair=[probe(case,5000,depth,m) for m in (current,target)]
        valid=all(checked_frame(p,case,5000,depth,m) for p,m in zip(pair,(current,target)))
        comparison=compare_children(*pair) if valid else dict(status='incomplete')
        result['fixed'].append(dict(parent=pair[0],target=pair[1],comparison=comparison))
    good=all(p['comparison']['status']=='comparable' and p['comparison']['improvement_cp']>=150 for p in result['fixed'])
    result['status']='validated_horizon_memory' if good else 'fixed_comparison_not_confirmed'
    return result


def propose(base,frozen,observations,cycle_id):
    from tools.research.postgame_knowledge import snapshot_rows
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,63}',cycle_id),'unsafe horizon identifier')
    require(frozen['policy']==POLICY_HORIZON and frozen['formal_adoption'] is False,'horizon frozen policy differs')
    require(sha256(base)==frozen['parent']['knowledge_sha256'],'horizon base changed')
    require([r['root'] for r in observations]==frozen['roots'],'horizon roots reordered/changed')
    rows=snapshot_rows(base);keys={r[0] for r in rows};ids={r[11] for r in rows if len(r)>11}
    accepted=[];rejected=[];lines=[]
    for observed in observations:
        # Independently replay every observation and reject missing/extra probes.
        queue=[]
        for key in ('parent','deeper','child_time'):queue.extend(observed[key])
        for pair in observed['fixed']:queue.extend([pair['parent'],pair['target']])
        it=iter(queue)
        replayed=evaluate(observed['root'],lambda *args,**kwargs:next(it))
        require(next(it,None) is None and replayed==observed,'horizon observations do not reproduce decision')
        root=observed['root'];case=root['case'];reason=observed['status']
        if reason=='validated_horizon_memory':
            for move in (root['target'],observed['compared_parent_move']):
                board,_=replay(case);board.push_usi(move)
                if set(leakage_keys(board)) & set(frozen['restricted_leakage_keys']):reason='child_split_collision'
        if reason=='validated_horizon_memory' and case['position_key'] in keys:reason='base_or_prior_position_preserved'
        if reason!='validated_horizon_memory':
            rejected.append(dict(case_id=case['case_id'],reason=reason));continue
        rid=cycle_id+'-'+case['case_id'][:16];require(rid not in ids,'horizon research ID collision')
        keys.add(case['position_key']);ids.add(rid)
        score=observed['deeper'][-1];target=root['target'];depth=observed['fixed_depth']
        lines.append('\t'.join([case['position_key'],target,cycle_id,'1','2000',str(depth),'0',
            'cp',str(score['value_stm']),'2000','research_decision',rid,target,' '.join(case['history_moves']) or '-']))
        accepted.append(dict(research_id=rid,case_id=case['case_id'],source=case['source'],position_key=case['position_key'],
            selected_move=target,actual_move=case['actual_move'],compared_parent_move=observed['compared_parent_move'],
            confirmed_improvement_cp=min(p['comparison']['improvement_cp'] for p in observed['fixed']),fixed_depth=depth,
            case=copy.deepcopy(case),observation_sha256=digest(observed),aliases=root['aliases'],
            terminal_reward_stm=case['outcome']['terminal_reward_stm']))
    candidate=base+(b'' if base.endswith(b'\n') else b'\n')+('# unadopted horizon research additions\n'+'\n'.join(lines)+'\n').encode() if lines else None
    manifest=dict(schema='postgame-horizon-proposal-v1',purpose='research',cycle_id=cycle_id,parent=frozen['parent'],
        policy=copy.deepcopy(POLICY_HORIZON),selection_sha256=digest(frozen),observations_sha256=digest(observations),
        base_sha256=sha256(base),base_positions=len(rows),candidate_positions=len(accepted),combined_positions=len(rows)+len(accepted),
        candidate_sha256=sha256(candidate) if candidate else None,accepted=accepted,rejected=rejected,
        status='requires_live_preflight' if candidate else 'no_effective_candidate',formal_adoption=False,
        production_match_eligible=True,strength_improvement_demonstrated=False)
    return candidate,manifest


def run(binary,base_file,preparation,diagnosis,frozen,params,cycle_id,output,expected_binary_sha256):
    from tools.research.postgame_knowledge import snapshot_rows,validate_snapshot,preflight,stage
    parent_values(params);require(digest(params)==frozen['parent']['parameters_sha256'],'horizon parent evaluation differs')
    require(selection(preparation,diagnosis,frozen['parent'])==frozen,'frozen horizon input selection changed')
    binary_hash=sha256(Path(binary).read_bytes());require(binary_hash==expected_binary_sha256,'horizon analyzer binary changed')
    output=Path(output);require(not output.exists(),'preserve original horizon attempt');output.mkdir(parents=True)
    raw=Path(base_file).read_bytes();count=len(snapshot_rows(raw));started=time.monotonic()
    def analyze(case,ms,depth=None,move=None):
        engine=Analyzer(binary,base_file,count,evaluation_options=params)
        try:return engine.search(case['start_sfen'],tuple(case['history_moves'])+((move,) if move else ()),ms,depth)
        finally:engine.close()
    observations=[];dump(output/'observations.json',observations)
    for root in frozen['roots']:
        observations.append(evaluate(root,analyze));dump(output/'observations.json',observations)
    candidate,manifest=propose(raw,frozen,observations,cycle_id)
    result=dict(schema='postgame-knowledge-stage-v1',manifest=manifest,binary_sha256=binary_hash,status=manifest['status'],
        formal_adoption=False,strength_improvement_demonstrated=False)
    dump(output/'selection.json',frozen)
    if candidate is not None:
        validate_snapshot(raw,candidate,manifest);(output/'candidate.tsv').write_bytes(candidate)
        def probe(case,which,ms,depth,enabled):
            path=base_file if which=='base' else output/'candidate.tsv';n=count if which=='base' else manifest['combined_positions']
            engine=Analyzer(binary,path,n,evaluation_options=params)
            try:
                if not enabled:
                    engine.send('setoption name PositionKnowledge value false');engine.send('isready');engine.until('readyok',15)
                return engine.search(case['start_sfen'],tuple(case['history_moves']),ms,depth)
            finally:engine.close()
        result['preflight']=preflight(manifest,probe)
        result['status']='ready_for_separate_match_adapter' if result['preflight']['passed'] else 'retain_parent_preflight_rejected'
        if result['preflight']['passed']:result['staging']=stage(raw,candidate,manifest,result['preflight'],output/'staged',params)
    result['horizon_summary']=dict(roots=len(observations),original_observations=sum(len(r['aliases']) for r in frozen['roots']),
        statuses=dict(Counter(r['status'] for r in observations)),seconds=round(time.monotonic()-started,3),
        independent_strength_test=False,parameter_updates=0)
    dump(output/'result.json',result);return result


def verify_saved(folder,base,preparation,diagnosis,frozen,result):
    folder=Path(folder)
    require(selection(preparation,diagnosis,frozen['parent'])==frozen,'saved horizon selection differs')
    require(json.loads((folder/'selection.json').read_bytes())==frozen,'saved horizon frozen selection differs')
    observations=json.loads((folder/'observations.json').read_bytes())
    candidate,manifest=propose(base,frozen,observations,result['manifest']['cycle_id'])
    require(manifest==result['manifest'],'saved horizon proposal differs from original observations')
    if candidate is not None:require((folder/'candidate.tsv').read_bytes()==candidate,'saved horizon TSV differs')
    return dict(roots=len(observations),proposal_reproduced=True,new_engine_runs=0,formal_adoption=False)
