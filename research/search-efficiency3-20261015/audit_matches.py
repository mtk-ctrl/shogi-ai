"""Independently reconcile downloaded raw/summary/played archives and replay moves."""
import argparse, collections, gzip, hashlib, json, math, statistics, zipfile
from pathlib import Path
import shogi

ap = argparse.ArgumentParser()
ap.add_argument('--artifacts', required=True)
ap.add_argument('--output', required=True)
ap.add_argument('--seed', type=int, default=2026101500)
ap.add_argument('--shards', type=int, required=True)
ap.add_argument('--baseline-ref', required=True)
ap.add_argument('--candidate-ref', required=True)
ap.add_argument('--reuse-mask', type=int, required=True)
ap.add_argument('--binary-hashes', required=True)
args = ap.parse_args()
artifacts = json.loads(Path(args.artifacts).read_text())
expected_hashes = json.loads(Path(args.binary_hashes).read_text())
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
    assert summary['ref_a'] == manifest['requested_ref_a'] == args.candidate_ref
    assert summary['ref_b'] == manifest['requested_ref_b'] == args.baseline_ref
    assert len(raw) == args.shards
    sources = {s['file']: s for s in manifest['sources']}
    records = {(g['source_id'], g['source_game_index']): g for g in archive}
    stats = {side: collections.defaultdict(list) for side in ['A','B']}
    wins = collections.Counter(); blacks = collections.Counter()
    color_results = {'A_black':collections.Counter(),'A_white':collections.Counter()}
    score_statuses = collections.Counter()
    plies = 0; games = 0; long_max = 0
    mask = args.reuse_mask
    assert summary['options_a']['SearchReuseMask'] == mask
    assert 'SearchReuseMask' not in summary['options_b']
    binaries = None
    for index, (name, (content, data)) in enumerate(sorted(raw.items())):
        source = sources[name]
        for key, value in source['metadata'].items(): assert data[key] == value
        shard_wins = collections.Counter()
        assert hashlib.sha256(content).hexdigest() == source['source_id']
        q, remainder = divmod(100, args.shards)
        expected_games = q + (index < remainder)
        expected_offset = index * q + min(index, remainder)
        assert data['games'] == len(data['details']) == expected_games
        assert data['game_offset'] == expected_offset
        assert data['seed'] == args.seed + index * 100000
        hashes = (data['sha256_a'], data['sha256_b'])
        assert hashes == (expected_hashes['engine-a'], expected_hashes['engine-b'])
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
            assert options['SearchResearchMask'] == 23
            assert options['SearchEfficiencyMask'] == 8
        assert data['options_a']['SearchReuseMask'] == mask
        assert data['options_a']['SearchResearchMask'] == 23
        for i, game in enumerate(data['details']):
            compressed = records[(source['source_id'], i)]
            assert game['a_black'] == ((data['game_offset'] + i) % 2 == 0)
            assert [m['move'] for m in compressed['moves']] == game['moves']
            assert game['winner'] == compressed['winner'] and game['final_sfen'] == compressed['final_sfen']
            assert len(game['moves']) == game['plies'] == len(game['move_records'])
            color_results['A_black' if game['a_black'] else 'A_white'][str(game['winner'])] += 1
            wins[game['winner']] += 1; shard_wins[game['winner']] += 1; blacks['A' if game['a_black'] else 'B'] += 1
            board = shogi.Board(); long = {'A':[], 'B':[]}
            for m, record, saved in zip(game['moves'], game['move_records'], compressed['moves']):
                assert m == record['move'] == saved['move']
                for field, value in saved.items():
                    if field != 'search': assert record.get(field) == value
                score_statuses[saved['search']['score_status']] += 1
                original_search = record['search']
                for field, value in saved['search'].items():
                    if field == 'score_status':
                        nscore = sum(original_search.get(f) is not None for f in ['score_cp_stm','score_mate_stm'])
                        assert value == ('ambiguous' if nscore == 2 else 'recorded' if nscore else 'not_recorded')
                    else: assert original_search.get(field) == value
                assert 'pv' not in saved['search']
                parsed = shogi.Move.from_usi(m)
                assert board.is_legal(parsed), (run, name, i, m)
                assert record['ply'] == board.move_number
                assert record['side_to_move'] == ('black' if board.turn == shogi.BLACK else 'white')
                assert record['in_check_before'] == board.is_check()
                assert record['legal_moves_before'] == sum(1 for _ in board.legal_moves)
                assert record['is_capture'] == (board.piece_at(parsed.to_square) is not None)
                assert record['is_promotion'] == bool(parsed.promotion)
                assert record['is_drop'] == (parsed.drop_piece_type is not None)
                side = record['engine']
                assert side == ('A' if (board.turn == shogi.BLACK) == game['a_black'] else 'B')
                board.push(parsed)
                assert record['gave_check'] == board.is_check()
                search = record['search']
                assert search['phase_version'] == 1
                if 'research_mask' in search: assert search['research_mask'] == 23
                if 'efficiency_mask' in search: assert search['efficiency_mask'] == 8
                if 'reuse_mask' in search: assert search['reuse_mask'] == (mask if side == 'A' else 0)
                for field in ['depth','nodes','qnodes','elapsed_ms','knowledge_probes','knowledge_hits','knowledge_promotions','research_mask','efficiency_mask','reuse_mask','legal_cache_hits','legal_cache_misses','selective_usi_skipped']:
                    if field in search: stats[side][field].append(search[field])
                if 'long_think_used' in search:
                    assert search['long_think_base_ms'] == 200 and search['long_think_max_ms'] == 1000
                    long[side].append(search['long_think_used'])
            assert board.sfen() == game['final_sfen']
            for seq in long.values():
                assert seq == list(range(1, len(seq)+1)) and len(seq) <= 10
                long_max = max(long_max, len(seq))
            plies += game['plies']; games += 1
        assert shard_wins['A'] == data['wins_a'] and shard_wins['B'] == data['wins_b']
        assert data['draws'] == data['games'] - shard_wins['A'] - shard_wins['B']
        assert abs(data['average_plies'] - sum(g['plies'] for g in data['details']) / data['games']) < 1e-8
    assert score_statuses['recorded'] == manifest['scored_plies']
    assert score_statuses['ambiguous'] == manifest['ambiguous_score_plies']
    assert score_statuses['not_recorded'] == manifest['missing_score_plies']
    assert manifest['phase_recorded_plies'] == manifest['plies'] and manifest['phase_missing_plies'] == 0
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
    out[str(run)] = {'reuse_mask':mask,'efficiency_mask':8,'research_mask':23,'candidate_ref':args.candidate_ref,'baseline_ref':args.baseline_ref,'wins':wins['A'],'draws':draws,'losses':wins['B'],
                    'score':score,'approx_95pct':[score-half,score+half],
                    'games':games,'plies':plies,'a_black':blacks['A'],'illegal_replay':0,
                    'max_long_uses':long_max,'summary':summary,'telemetry':observed,
                    'archive_manifest':{k:v for k,v in manifest.items() if k!='sources'},
                    'binary_sha256':expected_hashes,'color_results':color_results,'score_statuses':score_statuses,
                    'artifacts':[{k:v for k,v in a.items() if k!='path'} for a in group]}
    print(run, 'PASS', wins, 'plies', plies, flush=True)
Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
