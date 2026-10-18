"""Actual binary controls for the selfplay ordering experiment."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.arena import Engine,merge_info_line
from tools.research.postgame_eval_preflight import tactical_cases


def probe(binary,sfen,scale=0,depth=None,history=(),extra_options=None):
    options=dict(
        SearchThreads=1,AdaptiveLongThink=False,USI_Ponder=False,
        OpeningRandomNonLance=False,RandomSeed=2031101801,
        PositionKnowledge=True,PositionKnowledgeFile=str(ROOT/'position-knowledge-v1.tsv'))
    options.update(extra_options or {})
    e=Engine(binary,'probe',options)
    try:
        e.send('usinewgame');e.send('position sfen '+sfen+(' moves '+' '.join(history) if history else ''))
        start=time.monotonic();e.send('go depth '+str(depth) if depth else 'go movetime 200')
        info={}
        while True:
            line=e.lines.get(timeout=20)
            if line.startswith('info '):merge_info_line(info,line)
            if line.startswith('bestmove '):
                keys=('depth','nodes','score_cp','score_mate','selfplay_order_calls','selfplay_order_moves')
                return dict(move=line.split()[1],elapsed_ms=(time.monotonic()-start)*1000,
                            **{k:info[k] for k in keys if k in info})
    finally:e.close()

