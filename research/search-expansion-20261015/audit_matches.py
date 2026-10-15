"""Independently reconcile downloaded raw/summary/played archives and replay moves."""
import argparse, collections, gzip, hashlib, json, math, statistics, zipfile
from pathlib import Path
import shogi

ap = argparse.ArgumentParser()
ap.add_argument('--artifacts', required=True)
ap.add_argument('--output', required=True)
ap.add_argument('--seed', type=int, default=2026101500)
ap.add_argument('--games-per-shard', type=int, default=20)
ap.add_argument('--baseline-ref', default='7ab3dab9b909503d340fb1f374da09f8d0e2e209')
args = ap.parse_args()
artifacts = json.loads(Path(args.artifacts).read_text())
out = {}
for run in sorted({a['run'] for a in artifacts}):
    group = [a for a in artifacts if a['run'] == run]
    raw, summary, archive, manifest = {}, None, None, None
    for a in group:
        data = Path(a['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == a['digest'].split(':')[1]
        with zipfile.ZipFile(a['path']) as z:
            if a['name'].startswith('played-move-archive'):
                manifest = json.loads(z.read('manifest.json'))
                packed = z.read('played-games.jsonl.gz')
                assert hashlib.sha256(packed).hexdigest() == manifest['archive_sha256']
                archive = [json.loads(line) for line in gzip.decompress(packed).splitlines()]
            elif a['name'].startswith('generic-engine-match-summary'):
                summary = json.loads(z.read('aggregate.json'))
            else:
                name = z.namelist()[0]
                content = z.read(name)
                raw[name] = (content, json.loads(content))
    assert summary and archive and manifest
    assert summary['ref_a'] == manifest['requested_ref_a'] == '4d8a4b9723c21c6163cad03358ba35e4b93d4687'
    assert summary['ref_b'] == manifest['requested_ref_b'] == args.baseline_ref
    assert len(raw) == 100 // args.games_per_shard
    sources = {s['file']: s for s in manifest['sources']}
    records = {(g['source_id'], g['source_game_index']): g for g in archive}
    stats = {side: collections.defaultdict(list) for side in ['A','B']}
    wins = collections.Counter(); blacks = collections.Counter()
    plies = 0; games = 0; long_max = 0
    mask = summary['options_a']['SearchResearchMask']
    binaries = None
    for index, (name, (content, data)) in enumerate(sorted(raw.items())):
        source = sources[name]
        assert hashlib.sha256(content).hexdigest() == source['source_id']
        assert data['games'] == len(data['details']) == args.games_per_shard
        assert data['game_offset'] == index * args.games_per_shard
        assert data['seed'] == args.seed + index * 100000
        hashes = (data['sha256_a'], data['sha256_b'])
        if binaries is None: binaries = hashes
        assert hashes == binaries
        assert data['go_command'] == 'go movetime 200' and data['max_plies'] == 300
        assert data['options_a'] == summary['options_a'] and data['options_b'] == summary['options_b']
        assert data['illegal_games'] == 0
        for side in ['A','B']:
            k = data['position_knowledge'][side]
            assert k['enabled'] and k['available'] and k['positions'] == 163
            assert k['sha256'] == '6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'
            options = data['options_a' if side == 'A' else 'options_b']
            assert options['AdaptiveLongThink'] and options['OpeningRandomNonLance']
        assert data['options_a']['SearchResearchMask'] == mask
        for i, game in enumerate(data['details']):
            compressed = records[(source['source_id'], i)]
            assert game['a_black'] == ((data['game_offset'] + i) % 2 == 0)
            assert [m['move'] for m in compressed['moves']] == game['moves']
            assert game['winner'] == compressed['winner'] and game['final_sfen'] == compressed['final_sfen']
            assert len(game['moves']) == game['plies'] == len(game['move_records'])
            wins[game['winner']] += 1; blacks['A' if game['a_black'] else 'B'] += 1
            board = shogi.Board(); long = {'A':[], 'B':[]}
            for m, record, saved in zip(game['moves'], game['move_records'], compressed['moves']):
                assert m == record['move'] == saved['move']
                parsed = shogi.Move.from_usi(m)
                assert board.is_legal(parsed), (run, name, i, m)
                side = record['engine']
                assert side == ('A' if (board.turn == shogi.BLACK) == game['a_black'] else 'B')
                board.push(parsed)
                search = record['search']
                assert search['phase_version'] == 1
                for field in ['depth','nodes','elapsed_ms','knowledge_probes','knowledge_hits','knowledge_promotions']:
                    if field in search: stats[side][field].append(search[field])
                if 'long_think_used' in search:
                    assert search['long_think_base_ms'] == 200 and search['long_think_max_ms'] == 1000
                    long[side].append(search['long_think_used'])
            assert board.sfen() == game['final_sfen']
            for seq in long.values():
                assert seq == list(range(1, len(seq)+1)) and len(seq) <= 10
                long_max = max(long_max, len(seq))
            plies += game['plies']; games += 1
    assert games == summary['games'] == manifest['games'] == 100
    assert plies == manifest['plies'] and wins['A'] == summary['wins_a'] and wins['B'] == summary['wins_b']
    assert blacks == {'A':50, 'B':50}
    draws = games - wins['A'] - wins['B']
    assert draws == summary['draws']
    score = (wins['A'] + draws * .5) / games
    variance = (wins['A'] + draws*.25 - games*score*score) / (games-1)
    half = 1.96 * math.sqrt(variance / games)
    observed = {side: {field: {'n':len(vals),'total':sum(vals),'mean':statistics.mean(vals),'max':max(vals)}
                        for field, vals in fields.items()} for side, fields in stats.items()}
    out[str(run)] = {'mask':mask,'wins':wins['A'],'draws':draws,'losses':wins['B'],
                    'score':score,'approx_95pct':[score-half,score+half],
                    'games':games,'plies':plies,'a_black':blacks['A'],'illegal_replay':0,
                    'max_long_uses':long_max,'summary':summary,'telemetry':observed,
                    'archive_manifest':{k:v for k,v in manifest.items() if k!='sources'},
                    'artifacts':[{k:v for k,v in a.items() if k!='path'} for a in group]}
    print(run, 'PASS', wins, 'plies', plies, flush=True)
Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
