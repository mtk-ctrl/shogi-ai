"""Check actual feature/evaluator agreement, symmetry, controls and search cost."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from benchmarks.arena import Engine,merge_info_line
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.train_structured_value import PARENT

def search(binary,sfen,scale=None,depth=None,extra_options=None):
    options=dict(PARENT,SearchResearchMask=23,SearchEfficiencyMask=8,SearchReuseMask=6,
        SearchNextMask=4,SearchProbeMask=7,SearchThreads=1,RiskVerify=True,
        AdaptiveLongThink=False,USI_Ponder=False,OpeningRandomNonLance=False,RandomSeed=2031101801,
        PositionKnowledge=True,PositionKnowledgeFile=str(ROOT/'position-knowledge-v1.tsv'))
    options.update(extra_options or {})
    if scale is not None:options.update(StructuredEval=True,StructuredScale=scale)
    e=Engine(str(Path(binary).resolve()),'check',options)
    try:
        e.send('usinewgame');e.send('position sfen '+sfen)
        start=time.monotonic();e.send('go depth '+str(depth) if depth is not None else 'go movetime 200');info={}
        while True:
            line=e.lines.get(timeout=30)
            if line.startswith('info '):merge_info_line(info,line)
            if line.startswith('bestmove '):
                return dict(move=line.split()[1],elapsed_ms=(time.monotonic()-start)*1000,
                            **{k:info[k] for k in ('depth','nodes','score_cp','score_mate','structured_eval_calls') if k in info})
    finally:e.close()

def rotated(sfen):
    import shogi
    board=shogi.Board(sfen);out=shogi.Board();out.clear()
    for square in shogi.SQUARES:
        p=board.piece_at(square)
        if p:out.set_piece_at(80-square,shogi.Piece(p.piece_type,p.color^1))
    out.pieces_in_hand=[dict(board.pieces_in_hand[1]),dict(board.pieces_in_hand[0])]
    out.turn=board.turn^1;out.move_number=board.move_number
    return out.sfen()

def check(binary,parent,probe,positions,model,output,parent_options=None):
    rows=[json.loads(x) for x in Path(positions).read_text().splitlines()]
    train=[r for r in rows if r['split']=='train']
    chosen=sorted(train,key=lambda r:hashlib.sha256((r['game_hash']+':'+str(r['ply'])).encode()).hexdigest())[:128]
    sample=[v for r in chosen for v in (r['sfen'],rotated(r['sfen']))]
    raw=subprocess.run([str(Path(probe).resolve()),'--verify-modes'],input=''.join(s+'\n' for s in sample),text=True,capture_output=True,check=True)
    frames=[json.loads(s) for s in raw.stdout.splitlines()];m=json.loads(Path(model).read_text())
    weights=m['weights'];parent_weights=m['parent_weights'];max_error=0
    declared_parent=json.loads(Path(parent_options).read_text()) if parent_options else {}
    baseline_options={k:v for k,v in declared_parent.items() if k in PARENT or k in ('StructuredEval','StructuredScale')}
    inherited=m.get('parent_model_sha256') is not None
    if inherited and (baseline_options.get('StructuredEval') is not True
            or baseline_options.get('StructuredScale')!=m['parent_scale']):
        raise ValueError('the inherited fine-grained parent must be enabled in the baseline preflight')
    for i,r in enumerate(chosen):
        a,b=frames[2*i:2*i+2]
        if a['maturity']!=b['maturity'] or a['base']!=-b['base'] or dict(a['features'])!={j:-v for j,v in b['features']}:
            raise ValueError('colour rotation changed evaluation features')
        for scale in (50,100,150):
            dot=sum((parent_weights[j]*100+weights[j]*scale)*v for j,v in a['features'])
            wanted=int(max(-1200*640000,min(1200*640000,dot))/640000)
            if wanted!=a['learned'+str(scale)] or wanted!=-b['learned'+str(scale)]:
                raise ValueError('C++/trained coefficient evaluation differs')
    cases=[]
    for case in tactical_cases():
        values=[search(parent,case['start_sfen'],extra_options=baseline_options)]+[search(binary,case['start_sfen'],s) for s in (50,100,150)]
        cases.append(dict(case_id=case['case_id'],correct=[v['move'].startswith(case['expected_prefix']) for v in values],observations=values))
    by_maturity=sorted(train,key=lambda r:(r['maturity'],r['game_hash'],r['ply']))
    selected=[by_maturity[(len(by_maturity)-1)*i//15] for i in range(16)]
    speeds=[];disabled=[]
    for i,row in enumerate(selected):
        values=[search(parent,row['sfen'],extra_options=baseline_options)]+[search(binary,row['sfen'],s) for s in (50,100,150)]
        speeds.append(dict(game_hash=row['game_hash'],ply=row['ply'],maturity=row['maturity'],observations=values))
        if i<8:
            old=search(parent,row['sfen'],depth=2,extra_options=baseline_options)
            off=search(binary,row['sfen'],scale=0 if inherited else None,depth=2)
            keys=('move','nodes','score_cp','score_mate')
            disabled.append(dict(old=old,disabled=off,exact=all(old.get(k)==off.get(k) for k in keys)))
    depths=[sum(x['observations'][i].get('depth',0) for x in speeds) for i in range(4)]
    ratios=[d/depths[0] for d in depths[1:]]
    passed=[all(x['correct'][0] and x['correct'][i+1] for x in cases) and ratios[i]>=.9 for i in range(3)]
    if any(x['observations'][i+1].get('structured_eval_calls',0)<=0 for x in speeds for i in range(3)):
        raise ValueError('learned evaluator was not used during actual search')
    result=dict(feature_rotation_positions=len(chosen),integer_evaluation_exact=True,controls=cases,
        speed=speeds,depth_sums=depths,depth_ratios=ratios,candidates_passed=passed,
        disabled=disabled,disabled_exact=all(r['exact'] for r in disabled),
        parent_options=baseline_options,parent_model_retained=inherited,
        binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('controls','speed','disabled')},indent=2))
    if not result['disabled_exact']:raise ValueError('disabled engine changed parent search')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',required=True);p.add_argument('--parent',required=True)
    p.add_argument('--probe',required=True);p.add_argument('--positions',required=True);p.add_argument('--model',required=True)
    p.add_argument('--output',required=True);p.add_argument('--parent-options');a=p.parse_args();check(**vars(a))
