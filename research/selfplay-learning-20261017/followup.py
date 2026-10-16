#!/usr/bin/env python3
"""Bounded, turn-invariant own-selfplay learning and tactical ablations."""
import argparse, collections, gzip, hashlib, importlib.util, json, os
from pathlib import Path
import shutil, subprocess, sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'research/selfplay-learning-20261016'
sys.path.insert(0,str(OLD));sys.path.insert(0,str(ROOT))
import learn
from benchmarks.arena import Engine,merge_info_line
import shogi

def run(args):subprocess.run([str(x) for x in args],cwd=ROOT,check=True)
def header(model):
    text=model.text();digest=learn.digest(text.encode())
    return ('#pragma once\n#include <string_view>\nnamespace shogi::strategy::detail {\n'
        'inline constexpr std::string_view SelfPlayModelText = R"KUMOJISPLEARN('+text+')KUMOJISPLEARN";\n'
        'inline constexpr std::string_view SelfPlayModelSha256 = "'+digest+'";\n}\n')
def invariants(model):
    rng=np.random.default_rng(2026101701);x=rng.uniform(-4,4,(1001,12))
    a=model.correction(x);opposite=model.correction(-x)
    assert np.array_equal(a,-opposite),'color reversal'
    x[:,11]=1;y=x.copy();y[:,11]=-1
    assert np.array_equal(model.correction(x),model.correction(y)),'turn leaked into correction'
    assert np.max(np.abs(a))<=model.cap
    material=np.zeros((241,12));material[:,0]=np.linspace(-12000,12000,241)/3000
    values=np.linspace(-12000,12000,241)+model.correction(material)
    assert np.all(np.diff(values)>=0),'material score inverted'
    return {'random_vectors':1001,'turn_invariant':True,'color_odd':True,
            'max_abs_correction':int(np.max(abs(a))),'material_monotone_grid':241}
def train_models(dataset,out):
    rows=[json.loads(s) for s in dataset.read_text().splitlines()]
    assert learn.digest(dataset.read_bytes())=='a093cf34623ba559c8f11768dc0d00af0503c90a380402708d690348a79af603','changed source dataset'
    groups={s:[r for r in rows if r['split']==s] for s in ('train','validation','test')}
    rawdata={s:learn.arrays(rs) for s,rs in groups.items()}
    data={s:tuple(a.copy() for a in d) for s,d in rawdata.items()}
    for x,_,_,_ in data.values():x[:,11]=0
    temp=min((400,600,900,1300,1800,2500,3500,5000),
             key=lambda t:learn.metric(None,data['train'],t)['cross_entropy'])
    baseline={s:learn.metric(None,d,temp) for s,d in data.items()}
    summary={'dataset_sha256':learn.digest(dataset.read_bytes()),
        'previous_test_is_reused_diagnostic':True,'selection':'validation only; independent fresh matches are final strength evidence',
        'temperature_train_only':temp,'baseline':baseline,'models':{}}
    for cap in (150,600):
        candidates=[];models=[]
        for hidden in (4,8):
            for l2 in (.001,.01):
                m=learn.Residual(hidden,cap);m.w1[:,11]=0
                epoch=learn.fit(m,data['train'],data['validation'],temp,l2)
                assert np.all(m.w1[:,11]==0)
                candidates.append({'hidden':hidden,'cap':cap,'l2':l2,'epoch':epoch,
                    'validation':learn.metric(m,data['validation'],temp)})
                models.append(m)
        index=min(range(len(models)),key=lambda i:candidates[i]['validation']['brier'])
        m=models[index];name='no-turn'+str(cap);dest=out/'followup'/name;dest.mkdir(parents=True)
        (dest/'model.txt').write_text(m.text());(dest/'selfplay_residual_candidate.h').write_text(header(m))
        learned={s:learn.metric(m,d,temp) for s,d in data.items()}
        report={'dataset_sha256':summary['dataset_sha256'],'model_sha256':learn.digest(m.text().encode()),
            'temperature_train_only':temp,'selection':summary['selection'],'candidates':candidates,
            'selected':candidates[index],'baseline':baseline,'learned':learned,
            'validation_pass':learned['validation']['brier']<=baseline['validation']['brier'],
            'test_improved':learned['test']['brier']<baseline['test']['brier'],
            'previous_test_is_reused_diagnostic':True,'invariants':invariants(m),
            'learner_code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'learner_source_sha256':learn.digest(Path(__file__).read_bytes())}
        learn.save(dest/'training-report.json',report);summary['models'][name]=report
    old=learn.Residual.from_text((ROOT/'research/selfplay-learning-20261017/original-model.txt').read_text())
    summary['old_scale10']={s:learn.metric(old,d,temp,.1) for s,d in rawdata.items()}
    summary['old_scale10']['validation_pass']=summary['old_scale10']['validation']['brier']<=baseline['validation']['brier']
    learn.save(out/'followup/training-summary.json',summary)
    return summary

TACTICS=[
 ('hanging-pawn','8k/9/9/3p5/9/3P5/2P6/9/K8 b - 1','7g7f','6f6e'),
 ('hanging-lance','8k/9/9/3p5/9/3L5/2P6/9/K8 b - 1','7g7f','6f6e'),
 ('free-pawn','8k/9/9/9/3p5/3P5/2P6/9/K8 b - 1','6f6e','7g7f'),
 ('safe-promotion','8k/9/9/3P5/9/9/2P6/9/K8 b - 1','6d6c+','7g7f')]
def mirror_sfen(sfen):
    b=shogi.Board(sfen);out=shogi.Board();out.clear()
    for sq in range(81):
        p=b.piece_at(sq)
        if p:out.set_piece_at(80-sq,shogi.Piece(p.piece_type,p.color^1))
    out.turn=b.turn^1
    return out.sfen()
def mirror_move(move):
    # Rotation changes the two board square coordinates; no drops in fixtures.
    return ''.join(str(10-int(move[i]))+chr(ord('j')-ord(move[i+1])+ord('a')-1)
                   for i in (0,2))+move[4:]
def search(e,sfen,go,seed):
    e.configure_game(seed);e.send('position sfen '+sfen);e.send(go);info={}
    while True:
        line=e.lines.get(timeout=30)
        if line.startswith('info '):merge_info_line(info,line)
        if line.startswith('bestmove '):
            move=line.split()[1]
            assert shogi.Move.from_usi(move) in shogi.Board(sfen).legal_moves
            return move,info
def tactics(binary,enabled,scale=100):
    options={'OpeningRandomNonLance':False,'MateAssist':False,'MateLearning':False,
        'AdaptiveLongThink':False,'PositionKnowledge':True,'USI_Ponder':False,
        'SelfPlayEval':enabled,'SelfPlayEvalScale':scale,
        'EvalSafety':1,'EvalPressure':0,'EvalActivity':0,'EvalDanger':0,
        'EvalInfluence':0,'EvalPotential':0,'EvalCoordination':0,
        'EvalHandPotential':0,'EvalThreat':0}
    rows=[]
    for threads in (1,2):
        e=Engine(str(binary),'tactical',dict(options,SearchThreads=threads))
        try:
            for name,sfen,good,bad in TACTICS:
                for reflected in (False,True):
                    board=mirror_sfen(sfen) if reflected else sfen
                    g=mirror_move(good) if reflected else good
                    b=mirror_move(bad) if reflected else bad
                    assert shogi.Move.from_usi(g) in shogi.Board(board).legal_moves,(name,board,g)
                    assert shogi.Move.from_usi(b) in shogi.Board(board).legal_moves
                    for seed in range(2026101701,2026101707):
                        move,info=search(e,board,'go depth 1 searchmoves '+g+' '+b,seed)
                        if enabled:assert info['learned_eval']==1 and info['learned_scale']==scale
                        rows.append({'name':name,'mirrored':reflected,'threads':threads,
                            'seed':seed,'selected':move,'expected':g,'pass':move==g,
                            'score_cp':info.get('score_cp'),'nodes':info.get('nodes')})
        finally:e.close()
    return {'trials':len(rows),'passes':sum(r['pass'] for r in rows),
        'failures_by_case':dict(collections.Counter(r['name'] for r in rows if not r['pass'])),'rows':rows}

def cycle(args):
    run([sys.executable,'tests/test_selfplay_followup.py'])
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    dataset=out/'samples.jsonl'
    inventory=learn.prepare(args.archive_dir,dataset,args.baseline,args.provenance)
    summary=train_models(dataset,out)
    old_header=ROOT/'engine/models/selfplay_residual_candidate.h'
    original_header=old_header.read_text()
    binary_original=out/'candidate-original'
    run([sys.executable,'scripts/build.py','--output',binary_original])
    tactical={'official':tactics(args.baseline,False),
              'old100':tactics(binary_original,True,100),
              'scale10':tactics(binary_original,True,10)}
    assert tactical['official']['passes']==tactical['official']['trials'],'invalid tactical baseline fixture'
    validation={}
    for cap in (150,600):
        name='no-turn'+str(cap);dest=out/'followup'/name
        shutil.copyfile(dest/'selfplay_residual_candidate.h',old_header)
        binary=out/('candidate-'+name)
        run([sys.executable,'scripts/build.py','--output',binary])
        tactical[name]=tactics(binary,True)
        tactical_pass=tactical[name]['passes']==tactical[name]['trials']
        validation[name]={'tactical_pass':tactical_pass,'validation_brier_pass':summary['models'][name]['validation_pass']}
        if cap==150:
            run([sys.executable,'tests/test_selfplay_eval_usi.py',args.baseline.resolve(),binary,dest/'model.txt'])
            run([sys.executable,'tests/test_search_usi.py',binary,'2','3','embedded'])
        measurements=out/'followup'/('benchmark-'+name+'.json')
        run([sys.executable,OLD/'benchmark.py',args.baseline.resolve(),binary,measurements])
        metrics=json.loads(measurements.read_text())
        ratio=metrics['summary']['learned100']['timed_depth_sum']/metrics['summary']['official_v2020']['timed_depth_sum']
        validation[name].update(timed_depth_ratio=ratio,off_exact=not metrics['summary']['control']['full_mismatches'])
        validation[name]['match_gate_pass']=tactical_pass and summary['models'][name]['validation_pass'] and ratio>=.9 and validation[name]['off_exact']
    measurements=out/'followup/benchmark-scale10.json'
    run([sys.executable,OLD/'benchmark.py',args.baseline.resolve(),binary_original,measurements,
         json.dumps({'control':0,'learned100':10})])
    metrics=json.loads(measurements.read_text())
    ratio=metrics['summary']['learned100']['timed_depth_sum']/metrics['summary']['official_v2020']['timed_depth_sum']
    validation['scale10']={'tactical_pass':tactical['scale10']['passes']==tactical['scale10']['trials'],
        'validation_brier_pass':summary['old_scale10']['validation_pass'],'timed_depth_ratio':ratio,
        'off_exact':not metrics['summary']['control']['full_mismatches']}
    validation['scale10']['match_gate_pass']=all((validation['scale10']['tactical_pass'],
        validation['scale10']['validation_brier_pass'],ratio>=.9,validation['scale10']['off_exact']))
    learn.save(out/'followup/tactical-regression.json',tactical)
    learn.save(out/'followup/validation-summary.json',validation)
    primary=out/'followup/no-turn150'
    for n in ('model.txt','selfplay_residual_candidate.h','training-report.json'):shutil.copyfile(primary/n,out/n)
    shutil.copyfile(primary/'selfplay_residual_candidate.h',old_header)
    result={'dataset_manifest':str(dataset.with_suffix('.manifest.json')),
        'training_report':str(out/'training-report.json'),'model_sha256':summary['models']['no-turn150']['model_sha256'],
        'validation_pass':summary['models']['no-turn150']['validation_pass'],
        'test_improved':summary['models']['no-turn150']['test_improved'],
        'candidate_built':True,'formal_adoption':False,'followup':validation,
        'tactical_original100':{k:v for k,v in tactical['old100'].items() if k!='rows'},
        'test_split_status':'Reused diagnostic, not untouched test. Fresh seeded matches are required.'}
    learn.save(out/'cycle-result.json',result)
    for name,report in summary['models'].items():
        print('FOLLOWUP_MODEL '+json.dumps({'name':name,'model':(out/'followup'/name/'model.txt').read_text(),
            'header':(out/'followup'/name/'selfplay_residual_candidate.h').read_text(),'report':report},separators=(',',':')),flush=True)
    print('FOLLOWUP_RESULT '+json.dumps(result,separators=(',',':')),flush=True)
