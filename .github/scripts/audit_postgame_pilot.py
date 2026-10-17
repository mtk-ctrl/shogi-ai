"""Replay the fixed postgame screen and preserve actual played moves/binaries."""
from collections import Counter
import hashlib
import gzip
import math
import shogi
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.records.archive_played_moves import archive
from tools.research.postgame_cases import load_archive, verify_game
PARENT='efcfa0f80d218c3dbcc3162f5bee3366f6a835cf'
CANDIDATE='5a1997043f275d09099c4be67110ed96e2c80c88'
K0='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'
K1='afa3fe1248070bc9d2ebc566479da29ace7d4463492a28b8b31a67e2dcf9cacd'
REFERENCE_ASSETS=[{'name': 'selfplay-audit-38947455452.tgz', 'sha256': 'ad2e3b2413f0ba2bff553cc2a38089b8d36a5cc752b0f1068a2317643d7d5b03', 'bytes': 6032950}, {'name': 'selfplay-audit-38947742788.tgz', 'sha256': 'a680b884e1b17abb6231a39457c718d73b9f56448adfd9216efde9b060a0ec3b', 'bytes': 5983542}, {'name': 'selfplay-audit-38948491634.tgz', 'sha256': 'bbebce04baea7a1aeafb96f709f7f2772b91eccaa507b9a58821c7a1fd683965', 'bytes': 5992255}, {'name': 'selfplay-audit-38950067410.tgz', 'sha256': 'ad8e1ce5f873ebe34107ef45d9ebe48b6e95bcd250f7df6279eca015c38ec87f', 'bytes': 6716687}, {'name': 'selfplay-source-38853046638.tgz', 'sha256': '8069ececf0ce979768e0c093165b2b83dc7b9371aa7d237fb20e8cdf148cc740', 'bytes': 12380711}]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def gh(*args):return subprocess.check_output(['gh',*map(str,args)],text=True)
def sanitized_job_log(repo,job_id):
    # Never render terminal controls or disable the CLI display protection.
    class PublicRedirect(HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if urlparse(newurl).scheme!='https':raise ValueError('non-HTTPS log redirect')
            redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
            if urlparse(newurl).hostname!='api.github.com':redirected.remove_header('Authorization')
            return redirected
    request=Request(f'https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with build_opener(PublicRedirect()).open(request,timeout=45) as response:raw=response.read()
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',raw.decode('utf-8','replace'))

def options(side):
    return dict(SearchResearchMask=23,SearchEfficiencyMask=8,SearchReuseMask=6,SearchNextMask=4,SearchProbeMask=7,SearchThreads=2,RiskVerify=True,USI_Ponder=True,OpeningRandomNonLance=True,AdaptiveLongThink=True,PositionKnowledge=True,PositionKnowledgeFile='build/k1.tsv' if side=='A' else 'build/k0.tsv')
def validate_shard(row,number,binary_sha,total_games=100,shards=20):
    q,r=divmod(total_games,shards);count=q+(number<r);offset=q*number+min(number,r)
    seed=2031101801 if total_games==100 else 2031102801
    require(row['games']==count and len(row['details'])==count,'shard games')
    require(row['game_offset']==offset and row['seed']==seed+number*100000,'shard offset/seed')
    require(row['go_command']=='go movetime 200' and row['max_plies']==300 and row['illegal_games']==0,'match conditions')
    require(row['sha256_a']==row['sha256_b']==binary_sha,'binary hash mismatch')
    for side,digest,count in [('A',K1,165),('B',K0,163)]:
        require(row['options_'+side.lower()]==options(side),'USI options')
        k=row['position_knowledge'][side]
        require(k.get('enabled') and k.get('available') and k['sha256']==digest and k['positions']==count,'knowledge identity')
    for i,g in enumerate(row['details']):
        require(g['a_black']==((offset+i)%2==0),'color assignment')
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

def trajectory(start,moves):
    return hashlib.sha256((' '.join(start.split()[:3])+'\n'+' '.join(moves)).encode()).hexdigest()
def subset_result(rows):
    n=len(rows);a=sum(r['winner']=='A' for r in rows);b=sum(r['winner']=='B' for r in rows);d=n-a-b
    p=(a+.5*d)/n if n else None;se=math.sqrt(p*(1-p)/n) if n else None
    return dict(games=n,wins_a=a,wins_b=b,draws=d,score_a=p,approx_95pct=[max(0,p-1.96*se),min(1,p+1.96*se)] if n else None)
def references(out,repo,include_screen=False):
    corpus=set();source=set();screen=set();receipts=[]
    assets=REFERENCE_ASSETS+([{'name':'postgame-screen-39005539549.tgz','sha256':'d7571d8dd991e1d05963a512310d7622d20c26308c6086d894cb86c42bf19665','bytes':6001373}] if include_screen else [])
    for asset in assets:
        dest=out/asset['name'].removesuffix('.tgz');dest.mkdir()
        subprocess.run(['gh','release','download','records-2026-10-01','--repo',repo,'--pattern',asset['name'],'--dir',str(dest)],check=True)
        package=dest/asset['name'];require(sha(package)==asset['sha256'] and package.stat().st_size==asset['bytes'],'reference package hash/bytes')
        with tarfile.open(package) as tar:
            names=tar.getnames();archives=[n for n in names if Path(n).name=='played-games.jsonl.gz'];require(len(archives)==1,'reference original archive')
            lines=gzip.decompress(tar.extractfile(archives[0]).read()).splitlines()
        target=corpus if asset['name'].startswith('selfplay-source') else screen if asset['name'].startswith('postgame-screen') else source
        for line in lines:
            g=json.loads(line);target.add(trajectory(g.get('start_sfen') or shogi.STARTING_SFEN,[m['move'] for m in g['moves']]))
        receipts.append(dict(asset,verified=True,games=len(lines)))
    return corpus,source,screen,receipts

def audit(run_id,out,repo):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    info=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}'))
    require(info['status']=='completed' and info['conclusion']=='success','unfinished/failed match')
    identities={'Postgame postgame-g1-screen-20261017':100,'Postgame postgame-g1-confirm-20261017':200}
    require(info['event']=='workflow_dispatch' and info['display_title'] in identities,'operation identity')
    total_games=identities[info['display_title']]
    download=out/'downloads'
    subprocess.run(['gh','run','download',str(run_id),'--repo',repo,'--dir',str(download)],check=True)
    originals=list(download.rglob('binaries.tgz'));require(len(originals)==1,'binary artifact count')
    with tarfile.open(originals[0]) as t:t.extractall(out/'binaries',filter='data')
    build=out/'binaries/build';binary=sha(build/'engine-a')
    require(binary==sha(build/'engine-b') and sha(build/'k0.tsv')==K0 and sha(build/'k1.tsv')==K1,'preserved assets')
    rows=sorted(download.rglob('shard-*.json'));require(1<=len(rows)<=20,'missing/extra shard')
    numbers=[]
    for p in rows:
        number=int(p.stem.split('-')[-1]);numbers.append(number)
        validate_shard(json.loads(p.read_text()),number,binary,total_games,len(rows))
    require(sorted(numbers)==list(range(len(rows))),'duplicate shard numbers')
    dest=out/'played-archive';archive(rows,dest,run_id,PARENT+'+k1',PARENT+'+k0')
    games=load_archive(dest);require(len(games)==total_games,'verified games')
    jobs=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100'))['jobs']
    builds=[j for j in jobs if j['name']=='build' and j['conclusion']=='success'];require(len(builds)==1,'build proof')
    log=sanitized_job_log(repo,builds[0]['id'])
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
        signature=trajectory(g.start_sfen,g.moves)
        trajectories.append({'game_id':g.row['game_id'],'sha256':signature,'winner':g.row['winner'],'a_black':g.row['a_black']})
        wins[g.row['winner']]+=1;colors[g.row['a_black']]+=1
        for move in g.row['moves']:
            s=move['search']
            if s.get('research_id','').startswith('postgame-'):research[move.get('engine','unknown')]+=1
            if s.get('long_think_used'):long[move.get('engine','unknown')]+=1
    require(colors[True]==colors[False]==total_games//2,'global color balance')
    observed={}
    for side in ('A','B'):
        moves=[m for g in games for m in g.row['moves'] if m.get('engine')==side]
        observed[side]={'moves':len(moves),'depth_recorded_moves':sum('depth' in m['search'] for m in moves),'knowledge_probes':sum(m['search'].get('knowledge_probes',0) for m in moves),'knowledge_hits':sum(m['search'].get('knowledge_hits',0) for m in moves),'knowledge_promotions':sum(m['search'].get('knowledge_promotions',0) for m in moves),'ponder_hits':sum(json.loads(p.read_text())['ponder'][side]['hits'] for p in rows),'ponder_misses':sum(json.loads(p.read_text())['ponder'][side]['misses'] for p in rows)}
    result={'observed':observed,'schema':'postgame-match-audit-v1','match_run':run_id,'games':total_games,'plies':sum(len(g.moves) for g in games),
            'legal_replay':True,'termination_rules_verified':True,'conditions_verified':True,'binary_sha256':binary,
            'parent_ref':PARENT,'candidate_ref':CANDIDATE,'build_job':builds[0]['id'],'verification_ref':os.environ.get('GITHUB_SHA'),
            'k0_sha256':K0,'k1_sha256':K1,'loader_reproduction':load_proofs,'wins_a':wins['A'],'draws':wins[None],'wins_b':wins['B'],
            'score_a':(wins['A']+.5*wins[None])/total_games,'a_black':colors[True],'a_white':colors[False],
            'candidate_research_uses':dict(research),'long_thinks':dict(long),'trajectory_outcomes':trajectories,
            'internal_trajectory_duplicates':len(trajectories)-len({r['sha256'] for r in trajectories})}
    corpus,source,screen,receipts=references(out,repo,total_games==200)
    result['reference_packages']=receipts
    result['overlap_original_1000']=sum(r['sha256'] in corpus for r in trajectories)
    result['overlap_reanalysis_source_500']=sum(r['sha256'] in source for r in trajectories)
    result['overlap_screen_100']=sum(r['sha256'] in screen for r in trajectories)
    fresh=[r for r in trajectories if r['sha256'] not in corpus|source|screen]
    unique=list({r['sha256']:r for r in fresh}.values())
    result['all_games']=subset_result(trajectories)
    result['excluding_prior_trajectories']=subset_result(fresh)
    result['excluding_prior_and_internal_duplicates']=subset_result(unique)
    result['duplicate_note']='Descriptive sensitivity; prespecified screen selection uses all scheduled screen games. No claim that trajectory filtering removes all dependence.'
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
