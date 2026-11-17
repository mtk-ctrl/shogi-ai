"""Floodgate自戦ログ（floodgate-moves-*.tsv）から、勝敗つきの静かな局面表を作る（雲路自身の対局のみ）。
出力: game_id, ply, result_black(1/0.5/0), sfen  → research/eval-tuning/fit_weights.py の --dataset 形式。
静かな局面: 指し手が駒取り・成り・王手回避でなく、序盤8手以降。"""
import sys, csv
import shogi
src, dst = sys.argv[1], sys.argv[2]
n = 0
with open(src, encoding='utf-8') as f, open(dst, 'w', encoding='utf-8') as o:
    for r in csv.DictReader(f, delimiter='\t'):
        if r['result'] not in ('win', 'lose'): continue
        ply = int(r['ply'])
        if ply < 8: continue
        our_black = r['side'] == 'sente'
        won = r['result'] == 'win'
        res = 1.0 if (won == our_black) else 0.0
        try:
            b = shogi.Board(r['sfen'])
            mv = shogi.Move.from_usi(r['usi'])
        except Exception:
            continue
        if b.is_check() or mv.promotion or (mv.from_square is not None and b.piece_at(mv.to_square)) or (mv.from_square is None and False):
            continue
        if b.piece_at(mv.to_square): continue
        o.write(f"{r['game_id']}\t{ply}\t{res}\t{r['sfen']}\n"); n += 1
print('samples', n)
