#!/usr/bin/env python3
"""Verify frozen follow-up observations against original saved diagnoses; no engine runs."""
import argparse,json,sys,urllib.request,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from replay_progress import replay
from replay_progress import backend
from knowledge_saved_review import SOURCES
from tools.research.postgame_followup import verify_saved
from tools.research.postgame_ranker import require,digest
from tools.research.postgame_cases import load_archive


def verify(inputs,observations,download=False):
    report=json.loads(Path(observations).read_bytes());seen=[];games=[]
    def use(preparation,diagnosis,parent,generation,_):
        item=report['generations'][generation-1]
        name,expected,size=SOURCES[generation-1]
        require(item['source_package']==dict(name=name,sha256=expected,bytes=size),'follow-up source package differs')
        path=Path(inputs)/name
        if not path.exists():
            require(download,'provide verified source archive or explicitly download')
            with urllib.request.urlopen('https://github.com/mtk-ctrl/shogi-ai/releases/download/records-2026-10-01/'+name,timeout=45) as response:raw=response.read()
            require(len(raw)==size and hashlib.sha256(raw).hexdigest()==expected,'downloaded source differs');path.write_bytes(raw)
        raw=path.read_bytes();require(len(raw)==size and hashlib.sha256(raw).hexdigest()==expected,'source hash/bytes differ')
        dest=Path(inputs)/('verified-source-'+str(generation));dest.mkdir(exist_ok=True);backend.safe_extract(path,dest)
        require(hashlib.sha256((dest/'build/engine-a').read_bytes()).hexdigest()==item['binary_sha256'],'exact source binary differs')
        games.extend(load_archive(dest/'played-archive'))
        verify_saved(preparation,diagnosis,parent,item);seen.extend(item['completed_task_ids'])
    replay(inputs,download,on_preparation=use)
    require(len(seen)==len(set(seen))==report['research_tasks']==8,'saved follow-up did not cover fixed eight tasks')
    require(len(games)==report['source_games']==4 and sum(len(g.moves) for g in games)==report['source_plies']==474,
            'follow-up original game/ply counts differ')
    return dict(schema='postgame-followup-readback-v1',all_saved_decisions_reproduced=True,
                original_sources_reproduced=True,unique_tasks=8,new_engine_runs=0,new_games=0,
                source_result_sha256=digest(report),formal_adoption=False,strength_improvement_demonstrated=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--observations',type=Path,required=True)
    p.add_argument('--download',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=verify(a.inputs,a.observations,a.download);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
