"""Two small real correction cycles before the expensive distributed run."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.research import neural_cluster as nc
from tools.research import neural_model as nm


def run(source,binary,output,commit):
    output=Path(output)
    work=output/'run'
    request=dict(mode='smoke',evaluation_mode='correction',cycle_id='correction-preflight',
        generations=2,runners=1,selfplay_games=2,match_games=2,cases=2,
        medium_ms=50,long_ms=100,branch_ms=50,epochs=2,width=16,
        simulations=8,samples_per_game=8,max_plies=100,seed=20261024)
    nc.initialize(work,request,source,binary,'position-knowledge-v1.tsv',commit)
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
    assert len(state['seen_positions'])==4
    nc.pack(work,output/'checkpoint.tgz',durable=True)
    nc.unpack(output/'checkpoint.tgz',output/'restored')
    assert nc.read(output/'restored/state.json')==state
    assert nm.digest(work/'learner/student/model.pt')==nm.digest(output/'restored/learner/student/model.pt')
    report=dict(schema='correction-cycle-preflight-v1',generations=2,selfplay_games=4,evaluation_games=4,
        new_study_positions=4,status='completed',formal_adoption=False,strength_proven=False,
        checkpoint_sha256=nm.digest(output/'checkpoint.tgz'))
    nc.atomic_json(output/'report.json',report)
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':run(*sys.argv[1:])
