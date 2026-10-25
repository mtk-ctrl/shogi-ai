"""Two small real correction cycles before the expensive distributed run."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.research import neural_cluster as nc
from tools.research import neural_model as nm


def run(source,binary,output,commit):
    output=Path(output)
    # A small, group-balanced REAL-game subset keeps this wiring gate bounded.
    source=Path(source);subset=output/'source';subset.mkdir(parents=True,exist_ok=True)
    manifest=nc.read(source/'manifest.json');groups={k:[] for k in ('train','validation','test')}
    for line in gzip.decompress((source/manifest['archive']).read_bytes()).splitlines():
        row=json.loads(line);split=nm.split_root(row['game_id'],20261021)
        if len(groups[split])<4:groups[split].append(row)
    assert all(len(rows)==4 for rows in groups.values())
    rows=[r for split in groups.values() for r in split];raw=gzip.compress(('\n'.join(json.dumps(r) for r in rows)+'\n').encode(),mtime=0)
    (subset/'played-games.jsonl.gz').write_bytes(raw)
    manifest.update(archive='played-games.jsonl.gz',archive_sha256=hashlib.sha256(raw).hexdigest(),
                    archive_bytes=len(raw),games=len(rows),plies=sum(r['plies'] for r in rows),
                    parent_manifest_sha256=nm.digest(source/'manifest.json'))
    nc.atomic_json(subset/'manifest.json',manifest)
    work=output/'run'
    request=dict(mode='smoke',evaluation_mode='correction',cycle_id='correction-preflight',
        generations=2,runners=1,selfplay_games=2,match_games=2,cases=8,validation_cases=4,learner_selfplay=True,
        medium_ms=50,long_ms=100,branch_ms=50,epochs=2,width=16,
        simulations=8,samples_per_game=8,max_plies=100,seed=20261024)
    nc.initialize(work,request,subset,binary,'position-knowledge-v1.tsv',commit)
    for generation in range(2):
        nc.begin(work,1)
        for stage in ('selfplay','study','mcts','evaluate'):
            assert nc.read(work/'tasks.json')['stage']==stage
            directory=output/f'g{generation}-{stage}'
            nc.worker(work,directory/'lane-00',0)
            nc.reduce_stage(work,directory)
        result=nc.finish(work)
        assert not result['decision']['accepted']
        assert result['student']['architecture']['correction'] is True
        assert result['student']['architecture']['material_prior'] is False
        assert (work/f'history/g{generation:03d}/candidate.nnue').read_bytes()[:8]==b'KMNNUE04'
        print(json.dumps(dict(preflight_generation=generation,student=result['student']['model_sha256'])),flush=True)
    state=nc.read(work/'state.json')
    assert state['status']=='completed' and state['next_generation']==2 and state['accepted']==0
    assert len(state['seen_positions'])==16
    assert (work/'learner.nnue').is_file()
    assert nc.read(work/'research-validation.json')
    for row in nc.read(work/'research-replay.json'):assert nm.split_root(row['root'],20261021)=='train'
    for row in nc.read(work/'research-validation.json'):assert nm.split_root(row['root'],20261021)=='validation'
    nc.pack(work,output/'checkpoint.tgz',durable=True)
    nc.unpack(output/'checkpoint.tgz',output/'restored')
    assert nc.read(output/'restored/state.json')==state
    assert nm.digest(work/'learner/student/model.pt')==nm.digest(output/'restored/learner/student/model.pt')
    report=dict(schema='correction-cycle-preflight-v1',generations=2,selfplay_games=4,evaluation_games=4,
        new_study_positions=16,status='completed',formal_adoption=False,strength_proven=False,
        checkpoint_sha256=nm.digest(output/'checkpoint.tgz'))
    nc.atomic_json(output/'report.json',report)
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':run(*sys.argv[1:])
