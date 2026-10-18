"""Read a confirmed cycle's saved next generation; never launch games here."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from run_postgame_spiral import Backend

def main():
    if os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1':raise ValueError('reconcile saved output instead of repeating learning')
    ref=os.environ['PLAN_REF']
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=ref:raise ValueError('frozen learning checkout differs')
    out=ROOT/'build/order-next-learning';backend=Backend(os.environ['GITHUB_REPOSITORY'],out/'transport')
    publication=json.loads(os.environ['SOURCE_PUBLICATION'])
    previous=backend.unpack(publication);result=json.loads((previous/'result.json').read_text())
    if result.get('status')!='research_parent_improved':raise ValueError('previous cycle did not confirm improvement')
    source=backend.unpack(result['next_publication'])
    subprocess.run(['python3','scripts/build.py','--selfplay-order-probe','--output','build/next-feature-probe'],check=True)
    spec=importlib.util.spec_from_file_location('next_order_learning',ROOT/'research/selfplay-order-20261018/learn_next.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    lineage=module.run(previous/'result.json',source,ROOT/'build/next-feature-probe',out/'learned')
    lineage.update(execution_ref=ref,previous_publication=publication)
    (out/'learned/lineage.json').write_text(json.dumps(lineage,indent=2)+'\n')
    name='selfplay-order-next-learning-'+str(backend.run_id)+'.tgz';package=out/name
    with tarfile.open(package,'w:gz') as tar:
        for name in ('training/model.json','training/inputs.json','training/selfplay_order_weights.h','lineage.json'):
            tar.add(out/'learned'/name,arcname=name,recursive=False)
    receipt=backend.upload(package);readback=backend.unpack(receipt)
    if (readback/'training/model.json').read_bytes()!=(out/'learned/training/model.json').read_bytes():raise ValueError('learned model readback differs')
    (out/'publication.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('ORDER_NEXT_LEARNING_PUBLICATION '+json.dumps(dict(publication=receipt,lineage=lineage)),flush=True)

if __name__=='__main__':main()
