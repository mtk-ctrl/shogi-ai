#!/usr/bin/env python3
"""Publish the fixed eight-case follow-up observations after read-only verification."""
import base64,json,os,re,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(ROOT/'research/self-improvement-20261017'))
from run_postgame_spiral import Backend,api
from verify_followup_saved import verify
from tools.research.postgame_cases import sha256
from tools.research.postgame_ranker import require
from tools.research.postgame_bridge import dump


def main():
    ref=os.environ['PLAN_REF'];require(re.fullmatch('[0-9a-f]{40}',ref),'fixed observation ref required')
    require(os.environ['CYCLE_ID']=='saved-followup-20261018-01','fixed bounded follow-up publication identity')
    repo=os.environ['GITHUB_REPOSITORY'];out=ROOT/'build/followup-publication';out.mkdir(parents=True,exist_ok=False)
    hashes={}
    for name in ('followup-observations.json','FOLLOWUP_PLAN.md'):
        row=api(f'repos/{repo}/contents/research/self-improvement-20261017/{name}?ref={ref}')
        raw=base64.b64decode(row['content']);require(len(raw)<4*1024**2,'oversized selected research data')
        (out/name).write_bytes(raw);hashes[name]=sha256(raw)
    result=verify(ROOT/'build/followup-originals',out/'followup-observations.json',True)
    dump(out/'verification.json',result)
    binding=dict(schema='postgame-followup-publication-v1',observation_ref=ref,verification_ref=os.environ['GITHUB_SHA'],
                 source_files=hashes,formal_adoption=False,new_analysis=0,new_games=0)
    dump(out/'binding.json',binding)
    package=out/f'postgame-followup-20261018-01-{ref[:12]}.tgz'
    with tarfile.open(package,'w:gz') as tar:
        for name in (*hashes,'verification.json','binding.json'):tar.add(out/name,arcname=name)
    backend=Backend(repo,ROOT/'build/followup-publication-transport')
    release=backend.release();matches=[a for a in release['assets'] if a['name']==package.name]
    if matches:
        require(len(matches)==1,'duplicate research asset');receipt=backend.receipt(matches[0],backend.tag)
        saved=backend.unpack(receipt)
        require(json.loads((saved/'binding.json').read_bytes())==binding,'existing publication binding differs')
        require((saved/'followup-observations.json').read_bytes()==(out/'followup-observations.json').read_bytes(),
                'existing observations differ; never overwrite')
    else:receipt=backend.upload(package)
    dump(out/'publication.json',receipt);print('FOLLOWUP_PUBLICATION '+json.dumps(receipt),flush=True)

if __name__=='__main__':main()
