"""Bounded nine-weight outcome learning from verified, actual own games."""
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
from tools.research.postgame_ranker import BASE,OPTIONS,AXES

def sha(x):return hashlib.sha256(x).hexdigest()

def collect(inputs,parent_options):
    import shogi
    groups=[[],[],[]];seen=set();receipts=[];plies=0
    for folder in map(Path,inputs):
        games=load_archive(folder);manifest=json.loads((folder/'manifest.json').read_text())
        receipts.append(dict(run_id=manifest['run_id'],sha256=manifest['archive_sha256'],bytes=manifest['archive_bytes'],games=len(games)))
        for g in games:
            plies+=len(g.moves);gh=sha(' '.join(g.moves).encode())
            if gh in seen or g.outcome_status=='unresolved':continue
            seen.add(gh)
            if g.metadata['sha256_b']!='2de18d82f89b9fd1e6795ef6905f4a9bb46023771d7651a96b5f5682e1338f36':raise ValueError('unknown own parent')
            if any(g.metadata['options_b'].get(k,b)!=parent_options[k] for k,b in zip(OPTIONS,BASE)):raise ValueError('source parent parameters differ')
            if g.start_sfen!=shogi.STARTING_SFEN:raise ValueError('normal complete selfplay required; partial practice must keep its inherited split')
            winner=g.row['winner'];target=.5 if winner is None else float((winner=='A')==g.row['a_black'])
            board=shogi.Board(g.start_sfen);samples=[]
            for ply,m in enumerate(g.row['moves'],1):
                if m['engine']=='B' and 16<=ply<=len(g.moves)-12:
                    samples.append(dict(game_hash=gh,game_id=g.row['game_id'],run_id=g.run_id,ply=ply,
                        sfen=board.sfen(),actual_move=m['move'],target_black=target,
                        recorded_static=m['search'].get('phase_static_cp_black')))
                board.push_usi(m['move'])
            samples.sort(key=lambda r:sha((gh+':'+str(r['ply'])).encode()))
            h=int(gh[:8],16)%100;groups[0 if h<70 else 1 if h<85 else 2].extend(samples[:8])
    return groups,dict(receipts=receipts,verified_plies=plies,unique_resolved_games=len(seen))

def fit(inputs,binary,output,parent_options=None):
    import numpy as np
    parent_options=parent_options or dict(zip(OPTIONS,BASE))
    if set(parent_options)!=set(OPTIONS) or any(type(v)is not int or not 1<=v<=10000 for v in parent_options.values()):raise ValueError("complete parent parameters required")
    groups,provenance=collect(inputs,parent_options);rows=[r for g in groups for r in g]
    binary=Path(binary).resolve()
    if sha(binary.read_bytes())!='2de18d82f89b9fd1e6795ef6905f4a9bb46023771d7651a96b5f5682e1338f36':raise ValueError('feature binary differs')
    command='usi\n'+''.join('setoption name '+k+' value '+str(v)+'\n' for k,v in parent_options.items())+''.join('position sfen '+r['sfen']+'\neval\n' for r in rows)+'quit\n'
    run=subprocess.run([str(binary)],input=command,text=True,capture_output=True,check=True)
    frames=[l.split()[3:] for l in run.stdout.splitlines() if l.startswith('info string evaluation ')]
    if len(frames)!=len(rows):raise ValueError('static feature count differs')
    kept=[[],[],[]];occupied=set();offset=0
    for split,group in enumerate(groups):
        for r in group:
            tokens=frames[offset];offset+=1
            b={tokens[i]:int(tokens[i+1]) for i in range(0,len(tokens),2)}
            if r['recorded_static'] is not None and b['total']!=r['recorded_static']:raise ValueError('recorded parent static differs')
            key=' '.join(r['sfen'].split()[:3])
            if b['clamp'] or abs(b['total'])>800 or key in occupied:continue
            occupied.add(key);r['features']=b;r['split']=('train','validation','test')[split];kept[split].append(r)
    if any(len(g)<50 for g in kept):raise ValueError('insufficient independent split')
    all_rows=[r for g in kept for r in g];lengths=[len(g) for g in kept];cuts=np.cumsum([0]+lengths)
    x=np.asarray([[r['features'][a]/600 for a in AXES] for r in all_rows])
    offset=np.asarray([r['features']['total']/600 for r in all_rows]);y=np.asarray([r['target_black'] for r in all_rows])
    counts={}
    for r in all_rows:counts[r['game_hash']]=counts.get(r['game_hash'],0)+1
    weights=np.asarray([1/counts[r['game_hash']] for r in all_rows])
    def loss(delta,split):
        sl=slice(cuts[split],cuts[split+1]);z=offset[sl]+x[sl]@delta
        ce=np.logaddexp(0,z)-y[sl]*z
        return float(np.sum(weights[sl]*ce)/np.sum(weights[sl]))
    choices=[];tx=x[:cuts[1]];ty=y[:cuts[1]];tw=weights[:cuts[1]];base=offset[:cuts[1]]
    for penalty in (.001,.01,.1):
        d=np.zeros(9);m=d.copy();v=d.copy()
        for epoch in range(1,501):
            z=np.clip(base+tx@d,-40,40);p=1/(1+np.exp(-z));gradient=tx.T@(tw*(p-ty))/sum(tw)+penalty*d
            m=.9*m+.1*gradient;v=.999*v+.001*gradient*gradient
            d=np.clip(d-.025*(m/(1-.9**epoch))/(np.sqrt(v/(1-.999**epoch))+1e-8),-.25,.25)
        choices.append((loss(d,1),penalty,d))
    _,penalty,d=min(choices,key=lambda t:(t[0],t[1]))
    candidates=[]
    for fraction in (.25,.5,1.):
        values={k:min(math.floor(b*1.25),max(math.ceil(b*.75),int(round(b*(1+fraction*float(v)))))) for k,b,v in zip(OPTIONS,(parent_options[k] for k in OPTIONS),d)}
        candidates.append(dict(fraction=fraction,options=values))
    output.mkdir(parents=True,exist_ok=False)
    report=dict(schema='selfplay-value-v1',provenance=provenance,binary_sha256=sha(binary.read_bytes()),
        samples=dict(zip(('train','validation','test'),lengths)),base_options=parent_options,
        samples_sha256=sha((''.join(json.dumps(r,sort_keys=True)+'\n' for r in all_rows)).encode()),
        split_games={name:len({r['game_hash'] for r in g}) for name,g in zip(('train','validation','test'),kept)},
        selected_l2=penalty,relative_delta=d.tolist(),validation_choices=[dict(l2=p,loss=l) for l,p,_ in choices],
        baseline_loss={s:loss(np.zeros(9),i) for i,s in enumerate(('train','validation','test'))},
        learned_loss={s:loss(d,i) for i,s in enumerate(('train','validation','test'))},candidates=candidates,
        eligible=loss(np.zeros(9),1)-loss(d,1)>=.002,formal_adoption=False)
    (output/'model.json').write_text(json.dumps(report,indent=2)+'\n')
    with (output/'selected-actual-positions.jsonl').open('w') as f:
        for r in all_rows:f.write(json.dumps(r,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',nargs='+',required=True);p.add_argument('--binary',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--parent-options',type=Path);a=p.parse_args()
    fit(a.inputs,a.binary,a.output,json.loads(a.parent_options.read_text()) if a.parent_options else None)
