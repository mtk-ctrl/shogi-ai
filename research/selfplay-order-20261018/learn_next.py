"""Replay an inherited research parent's new actual games, then learn a proposal."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.research.postgame_cases import load_archive
from tools.research.train_selfplay_order import collect,matrices,train

def run(result_path,source,probe,output):
    result=json.loads(Path(result_path).read_text());source=Path(source)
    if result.get('status')!='research_parent_improved' or not result.get('research_parent_updated') or not result.get('next_selfplay_completed'):
        raise ValueError('no confirmed and inherited research parent')
    parent=result['research_parent'];audit=result['next_selfplay'];request=audit['request']
    if not all(result['confirmation'][k]['lower']>.5 for k in ('raw','unique')):raise ValueError('independent gate did not pass')
    if not (request['ref_a']==request['ref_b']==parent['engine_ref']):raise ValueError('research parent ref differs')
    if any(json.loads(request['options_'+s])!=parent['options'] for s in ('a','b')):raise ValueError('research parent options differ')
    if not min(audit['model_order_calls'].values())>0:raise ValueError('parent model was not used on both sides')
    manifest=json.loads((source/'manifest.json').read_text())
    if not (manifest['requested_ref_a']==manifest['requested_ref_b']==parent['engine_ref']):raise ValueError('saved source ref differs')
    games=load_archive(source)
    if len(games)!=100 or len(games)!=audit['raw']['games']:raise ValueError('new selfplay count differs')
    expected=audit['actual_binary_sha256']['B']
    if any(g.metadata['sha256_b']!=expected for g in games):raise ValueError('new source binary differs')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    binaries=output/'binaries'
    with tarfile.open(source/'engine-binaries.tgz') as tar:tar.extractall(binaries,filter='data')
    if hashlib.sha256((binaries/'build/engine-b').read_bytes()).hexdigest()!=expected:raise ValueError('saved binary bytes differ')
    groups=collect([source],output/'training',[expected])
    train(groups,matrices(groups,probe),output/'training')
    lineage=dict(schema='selfplay-order-next-learning-v1',parent=parent,source_publication=result['next_publication'],
        actual_binary_sha256=expected,games=len(games),plies=sum(len(g.moves) for g in games),
        all_moves_legal=True,all_terminations_verified=True,source_options_verified=True,
        parent_remains_unchanged=True,formal_adoption=False,
        model_sha256=hashlib.sha256((output/'training/model.json').read_bytes()).hexdigest(),
        input_manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),
        feature_probe_sha256=hashlib.sha256(Path(probe).read_bytes()).hexdigest())
    (output/'lineage.json').write_text(json.dumps(lineage,indent=2)+'\n')
    return lineage

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cycle-report',required=True);p.add_argument('--source',required=True)
    p.add_argument('--probe',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(run(a.cycle_report,a.source,a.probe,a.output),indent=2))
