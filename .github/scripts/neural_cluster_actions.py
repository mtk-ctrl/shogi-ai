#!/usr/bin/env python3
"""Actions transport for neural_cluster. No controller occupies a worker slot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.research import neural_cluster as nc
from tools.research.nnue_release_source import find_source,safely_extract

RELEASE='records-2026-10-01'
SOURCE='selfplay-value-next-generation-39120804144.tgz'
SOURCE_SHA='2bd392425a066c3a1bc88878c21d952c0acf1284638e52918fe89bb7173a760c'


def gh(*args):
    return subprocess.check_output(['gh',*args],text=True)


def api(path):
    return json.loads(gh('api',path))


def download(asset,directory):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+',asset):
        raise ValueError('invalid release asset name')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/asset
    if not target.exists():
        gh('release','download',RELEASE,'--pattern',asset,'--dir',str(directory))
    return target


def available_lanes(requested):
    """Count other running jobs across visible repositories owned by this user.

The current preparation job releases its slot before the matrix starts. Never
cancel another run to obtain capacity. Platform scheduling remains authoritative.
"""
    repository=os.environ['GITHUB_REPOSITORY'];owner=repository.split('/')[0]
    current=int(os.environ['GITHUB_RUN_ID'])
    repos=[];page=1
    while True:
        batch=api(f'users/{owner}/repos?per_page=100&page={page}')
        repos.extend(r['full_name'] for r in batch)
        if len(batch)<100:break
        page+=1
    def count(repo):
        occupied=0
        runs=api(f'repos/{repo}/actions/runs?status=in_progress&per_page=100')['workflow_runs']
        for run in runs:
            if repo==repository and run['id']==current:continue
            jobs=api(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")['jobs']
            occupied+=sum(j['status']=='in_progress' for j in jobs)
        return occupied
    with ThreadPoolExecutor(max_workers=5) as pool:
        occupied=sum(pool.map(count,repos))
    free=max(0,20-occupied)
    if not free:raise RuntimeError('no free runners; other active runs were left running')
    lanes=min(requested,free)
    nc.atomic_json('runner-allocation.json',dict(account_limit=20,other_running_jobs=occupied,
        requested=requested,allocated=lanes,current_run=current,visible_repositories=len(repos)))
    print(json.dumps(nc.read('runner-allocation.json')))
    return lanes


def restore_release(asset,work):
    manifest=nc.read(download(asset,'restored-release'))
    if manifest['schema']!='neural20-checkpoint-v1':raise ValueError('invalid checkpoint manifest')
    with Path('restored.tgz').open('wb') as out:
        for part in manifest['parts']:
            path=download(part['name'],'restored-release')
            if nc.sha(path)!=part['sha256'] or path.stat().st_size!=part['bytes']:
                raise ValueError('checkpoint part checksum mismatch')
            with path.open('rb') as f:shutil.copyfileobj(f,out)
    if nc.sha('restored.tgz')!=manifest['bundle_sha256']:
        raise ValueError('checkpoint bundle checksum mismatch')
    nc.unpack('restored.tgz',work)
    nc.context(work)


def bootstrap():
    envelope=nc.read('research/neural-distributed/REQUEST.json')
    if set(envelope)!={'enabled','parameters','checkpoint'} or type(envelope['enabled']) is not bool:
        raise ValueError('invalid explicit research request')
    if not envelope['enabled']:
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:print('more=false',file=f)
        print('Request disabled; no games or training started')
        return
    request=nc.parameters(envelope['parameters'])
    checkpoint=os.environ.get('CHECKPOINT','') or envelope['checkpoint']
    if checkpoint:
        restore_release(checkpoint,'run')
        _,plan,state=nc.context('run')
        if plan['parameters']!=request:
            raise ValueError('resume changes immutable research budgets')
        if state['status']=='completed':raise ValueError('requested research already completed')
    else:
        source=download(SOURCE,'source-download')
        if nc.sha(source)!=SOURCE_SHA:raise ValueError('source package checksum mismatch')
        safely_extract(source,'source-restored')
        (_,_,directory,_),_=find_source('source-restored')
        subprocess.run([sys.executable,'scripts/build.py','--output','build/shogi-ai'],check=True)
        nc.initialize('run',request,directory,'build/shogi-ai','position-knowledge-v1.tsv',os.environ['GITHUB_SHA'])
    nc.pack('run','out/state.tgz')
    nc.workflow_outputs('run')


def restore_input():
    # A retried reducer first restores its own last uploaded checkpoint.
    bundle=Path('resume/state.tgz')
    if not bundle.exists():bundle=Path('incoming/state.tgz')
    nc.unpack(bundle,'run')


def export_state():
    nc.pack('run','out/state.tgz')
    if Path('run/tasks.json').exists():nc.pack('run','out/workers.tgz',workers=True)
    nc.workflow_outputs('run')


def prepare():
    restore_input()
    work,plan,state=nc.context('run')
    if not (work/'current').exists():
        lanes=available_lanes(plan['parameters']['runners'])
        nc.begin(work,lanes)
    export_state()


def run_worker(lane):
    nc.unpack('incoming/workers.tgz','run')
    if Path('resume/task.tgz').exists():nc.unpack('resume/task.tgz','task')
    try:
        # Only retry transient execution errors, reusing completed pair/search
        # stages. Validation/data errors are not retried or silently discarded.
        for attempt in range(2):
            try:
                nc.worker('run','task',lane)
                break
            except (TimeoutError,RuntimeError,ConnectionError):
                if attempt==1:raise
    finally:
        if Path('task').exists():nc.pack('task','out/task.tgz')


def reduce(stage):
    restore_input()
    try:
        current=nc.read('run/tasks.json')['stage']
        # Reducers may have completed and uploaded state before a later step
        # failed. Reuse that state rather than training or playing again.
        if current==stage:
            for bundle in sorted(Path('downloads').glob('*/task.tgz')):
                lane=int(bundle.parent.name.rsplit('-',1)[1])
                nc.unpack(bundle,Path('results')/f'lane-{lane:02d}')
            # Preserve compact worker provenance and selected MCTS evidence
            # before the temporary transport artifacts can be removed.
            audit=Path('run/current/worker-audit')/stage
            audit.mkdir(parents=True,exist_ok=True)
            for receipt in Path('results').glob('lane-*/receipt.json'):
                shutil.copy2(receipt,audit/(receipt.parent.name+'.json'))
                if stage=='mcts':
                    shutil.copy2(receipt.parent/'mcts-checkpoint.json',
                                 audit/(receipt.parent.name+'-mcts.json'))
            nc.reduce_stage('run','results')
    finally:
        export_state()


def publish():
    """Persist completed generation, split before 256 MiB, re-download/hash."""
    work,plan,state=nc.context('run')
    directory=Path('publication');directory.mkdir(exist_ok=True)
    bundle=directory/'checkpoint.tgz'
    nc.pack(work,bundle,durable=True)
    digest=nc.sha(bundle)
    prefix=f"neural20-{plan['parameters']['cycle_id']}-g{state['next_generation']-1:03d}-{digest[:12]}"
    parts=[]
    with bundle.open('rb') as f:
        index=0
        while True:
            data=f.read(200*1024*1024)
            if not data:break
            path=directory/f'{prefix}.part{index:03d}'
            path.write_bytes(data)
            parts.append(dict(name=path.name,sha256=nc.sha(path),bytes=len(data)))
            index+=1
    manifest=dict(schema='neural20-checkpoint-v1',bundle_sha256=digest,parts=parts,
        source_commit=plan['source_commit'],plan_sha256=state['plan_sha256'],
        next_generation=state['next_generation'],formal_engine_adopted=False)
    path=directory/(prefix+'.json');nc.atomic_json(path,manifest)
    assets=json.loads(gh('release','view',RELEASE,'--json','assets'))['assets']
    names={a['name'] for a in assets}
    for file in [directory/p['name'] for p in parts]+[path]:
        if file.name not in names:
            gh('release','upload',RELEASE,str(file))
    # Verify the actual persisted bytes, including an existing upload on retry.
    verify=Path('publication-readback');verify.mkdir(exist_ok=True)
    for file in [directory/p['name'] for p in parts]+[path]:
        restored=download(file.name,verify)
        if nc.sha(restored)!=nc.sha(file):raise ValueError('release readback mismatch')
    receipt=dict(manifest_asset=path.name,bundle_sha256=digest,verified=True,
        total_bytes=sum(p['bytes'] for p in parts),parts=parts,
        url=f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/releases/download/{RELEASE}/{path.name}")
    nc.atomic_json('publication-receipt.json',receipt)
    return receipt


def finish():
    restore_input()
    try:
        if Path('run/current').exists():nc.finish('run')
        receipt=publish()
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            _,plan,state=nc.context('run')
            last=nc.read(Path('run/history')/f"g{state['next_generation']-1:03d}"/'result.json')
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
                f.write(f"## Neural generation {state['next_generation']}\n\n")
                f.write(f"- Research parent updates: {state['accepted']}\n- Formal adoption: false\n")
                f.write(f"- Study cases: {last['case_count']}; replay rows: {last['replay_rows']}\n")
                f.write(f"- Decision: {last['decision']['reason']}\n")
                f.write(f"- [Verified durable checkpoint]({receipt['url']})\n")
    finally:
        export_state()


def prune(prefix):
    """Remove only this completed generation's redundant transfer artifacts.

    Complete game archives, neural checkpoints, selected research and worker
    receipts have already been published and read back successfully. Keep the
    completed state artifact for the next generation and the publication receipt.
    """
    if not re.fullmatch('neural20-g[0-2]',prefix):raise ValueError('invalid generation prefix')
    if nc.read('publication-receipt.json').get('verified') is not True:
        raise ValueError('cannot prune before verified durable publication')
    repo=os.environ['GITHUB_REPOSITORY'];run=os.environ['GITHUB_RUN_ID']
    artifacts=[];page=1
    while True:
        rows=api(f'repos/{repo}/actions/runs/{run}/artifacts?per_page=100&page={page}')['artifacts']
        artifacts.extend(rows)
        if len(rows)<100:break
        page+=1
    keep={prefix+'-complete-state',prefix+'-publication'}
    removed=[]
    for item in artifacts:
        if item['name'].startswith(prefix+'-') and item['name'] not in keep:
            gh('api','--method','DELETE',f"repos/{repo}/actions/artifacts/{item['id']}")
            removed.append(dict(id=item['id'],name=item['name'],bytes=item['size_in_bytes']))
    nc.atomic_json('pruned-transfers.json',removed)
    print(json.dumps(dict(removed_artifacts=len(removed),bytes=sum(r['bytes'] for r in removed))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('bootstrap','prepare','worker','reduce','finish','prune'))
    p.add_argument('--lane',type=int)
    p.add_argument('--stage')
    p.add_argument('--prefix')
    args=p.parse_args()
    if args.command=='bootstrap':bootstrap()
    elif args.command=='prepare':prepare()
    elif args.command=='worker':run_worker(args.lane)
    elif args.command=='reduce':reduce(args.stage)
    elif args.command=='finish':finish()
    elif args.command=='prune':prune(args.prefix)


if __name__=='__main__':main()
