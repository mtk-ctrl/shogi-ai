"""Native correction arithmetic, zero preservation and incremental/full parity."""
import json
from pathlib import Path
import random
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import shogi
import torch
from benchmarks.arena import Engine
from tools.research import neural_model as nm
from tools.research.neural_residual import StaticOracle
from tools.research.nnue_cycle import verify_native


def run(binary):
    torch.set_num_threads(1)
    torch.manual_seed(2410)
    binary=str(Path(binary).resolve())
    knowledge=Path('position-knowledge-v1.tsv').resolve()
    rng=random.Random(2410);board=shogi.Board();history=[];samples=[]
    for ply in range(100):
        if board.is_game_over():break
        if ply in (8,15,30,45,60,81):samples.append((board.sfen(),history.copy()))
        move=rng.choice(sorted(m.usi() for m in board.legal_moves))
        board.push_usi(move);history.append(move)
    report={'positions':len(samples),'searches':[]}
    with tempfile.TemporaryDirectory() as tmp:
        zero=Path(tmp)/'zero.nnue';learned=Path(tmp)/'learned.nnue'
        net=nm.Network(32,correction=True);nm.export_nnue(net,zero)
        with torch.no_grad():
            net.value.weight.normal_(std=.02)
            net.value.bias.fill_(.1)
        nm.export_nnue(net,learned)
        oracle=StaticOracle(binary)
        try:
            for sfen,_ in samples:
                base=oracle.evaluate(sfen)
                verify_native(binary,zero,sfen,base,knowledge)
                verify_native(binary,learned,sfen,base+nm.quantized_cp(learned,sfen),knowledge)
            for bias in (-2.,2.):
                with torch.no_grad():net.value.weight.zero_();net.value.bias.fill_(bias)
                cap=Path(tmp)/'cap.nnue';nm.export_nnue(net,cap)
                sfen=samples[0][0]
                verify_native(binary,cap,sfen,oracle.evaluate(sfen)+(600 if bias>0 else -600),knowledge)
        finally:oracle.close()
        for threads in (1,2):
            for sfen,hist in samples[:4]:
                results=[]
                for model,incremental in ((None,True),(zero,True),(learned,True),(learned,False)):
                    opts=dict(SearchThreads=threads,OpeningRandomNonLance=False,
                        PositionKnowledge=True,PositionKnowledgeFile=str(knowledge),
                        MateAssist=False,MateLearning=False,AdaptiveLongThink=False,USI_Ponder=False,
                        EvalNeuralIncremental=incremental,EvalNeuralPolicy=False)
                    if model:opts.update(EvalNeural=True,EvalNeuralFile=str(model))
                    engine=Engine(binary,'A',opts,'go depth 2')
                    try:
                        engine.configure_game(2410)
                        start=time.monotonic();move=engine.bestmove(hist)
                        results.append(dict(move=move,search=engine.last_search.copy(),seconds=time.monotonic()-start))
                    finally:engine.close()
                for left,right in ((0,1),(2,3)):
                    assert results[left]['move']==results[right]['move'],results
                    for key in ('score_cp','nodes','depth'):
                        assert results[left]['search'].get(key)==results[right]['search'].get(key),(key,results)
                assert results[1]['search'].get('neural_updates',0)==0,results
                assert results[2]['search'].get('neural_updates',0)>0,results
                report['searches'].append(dict(threads=threads,results=results))
    print(json.dumps(report))
    return report


if __name__=='__main__':run(sys.argv[1])
