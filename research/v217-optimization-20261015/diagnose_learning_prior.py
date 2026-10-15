"""Post-freeze diagnostic: compare a train-only constant outcome prior.

Does not train, select, or change the frozen network or its mixing weight.
"""
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import shogi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'research/nn'))
from train import partition

archive, output = map(Path, sys.argv[1:3])
report = json.loads((Path(__file__).parent/'selfplay-learning-report.json').read_text())
raw = archive.read_bytes()
assert hashlib.sha256(raw).hexdigest() == report['provenance']['archive_sha256']
rows = []
seen = set()
for game in map(json.loads, gzip.decompress(raw).decode().splitlines()):
    assert (game['winner'] in ('A', 'B') and game['reason'] == 'checkmate') or (game['winner'] is None and game['reason'] == 'fourfold_repetition')
    board = shogi.Board()
    tokens = [m['move'] for m in game['moves']]
    key = hashlib.sha256((board.sfen()+'\n'+' '.join(tokens)).encode()).hexdigest()
    if key in seen:
        continue
    seen.add(key)
    target = .5 if game['winner'] is None else float((game['winner'] == 'A') == game['a_black'])
    indices = set(np.linspace(min(8, len(tokens)-1), len(tokens)-1, min(8, len(tokens)), dtype=int))
    for i, move in enumerate(game['moves']):
        if i in indices and type(move.get('search', {}).get('phase_static_cp_black')) is int:
            rows.append(dict(game_id=key, sfen=board.sfen(), target_black=target))
        board.push_usi(move['move'])
assignments = partition(rows, report['study']['seed'])
splits = {n: [r for r in rows if assignments[r['game_id']] == n] for n in ('train', 'val', 'test')}
positions = {r['sfen'].rsplit(' ', 1)[0] for r in splits['train']}
for name in ('val', 'test'):
    splits[name] = [r for r in splits[name] if r['sfen'].rsplit(' ', 1)[0] not in positions]
    positions.update(r['sfen'].rsplit(' ', 1)[0] for r in splits[name])
prior = float(np.mean([r['target_black'] for r in splits['train']]))
metrics = {}
for name, split in splits.items():
    assert len(split) == report['study']['metrics'][name]['positions']
    targets = np.asarray([r['target_black'] for r in split])
    metrics[name] = dict(positions=len(split), games=len({r['game_id'] for r in split}),
                        black_win_fraction=float(targets.mean()),
                        train_only_constant_brier=float(np.mean((targets-prior)**2)),
                        frozen_static_brier=report['study']['metrics'][name]['static_brier'],
                        frozen_blended_brier=report['study']['metrics'][name]['blended_brier'])
out = dict(archive_sha256=hashlib.sha256(raw).hexdigest(),
           train_only_constant_black_win_probability=prior, metrics=metrics,
           meaning='Post-freeze diagnostic baseline only; no model/blend tuning or additional model selection.')
output.write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps(out, indent=2))
