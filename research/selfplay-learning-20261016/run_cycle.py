#!/usr/bin/env python3
"""Reproduce one outcome-learning generation from a standard selfplay archive.

Writes a research candidate snapshot, never commits or adopts the candidate.
The existing generic match workflow supplies selfplay and independent matches.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from learn import prepare,train,save

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive-dir',required=True,type=Path)
    p.add_argument('--provenance',required=True,type=Path)
    p.add_argument('--baseline',required=True,type=Path)
    p.add_argument('--output-dir',default='build/selfplay-cycle',type=Path)
    p.add_argument('--build-candidate',action='store_true')
    a=p.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    dataset=out/'samples.jsonl'
    inventory=prepare(a.archive_dir,dataset,a.baseline,a.provenance)
    report=train(dataset,out)
    result={'dataset_manifest':str(dataset.with_suffix('.manifest.json')),
            'training_report':str(out/'training-report.json'),
            'model_sha256':report['model_sha256'],
            'validation_pass':report['validation_pass'],
            'test_improved':report['test_improved'],
            'candidate_built':False,'formal_adoption':False}
    if a.build_candidate and report['validation_pass']:
        shutil.copyfile(out/'selfplay_residual_candidate.h',ROOT/'engine/models/selfplay_residual_candidate.h')
        binary=out/'candidate-selfplay'
        subprocess.run([sys.executable,'scripts/build.py','--output',str(binary)],cwd=ROOT,check=True)
        subprocess.run([sys.executable,'tests/test_selfplay_eval_usi.py',str(a.baseline.resolve()),str(binary),str(out/'model.txt')],cwd=ROOT,check=True)
        subprocess.run([sys.executable,'tests/test_search_usi.py',str(binary),'2','3','embedded'],cwd=ROOT,check=True)
        result.update(candidate_built=True,candidate_binary=str(binary))
    save(out/'cycle-result.json',result)
    print(result,flush=True)

if __name__=='__main__':main()
