#!/usr/bin/env python3
"""Publish actual played archives and learned assets, verify the readback hash."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pack(path,files):
    # Stable metadata makes the original corpus package idempotent.
    with path.open('wb') as f:
        with gzip.GzipFile(filename='',fileobj=f,mode='wb',mtime=0) as zipped:
            with tarfile.open(fileobj=zipped,mode='w') as tar:
                for name,source in sorted(files.items()):
                    data=source.read_bytes();info=tarfile.TarInfo(name)
                    info.size=len(data);info.mode=0o644;info.mtime=0
                    tar.addfile(info,io.BytesIO(data))

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--cycle',type=Path,required=True);p.add_argument('--run',type=int,required=True)
    p.add_argument('--training-run',type=int,required=True);p.add_argument('--repository',required=True)
    p.add_argument('--release',default='records-2026-10-01');a=p.parse_args()
    if a.repository!='mtk-ctrl/shogi-ai' or a.release!='records-2026-10-01':raise ValueError('fixed data destination required')
    out=a.cycle/'publication';out.mkdir(parents=True,exist_ok=True)
    original={n:a.source/n for n in ('aggregate.json','manifest.json','played-games.jsonl.gz','engine-binaries.tgz','build-provenance.json')}
    corpus=out/f'selfplay-source-{a.run}.tgz';pack(corpus,original)
    model_files={n:a.cycle/n for n in ('samples.manifest.json','training-report.json','model.txt','selfplay_residual_candidate.h','cycle-result.json')}
    # A derived learning dataset contains only actual played positions, no PVs.
    samples=a.cycle/'samples.jsonl';compressed=a.cycle/'samples.jsonl.gz'
    with compressed.open('wb') as f:
        with gzip.GzipFile(filename='',fileobj=f,mode='wb',mtime=0) as g:g.write(samples.read_bytes())
    model_files['samples.jsonl.gz']=compressed
    for extra in sorted((a.cycle/'followup').rglob('*')):
        if extra.is_file() and extra.suffix in ('.json','.txt','.h'):
            model_files[str(extra.relative_to(a.cycle))]=extra
    asset=out/f'selfplay-model-{a.run}-{a.training_run}.tgz';pack(asset,model_files)
    receipts=[]
    for path in (corpus,asset):
        if path.stat().st_size>256*1024*1024:raise ValueError('split asset before 256MiB')
        check=out/('readback-'+path.stem);check.mkdir(exist_ok=True)
        command=['gh','release','download',a.release,'--repo',a.repository,'--pattern',path.name,'--dir',str(check)]
        existing=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if existing.returncode:
            # A permissions/network failure must not be mistaken for an absent release.
            metadata=json.loads(subprocess.check_output(['gh','api',f'repos/{a.repository}/releases/tags/{a.release}']))
            if any(x['name']==path.name for x in metadata['assets']):raise RuntimeError('existing asset could not be read')
            subprocess.run(['gh','release','upload',a.release,str(path),'--repo',a.repository],check=True)
            subprocess.run(command,check=True)
        if sha(check/path.name)!=sha(path):raise ValueError('release readback hash mismatch')
        receipts.append({'name':path.name,'sha256':sha(path),'bytes':path.stat().st_size,'readback_verified':True})
    report={'release':a.release,'url':f'https://github.com/{a.repository}/releases/tag/{a.release}',
            'source_run':a.run,'training_run':a.training_run,'assets':receipts,
            'note':'Data release only; no engine or knowledge adoption; raw PVs are not published.'}
    (a.cycle/'publication.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
