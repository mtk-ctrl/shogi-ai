"""Turn arena self-play JSON into quiet-position samples with game results (own games only).

Output TSV: game_id, ply, result_black (1/0.5/0), sfen. Positions are skipped when the move
played from them is a capture, promotion or played in check, or when the previous move was a
capture, so the static evaluation is a fair stand-in for a quiet position.
"""
import argparse, json, sys
import shogi

ap = argparse.ArgumentParser()
ap.add_argument('inputs', nargs='+')
ap.add_argument('--output', required=True)
ap.add_argument('--min-ply', type=int, default=8)
args = ap.parse_args()
rows = 0
with open(args.output, 'w', encoding='utf-8') as out:
    for path in args.inputs:
        data = json.load(open(path))
        for gi, g in enumerate(data['details']):
            if g['winner'] not in ('A', 'B') and g['reason'] not in ('fourfold_repetition', 'draw', 'max_plies'):
                continue
            a_black = g['a_black']
            if g['winner'] == 'A': black_won = a_black
            elif g['winner'] == 'B': black_won = not a_black
            else: black_won = None
            res = 0.5 if black_won is None else (1.0 if black_won else 0.0)
            if g['reason'] == 'max_plies': continue
            board = shogi.Board()
            recs = g['move_records']
            for ply, mv in enumerate(g['moves']):
                r = recs[ply] if ply < len(recs) else {}
                prev = recs[ply - 1] if ply > 0 and ply - 1 < len(recs) else {}
                quiet = (ply >= args.min_ply and not r.get('is_capture') and not r.get('is_promotion')
                         and not r.get('in_check_before') and not prev.get('is_capture'))
                if quiet:
                    out.write(f"{path.split('/')[-1]}:{gi}\t{ply}\t{res}\t{board.sfen()}\n"); rows += 1
                board.push_usi(mv)
print('samples', rows)
