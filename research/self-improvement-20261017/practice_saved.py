#!/usr/bin/env python3
"""One fixed practice trial, or read-only replay of its already saved results."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from replay_progress import replay,backend
from knowledge_saved_review import SOURCES
from tools.research.postgame_cases import load_archive,sha256
from tools.research.postgame_ranker import require,digest
from tools.research.postgame_practice import create_plan,run,prepare_candidates,verify_saved,verify_handoff,dump
SEED=2032101801


def inputs(directory,download=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);records=[];parent=None
    def collect(preparation,diagnosis,context,generation,_):
        nonlocal parent
        require(parent is None or parent==context,'original research parent changed');parent=context
        records.append((preparation,diagnosis))
    replay(directory,download,on_preparation=collect)
    games=[];builds=[]
    for n,(name,expected,size) in enumerate(SOURCES,1):
        path=directory/name
        if not path.exists():
            require(download,'provide original source package or explicitly download')
            with urllib.request.urlopen('https://github.com/mtk-ctrl/shogi-ai/releases/download/records-2026-10-01/'+name,timeout=45) as response:raw=response.read()
            require(len(raw)==size and sha256(raw)==expected,'practice source download differs');path.write_bytes(raw)
        raw=path.read_bytes();require(len(raw)==size and sha256(raw)==expected,'practice source archive differs')
        folder=directory/('practice-source-'+str(n));folder.mkdir(exist_ok=True);backend.safe_extract(path,folder)
        games.extend(load_archive(folder/'played-archive'));builds.append(folder/'build')
    require(len(games)==4 and sum(len(g.moves) for g in games)==474,'fixed original four-game input differs')
    plan=create_plan(records,parent,SEED)
    for build in builds:
        require(sha256((build/'engine-a').read_bytes())==plan['binary_sha256']
                and sha256((build/'position-knowledge-v1.tsv').read_bytes())==parent['knowledge_sha256'],'practice original binary/knowledge differs')
    return plan,games,builds[0],records[-1][0]


def verify(directory,originals,download=False):
    expected,games,build,previous=inputs(originals,download);directory=Path(directory)
    plan=json.loads((directory/'plan.json').read_bytes());require(plan==expected,'saved practice plan differs from original training queue')
    result=json.loads((directory/'result.json').read_bytes())
    audit=verify_saved(plan,result,games,directory)
    audit['handoff']=verify_handoff(plan,result,directory,previous,build/'position-knowledge-v1.tsv')
    audit['source_packages']=[dict(name=n,sha256=h,bytes=s) for n,h,s in SOURCES]
    audit['plan_sha256']=plan['plan_sha256'];audit['result_sha256']=digest(result)
    return audit


def execute(directory,originals,frozen_plan,download=False):
    plan,games,build,previous=inputs(originals,download)
    require(plan==json.loads(Path(frozen_plan).read_bytes()),'practice plan was not frozen before execution')
    binary=build/'engine-a';binary.chmod(0o755)
    report=run(plan,games,binary,build/'position-knowledge-v1.tsv',directory)
    prepare_candidates(plan,report,directory,binary,build/'position-knowledge-v1.tsv',previous)
    audit=verify(directory,originals,False);dump(Path(directory)/'verification.json',audit)
    return audit


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--directory',type=Path)
    p.add_argument('--download',action='store_true');p.add_argument('--plan-only',type=Path);p.add_argument('--frozen-plan',type=Path)
    p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    if a.plan_only:
        plan,*_=inputs(a.originals,a.download);require(not a.plan_only.exists(),'preserve frozen practice plan');dump(a.plan_only,plan)
        print(json.dumps(dict(plan_sha256=plan['plan_sha256'],roots=[r['task']['case']['case_id'] for r in plan['roots']],excluded=plan['excluded'])))
    elif a.verify_only:print(json.dumps(verify(a.directory,a.originals,a.download)))
    else:print(json.dumps(execute(a.directory,a.originals,a.frozen_plan,a.download)))
