#!/usr/bin/env python3
"""Existing research pilot's immutable-cycle knowledge mode; no normal Issue changes."""
import argparse,base64,json,os,re,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_postgame_spiral import Backend,gh,algorithm_hash,api
from tools.research.postgame_knowledge_route import validate_intent,materialize,verify_materialization,audit
from tools.research.postgame_ranker import require
from tools.research.postgame_bridge import dump


def checkpoint(backend):
    pub=json.loads(os.environ['SPIRAL_CHECKPOINT'])
    require(re.fullmatch(r'records-\d{4}-\d{2}-01',pub.get('release',''))
            and re.fullmatch(r'spiral-[A-Za-z0-9-]+-state-\d{6}\.json',pub.get('name','')),
            'not an immutable cycle checkpoint')
    env=json.loads(backend.bytes(pub).read_bytes());req=validate_intent(env)
    plan=env['state']['plan'];ref=env['plan_ref']
    require(re.fullmatch('[0-9a-f]{40}',ref) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9-]{0,63}',plan['cycle_id']),
            'original fixed plan identity differs')
    original=api(f"repos/{backend.repo}/contents/research/postgame-cycles/{plan['cycle_id']}/PLAN.json?ref={ref}")
    require(json.loads(base64.b64decode(original['content']))==plan,'checkpoint differs from committed original plan')
    require(env['state']['plan'].get('algorithm_sha256')==algorithm_hash(),'child learning/gate implementation differs')
    require(env['state']['pending']['operation_id']==os.environ['REQUEST_ID'] and str(req['games'])==os.environ['GAMES']
            and str(req['shards'])==os.environ['SHARDS'],'manual inputs differ from saved intent')
    return env,req


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('plan','materialize','play','aggregate'));args=p.parse_args()
    repo=os.environ['GITHUB_REPOSITORY'];run=int(os.environ['GITHUB_RUN_ID'])
    if args.command in ('plan','materialize'):
        backend=Backend(repo,ROOT/'build/knowledge-downloads');env,req=checkpoint(backend)
        if args.command=='plan':
            pages=json.loads(gh('api','--paginate','--slurp',f'repos/{repo}/actions/workflows/postgame-cycle-pilot.yml/runs?event=workflow_dispatch&per_page=100'))
            matches=[r for page in pages for r in page['workflow_runs'] if r['display_title']=='Postgame '+os.environ['REQUEST_ID'] and r['id']!=run]
            require(not matches,'operation already has a research body; do not repeat')
            q,r=divmod(req['games'],req['shards']);offset=0;include=[]
            for i in range(req['shards']):
                n=q+(i<r);include.append(dict(shard=i,games=n,offset=offset,seed=req['seed']+i*100000));offset+=n
            with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('matrix='+json.dumps(dict(include=include))+'\n')
        else:
            materialize(env,backend.unpack,ROOT/'build/knowledge-match/build')
            with tarfile.open('research-binaries.tgz','w:gz') as tar:tar.add(ROOT/'build/knowledge-match/build',arcname='build')
    elif args.command=='play':
        build=ROOT/'build';provenance=json.loads((build/'provenance.json').read_bytes());req=provenance['request'];verify_materialization(build,provenance,req)
        shard=int(os.environ['SHARD']);q,r=divmod(req['games'],req['shards'])
        require(int(os.environ['LANE_GAMES'])==q+(shard<r) and int(os.environ['GAME_OFFSET'])==q*shard+min(shard,r)
                and int(os.environ['LANE_SEED'])==req['seed']+shard*100000,'lane differs from frozen distribution')
        for side in ('a','b'):(build/('engine-'+side)).chmod(0o755)
        subprocess.run([sys.executable,str(ROOT/'benchmarks/arena.py'),'--engine-a','build/engine-a','--engine-b','build/engine-b',
                        '--options-a',req['options_a'],'--options-b',req['options_b'],'--games',os.environ['LANE_GAMES'],
                        '--game-offset',os.environ['GAME_OFFSET'],'--seed',os.environ['LANE_SEED'],'--max-plies','300',
                        '--go-command','go movetime 200','--output','results/shard-'+str(shard)+'.json'],check=True)
    else:
        req=json.loads((ROOT/'build/match-request.json').read_bytes())
        result=audit(ROOT/'build',ROOT/'results',req,run,ROOT/'research-audit')
        dump(ROOT/'research-audit/aggregate.json',result)
        print(json.dumps(result))

if __name__=='__main__':main()
