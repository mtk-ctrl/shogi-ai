#!/usr/bin/env python3
"""One frozen coverage experiment through the existing practice-only entry."""
import base64
import json
import os
from pathlib import Path
import re
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_postgame_spiral import Backend,api,module
from tools.research import postgame_curriculum as curriculum
from tools.research.postgame_cases import load_archive,sha256
from tools.research.postgame_practice import dump
from tools.research.postgame_ranker import digest,require


def inputs(spec,unpack):
    require(spec['schema']=='postgame-curriculum-trial-v1' and spec['policy']==curriculum.POLICY,
            'unsupported curriculum trial policy')
    folders=[unpack(p) for p in spec['source_publications']]
    games=[g for f in folders for g in load_archive(f/'played-archive')]
    require(len({(g.run_id,g.row['game_id']) for g in games})==len(games),'duplicate curriculum source')
    previous=json.loads((unpack(spec['preparation_publication'])/'preparation.json').read_bytes())
    require(not previous['examples'],'old fitted features require explicit reanalysis before reuse')
    require(previous['example_bank']['parent_context']==spec['parent'],'curriculum source parent differs')
    binary_hash=previous['progress']['analysis']['analyzer_binary_sha256']
    for f in folders:
        require(sha256((f/'build/engine-a').read_bytes())==binary_hash
                and sha256((f/'build/position-knowledge-v1.tsv').read_bytes())==spec['parent']['knowledge_sha256'],
                'curriculum source binary/knowledge differs')
    completed=set()
    for pub in spec['practice_publications']:
        plan=json.loads((unpack(pub)/'practice/plan.json').read_bytes())
        require(plan['parent']==spec['parent'],'completed practice parent differs')
        completed.update(r['task']['case']['history_key'] for r in plan['roots'])
    plan=curriculum.build_plan(games,previous,spec['parent'],binary_hash,completed,spec['seed'])
    registry,_=curriculum.protected_registry(games,previous)
    require(digest(registry)==plan['split_registry_sha256'],'curriculum registry differs')
    return plan,games,previous,registry,folders[0]/'build'


def main():
    repo=os.environ['GITHUB_REPOSITORY'];ref=os.environ['PLAN_REF'];cycle=os.environ['CYCLE_ID'];run_id=int(os.environ['GITHUB_RUN_ID'])
    require(repo=='mtk-ctrl/shogi-ai' and cycle=='diverse-practice-20261018-01'
            and re.fullmatch('[0-9a-f]{40}',ref),'fixed curriculum trial identity')
    require(os.environ.get('GITHUB_RUN_ATTEMPT','1')=='1','reconcile curriculum output; never retry games automatically')
    runs=api(f'repos/{repo}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    require(not any(r['id']!=run_id and r.get('display_title')=='Spiral '+cycle for r in runs),
            'curriculum body already exists; inspect its output')
    paths=sorted(ROOT.glob('tools/research/postgame_*.py'))+[Path(__file__),ROOT/'.github/scripts/run_postgame_practice.py',
        ROOT/'.github/workflows/postgame-spiral.yml']
    hashes={}
    for p in paths:
        path=p.relative_to(ROOT).as_posix();remote=api(f'repos/{repo}/contents/{path}?ref={ref}')
        require(base64.b64decode(remote['content'])==p.read_bytes(),'curriculum code differs from frozen ref: '+path)
        hashes[path]=sha256(p.read_bytes())
    raw=api(f'repos/{repo}/contents/research/postgame-cycles/{cycle}/PLAN.json?ref={ref}')
    spec=json.loads(base64.b64decode(raw['content']));require(spec['cycle_id']==cycle,'curriculum plan ID differs')
    backend=Backend(repo,ROOT/'build/curriculum-transport')
    name='postgame-'+cycle+'-'+ref[:12]+'.tgz'
    require(not any(a['name']==name for a in backend.release()['assets']),'curriculum already published')
    plan,games,previous,registry,build=inputs(spec,backend.unpack)
    require(plan==spec['selection_plan'],'curriculum selection was not frozen before execution')
    out=ROOT/'build/practice-trial';out.mkdir(parents=True,exist_ok=False)
    dump(out/'frozen-plan.json',spec)
    dump(out/'binding.json',dict(schema='postgame-curriculum-publication-v1',run_id=run_id,request_ref=ref,
        execution_ref=os.environ['GITHUB_SHA'],code_sha256=digest(hashes),code_files=hashes,formal_adoption=False))
    binary=build/'engine-a';binary.chmod(0o755)
    report=curriculum.run(plan,games,previous,registry,binary,build/'position-knowledge-v1.tsv',out/'practice')
    dump(out/'verification.json',report)
    files=[p for p in out.rglob('*') if p.is_file()]
    no_pv=module('curriculum_publish_checks',ROOT/'.github/scripts/publish_postgame.py').no_pv
    package=out/name
    with tarfile.open(package,'w:gz') as tar:
        for p in sorted(files):
            if p.suffix=='.json':no_pv(json.loads(p.read_bytes()))
            tar.add(p,arcname=p.relative_to(out).as_posix(),recursive=False)
    require(package.stat().st_size<=256*1024**2,'curriculum package needs splitting')
    receipt=backend.upload(package)
    downloaded=backend.unpack(receipt)
    require(json.loads((downloaded/'frozen-plan.json').read_bytes())==spec,'published curriculum frozen plan differs')
    readback=curriculum.verify_saved(plan,games,previous,registry,build/'position-knowledge-v1.tsv',downloaded/'practice')
    require(readback==report==json.loads((downloaded/'verification.json').read_bytes()),'curriculum publication replay differs')
    dump(out/'readback.json',readback);dump(out/'publication.json',receipt)
    print('CURRICULUM_PUBLICATION '+json.dumps(dict(publication=receipt,verification=report)),flush=True)


if __name__=='__main__':main()
