"""Learn thousands of contextual evaluation coefficients from actual own play.

No external scores, PVs or choices are teachers. Each real game has equal
total weight. The exact C++ feature extractor supplies training features.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.research.postgame_cases import load_archive

PARENT=dict(EvalSafety=540,EvalPressure=391,EvalActivity=422,EvalDanger=157,
            EvalInfluence=143,EvalPotential=190,EvalCoordination=343,
            EvalHandPotential=59,EvalThreat=22)
DIM=4893
def digest(x):return hashlib.sha256(x).hexdigest()

def collect(inputs):
    import shogi
    groups=[[],[],[]];seen=set();receipts=[];plies=0
    for path in map(Path,inputs):
        manifest=json.loads((path/'manifest.json').read_text())
        receipts.append(dict(run_id=manifest['run_id'],archive_sha256=manifest['archive_sha256'],
                             archive_bytes=manifest['archive_bytes'],games=manifest['games']))
        for game in load_archive(path):
            plies+=len(game.moves);gh=digest(' '.join(game.moves).encode())
            if gh in seen or game.outcome_status=='unresolved':continue
            seen.add(gh)
            for side in ('a','b'):
                if any(game.metadata['options_'+side].get(k)!=v for k,v in PARENT.items()):
                    raise ValueError('both sides must use the declared own research parent')
            winner=game.row['winner'];outcome=.5 if winner is None else float((winner=='A')==game.row['a_black'])
            bucket=int(gh[:8],16)%100;split=0 if bucket<70 else 1 if bucket<85 else 2
            board=shogi.Board(game.start_sfen)
            for ply,move in enumerate(game.row['moves'],1):
                if 8<=ply<=len(game.moves)-8:
                    search=move['search'];cp=search.get('score_cp_stm');soft=None
                    if (search.get('score_status')=='recorded' and cp is not None
                            and search.get('depth',0)>=2 and not search.get('score_lowerbound')
                            and not search.get('score_upperbound') and not search.get('knowledge_hits',0)):
                        black_cp=cp if board.turn==shogi.BLACK else -cp
                        soft=1/(1+math.exp(-max(-20,min(20,black_cp/600))))
                    groups[split].append(dict(game_hash=gh,game_id=game.row['game_id'],
                        run_id=manifest['run_id'],ply=ply,sfen=board.sfen(),outcome=outcome,
                        target=outcome if soft is None else .5*outcome+.5*soft,
                        own_search_target=soft))
                board.push_usi(move['move'])
    return groups,dict(receipts=receipts,verified_plies=plies,unique_resolved_games=len(seen))

def train(inputs,probe,output,parent_model=None,parent_scale=100,excluded_positions=None):
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.optimize import minimize
    groups,provenance=collect(inputs)
    all_rows=[r for g in groups for r in g]
    result=subprocess.run([str(Path(probe).resolve())],input=''.join(r['sfen']+'\n' for r in all_rows),
                          text=True,capture_output=True,check=True)
    frames=[json.loads(x) for x in result.stdout.splitlines()]
    if len(frames)!=len(all_rows):raise ValueError('feature row count differs')
    occupied=set();kept=[[],[],[]];frame_offset=0
    excluded=set(excluded_positions or ())
    for split,group in enumerate(groups):
        for row in group:
            frame=frames[frame_offset];frame_offset+=1
            key=' '.join(row['sfen'].split()[:3])
            if key in occupied or digest(key.encode()) in excluded or frame['clamp'] or abs(frame['base'])>1800:continue
            occupied.add(key);row.update(frame);row['split']=('train','validation','test')[split]
            kept[split].append(row)
    if any(len(g)<200 for g in kept):raise ValueError('too few distinct actual positions in a split')
    rows=[r for g in kept for r in g];lengths=[len(g) for g in kept];cuts=np.cumsum([0]+lengths)
    index=[];values=[];ptr=[0]
    for row in rows:
        for i,v in row['features']:index.append(i);values.append(v/100)
        ptr.append(len(index))
    x=csr_matrix((np.array(values),np.array(index),np.array(ptr)),shape=(len(rows),DIM))
    parent=np.zeros(DIM,dtype=np.int64)
    if parent_model is not None:
        old=json.loads(Path(parent_model).read_text())
        if old['schema']!='structured-own-value-v2' or old['parent_options']!=PARENT or parent_scale not in (50,100,150):
            raise ValueError('incompatible learned parent')
        delta=np.asarray(old['weights'],dtype=np.int64)*parent_scale
        if np.any(delta%100):raise ValueError('parent scale cannot be represented exactly')
        parent=np.asarray(old['parent_weights'],dtype=np.int64)+delta//100
    base=np.array([r['base']/600 for r in rows]);prior=np.asarray(x@parent).ravel()/38400
    y=np.array([r['target'] for r in rows]);outcomes=np.array([r['outcome'] for r in rows])
    counts={}
    for r in rows:counts[r['game_hash']]=counts.get(r['game_hash'],0)+1
    weight=np.array([1/counts[r['game_hash']] for r in rows]);fitted=[]
    def measure(w,split):
        sl=slice(cuts[split],cuts[split+1]);correction=np.clip(prior[sl]+x[sl]@w,-2,2);z=base[sl]+correction
        return dict(positions=int(cuts[split+1]-cuts[split]),
            mixed_loss=float(np.average(np.logaddexp(0,z)-y[sl]*z,weights=weight[sl])),
            outcome_loss=float(np.average(np.logaddexp(0,z)-outcomes[sl]*z,weights=weight[sl])),
            mean_abs_correction_cp=float(np.mean(np.abs(correction)*600)),
            p95_abs_correction_cp=float(np.percentile(np.abs(correction)*600,95)))
    tx=x[:cuts[1]];tb=base[:cuts[1]];ty=y[:cuts[1]];tw=weight[:cuts[1]];tw=tw/sum(tw)
    for penalty in (.0001,.001,.01):
        def objective(w):
            correction=prior[:cuts[1]]+tx@w
            z=np.clip(tb+np.clip(correction,-2,2),-40,40);p=1/(1+np.exp(-z))
            loss=np.sum(tw*(np.logaddexp(0,z)-ty*z))+.5*penalty*np.dot(w,w)
            gradient=np.asarray(tx.T@(tw*(p-ty)*(np.abs(correction)<2))).ravel()+penalty*w
            return loss,gradient
        fit=minimize(objective,np.zeros(DIM),jac=True,method='L-BFGS-B',bounds=[(-.5,.5)]*DIM,
                     options=dict(maxiter=300,ftol=1e-11,gtol=1e-8,maxcor=10))
        q=np.rint(fit.x*600*16).astype(np.int64)*4;deployed=q/(600*64)
        fitted.append((measure(deployed,1)['mixed_loss'],penalty,q,dict(iterations=fit.nit,converged=bool(fit.success))))
    _,penalty,q,optimization=min(fitted,key=lambda z:(z[0],z[1]));w=q/(600*64)
    report=dict(schema='structured-own-value-v2',features=DIM,phase_features=1631,
        feature_families=dict(piece_square=1134,king_distance=252,hand_count=35,attack_defence=126,mobility=84),
        phases=['opening','middle','end'],coefficient_units='cp/64',parent_options=PARENT,
        parent_model_sha256=digest(Path(parent_model).read_bytes()) if parent_model else None,
        parent_scale=parent_scale,parent_weights=parent.tolist(),
        historical_position_exclusions=len(excluded),
        objective='equal-game mixture: 50% actual outcome + 50% recorded own lookahead probability where eligible',
        provenance=provenance,samples=dict(zip(('train','validation','test'),lengths)),
        split_games={name:len({r['game_hash'] for r in group}) for name,group in zip(('train','validation','test'),kept)},
        selected_l2=penalty,optimization=optimization,nonzero_coefficients=int(np.count_nonzero(q)),
        trained_feature_support=int(np.count_nonzero(np.asarray(tx.getnnz(axis=0)))),
        baseline={n:measure(np.zeros(DIM),i) for i,n in enumerate(('train','validation','test'))},
        learned={n:measure(w,i) for i,n in enumerate(('train','validation','test'))},
        candidates=[50,100,150],residual_cap_cp=1200,coefficient_cap_cp=300,
        selection=[dict(l2=p,validation_loss=l) for l,p,_,_ in fitted],weights=q.tolist(),formal_adoption=False)
    report['eligible']=report['baseline']['validation']['mixed_loss']-report['learned']['validation']['mixed_loss']>=.002
    report['samples_sha256']=digest(''.join(json.dumps({k:v for k,v in r.items() if k!='features'},sort_keys=True)+'\n' for r in rows).encode())
    raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();model_sha=digest(raw)
    output.mkdir(parents=True,exist_ok=False);(output/'model.json').write_bytes(raw)
    (output/'structured_value_weights.h').write_text('#pragma once\n#include <array>\nnamespace shogi::strategy {\n'
        'inline constexpr std::array<int,4893> StructuredValueWeights{'+','.join(map(str,q))+'};\n'
        'inline constexpr std::array<int,4893> StructuredParentWeights{'+','.join(map(str,parent))+'};\n'
        'inline constexpr const char* StructuredValueModel="'+model_sha+'";\n'
        'inline constexpr bool StructuredValueReady=true;\n}\n')
    with (output/'actual-positions.jsonl').open('w') as f:
        for r in rows:f.write(json.dumps({k:v for k,v in r.items() if k!='features'},sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('weights','parent_weights')},indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',nargs='+',required=True);p.add_argument('--probe',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--parent-model',type=Path)
    p.add_argument('--parent-scale',type=int,default=100);a=p.parse_args()
    train(a.inputs,a.probe,a.output,a.parent_model,a.parent_scale)
