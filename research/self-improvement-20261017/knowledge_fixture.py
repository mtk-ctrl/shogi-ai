#!/usr/bin/env python3
"""Synthetic knowledge wiring exercise with the actual engine and arena.

The deliberately fabricated research comparison is NEVER a learning source or
strength result. propose() refuses it outside integration_smoke. The remembered
move is merely a distinct legal move, and can be worse than the parent's move.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'benchmarks'))
import shogi
from tools.research.postgame_analyze import Analyzer, OPTIONS as ANALYSIS_OPTIONS
from tools.research.postgame_cases import position_command,sha256
from tools.research.postgame_ranker import BASE,OPTIONS,digest
from tools.research.postgame_spiral import prepare
from tools.research.postgame_progress import describe
from tools.research.postgame_knowledge import run,staged_options
from position_arena import play
from arena import Engine

PREFIX=['7g7f','8b4b','2g2f','4c4d','2f2e','4d4e','9g9f','4b4d']
ALTERNATIVE=['9g9f','8b4b','7g7f','4c4d','2g2f','4d4e','2f2e','4b4d']


def exercise(binary,base,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    params=dict(zip(OPTIONS,BASE));base=Path(base);binary=Path(binary)
    count=sum(bool(l) and not l.startswith('#') for l in base.read_text().splitlines())
    parent=dict(engine_ref=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                knowledge_sha256=sha256(base.read_bytes()),parameters_sha256=digest(params))
    board=shogi.Board()
    for move in PREFIX:
        assert shogi.Move.from_usi(move) in board.legal_moves;board.push_usi(move)
    engine=Analyzer(binary,base,count,evaluation_options=params)
    try:original=engine.search(shogi.STARTING_SFEN,tuple(PREFIX),200)
    finally:engine.close()
    assert original['bestmove']=='8h4d',original
    target=next(m.usi() for m in board.legal_moves if m.usi()!=original['bestmove'])
    case=dict(case_id=digest(['synthetic-memory-fixture-v1',PREFIX,target]),start_sfen=shogi.STARTING_SFEN,
              history_moves=PREFIX,history_key=original['history_key'],position_key=' '.join(board.sfen().split()[:3]),
              actual_move=original['bestmove'],actor='A',evidence_purpose='synthetic_fixture',
              source=dict(run_id='synthetic-memory-fixture',game_id='not-a-training-game',ply=len(PREFIX)+1),
              outcome=dict(status='unresolved',terminal_reward_stm=None,winner=None,reason='synthetic_fixture'))
    def synthetic_frame(history,move,value):
        command=position_command(shogi.STARTING_SFEN,tuple(history))
        return dict(status='recorded',kind='cp',bound='exact',depth=3,pv_head_matches=True,
                    bestmove=move,value_stm=value,history_key=sha256(command.encode()),position_command=command)
    row=dict(case=case,route='stable_research_move_candidate',research_move=target,same_as_actual=False,
             root_short=synthetic_frame(PREFIX,target,0),root_deep=synthetic_frame(PREFIX,target,0))
    row['root_short']['requested_ms']=50;row['root_deep']['requested_ms']=500
    children={}
    for key,move,value in (('actual',case['actual_move'],200),('research',target,0)):
        child=shogi.Board(board.sfen());child.push_usi(move)
        children[key]=synthetic_frame(PREFIX+[move],next(iter(child.legal_moves)).usi(),value)
    row['followup']=dict(requested_depth=3,**children,
                         comparison=dict(status='comparable',improvement_cp=200,actual_depth=3,improved_depth=3))
    def static(_):
        return dict(material_term=0,safety=0,pressure=0,activity=0,danger=0,influence=0,potential=0,
                    coordination=0,hand_potential=0,threat=0,clamp=0,total=0)
    for i in range(100):
        report=prepare([row],lambda _:[original,copy.deepcopy(original)],static,'synthetic-memory-split-'+str(i),
                       parent_options=params,parent_context=parent,track_decisions=True)
        if report['candidate_knowledge']:break
    else:raise AssertionError('synthetic training-group fixture unavailable')
    summary=dict(source_games=1,source_plies=len(PREFIX)+1,selected_cases=1,routes=report['routes'],
                 verification_pairs=1,seconds=0.,analyzer_binary_sha256=sha256(binary.read_bytes()),
                 options=ANALYSIS_OPTIONS,evaluation_options=params)
    report['progress']=describe(report,summary,[row],parent)
    result=run(binary,base,report,[row],parent,params,'synthetic-memory-fixture-v1',output/'knowledge','integration_smoke')
    assert result['status']=='ready_for_separate_match_adapter',result
    stage=result['staging'];folder=output/'knowledge/staged';opts=staged_options(folder,stage)
    candidate=folder/'A.tsv';expected=result['manifest']['accepted'][0]['research_id']
    def candidate_probe(history,enabled=True):
        e=Analyzer(binary,candidate,count+1,evaluation_options=params)
        try:
            if not enabled:
                e.send('setoption name PositionKnowledge value false');e.send('isready');e.until('readyok',15)
            return e.search(shogi.STARTING_SFEN,tuple(history),200)
        finally:e.close()
    alt=shogi.Board()
    for move in ALTERNATIVE:alt.push_usi(move)
    assert ' '.join(alt.sfen().split()[:3])==case['position_key']
    transposed=candidate_probe(ALTERNATIVE)
    assert transposed['research_decision_id']==expected and transposed['bestmove']==target
    repeated=PREFIX+['5i5h','5a5b','5h5i','5b5a']
    repeated_probe=candidate_probe(repeated)
    assert repeated_probe['research_decision_id'] is None
    disabled=candidate_probe(PREFIX,False)
    assert disabled['research_decision_id'] is None
    restored=candidate_probe(PREFIX)
    assert restored['research_decision_id']==expected
    games=[]
    for a_black in (True,False):
        a=Engine(binary,'A',opts['A'],'go movetime 200');b=Engine(binary,'B',opts['B'],'go movetime 200')
        try:game=play(a,b,dict(id='synthetic-memory-wiring',moves=PREFIX),a_black,4,2036101801+int(a_black)*2)
        finally:a.close();b.close()
        replay=shogi.Board()
        for move in PREFIX+game['moves']:
            assert shogi.Move.from_usi(move) in replay.legal_moves;replay.push_usi(move)
        assert replay.sfen()==game['final_sfen'] and 'illegal_by' not in game
        games.append(game)
    uses=[m for g in games for m in g['move_records'] if m['search'].get('research_id')==expected]
    assert uses and all(m['engine']=='A' and m['move']==target for m in uses)
    assert sum(m['search'].get('research_id')==expected and m['engine']=='B' for g in games for m in g['move_records'])==0
    return dict(schema='synthetic-knowledge-wiring-v1',purpose='integration_smoke',source='own-authored synthetic fixture',
                fabricated_research_scores=True,not_a_training_source=True,strength_improvement_demonstrated=False,
                engine_ref=parent['engine_ref'],binary_sha256=result['binary_sha256'],
                base_sha256=parent['knowledge_sha256'],candidate_sha256=result['manifest']['candidate_sha256'],
                base_positions=count,candidate_positions=count+1,disabled_exact=result['preflight']['disabled_exact'],
                tactical_regressions=result['preflight']['regressions'],depth_ratio=result['preflight']['depth_ratio'],
                targeted_behavior_changes=result['preflight']['targeted_corrections'],
                parent_move=case['actual_move'],synthetic_remembered_move=target,
                transposed_arrival_direct=True,repeated_position_falls_back=True,disabled_falls_back=True,reenabled_uses_memory=True,
                partial_games=len(games),played_plies=sum(len(g['moves']) for g in games),all_played_moves_legal=True,
                new_research_uses_A=len(uses),new_research_uses_B=0,
                ponder_protocol_exercised=False,original_arena_loader_handshake_retained=False,
                partial_game_results_not_training_rewards=True,formal_adoption=False,
                limitation='Only a file-delivery/behavior test. The chosen synthetic move is not claimed to be good. No strength comparison.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--base',type=Path,default=ROOT/'position-knowledge-v1.tsv')
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report=exercise(args.binary,args.base,args.directory)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
