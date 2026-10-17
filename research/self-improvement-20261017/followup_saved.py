#!/usr/bin/env python3
"""Execute the frozen training research queue on hash-verified saved binaries."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from replay_progress import replay,backend
from knowledge_saved_review import SOURCES
from tools.research.postgame_followup import run,POLICY_FOLLOWUP
from tools.research.postgame_ranker import require,digest


def review(inputs,output):
    inputs=Path(inputs);output=Path(output);require(not output.exists(),'preserve original follow-up run');output.mkdir(parents=True)
    results=[];completed=[]
    def use(preparation,diagnosis,parent,generation,_):
        name,expected,size=SOURCES[generation-1];path=inputs/name
        raw=path.read_bytes();require(len(raw)==size and hashlib.sha256(raw).hexdigest()==expected,'saved source package differs')
        source=output/('source-'+str(generation));source.mkdir();backend.safe_extract(path,source)
        binary=source/'build/engine-a';binary.chmod(0o755)
        result=run(binary,source/'build/position-knowledge-v1.tsv',preparation,diagnosis,parent,
                   output/('followup-'+str(generation)),completed)
        result['source_package']=dict(name=name,sha256=expected,bytes=size)
        results.append(result);completed.extend(result['completed_task_ids'])
    replay(inputs,False,on_preparation=use)
    require(sum(r['tasks'] for r in results)==8 and len(set(completed))==8,'fixed eight-task input changed; review rather than select other cases')
    report=dict(schema='postgame-followup-saved-v1',policy=POLICY_FOLLOWUP,generations=results,
                source_games=4,source_plies=474,selected_cases=16,research_tasks=8,
                search_probes=sum(r['search_probes'] for r in results),mate_probes=sum(r['mate_probes'] for r in results),
                knowledge_ready_cases=sum(len(r['diagnosis_updates']) for r in results),
                new_games=0,formal_adoption=False,strength_improvement_demonstrated=False,
                limitation='A single bounded follow-up of previously selected training cases; not an independent strength measurement.')
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=review(args.inputs,args.output)
    print(json.dumps({k:v for k,v in r.items() if k!='generations'}))
