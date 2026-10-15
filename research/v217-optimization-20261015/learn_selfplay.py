"""Research-only learning from fixed v2.0.17 self-play; never alters the engine."""
import argparse, gzip, hashlib, json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import shogi

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/nn'))
from network import PositionNet,encode_sfen,sigmoid
from train import partition,calibrate_cp

BASE='003f42c66f8e3f2e5deb1898103555466e72016f'
SEED=202610151
def sha(data):return hashlib.sha256(data).hexdigest()

def equivalent_builds(directory):
    """Keep actual executable hashes; prove equivalence apart from debug paths."""
    originals={n:sha((directory/n).read_bytes()) for n in ('engine-a','engine-b')}
    normalized=[]
    with tempfile.TemporaryDirectory() as temp:
        for name in originals:
            out=Path(temp)/name
            subprocess.run(['objcopy','--strip-debug','--remove-section=.note.gnu.build-id',
                str(directory/name),str(out)],check=True)
            normalized.append(out.read_bytes().replace(name.encode()+b'-src',b'engine-X-src'))
    if normalized[0]!=normalized[1]:raise ValueError('build equivalence is unproven')
    return {'actual_sha256':originals,'normalized_elf_sha256':sha(normalized[0]),
        'normalization':'objcopy: remove debug and build-id; normalize engine-a-src/engine-b-src diagnostic paths',
        'same_source_commit':BASE,'same_actual_binary':originals['engine-a']==originals['engine-b']}

def prepare(archive,binaries,output):
    manifest=json.loads((archive/'manifest.json').read_text())
    if manifest['requested_ref_a']!=BASE or manifest['requested_ref_b']!=BASE:
        raise ValueError('both requested engine commits must be the fixed baseline')
    raw=(archive/'played-games.jsonl.gz').read_bytes()
    if sha(raw)!=manifest['archive_sha256']:raise ValueError('archive hash mismatch')
    proof=equivalent_builds(binaries)
    sources={s['source_id']:s['metadata'] for s in manifest['sources']}
    for meta in sources.values():
        if meta['sha256_a']!=proof['actual_sha256']['engine-a'] or meta['sha256_b']!=proof['actual_sha256']['engine-b']:
            raise ValueError('actual self-play binaries differ from inspected executables')
        if meta['options_a']!=meta['options_b'] or meta['go_command']!='go movetime 200':
            raise ValueError('unequal self-play conditions')
        knowledge=meta['position_knowledge']
        if knowledge['A']!=knowledge['B'] or knowledge['A']['sha256']!=sha((binaries/'position-knowledge-v1.tsv').read_bytes()):
            raise ValueError('knowledge identity mismatch')
    rows=[];seen=set();games=excluded=duplicates=0
    for game in map(json.loads,gzip.decompress(raw).decode().splitlines()):
        if game.get('illegal_by'):raise ValueError('illegal self-play game')
        if game.get('winner') in ('A','B') and game['reason'] in ('resign','checkmate','no_legal_moves','declare_win','perpetual_check'):
            target=float((game['winner']=='A')==bool(game['a_black']))
        elif game.get('winner') is None and game['reason']=='fourfold_repetition':target=.5
        else:excluded+=1;continue
        board=shogi.Board(game.get('start_sfen') or shogi.STARTING_SFEN)
        tokens=[r['move'] for r in game['moves']]
        identity=sha((board.sfen()+'\n'+' '.join(tokens)).encode())
        if identity in seen:duplicates+=1;continue
        seen.add(identity);games+=1
        indices=set(np.linspace(min(8,len(tokens)-1),len(tokens)-1,min(8,len(tokens)),dtype=int))
        for i,record in enumerate(game['moves']):
            move=shogi.Move.from_usi(record['move'])
            if move not in board.legal_moves:raise ValueError('recorded illegal move')
            if i in indices:
                score=record.get('search',{}).get('phase_static_cp_black')
                if type(score) is int:
                    rows.append({'source':'kumoji_selfplay','game_id':identity,'sfen':board.sfen(),
                        'ply':i+1,'target_black':target,'static_cp_black':score,
                        'phase_stage':record.get('search',{}).get('phase_stage'),
                        'source_group':manifest['run_id'],'source_commit':BASE,
                        'provenance_type':'same_commit_equivalent_executables'})
            board.push(move)
    output.mkdir(parents=True,exist_ok=True)
    (output/'samples.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return rows,{'run_id':manifest['run_id'],'archive_sha256':manifest['archive_sha256'],
        'archive_games':manifest['games'],'used_games':games,'excluded_unresolved_games':excluded,
        'duplicate_games':duplicates,'samples':len(rows),'build_proof':proof}

def study(rows,output):
    assignments=partition(rows,SEED)
    splits={n:[r for r in rows if assignments[r['game_id']]==n] for n in ('train','val','test')}
    seen={r['sfen'].rsplit(' ',1)[0] for r in splits['train']};removed={}
    for n in ('val','test'):
        old=splits[n];splits[n]=[r for r in old if r['sfen'].rsplit(' ',1)[0] not in seen]
        removed[n]=len(old)-len(splits[n]);seen.update(r['sfen'].rsplit(' ',1)[0] for r in splits[n])
        if not splits[n]:raise ValueError('empty independent holdout')
    train=splits['train'];temperature=calibrate_cp(train)
    if temperature is None:raise ValueError('insufficient calibration observations')
    x={n:np.stack([encode_sfen(r['sfen']) for r in split]) for n,split in splits.items()}
    y={n:np.asarray([r['target_black'] for r in split],dtype=np.float32) for n,split in splits.items()}
    baseline={n:sigmoid(np.asarray([r['static_cp_black'] for r in split])/temperature) for n,split in splits.items()}
    brier=lambda p,n:float(np.mean((p-y[n])**2))
    candidates=[];best=None
    for hidden,epochs in ((4,2),(8,3),(16,4)):
        model=PositionNet(hidden=hidden,seed=SEED);model.fit(x['train'],y['train'],epochs=epochs,seed=SEED)
        val=model.predict(x['val'])
        entry={'hidden':hidden,'epochs':epochs,'validation_neural_brier':brier(val,'val')}
        blends=[(brier((1-w)*baseline['val']+w*val,'val'),w) for w in (0,.1,.25,.5,.75,1)]
        loss,weight=min(blends)
        entry.update(validation_blended_brier=loss,neural_weight=weight);candidates.append(entry)
        if best is None or loss<best[0]:best=(loss,model,entry)
    model=best[1];weight=best[2]['neural_weight'];model.save(output/'research-model.npz')
    # First and only test-set measurement after all model/blend choices are fixed.
    prediction={n:model.predict(x[n]) for n in splits}
    metrics={n:{'games':len({r['game_id'] for r in splits[n]}),'positions':len(splits[n]),
        'static_brier':brier(baseline[n],n),'neural_brier':brier(prediction[n],n),
        'blended_brier':brier((1-weight)*baseline[n]+weight*prediction[n],n)} for n in splits}
    return {'seed':SEED,'split':'whole games; exact board/hand/turn overlap removed from holdouts',
        'removed_duplicate_holdout_positions':removed,'calibration_temperature_train_only':temperature,
        'candidate_selection':'validation only; test evaluated once after selection',
        'candidates':candidates,'selected':best[2],'metrics':metrics,
        'meaning':'Prediction of empirical final game results. Not certified move labels or proof of engine strength.',
        'engine_integration':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--binaries',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();rows,provenance=prepare(args.archive,args.binaries,args.output)
    report={'provenance':provenance,'study':study(rows,args.output)}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
