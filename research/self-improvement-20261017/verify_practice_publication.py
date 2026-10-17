#!/usr/bin/env python3
"""Read a saved practice publication; never replay games or engine searches."""
import argparse,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from practice_saved import verify,backend
from tools.research.postgame_cases import sha256
from tools.research.postgame_ranker import require
from tools.research.postgame_practice import dump


def inspect(receipt,directory,originals):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    require(receipt['readback_verified'] is True and receipt['api_digest_verified'] is True,'practice publication lacks verified receipt')
    require(receipt['url']=='https://github.com/mtk-ctrl/shogi-ai/releases/download/records-2026-10-01/'+receipt['name'],
            'unexpected practice publication URL')
    with urllib.request.urlopen(receipt['url'],timeout=45) as r:raw=r.read()
    require(len(raw)==receipt['bytes'] and sha256(raw)==receipt['sha256'],'retrieved practice package differs')
    package=directory/receipt['name'];package.write_bytes(raw);backend.safe_extract(package,directory/'unpacked')
    result=verify(directory/'unpacked/practice',originals,True)
    require(result==json.loads((directory/'unpacked/verification.json').read_bytes()),'practice saved verification differs')
    binding=json.loads((directory/'unpacked/binding.json').read_bytes())
    require(binding['plan_sha256']==result['plan_sha256'] and binding['purpose']=='training_practice'
            and binding['formal_adoption'] is False and binding['strength_measurement'] is False,'practice publication purpose differs')
    return dict(result,publication_sha256=receipt['sha256'],publication_bytes=receipt['bytes'],publication_retrieved=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,default=ROOT/'research/self-improvement-20261017/practice-publication.json')
    p.add_argument('--directory',type=Path,required=True);p.add_argument('--originals',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not a.receipt.exists():r=dict(status='not_run_no_saved_practice_receipt',new_games=0,new_engine_runs=0)
    else:r=inspect(json.loads(a.receipt.read_bytes()),a.directory,a.originals)
    a.output.parent.mkdir(parents=True,exist_ok=True);dump(a.output,r);print(json.dumps(r))
