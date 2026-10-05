"""Descriptive move flags, not automatic judgments of good or bad shogi."""
import argparse
import json
from pathlib import Path
import shogi

p=argparse.ArgumentParser();p.add_argument('--match',required=True);p.add_argument('--output',required=True);a=p.parse_args()
match=json.loads(Path(a.match).read_text())
counts={label:{'moves':0,'king_moves_first40plies':0,'king_forward_first40plies':0,'unguarded_major_captured_next':0,'premature_nonpromotion':0,'uncompensated_major_capture_next':0} for label in ['A','B']}
examples=[]
values={shogi.PAWN:100,shogi.LANCE:300,shogi.KNIGHT:300,shogi.SILVER:500,shogi.GOLD:600,
        shogi.BISHOP:800,shogi.ROOK:1000,shogi.KING:0,shogi.PROM_PAWN:600,shogi.PROM_LANCE:600,
        shogi.PROM_KNIGHT:600,shogi.PROM_SILVER:600,shogi.PROM_BISHOP:1000,shogi.PROM_ROOK:1200}
def material(board):
    result=0
    for square in shogi.SQUARES:
        pc=board.piece_at(square)
        if pc:result+=(1 if pc.color==shogi.BLACK else -1)*values[pc.piece_type]
    for color,hand in enumerate(board.pieces_in_hand):
        result+=(1 if color==shogi.BLACK else -1)*sum(values[k]*n for k,n in hand.items())
    return result

for gi,game in enumerate(match['details']):
    b=shogi.Board()
    for ply,token in enumerate(game['moves']):
        mover=b.turn;label='A' if (mover==shogi.BLACK)==game['a_black'] else 'B'
        m=shogi.Move.from_usi(token);piece=b.piece_at(m.from_square) if m.from_square is not None else None
        counts[label]['moves']+=1
        if piece and piece.piece_type==shogi.KING and ply<40:
            counts[label]['king_moves_first40plies']+=1
            dr=m.to_square//9-m.from_square//9
            if (dr<0)==(mover==shogi.BLACK) and dr:
                counts[label]['king_forward_first40plies']+=1
        if piece and piece.piece_type in [shogi.PAWN,shogi.BISHOP,shogi.ROOK] and not m.promotion:
            promoted=shogi.Move(m.from_square,m.to_square,promotion=True)
            counts[label]['premature_nonpromotion']+=int(promoted in b.legal_moves)
        before=b.sfen();before_material=material(b);was_check=b.is_check();b.push(m)
        if ply+1<len(game['moves']):
            reply=shogi.Move.from_usi(game['moves'][ply+1]);victim=b.piece_at(reply.to_square)
            if victim and victim.color==mover and victim.piece_type in [shogi.ROOK,shogi.BISHOP,shogi.PROM_ROOK,shogi.PROM_BISHOP]:
                if not b.is_attacked_by(mover,reply.to_square):
                    counts[label]['unguarded_major_captured_next']+=1
                    b.push(reply);delta=(material(b)-before_material)*(1 if mover==shogi.BLACK else -1);b.pop()
                    if delta<0:counts[label]['uncompensated_major_capture_next']+=1
                    examples.append({'net_material_cp_over_two_plies':delta,'was_in_check':was_check,'game':gi+1,'ply':ply+1,'side':label,'move':token,'next_move':game['moves'][ply+1],
                                     'before_sfen':before,'after_sfen':b.sfen(),'winner':game['winner']})
result={'source':a.match,'note':'Flags are descriptive, may include sound sacrifices; geometric defense ignores pins. First40 means game plies, not own moves.',
        'counts':counts,'unguarded_major_capture_examples':examples}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(counts,indent=2))
