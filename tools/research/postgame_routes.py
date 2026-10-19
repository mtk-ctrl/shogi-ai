"""Training-only replay knowledge, research allocation and inherited practice.

This adds no evaluation coefficients. Observed own moves are search hints;
read-more disagreement is an uncertainty signal, never a correctness label.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp
from tools.research.postgame_cases import load_archive, make_case, position_command, sha256, require
from tools.research.train_structured_value import PARENT
from tools.research.postgame_eval_preflight import tactical_cases

POLICY=dict(schema='postgame-routes-policy-v1',max_hints=8192,max_research=24,max_per_game=2,
    short_ms=200,deep_ms=1000,deep_repeats=2,fixed_ms=3000,fixed_depth_cap=3,
    verified_gap_cp=150,max_seconds=600,max_practice_roots=4,max_practice_games=16,
    practice_new_plies=8,practice_ms=200,formal_adoption=False)
MODEL='8c174f7adac2d45cc0ab2633986ab89db3f24906bd655f5e18e81538eb7fdb1c'

def dump(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(raw);temp.replace(p)

def key(sfen):return ' '.join(sfen.split()[:3])

class OwnAnalyzer(Analyzer):
    def __init__(self,binary,knowledge,learned=True,modes=()):
        super().__init__(binary,knowledge,evaluation_options=PARENT)
        handshake=self.option_defaults
        if learned:
            require('StructuredEval' in handshake,'learned parent is absent')
            self.send('setoption name StructuredEval value true')
            self.send('setoption name StructuredScale value 50')
        for name in modes:
            require(name in handshake,'route option absent: '+name)
            self.send('setoption name '+name+' value true')
        self.send('isready');self.until('readyok',15)

def collect(source,positions):
    """A board is usable only when both its game AND frozen position are train."""
    manifest=json.loads((Path(source)/'manifest.json').read_text())
    require(manifest['requested_ref_a']==manifest['requested_ref_b']==
            '055732661e303a46aaf912bd6a0dc9784e50721e','unexpected immutable selfplay parent')
    allowed={};blocked=set()
    for line in Path(positions).read_text().splitlines():
        row=json.loads(line);k=key(row['sfen'])
        if row['split']=='train':allowed[k]=row['game_hash']
        else:blocked.add(k)
    games=load_archive(source)
    # Guard against a held-out board occurring in an otherwise training game.
    for game in games:
        gh=sha256(' '.join(game.moves).encode())
        if int(gh[:8],16)%100<70:continue
        board=shogi.Board(game.start_sfen)
        for token in game.moves:blocked.add(key(board.sfen()));board.push_usi(token)
        blocked.add(key(board.sfen()))
    observations=[];seen_games=set()
    for game in games:
        gh=sha256(' '.join(game.moves).encode())
        if int(gh[:8],16)%100>=70 or gh in seen_games:continue
        seen_games.add(gh)
        for side in ('a','b'):
            opts=game.metadata['options_'+side]
            require(all(opts.get(k)==v for k,v in PARENT.items()) and opts.get('StructuredEval') is True
                    and opts.get('StructuredScale')==50,'selfplay profile differs')
        board=shogi.Board(game.start_sfen);previous={}
        for ply,row in enumerate(game.row['moves'],1):
            k=key(board.sfen());search=row['search'];cp=search.get('score_cp_stm');side=board.turn
            if k in allowed and k not in blocked:
                exact=(search.get('score_status')=='recorded' and type(cp)is int
                    and not search.get('score_lowerbound') and not search.get('score_upperbound')
                    and search.get('depth',0)>=2 and not search.get('knowledge_hits',0))
                if exact:
                    phase=search.get('phase_maturity');require(type(phase)is int,'missing phase observation')
                    reason=('insufficient_depth' if search['depth']<3 else
                        'score_drop' if side in previous and previous[side]-cp>=150 else
                        'late_game_review' if ply>=len(game.moves)-20 else 'coverage')
                    rank={'insufficient_depth':0,'score_drop':1,'late_game_review':2,'coverage':3}[reason]
                    observations.append(dict(sfen=board.sfen(),key=k,move=row['move'],depth=search['depth'],
                        game_id=game.row['game_id'],game_hash=gh,ply=ply,phase=0 if phase<34 else 1 if phase<67 else 2,
                        side=int(side),reason=reason,priority=rank,source=game))
            if type(cp)is int:previous[side]=cp
            board.push_usi(row['move'])
    return games,observations,dict(archive_sha256=manifest['archive_sha256'],
        archive_bytes=manifest['archive_bytes'],games=len(games),verified_plies=sum(len(g.moves) for g in games),
        training_games=len(seen_games),protected_boards=len(blocked),eligible_positions=len(observations))

def select(observations):
    by_cell=defaultdict(list)
    for r in observations:by_cell[(r['phase'],r['side'])].append(r)
    for rows in by_cell.values():rows.sort(key=lambda r:(r['priority'],-r['ply'],r['game_hash']))
    chosen=[];counts=Counter();seen=set()
    while len(chosen)<POLICY['max_research']:
        added=False
        for cell in sorted(by_cell):
            while by_cell[cell]:
                r=by_cell[cell].pop(0)
                if counts[r['game_hash']]>=POLICY['max_per_game'] or r['key'] in seen:continue
                chosen.append(r);counts[r['game_hash']]+=1;seen.add(r['key']);added=True;break
            if len(chosen)==POLICY['max_research']:break
        if not added:break
    return chosen

def research(case,probe):
    history=tuple(case['history_moves'])
    short=probe(case,history,200,None)
    deep=[probe(case,history,1000,None) for _ in range(2)]
    stable=all(exact_cp(r) and not r.get('research_decision_id') for r in deep) and deep[0]['bestmove']==deep[1]['bestmove']
    result=dict(case=case,short=short,deep=deep,time_need=False,verified_research_move=None,
                status='deep_incomplete_or_unstable')
    if not stable:return result
    move=deep[0]['bestmove']
    result['status']='same_choice' if exact_cp(short) and move==short['bestmove'] else 'read_more_disagreement'
    result['time_need']=exact_cp(short) and short['bestmove']!=move
    if move==case['actual_move']:return result
    # Equal-depth child values, both from the same opponent perspective.
    depth=min(POLICY['fixed_depth_cap'],short.get('depth') or 1,*(r['depth'] for r in deep))
    children={name:probe(case,history+(token,),3000,depth)
              for name,token in [('actual',case['actual_move']),('research',move)]}
    result['children']=children;result['fixed_depth']=depth
    if all(exact_cp(r) and r['depth']==depth and not r.get('research_decision_id') for r in children.values()):
        gap=children['actual']['value_stm']-children['research']['value_stm'];result['gap_cp']=gap
        if gap>=POLICY['verified_gap_cp']:
            result['verified_research_move']=move;result['status']='verified_same_depth_research_hint'
    return result

def make_memory(observations,results):
    # These are hints, not correct moves. Conflicting observations remain out.
    choices=defaultdict(set);best={}
    for row in observations:
        if row['depth']<3:continue
        choices[row['key']].add(row['move'])
        if row['key'] not in best or row['depth']>best[row['key']]['depth']:best[row['key']]=row
    rows={}
    for k in sorted(best,key=lambda k:(-best[k]['depth'],sha256(k.encode())))[:POLICY['max_hints']]:
        if len(choices[k])!=1:continue
        r=best[k];rows[k]=dict(order=r['move'],research='-',time_need=False,game_hash=r['game_hash'])
    for r in results:
        case=r['case'];k=case['position_key']
        if not(r['time_need'] or r['verified_research_move']):continue
        e=rows.setdefault(k,dict(order='-',research='-',time_need=False,
                                game_hash=case['source_game_hash']))
        e['research']=r['verified_research_move'] or '-';e['time_need']=r['time_need']
    return rows

def write_memory(output,rows):
    text=''.join(k+'\t'+v['order']+'\t'+v['research']+'\t'+str(int(v['time_need']))+'\n' for k,v in sorted(rows.items()))
    (output/'replay-knowledge.tsv').write_text(text)
    digest=sha256(text.encode())
    (output/'replay_knowledge_data.h').write_text('#pragma once\n#include <string_view>\nnamespace shogi::strategy::detail {\n'
        'inline constexpr const char* ReplayKnowledgeSha="'+digest+'";\n'
        'inline constexpr std::string_view ReplayKnowledgeText{R"KUMOJIREPLAY('+text+')KUMOJIREPLAY",'+str(len(text.encode()))+'};\n}\n')
    return digest

def build(source,positions,binary,knowledge,output):
    output=Path(output);require(not output.exists(),'preserve previous route observations');output.mkdir(parents=True)
    games,rows,provenance=collect(source,positions);selected=select(rows)
    selection=[dict(case=make_case(r['source'],r['ply']),reason=r['reason'],game_hash=r['game_hash'],
                    phase=r['phase'],side=r['side']) for r in selected]
    # Full trajectory is used only to bind lineage, never as a PV teacher.
    for item,r in zip(selection,selected):item['case']['source_game_hash']=r['game_hash']
    plan=dict(schema='postgame-routes-plan-v1',policy=POLICY,parent_model=MODEL,parent_scale=50,
              binary_sha256=sha256(Path(binary).read_bytes()),knowledge_sha256=sha256(Path(knowledge).read_bytes()),
              positions_sha256=sha256(Path(positions).read_bytes()),provenance=provenance,selection=selection)
    dump(output/'selection.json',plan);started=time.monotonic();results=[];calls=0
    def probe(case,history,ms,depth=None):
        nonlocal calls
        require(time.monotonic()-started<POLICY['max_seconds'],'research time budget reached')
        calls+=1;engine=OwnAnalyzer(binary,knowledge)
        try:return engine.search(case['start_sfen'],history,ms,depth,include_telemetry=False)
        finally:engine.close()
    for item in selection:
        results.append(research(item['case'],probe));dump(output/'research.json',results)
        print('ROUTE_RESEARCH',len(results),results[-1]['status'],flush=True)
    memory=make_memory(rows,results);memory_sha=write_memory(output,memory)
    # Freeze retention targets before any candidate can be measured.
    controls=[]
    for case in tactical_cases():
        frame=probe(case,tuple(case['history_moves']),200)
        controls.append(dict(case=case,parent=frame,passed=frame['bestmove'].startswith(case['expected_prefix'])))
    dump(output/'retention.json',controls)
    dump(output/'lineage.json',{k:v for k,v in memory.items()})
    report=dict(schema='postgame-routes-v1',policy=POLICY,provenance=provenance,memory_sha256=memory_sha,
        parent_model=MODEL,parent_scale=50,binary_sha256=plan['binary_sha256'],knowledge_sha256=plan['knowledge_sha256'],
        order_hints=sum(v['order']!='-' for v in memory.values()),
        research_hints=sum(v['research']!='-' for v in memory.values()),
        time_cases=sum(v['time_need'] for v in memory.values()),research_cases=len(results),
        status_counts=dict(Counter(r['status'] for r in results)),search_calls=calls,
        elapsed_seconds=round(time.monotonic()-started,3),
        retention_parent_passed=sum(r['passed'] for r in controls),retention_cases=len(controls),
        formal_adoption=False,strength_improvement_demonstrated=False)
    dump(output/'report.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
    return report

def practice(source,results,binary,older_binary,knowledge,output):
    from tools.research.postgame_practice import play_branch
    from tools.records.archive_played_moves import archive
    games={g.row['game_id']:g for g in load_archive(source)};candidates=[]
    for result in results:
        case=result['case'];choices=[r['bestmove'] for r in result['deep'] if exact_cp(r)]
        alternatives=[m for m in choices if m!=case['actual_move']]
        if alternatives:candidates.append((result,alternatives[0]))
    selected=[];used=set()
    for result,move in sorted(candidates,key=lambda p:(p[0]['case']['side_to_move'],p[0]['case']['source']['game_id'])):
        case=result['case'];gh=case['source_game_hash']
        if gh in used:continue
        used.add(gh);selected.append((result,move))
        if len(selected)==POLICY['max_practice_roots']:break
    output=Path(output);require(not output.exists(),'preserve previous practice');output.mkdir()
    intent=[dict(case=r['case'],alternative=m,opponents=['parent','previous-own-parent']) for r,m in selected]
    dump(output/'plan.json',dict(policy=POLICY,roots=intent,independent_new_groups=0))
    publications=[];observations=[];new_keys=set();calls=0
    for index,(result,alternative) in enumerate(selected):
        case=result['case'];game=games[case['source']['game_id']];actor_black=case['side_to_move']=='black'
        root=dict(practice_id=sha256((case['case_id']+MODEL).encode()),task=dict(case=case),
            actual_move=case['actual_move'],alternative_move=alternative,
            lineage=dict(group=case['source_game_hash'],split='train',heldout_consumed=False))
        for opponent in ('parent','previous-own-parent'):
            actor_label='A' if actor_black==game.row['a_black'] else 'B'
            a_learned=opponent=='parent' or actor_label=='A';b_learned=opponent=='parent' or actor_label=='B'
            for branch in ('actual','alternative'):
                def probe(case,history,ms):
                    nonlocal calls
                    calls+=1;board=shogi.Board(case['start_sfen'])
                    for token in history:board.push_usi(token)
                    learned=opponent=='parent' or (board.turn==shogi.BLACK)==actor_black
                    engine=OwnAnalyzer(binary if learned else older_binary,knowledge,learned=learned)
                    try:return engine.search(case['start_sfen'],history,ms,include_telemetry=True)
                    finally:engine.close()
                played,info=play_branch(root,dict(name=opponent,actor_ms=200,reply_ms=200),branch,game,probe,
                                       max_new_plies=POLICY['practice_new_plies'])
                if info['terminal_observation'] and played['reason']=='practice_resign_unverified':
                    raise ValueError('unverified practice resignation cannot enter the standard archive')
                opts=dict(game.metadata['options_a']);opts.update(AdaptiveLongThink=False,USI_Ponder=False,OpeningRandomNonLance=False)
                oa=dict(opts);ob=dict(opts)
                if not a_learned:oa.pop('StructuredEval',None);oa.pop('StructuredScale',None)
                if not b_learned:ob.pop('StructuredEval',None);ob.pop('StructuredScale',None)
                path=output/f'practice-{index}-{opponent}-{branch}.json'
                metadata=dict(game.metadata,engine_a=str(binary if a_learned else older_binary),
                    engine_b=str(binary if b_learned else older_binary),
                    sha256_a=sha256(Path(binary if a_learned else older_binary).read_bytes()),
                    sha256_b=sha256(Path(binary if b_learned else older_binary).read_bytes()),
                    options_a=oa,options_b=ob,go_command='go movetime 200',
                    max_plies=info['prefix_plies']+POLICY['practice_new_plies'])
                metadata['execution_segments']=[dict(first_ply=1,last_ply=info['prefix_plies'],
                    role='replayed_original_history',source=case['source'],original_metadata=game.metadata),
                    dict(first_ply=info['prefix_plies']+1,last_ply=played['plies'],role='new_practice',
                         options_apply_to='new_practice_only')]
                metadata['training_lineage']=root['lineage']
                detail=dict(played,moves=[r['move'] for r in played['moves']],move_records=played['moves'])
                dump(path,dict(metadata,details=[detail],games=1));publications.append(path)
                observations.append(info)
                board=shogi.Board(case['start_sfen'])
                for row in played['moves']:
                    if row['ply']>info['prefix_plies']:new_keys.add(key(board.sfen()))
                    board.push_usi(row['move'])
                dump(output/'checkpoint.json',observations)
                print('ROUTE_PRACTICE',len(observations),opponent,branch,info['new_plies'],flush=True)
    if publications:
        archive(publications,output/'archive',run_id='routes-practice-20261019')
        saved=load_archive(output/'archive');require(len(saved)==len(observations),'practice readback count differs')
    report=dict(roots=len(selected),games=len(observations),new_plies=sum(r['new_plies'] for r in observations),
        unique_reached_positions=len(new_keys),source_groups=len(used),independent_new_groups=0,search_calls=calls,
        opponents=['parent','previous-own-parent'],all_legal_and_terminations_verified=True,
        lineages=observations,formal_adoption=False,strength_measurement=False)
    dump(output/'report.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--positions',type=Path,required=True);p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--knowledge',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.source,a.positions,a.binary,a.knowledge,a.output)
