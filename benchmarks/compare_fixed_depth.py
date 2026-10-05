"""Compare identical positions, seeds and depth; never infer speed from different games."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

parser = argparse.ArgumentParser()
parser.add_argument('--current', required=True)
parser.add_argument('--baseline', required=True)
parser.add_argument('--games-json', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
games = json.loads(Path(args.games_json).read_text())['details']
a = Engine(args.current, 'current', {'ExperienceCache':False})
b = Engine(args.baseline, 'baseline', {'ExperienceCache':False})
rows = []
try:
    for game in games:
        for ply in [0,10,30,60,90,120,150,180,210]:
            if ply >= len(game['moves']): continue
            prefix = game['moves'][:ply]
            seed = 20261104 + len(rows)
            for engine in (a,b): engine.configure_game(seed)
            order = (a,b) if len(rows)%2 == 0 else (b,a)
            moves = {e.label:e.bestmove(prefix) for e in order}
            rows.append({'moves':prefix,'seed':seed,'choices':moves,
                         'nodes':{'current':a.search_stats[-1]['nodes'],'baseline':b.search_stats[-1]['nodes']},
                         'elapsed_ms':{'current':a.elapsed[-1]*1000,'baseline':b.elapsed[-1]*1000}})
finally:
    a.close(); b.close()
result = {'go':'go depth 3', 'experience':False, 'cases':len(rows),
          'matching_moves':sum(r['choices']['current']==r['choices']['baseline'] for r in rows),
          'nodes':{k:sum(r['nodes'][k] for r in rows) for k in ['current','baseline']},
          'elapsed_ms':{k:sum(r['elapsed_ms'][k] for r in rows) for k in ['current','baseline']},
          'sha256':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in [('current',args.current),('baseline',args.baseline)]},
          'rows':rows}
Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
