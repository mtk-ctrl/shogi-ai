#!/usr/bin/env python3
"""Execute the explicitly frozen, one-off practice trial and save its evidence."""
import base64,json,os,re,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(ROOT/'research/self-improvement-20261017'))
from run_postgame_spiral import Backend,api,module
from practice_saved import execute
from tools.research.postgame_practice import dump
from tools.research.postgame_ranker import require,digest
from tools.research.postgame_cases import sha256


def main():
    repo=os.environ['GITHUB_REPOSITORY'];ref=os.environ['PLAN_REF'];cycle=os.environ['CYCLE_ID'];run_id=int(os.environ['GITHUB_RUN_ID'])
    require(repo=='mtk-ctrl/shogi-ai' and cycle=='saved-practice-20261018-01' and re.fullmatch('[0-9a-f]{40}',ref),'fixed practice trial identity')
    require(os.environ.get('GITHUB_RUN_ATTEMPT','1')=='1','practice retry needs saved-output reconciliation, not new games')
    runs=api(f'repos/{repo}/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
    require(not any(r['id']!=run_id and r.get('display_title')=='Spiral '+cycle for r in runs),
            'a practice body already exists; inspect its saved output instead of rerunning')
    # Bind the complete research algorithm, the source adapter and this runner
    # to the immutable request ref before starting even a short game.
    code=sorted(ROOT.glob('tools/research/postgame_*.py'))+[Path(__file__),ROOT/'research/self-improvement-20261017/practice_saved.py']
    hashes={}
    for p in code:
        path=p.relative_to(ROOT).as_posix();remote=api(f'repos/{repo}/contents/{path}?ref={ref}')
        require(base64.b64decode(remote['content'])==p.read_bytes(),'practice code differs from frozen plan ref: '+path)
        hashes[path]=sha256(p.read_bytes())
    backend=Backend(repo,ROOT/'build/practice-transport');release=backend.release()
    name='postgame-practice-20261018-01-'+ref[:12]+'.tgz'
    require(not any(a['name']==name for a in release['assets']),'practice result already published; do not repeat games')
    out=ROOT/'build/practice-trial';out.mkdir(parents=True,exist_ok=False)
    path='research/self-improvement-20261017/practice-plan.json'
    remote=api(f'repos/{repo}/contents/{path}?ref={ref}');frozen=out/'frozen-plan.json';frozen.write_bytes(base64.b64decode(remote['content']))
    verification=execute(out/'practice',ROOT/'build/practice-originals',frozen,True)
    dump(out/'verification.json',verification)
    binding=dict(schema='postgame-practice-publication-v1',request_ref=ref,execution_ref=os.environ['GITHUB_SHA'],
        run_id=run_id,plan_sha256=verification['plan_sha256'],code_sha256=digest(hashes),code_files=hashes,
        purpose='training_practice',strength_measurement=False,formal_adoption=False,
        source_packages=verification['source_packages'],source_binary_shared_by_reference=True,
        original_loader_handshake_retained=False)
    dump(out/'binding.json',binding)
    no_pv=module('practice_publish_checks',ROOT/'.github/scripts/publish_postgame.py').no_pv
    files=[p for p in out.rglob('*') if p.is_file()]
    package=out/name
    with tarfile.open(package,'w:gz') as tar:
        for p in sorted(files):
            if p.suffix=='.json':no_pv(json.loads(p.read_bytes()))
            tar.add(p,arcname=p.relative_to(out).as_posix(),recursive=False)
    require(package.stat().st_size<=256*1024**2,'practice package needs splitting')
    receipt=backend.upload(package);dump(out/'publication.json',receipt)
    print('PRACTICE_PUBLICATION '+json.dumps(receipt),flush=True)

if __name__=='__main__':main()
