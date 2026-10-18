"""Train a research-only move-order prior from archived, actually played moves.

The temporary legal candidate matrix is deliberately not part of the durable
output. Predictions prioritize search, and are never treated as correct moves.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def collect(inputs, output):
    import shogi
    seen_games, occupied = set(), set()
    groups = [[], [], []]
    receipts = []
    counts = dict(games=0, duplicate_games=0, verified_plies=0, eligible=0,
                  cross_split_positions_removed=0)
    for root in map(Path, inputs):
        manifest = json.loads((root / 'manifest.json').read_text())
        archive = root / manifest['archive']
        raw = archive.read_bytes()
        if len(raw) != manifest['archive_bytes'] or digest(raw) != manifest['archive_sha256']:
            raise ValueError('archive identity mismatch: ' + str(root))
        metadata = {x['source_id']: x['metadata'] for x in manifest['sources']}
        receipts.append(dict(run_id=manifest['run_id'], archive_sha256=digest(raw),
                             archive_bytes=len(raw), games=manifest['games']))
        with gzip.open(archive, 'rt') as f:
            for line in f:
                g = json.loads(line)
                game_hash = digest(' '.join(m['move'] for m in g['moves']).encode())
                b = shogi.Board()
                eligible = []
                meta = metadata[g['source_id']]
                if meta['sha256_b'] != '2de18d82f89b9fd1e6795ef6905f4a9bb46023771d7651a96b5f5682e1338f36':
                    raise ValueError('unrecognized own parent binary')
                for row in g['moves']:
                    m = shogi.Move.from_usi(row['move'])
                    if m not in b.legal_moves:
                        raise ValueError('illegal actual move: ' + g['game_id'])
                    s = row.get('search', {})
                    if (row['engine'] == 'B' and s.get('score_status') == 'recorded'
                            and s.get('score_cp_stm') is not None and s.get('depth', 0) >= 2
                            and not s.get('knowledge_hits', 0)):
                        key = ' '.join(b.sfen().split()[:3])
                        eligible.append(dict(game_hash=game_hash, game_id=g['game_id'],
                            run_id=manifest['run_id'], ply=row['ply'], move=row['move'],
                            sfen=b.sfen(), key=key, depth=s['depth']))
                    b.push(m)
                    counts['verified_plies'] += 1
                if b.sfen() != g['final_sfen'] or len(g['moves']) != g['plies']:
                    raise ValueError('final position mismatch')
                if game_hash in seen_games:
                    counts['duplicate_games'] += 1
                    continue
                seen_games.add(game_hash)
                counts['games'] += 1
                counts['eligible'] += len(eligible)
                bucket = int(game_hash[:8], 16) % 100
                group = 0 if bucket < 70 else (1 if bucket < 85 else 2)
                # The target choice is never part of the selection hash.
                eligible.sort(key=lambda r: digest((game_hash + ':' + str(r['ply'])).encode()))
                groups[group].extend(eligible[:8])
    for group in groups:
        kept = []
        for r in group:
            if r['key'] in occupied:
                counts['cross_split_positions_removed'] += 1
            else:
                occupied.add(r['key'])
                kept.append(r)
        group[:] = kept
    if any(len(g) < 50 for g in groups):
        raise ValueError('insufficient independent split')
    output.mkdir(parents=True, exist_ok=False)
    for i, name in enumerate(('train', 'validation', 'test')):
        with (output / (name + '-actual-choices.jsonl')).open('w') as f:
            for r in groups[i]:
                r['split'] = name
                f.write(json.dumps(r, sort_keys=True) + '\n')
    (output / 'inputs.json').write_text(json.dumps(dict(receipts=receipts, counts=counts,
        samples={n: len(g) for n, g in zip(('train', 'validation', 'test'), groups)}), indent=2) + '\n')
    return groups


def matrices(groups, probe):
    import numpy as np
    all_rows = [r for g in groups for r in g]
    text = ''.join(r['sfen'] + '\n' for r in all_rows)
    result = subprocess.run([str(Path(probe).resolve())], input=text, text=True,
                            check=True, capture_output=True)
    lines = result.stdout.splitlines()
    if len(lines) != len(all_rows):
        raise ValueError('feature probe row mismatch')
    features, starts, ends, targets = [], [], [], []
    for row, line in zip(all_rows, lines):
        candidates = json.loads(line)['moves']
        moves = [c['move'] for c in candidates]
        if len(moves) != len(set(moves)) or row['move'] not in moves:
            raise ValueError('invalid candidate feature list')
        starts.append(len(features))
        targets.append(len(features) + moves.index(row['move']))
        features.extend(c['x'] for c in candidates)
        ends.append(len(features))
    x = np.asarray(features, dtype=np.float64) / 8
    a, b, y = (np.asarray(t, dtype=np.int64) for t in (starts, ends, targets))
    sizes = b-a
    rows = np.repeat(np.arange(len(a)), sizes)
    return x, a, b, y, rows


def train(groups, data, output):
    import numpy as np
    x, starts, ends, targets, rows = data
    lengths = [len(g) for g in groups]
    n = lengths[0]
    nval = n + lengths[1]
    train_end = ends[n-1]
    tx, ta, ty, tr = x[:train_end], starts[:n], targets[:n], rows[:train_end]
    penalties = (0.001, 0.01, 0.1)
    def measure(w, first, last):
        first_c, last_c = starts[first], ends[last-1]
        logits = x[first_c:last_c] @ w
        local_starts = starts[first:last] - first_c
        maximum = np.maximum.reduceat(logits, local_starts)
        exp = np.exp(logits - np.repeat(maximum, ends[first:last]-starts[first:last]))
        sums = np.add.reduceat(exp, local_starts)
        chosen = targets[first:last]-first_c
        losses = np.log(sums)+maximum-logits[chosen]
        ranks = [1+int(np.count_nonzero(logits[a:b] > logits[y])) for a,b,y in
                 zip(local_starts, ends[first:last]-first_c, chosen)]
        return dict(loss=float(np.mean(losses)), top1=float(np.mean(np.asarray(ranks)==1)),
                    top6=float(np.mean(np.asarray(ranks)<=6)), mean_rank=float(np.mean(ranks)),
                    positions=last-first)
    fitted = []
    for penalty in penalties:
        w = np.zeros(64)
        m, v = w.copy(), w.copy()
        for epoch in range(1, 301):
            logits = tx @ w
            maximum = np.maximum.reduceat(logits, ta)
            exp = np.exp(logits-maximum[tr])
            sums = np.add.reduceat(exp, ta)
            residual = exp/sums[tr]
            residual[ty] -= 1
            gradient = tx.T @ residual/n + penalty*w
            m = .9*m + .1*gradient
            v = .999*v + .001*gradient*gradient
            w -= .03*(m/(1-.9**epoch))/(np.sqrt(v/(1-.999**epoch))+1e-8)
        fitted.append((measure(w,n,nval)['loss'], penalty, w))
    _, penalty, weights = min(fitted, key=lambda t:(t[0],t[1]))
    quantized = np.rint(weights*10000/8).astype(np.int64)
    deployed = quantized*8/10000
    report = dict(schema_version=1, features=64, units=8, epochs=300,
        selected_l2=penalty, validation_candidates=[dict(l2=p,loss=l) for l,p,_ in fitted],
        train=measure(deployed,0,n), validation=measure(deployed,n,nval),
        test=measure(deployed,nval,sum(lengths)),
        weights=quantized.tolist(), scope='search ordering only; actual own parent choices')
    raw = (json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    sha = digest(raw)
    (output / 'model.json').write_bytes(raw)
    (output / 'selfplay_order_weights.h').write_text(
        '#pragma once\n#include <array>\nnamespace shogi::strategy {\n'
        'inline constexpr std::array<int,64> SelfplayOrderWeights{' + ','.join(map(str,quantized)) + '};\n'
        'inline constexpr const char* SelfplayOrderModel = "'+sha+'";\n'
        'inline constexpr bool SelfplayOrderReady = true;\n}\n')
    print(json.dumps(dict(model_sha256=sha,train=report['train'],validation=report['validation'],
                         test=report['test'], selected_l2=penalty),indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--inputs', nargs='+', required=True)
    p.add_argument('--probe', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    groups = collect(args.inputs,args.output)
    train(groups,matrices(groups,args.probe),args.output)


if __name__ == '__main__':
    main()
