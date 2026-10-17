#!/usr/bin/env python3
"""Apply knowledge preparation to existing verified diagnoses, without new games.

Uses the exact archived analyzer binary and K0, not a guessed equivalent build.
The fixed original inputs have no eligible knowledge tasks, so no probes run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from replay_progress import replay,backend
from tools.research.postgame_knowledge import run
from tools.research.postgame_ranker import require

SOURCES=(
    ('spiral-spiral-auto-smoke-20261017-01-initial_source-e8181c0b9aa52b1a-39021709686-a1.tgz',
     '8678dbf172bb5233ffe6841e10a69032d483f01740ef68b8dcf0876edaca0823',5208460),
    ('spiral-spiral-auto-smoke-20261017-01-collect_source-2d6bac99767cdc1a-39021709686-a1.tgz',
     '48c46d92e88fa0604ee796babbfeceb2ad0ce3ca41e7b6289b7fce46117b8e84',5212920),
)


def review(directory,download):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);results=[]
    def use(preparation,diagnosis,parent,generation,_):
        require(preparation['progress']['task_counts'].get('validate_research_knowledge',0)==0,
                'fixed source no longer has zero knowledge tasks; do not claim zero probes')
        name,expected,size=SOURCES[generation-1];archive=directory/name
        if not archive.exists():
            require(download,'source package missing; provide it or explicitly download')
            url='https://github.com/mtk-ctrl/shogi-ai/releases/download/records-2026-10-01/'+name
            with urllib.request.urlopen(url,timeout=45) as response:data=response.read()
            require(len(data)==size and hashlib.sha256(data).hexdigest()==expected,'source download differs')
            archive.write_bytes(data)
        data=archive.read_bytes();require(len(data)==size and hashlib.sha256(data).hexdigest()==expected,'source package differs')
        source=directory/('source-'+str(generation));source.mkdir(exist_ok=True);backend.safe_extract(archive,source)
        # Use each generation's actual binary; do not assume builds are equal.
        binary=source/'build/engine-a';binary.chmod(0o755)
        result=run(binary,source/'build/position-knowledge-v1.tsv',preparation,diagnosis,parent,
                   preparation['learning']['parent_options'],'saved-knowledge-review-g'+str(generation),
                   directory/('knowledge-review-'+str(generation)))
        require(result['status']=='no_effective_candidate' and result['manifest']['accepted']==[],
                'fixed source evidence unexpectedly changed')
        results.append(dict(generation=generation,source_package=dict(name=name,sha256=expected,bytes=size),
                            binary_sha256=result['binary_sha256'],parent=parent,status=result['status'],
                            candidate_positions=result['manifest']['candidate_positions'],
                            rejected=result['manifest']['rejected'],knowledge_tasks=0,engine_probes=0))
    replay(directory,download,on_preparation=use)
    return dict(schema='postgame-knowledge-saved-review-v1',source_cycle='spiral-auto-smoke-20261017-01',
                generations=results,source_games=4,source_plies=474,selected_cases=16,
                scope='Research knowledge preparation on exact saved inputs; original experiments unchanged.',
                new_games=0,new_analysis=0,engine_probes=0,new_knowledge_positions=0,formal_adoption=False,
                strength_improvement_demonstrated=False,
                next_action='Investigate queued missing observations and search stability; do not manufacture knowledge or start comparison games.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--download',action='store_true');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=review(args.directory,args.download)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
