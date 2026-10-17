#!/usr/bin/env python3
"""Research-only A/B knowledge match materialization and all-move audit.

Uses existing arena and archive validators. Inputs are immutable saved cycle
intents and publications, never paths supplied through the normal Issue API.
"""
from __future__ import annotations
import copy,json,shutil
from pathlib import Path
from tools.research.postgame_ranker import require,digest,OPTIONS,BASE
from tools.research.postgame_cases import sha256,load_archive
from tools.research.postgame_knowledge import validate_snapshot,staged_options,snapshot_rows
from tools.research.postgame_bridge import FORMAL_DEFAULTS,validate_shard,trajectory,dump
from tools.research.postgame_analyze import Analyzer
from tools.records.archive_played_moves import archive


def validate_intent(env,purpose='research'):
    s=env['state'];p=s['pending'];req=env['match_request']
    require(env['formal_adoption'] is False and env['blocked'] is None and p is not None,'not an active research intent')
    require(digest(s['plan'])==s['plan_sha256'] and digest(p['payload'])==p['operation_id'],'frozen intent changed')
    require(p['payload']['inputs']['parent']==s['parent'] and p['payload']['stage']==s['stage']
            and p['payload']['policy']==s['plan_sha256'],'operation parent/stage/policy differs')
    require(p['input_sha256']==digest(p['payload']['inputs']) and p['payload']['cycle']==s['plan']['cycle_id']
            and p['payload']['generation']==s['generation'],'operation inputs/cycle/generation differs')
    require(s['plan']['candidate_kind']=='knowledge' and req['execution_route']=='research_knowledge','not knowledge-only execution')
    from tools.research.postgame_runtime import POLICY_KNOWLEDGE_EXECUTION
    require(s['plan'].get('knowledge_execution_policy')==POLICY_KNOWLEDGE_EXECUTION,'knowledge execution policy differs')
    require(s['stage'] in ('screen','confirm','collect_source','initial_source'),'unsupported knowledge match stage')
    require(env['dispatch']['attempted'] is True and env['dispatch']['body_run'] is None,'intent was already dispatched')
    require(req['games']==p['payload']['games'] and req['seed']==p['payload']['seed'],'games/seed differs from saved operation')
    require(req['ref_a']==req['ref_b']==s['parent']['engine_ref'],'knowledge match changed engine')
    require(req['go_command']=='go movetime 200' and (req['max_plies']==300 or purpose=='integration_smoke' and req['max_plies']==4),
            'formal comparison limits changed')
    require(type(req['shards']) is int and 1<=req['shards']<=min(20,req['games']),'invalid actual runner distribution')
    require(purpose in ('research','integration_smoke'),'unknown route purpose')
    if purpose=='research':
        require(s['plan'].get('purpose')!='integration_smoke' or s['stage'] not in ('screen','confirm'),
                'smoke plan cannot launch a strength comparison')
        expected_games={'screen':100,'confirm':200}.get(s['stage'],s['plan'].get('source_games',100))
        require(req['games']==expected_games,'research match game budget differs from frozen stage')
        index=s['generation'] if s['stage']=='collect_source' else s['generation']-1
        seed_key=s['stage'] if s['stage'] in ('screen','confirm') else 'source'
        require(req['seed']==s['plan']['seeds'][index][seed_key]
                and s['used_games']+req['games']<=s['plan']['max_new_games'],'research seed/budget differs from fixed plan')
    if s['stage'] in ('screen','confirm'):
        require(p['payload']['inputs']['candidate']==s['candidate'],'candidate changed after saved operation intent')
    for side in ('a','b'):
        options=json.loads(req['options_'+side])
        require(options==dict(FORMAL_DEFAULTS,**env['parent_options'],PositionKnowledgeFile='build/knowledge-'+side.upper()+'.tsv'),
                'knowledge match altered search/evaluation or snapshot path')
    require(digest(env['parent_options'])==s['parent']['parameters_sha256'],'knowledge match parameters differ')
    return req


def staged(folder,expected_parent,purpose):
    root=Path(folder)/'knowledge-stage';result=json.loads((root/'result.json').read_bytes())
    manifest=result['manifest'];check=result['preflight'];package=result['staging']
    require(result['status']=='ready_for_separate_match_adapter' and check['passed'] is True,
            'knowledge candidate did not pass actual preflight')
    require(manifest['purpose']==purpose and manifest['formal_adoption'] is False,'wrong knowledge purpose/adoption')
    require(package['manifest_sha256']==digest(manifest) and package['preflight_sha256']==digest(check),
            'knowledge evidence hashes differ')
    require(manifest['parent']==expected_parent,'knowledge stage is from another parent')
    staged_options(root/'staged',package)
    a=(root/'staged/A.tsv').read_bytes();b=(root/'staged/B.tsv').read_bytes()
    validate_snapshot(b,a,manifest)
    return a,b,result


def materialize(env,reader,directory,purpose='research'):
    """reader(publication) returns an already hash/API-digest-verified folder."""
    req=validate_intent(env,purpose);s=env['state'];source=Path(reader(env['source_publication']))
    source_result=json.loads((source/'stage-result.json').read_bytes());source_audit=source_result['audit']
    require(all(source_audit.get(k) is True for k in ('all_moves_legal','all_terminations_verified','binary_verified','knowledge_snapshot_verified')),
            'source publication is not verified')
    require(source_audit['parent_ref']==s['parent']['engine_ref'],'source engine ref differs')
    binary=source/'build/engine-a';binary_sha=sha256(binary.read_bytes())
    require(binary_sha==source_audit['actual_binary_sha256']['A'],'source actual binary differs')
    base=(source/'build/position-knowledge-v1.tsv').read_bytes()
    if env.get('parent_knowledge_publication'):
        oldfolder=reader(env['parent_knowledge_publication'])
        old=json.loads((Path(oldfolder)/'knowledge-stage/result.json').read_bytes())
        base,_,_=staged(oldfolder,old['manifest']['parent'],purpose)
    require(sha256(base)==s['parent']['knowledge_sha256'],'research parent snapshot differs')
    candidate=base;ids=[]
    if s['stage'] in ('screen','confirm'):
        candidate,original,result=staged(reader(env['preparation_publication']),s['parent'],purpose)
        require(original==base and result==env['knowledge_candidate'],'candidate changed since preparation')
        require(sha256(candidate)==s['candidate']['knowledge_sha256'],'candidate differs from preflight identity')
        require(s['candidate']['engine_ref']==s['parent']['engine_ref']
                and s['candidate']['parameters_sha256']==s['parent']['parameters_sha256'],
                'knowledge candidate changed engine/evaluation')
        ids=[r['research_id'] for r in result['manifest']['accepted']]
        require(result['binary_sha256']==binary_sha,'candidate was not tested on this actual binary')
    directory=Path(directory);require(not directory.exists(),'do not overwrite materialized research inputs');directory.mkdir(parents=True)
    for side,data in (('A',candidate),('B',base)):
        (directory/('knowledge-'+side+'.tsv')).write_bytes(data)
        shutil.copyfile(binary,directory/('engine-'+side.lower()));(directory/('engine-'+side.lower())).chmod(0o755)
    (directory/'position-knowledge-v1.tsv').write_bytes(base)
    provenance=dict(schema='postgame-knowledge-materialization-v1',operation_id=s['pending']['operation_id'],
                    parent=s['parent'],stage=s['stage'],purpose=purpose,source_publication=env['source_publication'],
                    parent_knowledge_publication=env.get('parent_knowledge_publication'),
                    candidate_publication=env['preparation_publication'] if ids else None,
                    actual_binary_sha256=dict(A=binary_sha,B=binary_sha),source_binary_used='A',new_build_performed=False,
                    snapshots={side:dict(sha256=sha256(data),positions=len(snapshot_rows(data))) for side,data in (('A',candidate),('B',base))},
                    candidate_research_ids=ids,request=copy.deepcopy(req),formal_adoption=False)
    dump(directory/'provenance.json',provenance);dump(directory/'match-request.json',req)
    return provenance


def verify_materialization(build,provenance,request):
    build=Path(build)
    require(provenance['formal_adoption'] is False and provenance['request']==request,'materialized request differs')
    for side in ('A','B'):
        require(sha256((build/('engine-'+side.lower())).read_bytes())==provenance['actual_binary_sha256'][side],
                'materialized binary changed')
        data=(build/('knowledge-'+side+'.tsv')).read_bytes();spec=provenance['snapshots'][side]
        require(sha256(data)==spec['sha256'] and len(snapshot_rows(data))==spec['positions'],'materialized snapshot changed')
    require((build/'position-knowledge-v1.tsv').read_bytes()==(build/'knowledge-B.tsv').read_bytes(),'parent archive snapshot changed')


def audit(build,shards,request,run_id,output,prior_signatures=(),reproduce_loader=True):
    build=Path(build);provenance=json.loads((build/'provenance.json').read_bytes())
    verify_materialization(build,provenance,request)
    rows=sorted(Path(shards).glob('shard-*.json'));require(len(rows)==request['shards'],'missing actual match lanes')
    require([int(p.stem.split('-')[-1]) for p in sorted(rows,key=lambda p:int(p.stem.split('-')[-1]))]==list(range(request['shards'])),
            'missing/duplicate lane indices')
    for path in rows:
        validate_shard(json.loads(path.read_bytes()),int(path.stem.split('-')[-1]),request,
                       provenance['actual_binary_sha256'],provenance['snapshots'])
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    archive(rows,output/'played-archive',run_id,request['ref_a'],request['ref_b'])
    games=load_archive(output/'played-archive');require(len(games)==request['games'],'actual knowledge game count differs')
    ids=set(provenance['candidate_research_ids']);uses=0;signatures=[];unique={}
    for game in games:
        sig=trajectory(game.start_sfen,game.moves);signatures.append(sig)
        if sig not in prior_signatures:unique.setdefault(sig,game)
        for move in game.row['moves']:
            rid=move['search'].get('research_id')
            if rid in ids:
                require(move['engine']=='A','candidate knowledge leaked into B');uses+=1
    def counts(gs):
        gs=list(gs);return dict(wins=sum(g.row['winner']=='A' for g in gs),losses=sum(g.row['winner']=='B' for g in gs),draws=sum(g.row['winner'] is None for g in gs))
    if reproduce_loader:
        params={k:json.loads(request['options_a'])[k] for k in OPTIONS}
        for side in ('A','B'):
            spec=provenance['snapshots'][side];binary=build/('engine-'+side.lower());binary.chmod(0o755)
            engine=Analyzer(binary,build/('knowledge-'+side+'.tsv'),spec['positions'],evaluation_options=params)
            try:
                for key,value in dict(FORMAL_DEFAULTS,**dict(zip(OPTIONS,BASE))).items():
                    expected=str(value).lower() if type(value) is bool else str(value)
                    require(engine.option_defaults.get(key)==expected,'saved engine formal defaults differ')
            finally:engine.close()
    result=dict(schema='postgame-knowledge-match-audit-v1',purpose=provenance['purpose'],games=len(games),plies=sum(len(g.moves) for g in games),
                all_moves_legal=True,all_terminations_verified=True,conditions_verified=True,binary_verified=True,
                knowledge_snapshot_verified=True,duplicates_checked=True,candidate_knowledge_uses=uses,
                prior_and_internal_duplicates_excluded=counts(unique.values()),parent_ref=request['ref_a'],
                actual_binary_sha256=provenance['actual_binary_sha256'],knowledge_snapshots=provenance['snapshots'],
                internal_duplicates=len(games)-len(set(signatures)),prior_trajectory_overlap=sum(s in prior_signatures for s in signatures),
                trajectory_outcomes=[dict(sha256=s,winner=g.row['winner'],a_black=g.row['a_black'],game_id=g.row['game_id']) for s,g in zip(signatures,games)],
                loader_reproduced=reproduce_loader,original_loader_handshake_retained=False,
                scope='A/B knowledge research match with exact archived source binary; no new engine build or formal adoption.')
    dump(output/'audit.json',result)
    return dict(audit=result,result=counts(games),started_lanes=len(rows))
