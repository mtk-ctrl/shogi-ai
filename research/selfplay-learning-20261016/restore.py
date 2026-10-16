#!/usr/bin/env python3
"""Restore one successful standard selfplay run and verify actual build identity."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

def gh(*args):return subprocess.check_output(['gh',*args],text=True)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=int)
    p.add_argument('--source-ref',required=True);p.add_argument('--repository',required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.repository!='mtk-ctrl/shogi-ai' or not re.fullmatch('[0-9a-f]{40}',a.source_ref) or a.run<=0:
        raise ValueError('require fixed source and repository')
    info=json.loads(gh('run','view',str(a.run),'--repo',a.repository,'--json','conclusion,status'))
    if info!={'conclusion':'success','status':'completed'}:raise ValueError('source run not successful')
    out=a.output.resolve();downloads=out/'downloads';downloads.mkdir(parents=True,exist_ok=True)
    subprocess.run(['gh','run','download',str(a.run),'--repo',a.repository,'--dir',str(downloads)],check=True)
    (out/'shards').mkdir(exist_ok=True)
    for path in downloads.rglob('shard-*.json'):shutil.copyfile(path,out/'shards'/path.name)
    for name in ('aggregate.json','manifest.json','played-games.jsonl.gz','engine-binaries.tgz'):
        matches=list(downloads.rglob(name))
        if len(matches)!=1:raise ValueError('missing or ambiguous original: '+name)
        shutil.copyfile(matches[0],out/name)
    with tarfile.open(out/'engine-binaries.tgz') as t:t.extractall(out/'binaries',filter='data')
    jobs=json.loads(gh('api',f'repos/{a.repository}/actions/runs/{a.run}/jobs?per_page=100'))['jobs']
    build=[j for j in jobs if j['name']=='build' and j['conclusion']=='success']
    if len(build)!=1:raise ValueError('ambiguous source build')
    log=gh('api',f"repos/{a.repository}/actions/jobs/{build[0]['id']}/logs")
    if len(re.findall(r'git checkout --progress --force '+a.source_ref,log))<2:
        raise ValueError('both actual source checkouts not proven')
    proof={'run_id':a.run,'job_id':build[0]['id'],'observed_ref_a':a.source_ref,'observed_ref_b':a.source_ref}
    for side in ('a','b'):
        binary=out/'binaries/build'/('engine-'+side)
        expected=re.findall(r'([a-f0-9]{64})  build/engine-'+side,log)
        if len(expected)!=1 or sha(binary)!=expected[0]:raise ValueError('download/build binary hash mismatch')
        proof['binary_sha256_'+side]=expected[0]
        section=out/('text-'+side)
        subprocess.run(['objcopy','--dump-section','.text='+str(section),str(binary)],check=True)
        proof['executable_text_sha256_'+side]=sha(section)
    proof['executable_text_equal']=proof['executable_text_sha256_a']==proof['executable_text_sha256_b']
    if not proof['executable_text_equal']:raise ValueError('executable code differs despite equal source')
    proof['log_evidence']=[s for s in log.splitlines() if s.endswith(a.source_ref) or re.search(r'[a-f0-9]{64}  build/engine-[ab]',s)]
    (out/'build-provenance.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
