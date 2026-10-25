#!/usr/bin/env python3
"""Quantized/native and incremental/full search differential checks on legal play."""
from pathlib import Path
import random
import re
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import shogi
import torch
from tools.research import neural_model as nm
from tools.research.neural_mcts import RulesOracle, research
from tools.research.postgame_analyze import Analyzer
from benchmarks.arena import Engine


def run(binary):
    torch.set_num_threads(1)
    torch.manual_seed(271)
    with tempfile.TemporaryDirectory() as tmp:
        net=nm.Network(32)
        path=Path(tmp)/'fixture.nnue'
        nm.export_nnue(net,path)
        knowledge=Path('position-knowledge-v1.tsv').resolve()
        oracle=RulesOracle(binary)
        rng=random.Random(876)
        board=shogi.Board()
        history=[]
        samples=[]
        for ply in range(220):
            state=oracle.state(shogi.Board().sfen(),history)
            legal=sorted(m.usi() for m in board.legal_moves)
            assert sorted(state['moves'])==legal, (ply,state,legal)
            if state['result'] or state['declare']:break
            if ply in (0,14,29,55,89,130,180):samples.append((board.sfen(),list(history)))
            # Prefer tactical transformations at a few plies to cover hand and promotion updates.
            tactical=[m for m in legal if '+' in m or '*' in m]
            move=rng.choice(tactical if tactical and ply%3==0 else legal)
            board.push_usi(move)
            history.append(move)
        for sfen,hist in samples:
            analyzer=Analyzer(binary,knowledge,neural_options={
                'EvalNeuralFile':str(path),'EvalNeural':True,'EvalNeuralPolicy':True})
            try:
                analyzer.send('position sfen '+sfen)
                analyzer.send('eval')
                lines=analyzer.until('info string evaluation ',15)
                cp=next(int(line.split()[-1]) for line in lines if 'neural_evaluation static_cp_black' in line)
                assert cp==nm.quantized_cp(path,sfen),(cp,nm.quantized_cp(path,sfen),sfen)
            finally:analyzer.close()
        options=dict(EvalNeuralFile=str(path),EvalNeural=True,EvalNeuralPolicy=True,
            SearchThreads=1,OpeningRandomNonLance=False,PositionKnowledge=True,
            PositionKnowledgeFile=str(knowledge),MateAssist=False,MateLearning=False,
            AdaptiveLongThink=False,USI_Ponder=False)
        for sfen,hist in samples[:4]:
            results=[]
            for incremental in (True,False):
                engine=Engine(str(Path(binary).resolve()),'A',dict(options,
                    EvalNeuralIncremental=incremental),'go depth 2')
                try:
                    engine.configure_game(17)
                    move=engine.bestmove(hist)
                    results.append((move,engine.last_search.copy()))
                finally:engine.close()
            assert results[0][0]==results[1][0],results
            assert results[0][1]['score_cp']==results[1][1]['score_cp'],results
            assert results[0][1].get('neural_updates',0)>0,results
            assert results[0][1].get('neural_policy_nodes',0)>0,results
            assert results[1][1].get('neural_updates',0)==0,results
        result=research(net,oracle,shogi.Board().sfen(),[],32)
        assert result['bestmove'] in [m.usi() for m in shogi.Board().legal_moves]
        assert sum(result['root_visits'].values())==32
        # Fourfold repetition uses the COMPLETE history, not just final SFEN.
        start='4k4/9/9/9/9/9/9/9/4K4 b - 1'
        cycle=['5i6i','5a6a','6i5i','6a5a']
        assert oracle.state(start,cycle*3)['result']==1
        assert oracle.state(start,[])['result']==0
        oracle.close()
        print(f'native NNUE/MCTS passed: {len(samples)} positions, {len(history)} legal plies, depth-2 differential')

if __name__=='__main__':run(sys.argv[1])
