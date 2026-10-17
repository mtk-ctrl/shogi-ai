"""Replay the fixed postgame screen and preserve actual played moves/binaries."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.records.archive_played_moves import archive
from tools.research.postgame_cases import load_archive, verify_game
PARENT='efcfa0f80d218c3dbcc3162f5bee3366f6a835cf'
CANDIDATE='5a1997043f275d09099c4be67110ed96e2c80c88'
K0='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'
K1='afa3fe1248070bc9d2ebc566479da29ace7d4463492a28b8b31a67e2dcf9cacd'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def gh(*args):return subprocess.check_output(['gh',*map(str,args)],text=True)
def options(side):
    return dict(SearchResearchMask=23,SearchEfficiencyMask=8,SearchReuseMask=6,SearchNextMask=4,SearchProbeMask=7,SearchThreads=2,RiskVerify=True,USI_Ponder=True,OpeningRandomNonLance=True,AdaptiveLongThink=True,PositionKnowledge=True,PositionKnowledgeFile='build/k1.tsv' if side=='A' else 'build/k0.tsv')
def validate_shard(row,number,binary_sha):
    require(row['games']==5 and len(row['details'])==5,'shard games')
    require(row['game_offset']==number*5 and row['seed']==2031101801+number*100000,'shard offset/seed')
    require(row['go_command']=='go movetime 200' and row['max_plies']==300 and row['illegal_games']==0,'match conditions')
    require(row['sha256_a']==row['sha256_b']==binary_sha,'binary hash mismatch')
    for side,digest,count in [('A',K1,165),('B',K0,163)]:
        require(row['options_'+side.lower()]==options(side),'USI options')
        k=row['position_knowledge'][side]
        require(k.get('enabled') and k.get('available') and k['sha256']==digest and k['positions']==count,'knowledge identity')
    for i,g in enumerate(row['details']):
        require(g['a_black']==((number*5+i)%2==0),'color assignment')
        records=g['move_records']; require(len(records)==len(g['moves']),'telemetry length')
        require([x['move'] for x in records]==g['moves'],'telemetry move correspondence')
        verify_game(dict(g,moves=records),row)
        long=Counter()
        for move in records:
            s=move['search'];require('phase_maturity' in s,'missing phase observation')
            if s.get('long_think_used'):long[move['engine']]+=1
        require(max(long.values(),default=0)<=10,'long-think budget exceeded')
    counts=Counter(g['winner'] for g in row['details'])
    require((counts['A'],counts['B'],counts[None])==(row['wins_a'],row['wins_b'],row['draws']),'outcome totals')

def audit(run_id,out,repo):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    info=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}'))
    require(info['status']=='completed' and info['conclusion']=='success','unfinished/failed match')
    require(info['event']=='workflow_dispatch' and info['display_title']=='Postgame postgame-g1-screen-20261017','operation identity')
    download=out/'downloads'
    subprocess.run(['gh','run','download',str(run_id),'--repo',repo,'--dir',str(download)],check=True)
    originals=list(download.rglob('binaries.tgz'));require(len(originals)==1,'binary artifact count')
    with tarfile.open(originals[0]) as t:t.extractall(out/'binaries',filter='data')
    build=out/'binaries/build';binary=sha(build/'engine-a')
    require(binary==sha(build/'engine-b') and sha(build/'k0.tsv')==K0 and sha(build/'k1.tsv')==K1,'preserved assets')
    rows=sorted(download.rglob('shard-*.json'));require(len(rows)==20,'missing/extra shard')
    numbers=[]
    for p in rows:
        number=int(p.stem.split('-')[-1]);numbers.append(number)
        validate_shard(json.loads(p.read_text()),number,binary)
    require(sorted(numbers)==list(range(20)),'duplicate shard numbers')
    dest=out/'played-archive';archive(rows,dest,run_id,PARENT+'+k1',PARENT+'+k0')
    games=load_archive(dest);require(len(games)==100,'verified games')
    jobs=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100'))['jobs']
    builds=[j for j in jobs if j['name']=='build' and j['conclusion']=='success'];require(len(builds)==1,'build proof')
    log=gh('api',f"repos/{repo}/actions/jobs/{builds[0]['id']}/logs")
    require(PARENT in log and CANDIDATE in log,'fixed checkout evidence')
    # Reproduce loader handshake using the preserved exact binaries and snapshots.
    load_proofs={}
    executable=build/'engine-a';executable.chmod(0o755)
    for side,name,count in [('A','k1.tsv',165),('B','k0.tsv',163)]:
        commands='usi\nsetoption name PositionKnowledge value true\nsetoption name PositionKnowledgeFile value '+str((build/name).resolve())+'\nisready\nquit\n'
        text=subprocess.check_output([str(executable.resolve())],input=commands,text=True,timeout=20)
        require(f'position_knowledge loaded {count}' in text,'saved binary loader reproduction')
        load_proofs[side]={'positions':count,'reproduced':True,'note':'Replayed exact saved binary and snapshot; original startup handshake is not retained by this arena.'}
    trajectories=[];research=Counter();long=Counter();wins=Counter();colors=Counter();originals_set=set()
    # Only completed full trajectories are compared; prior corpus was already used.
    for g in games:
        signature=hashlib.sha256((g.start_sfen.split(' ')[0]+' '+g.start_sfen.split(' ')[1]+' '+g.start_sfen.split(' ')[2]+'\n'+' '.join(g.moves)).encode()).hexdigest()
        trajectories.append({'game_id':g.row['game_id'],'sha256':signature,'winner':g.row['winner'],'a_black':g.row['a_black']})
        wins[g.row['winner']]+=1;colors[g.row['a_black']]+=1
        for move in g.row['moves']:
            s=move['search']
            if s.get('research_id','').startswith('postgame-'):research[move.get('engine','unknown')]+=1
            if s.get('long_think_used'):long[move.get('engine','unknown')]+=1
    require(colors[True]==colors[False]==50,'global color balance')
    result={'schema':'postgame-match-audit-v1','match_run':run_id,'games':100,'plies':sum(len(g.moves) for g in games),
            'legal_replay':True,'termination_rules_verified':True,'conditions_verified':True,'binary_sha256':binary,
            'parent_ref':PARENT,'candidate_ref':CANDIDATE,'build_job':builds[0]['id'],'verification_ref':os.environ.get('GITHUB_SHA'),
            'k0_sha256':K0,'k1_sha256':K1,'loader_reproduction':load_proofs,'wins_a':wins['A'],'draws':wins[None],'wins_b':wins['B'],
            'score_a':(wins['A']+.5*wins[None])/100,'a_black':colors[True],'a_white':colors[False],
            'candidate_research_uses':dict(research),'long_thinks':dict(long),'trajectory_outcomes':trajectories,
            'internal_trajectory_duplicates':len(trajectories)-len({r['sha256'] for r in trajectories})}
    save(out/'audit.json',result)
    package=out/f'postgame-audit-{run_id}-{os.environ["GITHUB_RUN_ID"]}.tgz'
    with tarfile.open(package,'w:gz') as t:
        t.add(out/'audit.json',arcname='audit.json');t.add(dest,arcname='played-archive');t.add(build,arcname='build')
    tag='records-2026-10-01'
    subprocess.run(['gh','release','upload',tag,str(package),'--repo',repo],check=True)
    check=out/'readback';check.mkdir()
    subprocess.run(['gh','release','download',tag,'--repo',repo,'--pattern',package.name,'--dir',str(check)],check=True)
    require(sha(package)==sha(check/package.name),'Release readback')
    release=json.loads(gh('api',f'repos/{repo}/releases/tags/{tag}'));asset=next(a for a in release['assets'] if a['name']==package.name)
    require(asset['size']==package.stat().st_size and asset.get('digest')=='sha256:'+sha(package),'Release API digest/bytes')
    receipt={'release':tag,'name':package.name,'sha256':sha(package),'bytes':package.stat().st_size,'readback_verified':True,'api_digest_verified':True,'url':asset['browser_download_url']}
    save(out/'publication.json',receipt);result['publication']=receipt
    print('POSTGAME_AUDIT_RESULT '+json.dumps(result,separators=(',',':')))
    return result
