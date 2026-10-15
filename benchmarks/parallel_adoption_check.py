"""Check extracted production search against the frozen research executable.

The caller supplies the studied executable (NN/difference updates disabled).
Only fingerprints are compared in memory; no PVs or unplayed moves are saved.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

reference, adopted, output = sys.argv[1:4]
options = dict(OpeningRandomNonLance=False, MateAssist=False, MateLearning=False,
               AdaptiveLongThink=False, PositionKnowledge=True, SearchThreads=2)
engines = [Engine(reference, 'frozen-research', {**options, 'EvalUpdateMask': 0, 'EvalNeuralBlend': 0}),
           Engine(adopted, 'adopted-parallel', options)]
cases = json.loads(Path('research/search-efficiency3-20261015/positions.json').read_text())['rows'][:24]
fields = ('score_cp', 'score_mate', 'depth', 'nodes', 'qnodes', 'cutoffs', 'pv')
checks = 0
try:
    for repeat in range(3):
        for index, row in enumerate(cases):
            observed = []
            for e in engines:
                e.configure_game(2026101583 + index)
                e.go_command = 'go depth 2'
                move = e.bestmove(row['moves'])
                observed.append((move, *(e.last_search.get(k) for k in fields)))
            assert observed[0] == observed[1], (repeat, index, observed)
            checks += 1
finally:
    for e in engines:
        e.close()
report = dict(reference_sha256=hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
              adopted_sha256=hashlib.sha256(Path(adopted).read_bytes()).hexdigest(),
              cases=len(cases), repeats=3, checked=checks, mismatches=0,
              compared_fields=['move', *fields], options=options,
              reference_note='Frozen research 00904045c69c5c76ca78f85b5a47391bfb5c1a86 with EvalUpdateMask=0 and EvalNeuralBlend=0.',
              meaning='Fixed-depth extraction regression, not a new strength estimate.')
Path(output).write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
