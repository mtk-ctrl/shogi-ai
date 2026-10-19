"""Separate executed mask-6 evaluation from an early root-observation bug."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.research.postgame_cases import load_archive
from tools.research.train_structured_value import PARENT

def evaluations(binary,rows):
    options=dict(PARENT,StructuredEval=True,StructuredScale=50)
    command='usi\n'+''.join('setoption name '+k+' value '+('true' if v is True else str(v))+'\n' for k,v in options.items())
    command+=''.join('position sfen '+r['sfen']+'\neval\n' for r in rows)+'quit\n'
    run=subprocess.run([str(Path(binary).resolve())],input=command,text=True,capture_output=True,check=True)
    values=[]
    for line in run.stdout.splitlines():
        if line.startswith('info string evaluation material '):
            tokens=line.split()[3:];values.append({tokens[i]:int(tokens[i+1]) for i in range(0,len(tokens),2)})
    if len(values)!=len(rows):raise ValueError('actual root evaluation count differs')
    return values

def main(old,fixed,probe,source,output):
    import shogi
    import numpy as np
    rows=[]
    for game in load_archive(Path(source)):
        b=shogi.Board(game.start_sfen)
        for m in game.row['moves']:
            if m['engine']=='A' and m['search'].get('phase_static_cp_black') is not None:
                rows.append(dict(game_id=game.row['game_id'],ply=m['ply'],sfen=b.sfen(),recorded=m['search']['phase_static_cp_black']))
            b.push_usi(m['move'])
    observed=evaluations(old,rows);corrected=evaluations(fixed,rows)
    run=subprocess.run([str(Path(probe).resolve()),'--verify-modes'],input=''.join(r['sfen']+'\n' for r in rows),text=True,capture_output=True,check=True)
    frames=[json.loads(s) for s in run.stdout.splitlines()]
    if len(frames)!=len(rows):raise ValueError('feature count differs')
    for row,raw,c,f in zip(rows,observed,corrected,frames):
        if row['recorded']!=raw['total']:raise ValueError('historical observation does not match historical executable')
        expected=f['material']+max(-5000,min(5000,f['positional_raw']+f['learned50']))
        if c['total']!=expected or c['structured']!=f['learned50']:
            raise ValueError('fixed root value differs from the actual indexed search evaluator')
    spec=importlib.util.spec_from_file_location('preflight',Path(__file__).with_name('preflight.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    selected=rows[::max(1,len(rows)//8)][:8];searches=[]
    for row in selected:
        a=helper.search(old,row['sfen'],50,depth=2);b=helper.search(fixed,row['sfen'],50,depth=2)
        if any(a.get(k)!=b.get(k) for k in ('move','score_cp','score_mate','nodes','structured_eval_calls')):
            raise ValueError('recording fix changed configured mask-6 search')
        searches.append(dict(game_id=row['game_id'],ply=row['ply'],before=a,after=b))
    delta=[c['total']-f['base'] for c,f in zip(corrected,frames)]
    result=dict(run_id=39195895351,positions=len(rows),historical_raw_observations_reproduced=True,
        attack_map_modes_checked_per_position=8,corrected_static_matches_indexed_search=True,
        configured_search_mask=6,configured_fixed_depth_search_unchanged=True,search_checks=searches,
        raw_static_values_affected=sum(a['total']!=b['total'] for a,b in zip(observed,corrected)),
        nonzero_actual_position_corrections=sum(d!=0 for d in delta),
        mean_abs_correction_cp=float(np.mean(np.abs(delta))),p95_abs_correction_cp=float(np.percentile(np.abs(delta),95)),
        min_correction_cp=min(delta),max_correction_cp=max(delta),
        original_binary_sha256=hashlib.sha256(Path(old).read_bytes()).hexdigest(),
        fixed_binary_sha256=hashlib.sha256(Path(fixed).read_bytes()).hexdigest(),
        note='Original played moves, searched scores and results are retained. Only the root static observation used a buggy non-indexed scan. Training targets use actual searched scores and outcomes, not that static observation.')
    Path(output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='search_checks'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('old','fixed','probe','source','output'):p.add_argument('--'+name,required=True)
    main(**vars(p.parse_args()))
