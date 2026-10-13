#!/usr/bin/env python3
"""Research-only, balanced multi-profile selection using the standard arena."""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_ROOT = ROOT / 'research/variable-eval-20261012/search-rounds'
REGISTRY = ROOT / 'research/variable-eval-20261012/profiles.json'
KNOWLEDGE_HASH = '6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_plan(plan_id):
    if not re.fullmatch(r'[a-z0-9_-]{1,48}', plan_id):
        raise ValueError('invalid plan identifier')
    plan = json.loads((PLAN_ROOT / (plan_id + '.json')).read_text())
    registry = json.loads(REGISTRY.read_text())['profiles']
    expected = {'plan_id','stage','profiles','games_per_baseline','go_command',
                'adaptive_long_think','seeds','max_plies','controls','selection_notice'}
    if set(plan) != expected or plan['plan_id'] != plan_id:
        raise ValueError('plan schema mismatch')
    profiles = plan['profiles']
    if not 1 <= len(profiles) <= 100 or len(profiles) != len(set(profiles)):
        raise ValueError('invalid candidate set')
    if any(type(i) is not int or not 2 <= i < len(registry) for i in profiles):
        raise ValueError('invalid candidate profile index')
    n = plan['games_per_baseline']
    if type(n) is not int or not 2 <= n <= 80 or n % 2:
        raise ValueError('comparisons must have balanced colors and 2..80 games')
    if plan['controls'] != {'M':1,'Q14':0}:
        raise ValueError('fixed M and Q14 controls required')
    valid_time = ((plan['stage'] == 'coarse' and plan['go_command'] == 'go movetime 50'
                   and plan['adaptive_long_think'] is False) or
                  (plan['stage'] == 'followup' and plan['go_command'] == 'go movetime 200'
                   and plan['adaptive_long_think'] is True))
    if not valid_time or plan['max_plies'] != 300:
        raise ValueError('unexpected time, long-think or ply limit')
    if set(plan['seeds']) != {'M','Q14'} or any(type(s) is not int or
            not 0 <= s <= 2147483647 - 2*n for s in plan['seeds'].values()):
        raise ValueError('invalid seeds')
    return plan, registry

def allocation(plan, shards):
    if type(shards) is not int or not 1 <= shards <= 10:
        raise ValueError('total study runner limit is 10')
    pairs = [(p,b) for p in plan['profiles'] for b in ['M','Q14']]
    per = plan['games_per_baseline']
    total = len(pairs)*per
    q,r = divmod(total,shards)
    counts = [q+(i<r) for i in range(shards)]
    if min(counts) < 1:
        raise ValueError('empty lane')
    limit = 240 if plan['stage']=='coarse' else 120
    if max(counts)>limit:
        raise ValueError('too many games per lane; timeout-safe limit exceeded')
    assigned = []
    cursor = 0
    for count in counts:
        lane=[]
        stop=cursor+count
        while cursor<stop:
            pair_index,offset=divmod(cursor,per)
            profile,baseline=pairs[pair_index]
            n=min(stop-cursor,per-offset)
            lane.append(dict(profile=profile,baseline=baseline,offset=offset,games=n,
                seed=plan['seeds'][baseline]+2*offset))
            cursor+=n
        assigned.append(lane)
    return assigned

def options(index, plan):
    return {'ResearchProfile':index,'AdaptiveLongThink':plan['adaptive_long_think'],
            'PositionKnowledge':True,'PositionKnowledgeFile':'build/position-knowledge-v1.tsv'}

def filename(fragment):
    return f"raw-p{fragment['profile']:03d}-{fragment['baseline']}-{fragment['offset']:03d}.json"

def audit(data,fragment,plan,binary_hash=None):
    n=fragment['games']; baseline=plan['controls'][fragment['baseline']]
    if (data['games']!=n or len(data['details'])!=n or data['seed']!=fragment['seed'] or
        data['game_offset']!=fragment['offset'] or data['max_plies']!=plan['max_plies'] or
        data['go_command']!=plan['go_command'] or
        data['options_a']!=options(fragment['profile'],plan) or
        data['options_b']!=options(baseline,plan)):
        raise ValueError('actual settings do not match the frozen fragment')
    if data['sha256_a']!=data['sha256_b'] or (binary_hash and data['sha256_a']!=binary_hash):
        raise ValueError('shared binary hash mismatch')
    for side in ['A','B']:
        k=data['position_knowledge'][side]
        if not k['enabled'] or not k['available'] or k['positions']!=163 or k['sha256']!=KNOWLEDGE_HASH:
            raise ValueError('adopted knowledge identity mismatch')
    wins=draws=losses=0
    for i,g in enumerate(data['details']):
        if 'illegal_by' in g or g['a_black']!=((fragment['offset']+i)%2==0):
            raise ValueError('illegal move or color mismatch')
        if len(g['moves'])!=g['plies'] or len(g['move_records'])!=g['plies']:
            raise ValueError('move record length mismatch')
        wins+=g['winner']=='A'; losses+=g['winner']=='B'; draws+=g['winner'] is None
        long_used={'A':0,'B':0}
        for move in g['move_records']:
            expected=fragment['profile'] if move['engine']=='A' else baseline
            s=move['search']
            if s.get('phase_research_profile')!=expected or 'phase_maturity' not in s:
                raise ValueError('actual profile selection or phase record missing')
            used=s.get('long_think_used',long_used[move['engine']])
            if not long_used[move['engine']]<=used<=10:
                raise ValueError('long-think limit mismatch')
            if not plan['adaptive_long_think'] and used:
                raise ValueError('long think used during fast screening')
            long_used[move['engine']]=used
    if (wins,draws,losses)!=(data['wins_a'],data['draws'],data['wins_b']) or data['illegal_games']:
        raise ValueError('summary does not match raw outcomes')
    return wins,draws,losses

def run_lane(args,plan,registry):
    assigned=allocation(plan,args.shards)
    if not 0<=args.shard<args.shards:
        raise ValueError('invalid shard')
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    binary_hash=digest(args.engine)
    for fragment in assigned[args.shard]:
        path=out/filename(fragment)
        baseline=plan['controls'][fragment['baseline']]
        command=[sys.executable,str(ROOT/'benchmarks/arena.py'),
            '--engine-a',args.engine,'--engine-b',args.engine,
            '--options-a',json.dumps(options(fragment['profile'],plan)),
            '--options-b',json.dumps(options(baseline,plan)),
            '--games',str(fragment['games']),'--game-offset',str(fragment['offset']),
            '--seed',str(fragment['seed']),'--max-plies',str(plan['max_plies']),
            '--go-command',plan['go_command'],'--output',str(path)]
        print('START',plan['plan_id'],registry[fragment['profile']]['name'],fragment,flush=True)
        subprocess.run(command,check=True)
        data=json.loads(path.read_text())
        audit(data,fragment,plan,binary_hash)
        data['research_meta']={'plan_id':plan['plan_id'],'engine_ref':args.engine_ref,
            'registry_sha256':digest(REGISTRY),'shard':args.shard,'fragment':fragment,
            'profile_a_name':registry[fragment['profile']]['name'],'profile_b':baseline}
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        print('VERIFIED',path,flush=True)

def interval(w,d,l):
    n=w+d+l; score=(w+.5*d)/n
    variance=(w*(1-score)**2+d*(.5-score)**2+l*score**2)/(n-1)
    # Keep a non-degenerate bound even for all wins/draws in a tiny sample.
    # Hoeffding applies to bounded 0/.5/1 scores assuming independent games.
    # Shared openings and candidate selection remain separate limitations.
    error=max(1.96*math.sqrt(variance/n),math.sqrt(math.log(40)/(2*n)))
    return score,[max(0,score-error),min(1,score+error)]

def aggregate(args,plan,registry):
    assigned=allocation(plan,args.shards)
    by_pair=defaultdict(lambda: {'wins':0,'draws':0,'losses':0,'colors':0,'fragments':[]})
    expected_files=set()
    binary_hash=None
    archives=[]
    for shard,lane in enumerate(assigned):
        for fragment in lane:
            path=Path(args.input_dir)/filename(fragment); expected_files.add(path.name)
            data=json.loads(path.read_text())
            if data['research_meta']!={'plan_id':plan['plan_id'],'engine_ref':args.engine_ref,
                    'registry_sha256':digest(REGISTRY),'shard':shard,'fragment':fragment,
                    'profile_a_name':registry[fragment['profile']]['name'],
                    'profile_b':plan['controls'][fragment['baseline']]}:
                raise ValueError('metadata mismatch')
            w,d,l=audit(data,fragment,plan,binary_hash)
            binary_hash=data['sha256_a']
            row=by_pair[(fragment['profile'],fragment['baseline'])]
            row['wins']+=w; row['draws']+=d; row['losses']+=l
            row['colors']+=sum(g['a_black'] for g in data['details'])
            row['fragments'].append(dict(fragment,path=path.name,sha256=digest(path)))
        archive_dir=Path(args.input_dir)/f'played-archive-{shard}'
        manifest=json.loads((archive_dir/'manifest.json').read_text())
        if (manifest['games']!=sum(f['games'] for f in lane) or
            manifest['phase_missing_plies']!=0 or
            manifest['requested_ref_a']!=args.engine_ref or
            manifest['requested_ref_b']!=args.engine_ref or
            digest(archive_dir/manifest['archive'])!=manifest['archive_sha256']):
            raise ValueError('played-move archive mismatch')
        source_hashes={digest(Path(args.input_dir)/filename(f)) for f in lane}
        if {x['source_id'] for x in manifest['sources']}!=source_hashes:
            raise ValueError('played-move archive sources do not match raw files')
        archives.append({'shard':shard,'games':manifest['games'],
            'plies':manifest['plies'],'sha256':manifest['archive_sha256'],
            'manifest_sha256':digest(archive_dir/'manifest.json')})
    if {p.name for p in Path(args.input_dir).glob('raw-*.json')}!=expected_files:
        raise ValueError('missing/extra raw files')
    records=[]
    for (profile,baseline),row in sorted(by_pair.items()):
        if sum(row[k] for k in ['wins','draws','losses'])!=plan['games_per_baseline'] or row['colors']*2!=plan['games_per_baseline']:
            raise ValueError('total comparison count/color mismatch')
        score,ci=interval(row['wins'],row['draws'],row['losses'])
        records.append(dict(profile=profile,baseline=baseline,score=score,approx95=ci,**row))
    ranked=[]
    for index in plan['profiles']:
        r={b:next(x for x in records if x['profile']==index and x['baseline']==b) for b in ['M','Q14']}
        ranked.append(dict(profile=index,name=registry[index]['name'],family=registry[index]['family'],
            min_score=min(x['score'] for x in r.values()),mean_score=sum(x['score'] for x in r.values())/2,
            results=r,settings=registry[index]))
    ranked.sort(key=lambda x:(-x['min_score'],-x['mean_score'],x['profile']))
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    report={'plan':plan,'shards':args.shards,
        'games':len(plan['profiles'])*2*plan['games_per_baseline'],'binary_sha256':binary_hash,
        'registry_sha256':digest(REGISTRY),'engine_ref':args.engine_ref,
        'illegal':0,'settings_raw_verified':True,'knowledge_positions':163,
        'knowledge_sha256':KNOWLEDGE_HASH,'ranking':ranked,'records':records,
        'played_move_archives':archives,
        'interval_note':'Conservative 95% bounded-score interval assumes independent games; not adjusted for selecting many candidates.',
        'warning':'Selection only. Small samples and many candidates; no strength or adoption proof.'}
    (out/'search-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    md=f"# 新配点の組合せ探索 {plan['plan_id']}\n\n{report['games']}局。選択用の結果で、強さ・採用の証明ではない。全原記録の設定・実選択profile・知識163同hash・先後・長考上限・違法0を照合。\n\n"
    md+='|案|系列|対M 勝-分-負/得点率|対Q14 勝-分-負/得点率|低い方|\n|---|---|---|---|---:|\n'
    for x in ranked:
        cell=lambda r:f"{r['wins']}-{r['draws']}-{r['losses']} / {100*r['score']:.1f}%"
        md+=f"|{x['name']}|{x['family']}|{cell(x['results']['M'])}|{cell(x['results']['Q14'])}|{100*x['min_score']:.1f}%|\n"
    (out/'search-summary.md').write_text(md)
    if plan['stage']=='coarse':
        selected=[]; families=defaultdict(int)
        for x in ranked:
            if families[x['family']]<2:
                selected.append(x['profile']); families[x['family']]+=1
            if len(selected)==min(8,len(ranked)): break
        follow=dict(plan,plan_id='round2-followup',stage='followup',profiles=selected,
            games_per_baseline=24,go_command='go movetime 200',adaptive_long_think=True,
            seeds={'M':1915100000,'Q14':1915110000},
            selection_notice='New seeds; still selection data. Next create 20 NEW combinations using observed contributions.')
        (out/'round2-followup.json').write_text(json.dumps(follow,ensure_ascii=False,indent=2)+'\n')
    print(md)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['validate','run','aggregate'])
    parser.add_argument('--plan',required=True)
    parser.add_argument('--shards',type=int,required=True)
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--engine',default='build/search-engine')
    parser.add_argument('--engine-ref',required=True)
    parser.add_argument('--input-dir',default='results')
    parser.add_argument('--output-dir',default='results')
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}',args.engine_ref):
        raise ValueError('immutable engine SHA required')
    plan,registry=load_plan(args.plan); assigned=allocation(plan,args.shards)
    if args.command=='validate':
        print(json.dumps({'plan':args.plan,'profiles':len(plan['profiles']),
            'games':sum(f['games'] for l in assigned for f in l),
            'lane_games':[sum(f['games'] for f in l) for l in assigned]},ensure_ascii=False))
    elif args.command=='run': run_lane(args,plan,registry)
    else: aggregate(args,plan,registry)

if __name__=='__main__': main()
