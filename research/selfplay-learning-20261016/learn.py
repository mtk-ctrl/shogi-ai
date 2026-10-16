#!/usr/bin/env python3
"""Own selfplay outcomes -> audited fixed splits -> a bounded CPU residual.

Only actual played positions enter the dataset. No PV or unplayed move teacher.
"""
from __future__ import annotations
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

import numpy as np
import shogi

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

INPUTS = 12
TERMS = ('safety','pressure','activity','danger','influence','potential',
         'coordination','hand_potential','threat')
SEED = 2026101696

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def split_for_shard(index, total):
    if total < 6 or not 0 <= index < total:
        raise ValueError('need at least six distinct source shards')
    train=int(total*.7); validation=max(1,round(total*.15))
    return 'train' if index < train else 'validation' if index < train+validation else 'test'

def validate_game(game):
    # Independent replay; never accept a winner inferred from a static score.
    board=shogi.Board(); keys=[" ".join(board.sfen().split()[:3])];checks=[]
    positions=[]
    for i,row in enumerate(game['moves'],1):
        move=shogi.Move.from_usi(row['move'])
        if move not in board.legal_moves or row['ply']!=i:
            raise ValueError('illegal/inconsistent actual move')
        expected='A' if (board.turn==0)==game['a_black'] else 'B'
        if row['engine']!=expected or row['side_to_move']!=('black' if board.turn==0 else 'white'):
            raise ValueError('wrong mover')
        positions.append(board.sfen())
        board.push(move);checks.append((board.turn^1,board.is_check()))
        keys.append(' '.join(board.sfen().split()[:3]))
    if len(positions)!=game['plies'] or board.sfen()!=game['final_sfen']:
        raise ValueError('wrong final position')
    reason=game['reason'];winner=game['winner']
    if winner not in (None,'A','B'):
        raise ValueError('unknown winner')
    label=lambda c:'A' if (c==0)==game['a_black'] else 'B'
    if reason=='checkmate':
        if not board.is_checkmate() or winner!=label(board.turn^1):
            raise ValueError('unverified checkmate')
    elif reason in ('fourfold_repetition','perpetual_check'):
        occurrences=[i for i,key in enumerate(keys) if key==keys[-1]]
        if len(occurrences)<4: raise ValueError('unverified repetition')
        interval=checks[occurrences[-4]:]
        continuous=[c for c in (0,1) if any(m==c for m,_ in interval)
                    and all(check for m,check in interval if m==c)]
        if reason=='fourfold_repetition':
            if continuous or winner is not None:raise ValueError('wrong repetition outcome')
        elif not continuous or winner!=label(continuous[0]^1):
            raise ValueError('wrong perpetual check outcome')
    elif reason=='no_legal_moves':
        if any(board.legal_moves) or winner!=label(board.turn^1):
            raise ValueError('unverified no-legal-moves')
    elif reason=='resign':
        if winner!=label(board.turn^1):raise ValueError('wrong resign outcome')
    elif reason=='declare_win':
        from benchmarks.arena import can_declare_win
        if not can_declare_win(board) or winner!=label(board.turn):
            raise ValueError('unverified declaration')
    elif reason=='move_limit':
        if winner is not None:raise ValueError('move limit has no outcome teacher')
        return positions,None
    else:
        raise ValueError('unsupported terminal reason: '+reason)
    black_winner=winner==label(0)
    return positions,.5 if winner is None else float(black_winner)

def exclude_cross_split(selected):
    known=set();kept=[];removed=collections.Counter()
    for split in ('train','validation','test'):
        local=set()
        for row in (r for r in selected if r['split']==split):
            key=' '.join(row['sfen'].split()[:3])
            if key in known:removed[split]+=1;continue
            kept.append(row);local.add(key)
        known.update(local)
    return kept,removed

class StaticFeatures:
    def __init__(self, engine):
        self.p=subprocess.Popen([str(Path(engine).resolve())],stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,text=True,bufsize=1)
        self.q=queue.Queue()
        def read():
            for line in self.p.stdout:self.q.put(line.rstrip())
            self.q.put(None)
        threading.Thread(target=read,daemon=True).start()
        self.send('usi');self.wait('usiok')
    def send(self,s):
        self.p.stdin.write(s+'\n');self.p.stdin.flush()
    def wait(self,prefix):
        while True:
            line=self.q.get(timeout=30)
            if line is None:raise RuntimeError('static engine exited')
            if line.startswith(prefix):return line
    def score(self,sfen):
        self.send('position sfen '+sfen);self.send('eval')
        words=self.wait('info string evaluation ').split()[3:]
        values={k:int(v) for k,v in zip(words[::2],words[1::2])}
        x=[values['material_term']/3000]+[values[k]/1000 for k in TERMS]
        x += [values['clamp']/1000,1 if sfen.split()[1]=='b' else -1]
        return np.clip(x,-4,4).tolist(),values['total']
    def close(self):
        try:self.send('quit');self.p.wait(timeout=5)
        except Exception:self.p.kill();self.p.wait()

def prepare(root, output, engine, provenance):
    root=Path(root);m=json.loads((root/'manifest.json').read_text())
    a=json.loads((root/'aggregate.json').read_text());proof=json.loads(Path(provenance).read_text())
    if a['ref_a']!=a['ref_b'] or proof['observed_ref_a']!=a['ref_a'] or proof['observed_ref_b']!=a['ref_b']:
        raise ValueError('not proven same-source engine selfplay')
    if digest(Path(engine).read_bytes()) not in (proof['binary_sha256_a'],proof['binary_sha256_b']):
        raise ValueError('static scorer is not one of the frozen corpus binaries')
    archive=root/m['archive']
    if digest(archive.read_bytes())!=m['archive_sha256']:raise ValueError('archive hash mismatch')
    sources={s['source_id']:s for s in m['sources']}
    raw_games={};ponder={side:collections.Counter() for side in ('A','B')}
    for sid,source in sources.items():
        raw=(root/'shards'/source['file']).read_bytes()
        if digest(raw)!=sid or len(raw)!=source['bytes']:
            raise ValueError('raw source hash/size mismatch')
        shard=json.loads(raw)
        for key,value in source['metadata'].items():
            if shard.get(key)!=value:raise ValueError('raw source metadata mismatch: '+key)
        for side in ('A','B'):
            ponder[side].update(shard.get('ponder',{}).get(side,{}))
        for i,g in enumerate(shard['details']):
            if g['a_black']!=((shard['game_offset']+i)%2==0):
                raise ValueError('unbalanced color allocation')
            raw_games[(sid,i)]={k:g[k] for k in ('winner','reason','plies','final_sfen','moves','a_black')}
    hashes={side:{s['metadata']['sha256_'+side.lower()] for s in sources.values()} for side in ('A','B')}
    if any(len(v)!=1 for v in hashes.values()):raise ValueError('binary changed within corpus')
    for side in ('A','B'):
        if sorted(hashes[side])!=[proof['binary_sha256_'+side.lower()]]:
            raise ValueError('build log/binary provenance mismatch')
    if a['go_command']!='go movetime 200':raise ValueError('wrong collection time')
    if a['position_knowledge']['A']!=a['position_knowledge']['B']:
        raise ValueError('knowledge differs')
    knowledge=a['position_knowledge']['A']
    if not knowledge['enabled'] or not knowledge['available'] or knowledge['positions']!=163 or knowledge['sha256']!='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c':
        raise ValueError('not the fixed adopted knowledge')
    for source in sources.values():
        md=source['metadata']
        if md['go_command']!='go movetime 200' or md['options_a']!=md['options_b']:
            raise ValueError('selfplay conditions differ')
        for side in ('a','b'):
            if not all(md['options_'+side].get(k,True) for k in
                       ('AdaptiveLongThink','PositionKnowledge','OpeningRandomNonLance','USI_Ponder','RiskVerify')):
                raise ValueError('formal selfplay option disabled')
        if md['position_knowledge']!=a['position_knowledge']:
            raise ValueError('knowledge changed')
    games=[json.loads(s) for s in gzip.open(archive,'rt')]
    games.sort(key=lambda g:(int(Path(sources[g['source_id']]['file']).stem.split('-')[-1]),g['source_game_index']))
    if int(proof['run_id'])!=int(m['run_id']) or m['requested_ref_a']!=a['ref_a'] or m['requested_ref_b']!=a['ref_b']:
        raise ValueError('manifest/source run/reference mismatch')
    if len(games)!=m['games'] or len(games)!=a['games'] or a['illegal_games']:
        raise ValueError('game count/legality metadata mismatch')
    if len({g['game_id'] for g in games})!=len(games):raise ValueError('duplicate game IDs')
    seen_games={};selected=[];counts=collections.Counter();legal_plies=0
    for game in games:
        raw=raw_games[(game['source_id'],game['source_game_index'])]
        if any(game[k]!=raw[k] for k in ('winner','reason','plies','final_sfen','a_black')) or [r['move'] for r in game['moves']]!=raw['moves']:
            raise ValueError('archive/raw game mismatch')
        positions,y=validate_game(game);legal_plies+=len(positions)
        counts['reason/'+game['reason']]+=1
        used=collections.Counter()
        for row in game['moves']:
            info=row.get('search',{});side=row['engine']
            for key in ('knowledge_probes','knowledge_hits','knowledge_promotions','nodes'):
                counts[side+'/'+key]+=info.get(key,0)
            if 'long_think_used' in info:
                used[side]+=1
                if info['long_think_used']!=used[side] or used[side]>10 or info.get('long_think_base_ms')!=200 or info.get('long_think_max_ms')!=1000:
                    raise ValueError('invalid long-think sequence/budget')
                counts[side+'/long_think_moves']+=1
        signature=digest(('startpos\n'+' '.join(r['move'] for r in game['moves'])).encode())
        if y is None:counts['unresolved_games']+=1;continue
        if signature in seen_games:
            if seen_games[signature]!=y:raise ValueError('conflicting outcome for identical game')
            counts['duplicate_games']+=1;continue
        seen_games[signature]=y
        if len(positions)<12:counts['short_games']+=1;continue
        source=sources[game['source_id']]
        shard=int(Path(source['file']).stem.split('-')[-1])
        split=split_for_shard(shard,len(sources));counts['games/'+split]+=1
        # Up to twelve distinct positions after the first eight plies; no terminal SFEN.
        indices=sorted(set(np.linspace(8,len(positions)-1,min(12,len(positions)-8),dtype=int).tolist()))
        for i in indices:
            selected.append({'game_id':game['game_id'],'game_hash':signature,'split':split,
                             'ply':i+1,'sfen':positions[i],'target':y,'shard':shard})
    if legal_plies!=m['plies']:raise ValueError('manifest ply count mismatch')
    if abs(sum(g['a_black'] for g in games)*2-len(games))>1:
        raise ValueError('global colors not balanced')
    kept,removed=exclude_cross_split(selected)
    for split,n in removed.items():counts['overlap_removed/'+split]=n
    static=StaticFeatures(engine)
    try:
        for row in kept:
            x,base=static.score(row['sfen']);row.update(x=x,base_cp=base)
    finally:static.close()
    for split in ('train','validation','test'):
        rows=[r for r in kept if r['split']==split];sizes=collections.Counter(r['game_id'] for r in rows)
        for r in rows:r['weight']=1/sizes[r['game_id']]
        counts['samples/'+split]=len(rows);counts['effective_games/'+split]=len(sizes)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in kept))
    report={'archive_sha256':m['archive_sha256'],'archive_bytes':archive.stat().st_size,
            'run_id':m['run_id'],'source_ref':a['ref_a'],'binary_hashes':{k:sorted(v) for k,v in hashes.items()},
            'knowledge':a['position_knowledge'],'games':len(games),'legal_plies':legal_plies,
            'counts':dict(counts),'dataset_sha256':digest(output.read_bytes()),'static_evaluator_sha256':digest(Path(engine).read_bytes()),
            'split_note':'source shard groups 70/15/15; complete-game dedupe; cross-split position exclusion',
            'build_proof':proof,'ponder':{s:dict(v) for s,v in ponder.items()}}
    save(output.with_suffix('.manifest.json'),report)
    return report

def sigmoid(z):
    return 1/(1+np.exp(-np.clip(z,-40,40)))

class Residual:
    def __init__(self, hidden, cap, seed=SEED):
        self.cap=cap
        self.w1=np.random.default_rng(seed).normal(0,.15,(hidden,INPUTS))
        self.w2=np.zeros(hidden)
    def predict(self,x):
        h=np.tanh(np.clip(x,-4,4)@self.w1.T)
        return self.cap*np.tanh(h@self.w2)
    def correction(self,x):
        raw=self.predict(x)
        # Match C++ lround: ties away from zero, unlike NumPy's bankers rounding.
        return (np.sign(raw)*np.floor(abs(raw)+.5)).astype(np.int64)
    def text(self):
        rows=[f'KUMOJI_SELFPLAY_RESIDUAL_V1 {INPUTS} {len(self.w2)} {self.cap}']
        rows += [' '.join(format(w,'.17g') for w in row) for row in self.w1]
        rows += [' '.join(format(w,'.17g') for w in self.w2),'END']
        return '\n'.join(rows)+'\n'
    @classmethod
    def from_text(cls,text):
        p=text.split();h=int(p[2]);cap=int(p[3]);m=cls(h,cap)
        if p[0]!='KUMOJI_SELFPLAY_RESIDUAL_V1' or int(p[1])!=INPUTS or not 1<=h<=8 or not 1<=cap<=1000 or p[-1]!='END':
            raise ValueError('invalid model header')
        values=np.array([float(x) for x in p[4:-1]])
        if len(values)!=h*(INPUTS+1) or not np.isfinite(values).all() or (np.abs(values)>32).any():
            raise ValueError('invalid model weights')
        m.w1=values[:h*INPUTS].reshape(h,INPUTS);m.w2=values[h*INPUTS:];return m

def arrays(rows):
    return (np.array([r['x'] for r in rows]),np.array([r['base_cp'] for r in rows]),
            np.array([r['target'] for r in rows]),np.array([r['weight'] for r in rows]))

def metric(model,data,temp,scale=1):
    x,base,y,w=data;extra=np.zeros(len(y)) if model is None else np.trunc(model.correction(x)*scale)
    pred=sigmoid((base+extra)/temp)
    return {'brier':float(np.average((pred-y)**2,weights=w)),
            'cross_entropy':float(np.average(-y*np.log(pred+1e-12)-(1-y)*np.log(1-pred+1e-12),weights=w)),
            'samples':len(y),'mean_absolute_correction':float(np.average(abs(extra),weights=w))}

def fit(model,train,validation,temp,l2,epochs=80):
    x,base,y,w=train;w=w/w.sum();params=[model.w1,model.w2]
    first=[np.zeros_like(p) for p in params];second=[np.zeros_like(p) for p in params]
    best=None;best_error=float('inf');best_epoch=0
    for epoch in range(1,epochs+1):
        h=np.tanh(x@model.w1.T);t=np.tanh(h@model.w2)
        p=sigmoid((base+model.cap*t)/temp)
        dz=(p-y)*w*model.cap*(1-t*t)/temp
        grads=[((dz[:,None]*model.w2)*(1-h*h)).T@x+2*l2*model.w1,
               h.T@dz+2*l2*model.w2]
        for i,(p,g) in enumerate(zip(params,grads)):
            first[i]=.9*first[i]+.1*g;second[i]=.999*second[i]+.001*g*g
            p -= .02*(first[i]/(1-.9**epoch))/(np.sqrt(second[i]/(1-.999**epoch))+1e-8)
            np.clip(p,-32,32,out=p)
        error=metric(model,validation,temp)['brier']
        if error < best_error:
            best_error=error;best=(model.w1.copy(),model.w2.copy());best_epoch=epoch
    model.w1,model.w2=best
    return best_epoch

def train(input_path,output_dir):
    path=Path(input_path);rows=[json.loads(s) for s in path.read_text().splitlines() if s.strip()]
    groups={s:[r for r in rows if r['split']==s] for s in ('train','validation','test')}
    for s,n in [('train',500),('validation',100),('test',100)]:
        if len(groups[s])<n:raise ValueError(f'insufficient independent split samples: {s}={len(groups[s])}')
    data={s:arrays(rs) for s,rs in groups.items()}
    temp=min((400,600,900,1300,1800,2500,3500,5000),key=lambda t:metric(None,data['train'],t)['cross_entropy'])
    candidates=[];models=[]
    for hidden in (4,8):
        for cap in (300,600):
            for l2 in (.001,.01):
                model=Residual(hidden,cap);epoch=fit(model,data['train'],data['validation'],temp,l2)
                record={'hidden':hidden,'cap':cap,'l2':l2,'epoch':epoch,
                        'validation':metric(model,data['validation'],temp)}
                candidates.append(record);models.append(model)
    index=min(range(len(models)),key=lambda i:candidates[i]['validation']['brier'])
    model=models[index];text=model.text();out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'model.txt').write_text(text)
    baseline={s:metric(None,d,temp) for s,d in data.items()}
    chosen={s:metric(model,d,temp) for s,d in data.items()}
    report={'dataset_sha256':digest(path.read_bytes()),'seed':SEED,'temperature_train_only':temp,
            'model_sha256':digest(text.encode()),'selection':'validation Brier only; test consulted once after freeze',
            'candidates':candidates,'selected':candidates[index], 'baseline':baseline,'learned':chosen,
            'validation_pass':chosen['validation']['brier']<=baseline['validation']['brier']
                and chosen['validation']['mean_absolute_correction']>0,
            'test_improved':chosen['test']['brier']<baseline['test']['brier'],
            'warning':'outcome prediction is not playing strength; no optimal-move labels'}
    test_rows=groups['test'];tx,tbase,ty,tw=data['test']
    pb=sigmoid(tbase/temp);pl=sigmoid((tbase+model.correction(tx))/temp)
    game_errors=collections.defaultdict(list)
    for row,difference in zip(test_rows,(pl-ty)**2-(pb-ty)**2):
        game_errors[row['game_id']].append(float(difference))
    diffs=np.array([np.mean(values) for values in game_errors.values()])
    rng=np.random.default_rng(SEED+1)
    boot=np.array([rng.choice(diffs,len(diffs),replace=True).mean() for _ in range(2000)])
    report['paired_test_brier_difference']={'learned_minus_baseline':float(diffs.mean()),
        'bootstrap_95_by_game':np.quantile(boot,[.025,.975]).tolist(),
        'independent_game_groups':len(diffs),'resamples':2000}
    report['prediction_rounding']='C++ lround residual points, then integer scale division'
    report['runtime']={'numpy':np.__version__,'python':sys.version}
    root=Path(__file__).resolve().parents[2]
    report['learner_code_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    report['learner_source_sha256']=digest(Path(__file__).read_bytes())
    save(out/'training-report.json',report)
    header=('#pragma once\n#include <string_view>\nnamespace shogi::strategy::detail {\n'
            'inline constexpr std::string_view SelfPlayModelText = R"KUMOJISPLEARN('+text+')KUMOJISPLEARN";\n'
            'inline constexpr std::string_view SelfPlayModelSha256 = "'+report['model_sha256']+'";\n}\n')
    (out/'selfplay_residual_candidate.h').write_text(header)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare');a.add_argument('--input',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a.add_argument('--engine',type=Path,required=True);a.add_argument('--provenance',type=Path,required=True)
    a=sub.add_parser('train');a.add_argument('--input',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=prepare(a.input,a.output,a.engine,a.provenance) if a.mode=='prepare' else train(a.input,a.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
