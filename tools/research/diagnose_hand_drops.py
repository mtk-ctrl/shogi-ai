#!/usr/bin/env python3
"""Reproducible hand-drop diagnosis, independent legality and short tactics.

Synthetic positions isolate motifs; they do not measure strength or prove
optimal moves in full games. No external engine recommendations are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import shogi
from diagnose_positions import Usi

ROOT = Path(__file__).resolve().parents[2]
VALUES = {shogi.PAWN:100, shogi.LANCE:300, shogi.KNIGHT:300,
          shogi.SILVER:500, shogi.GOLD:600, shogi.BISHOP:800, shogi.ROOK:1000,
          shogi.KING:0, shogi.PROM_PAWN:600, shogi.PROM_LANCE:600,
          shogi.PROM_KNIGHT:600, shogi.PROM_SILVER:600,
          shogi.PROM_BISHOP:1000, shogi.PROM_ROOK:1200}
UNPROMOTE = {shogi.PROM_PAWN:shogi.PAWN, shogi.PROM_LANCE:shogi.LANCE,
             shogi.PROM_KNIGHT:shogi.KNIGHT, shogi.PROM_SILVER:shogi.SILVER,
             shogi.PROM_BISHOP:shogi.BISHOP, shogi.PROM_ROOK:shogi.ROOK}


def sq(name):
    return shogi.SQUARE_NAMES.index(name)


def make_case(name, motif, pieces, hand, target, expected, note):
    board = shogi.Board(); board.clear()
    pieces=dict(pieces)
    if name not in ('fork_ignores_check','countercheck_silver_fork'):
        # Shield the test king from incidental rook checks; the countercheck
        # control deliberately removes this shelter.
        pieces.update({'9h':'P','8i':'P'})
    for square, symbol in pieces.items():
        board.set_piece_at(sq(square), shogi.Piece.from_symbol(symbol))
    board.add_piece_into_hand(shogi.Piece.from_symbol(hand).piece_type, shogi.BLACK)
    board.turn = shogi.BLACK
    return dict(id=name, motif=motif, sfen=board.sfen(), target=target,
                expected=expected, note=note)


def rotated(case):
    old = shogi.Board(case['sfen']); new = shogi.Board(); new.clear()
    for square in shogi.SQUARES:
        piece = old.piece_at(square)
        if piece:
            new.set_piece_at(80-square, shogi.Piece(piece.piece_type, 1-piece.color))
    for color in (shogi.BLACK, shogi.WHITE):
        for kind, count in old.pieces_in_hand[color].items():
            new.add_piece_into_hand(kind, 1-color, count)
    new.turn = 1-old.turn
    move = shogi.Move.from_usi(case['target'])
    reflected = shogi.Move(None if move.from_square is None else 80-move.from_square,
                          80-move.to_square, move.promotion, move.drop_piece_type)
    return dict(case, id=case['id']+'_white', sfen=new.sfen(), target=reflected.usi())


def fixtures():
    base = {'9i':'K', '1a':'k'}
    rows = [
        make_case('knight_royal_fork','両取り', {'9i':'K','6c':'k','4c':'r'}, 'N','N*5e','gain',
                  '王手で玉を動かし、桂で飛車を取る。'),
        make_case('knight_two_rooks','両取り', dict(base, **{'4c':'r','6c':'r'}), 'N','N*5e','gain',
                  '王手を伴わない桂の飛車二枚への両取り。'),
        make_case('silver_two_rooks','両取り', dict(base, **{'4d':'r','6d':'r'}), 'S','S*5e','gain',
                  '銀で二枚の飛車を同時に狙う。'),
        make_case('countercheck_silver_fork','反撃可能な両取り', dict(base, **{'4d':'r','6d':'r'}), 'S','S*5e','observe',
                  '玉の遮蔽物がなく、飛車の王手によって両取りを回避できる。形だけで有効と判定しない対照例。'),
        make_case('bishop_two_rooks','両取り', dict(base, **{'3c':'r','7c':'r'}), 'B','B*5e','gain',
                  '角の二方向の射線で二枚の飛車を狙う。'),
        make_case('bishop_royal_skewer','串刺し', {'9i':'K','5e':'k','3c':'r'}, 'B','B*7g','gain',
                  '角で玉の背後の飛車を狙う。'),
        make_case('rook_royal_skewer','串刺し', {'9i':'K','5e':'k','5b':'b'}, 'R','R*5h','gain',
                  '飛車で玉の背後の角を狙う。'),
        make_case('lance_royal_skewer','串刺し', {'9i':'K','5e':'k','5b':'r'}, 'L','L*5h','gain',
                  '香で玉の背後の飛車を狙う。'),
        make_case('pawn_rook_harassment','攻め駒への当たり', dict(base, **{'5d':'r','4f':'G','5g':'S'}), 'P','P*5e','observe',
                  '銀取りを遮断し、金で支えた歩で相手飛車に当てる。別の有効な受けもあり、指定手のみを正解とはしない。'),
        make_case('capture_instead_of_harassment','直接の駒取りがある対照例', dict(base, **{'5d':'r','4f':'G','5g':'R'}), 'P','P*5e','observe',
                  '歩で飛車に当てることもできるが、自分の飛車で相手飛車を直接取れる。打ち手を選ばなくても見落としではない。'),
        make_case('gold_drop_mate','攻め', dict(base, **{'2f':'R'}), 'G','G*2b','mate',
                  '飛車に支えられた金打ちの一手詰め。'),
        make_case('poisoned_silver_fork','偽の両取り', dict(base, **{'4d':'r','6d':'r','5d':'p'}), 'S','S*5e','avoid',
                  '二枚の飛車に当たるが、歩で銀を取られる。'),
        make_case('poisoned_bishop_skewer','偽の串刺し', {'9i':'K','5e':'k','3c':'r','6g':'g'}, 'B','B*7g','avoid',
                  '王手の串刺しに見えるが、金で角を取って王手を解消できる。'),
        make_case('fork_ignores_check','王手放置', {'9i':'K','6c':'k','4c':'r','9a':'r'}, 'N','N*5e','illegal',
                  '桂の両取りは自玉への飛車の王手を解消せず、合法候補にならない。'),
    ]
    return [item for case in rows for item in (case, rotated(case))]


def material(board, root):
    value = 0
    for square in shogi.SQUARES:
        piece = board.piece_at(square)
        if piece: value += VALUES[piece.piece_type] * (1 if piece.color == root else -1)
    for color in (0, 1):
        value += sum(VALUES[k]*n for k,n in board.pieces_in_hand[color].items()) * (1 if color == root else -1)
    return value


def delta(board, move, root):
    sign = 1 if board.turn == root else -1
    captured = board.piece_at(move.to_square)
    change = VALUES[captured.piece_type] + VALUES[UNPROMOTE.get(captured.piece_type, captured.piece_type)] if captured else 0
    if move.promotion:
        piece = board.piece_at(move.from_square)
        promoted = {v:k for k,v in UNPROMOTE.items()}[piece.piece_type]
        change += VALUES[promoted] - VALUES[piece.piece_type]
    return sign * change


def exchange_certificate(case):
    """Exact material minimax for target -> reply -> move -> reply (4 plies).

    The last ply uses move deltas rather than pushing positions. Checkmate at
    intermediate nodes overrides material. Future tactics beyond this horizon
    are deliberately not claimed. Includes every legal reply, not only escapes.
    """
    board = shogi.Board(case['sfen']); root = board.turn
    target = shogi.Move.from_usi(case['target'])
    legal = list(board.legal_moves)
    if target not in legal: return {'legal':False}
    initial = material(board, root)
    board.push(target)
    if board.is_checkmate(): return {'legal':True,'mate_in_one':True}
    worst = 10**9; worst_line = []
    reply_count = 0
    for reply in list(board.legal_moves):
        reply_count += 1; board.push(reply)
        if board.is_checkmate():
            best = -10**8; best_line = [reply.usi()]
        else:
            current = material(board, root)
            best = -10**9; best_line = []
            for follow in list(board.legal_moves):
                next_value = current + delta(board, follow, root)
                board.push(follow)
                responses = list(board.legal_moves)
                if not responses:
                    value = 10**8; response = None
                else:
                    response = min(responses, key=lambda m:delta(board,m,root))
                    value = next_value + delta(board,response,root)
                board.pop()
                if value > best:
                    best = value
                    best_line = [reply.usi(), follow.usi()] + ([response.usi()] if response else [])
        board.pop()
        if best < worst: worst = best; worst_line = best_line
    return {'legal':True,'reply_count':reply_count,'material_gain_4ply':worst-initial,
            'worst_witness':[case['target']]+worst_line,
            'scope':'four-ply material result, not a full-game guarantee'}


def full_search(engine, sfen, ms):
    engine.send('usinewgame'); engine.send('position sfen '+sfen)
    engine.send(f'go movetime {ms}')
    _, lines = engine.wait('bestmove ', max(30,ms/1000+10))
    move = lines[-1].split()[1]
    latest = {}
    for line in lines:
        parts = line.split()
        if line.startswith('info depth '):
            latest = {'depth':int(parts[parts.index('depth')+1]),
                      'pv':parts[parts.index('pv')+1:] if 'pv' in parts else []}
            if 'score' in parts: latest['score']=parts[parts.index('score')+1:parts.index('score')+3]
    return dict(latest,bestmove=move,raw=lines)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',default='build/shogi-ai')
    parser.add_argument('--probe',default='build/hand-drop-probe')
    parser.add_argument('--output',default='benchmarks/results/2026-10-06_hand-drop-diagnosis.json')
    parser.add_argument('--only', help='Run case IDs containing this substring')
    args=parser.parse_args()
    cases=fixtures()
    fixture_path=ROOT/'benchmarks/positions/hand_drop_cases.json'
    fixture_path.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    if args.only: cases=[case for case in cases if args.only in case['id']]
    engine_path=(ROOT/args.engine).resolve(); probe_path=(ROOT/args.probe).resolve()
    engine=Usi(str(engine_path),{'OpeningBook':False,'ExperienceCache':False})
    rows=[]
    try:
        for case in cases:
            board=shogi.Board(case['sfen'])
            previous_side=shogi.Board(case['sfen']); previous_side.turn=1-board.turn
            assert not previous_side.is_check(), 'non-moving king is already in check: '+case['id']
            certificate=exchange_certificate(case)
            expected=case['expected']
            assert certificate['legal'] == (expected!='illegal'), case['id']
            if expected=='gain': assert certificate['material_gain_4ply']>0, (case['id'],certificate)
            if expected=='mate': assert certificate.get('mate_in_one'), case['id']
            if expected=='avoid': assert certificate['material_gain_4ply']<0, (case['id'],certificate)
            modes={'50ms':(45,64,False,True,False),'500ms':(490,64,False,True,False),
                   'depth3':(0,3,False,True,False),'material_depth3':(0,3,True,True,False),
                   'no_q_depth3':(0,3,False,False,False)}
            if certificate['legal']: modes['target_depth3']=(0,3,False,True,True)
            commands=''.join('|'.join(map(str,[case['sfen'],case['target'],ms,depth,int(mat),int(q),int(forced)]))+'\n'
                             for ms,depth,mat,q,forced in modes.values())
            result=subprocess.run([str(probe_path)],input=commands,capture_output=True,text=True,timeout=120,check=True)
            outputs=[json.loads(line) for line in result.stdout.splitlines()]
            assert len(outputs)==len(modes)
            diagnostic=dict(zip(modes,outputs))
            full={str(ms):full_search(engine,case['sfen'],ms) for ms in (50,500)}
            for output in [*diagnostic.values(),*full.values()]:
                move=shogi.Move.from_usi(output['bestmove'])
                assert move in board.legal_moves, (case['id'],output)
                replay=shogi.Board(case['sfen'])
                for pv_move in output.get('pv',[]):
                    parsed=shogi.Move.from_usi(pv_move)
                    assert parsed in replay.legal_moves, (case['id'],pv_move,output)
                    replay.push(parsed)
            selected_certificates={case['target']:certificate}
            if expected in ('gain','mate'):
                for selected in {output['bestmove'] for output in full.values()}:
                    if selected not in selected_certificates:
                        selected_certificates[selected]=exchange_certificate(dict(case,target=selected))
            row=dict(case,certificate=certificate,core=diagnostic,production=full,
                     selected_certificates=selected_certificates)
            rows.append(row)
            print(case['id'],case['target'],certificate.get('material_gain_4ply','mate/illegal'),
                  '50ms='+full['50']['bestmove'],'500ms='+full['500']['bestmove'],flush=True)
            # Checkpoint each completed case; final metadata is rewritten below.
            (ROOT/args.output).parent.mkdir(parents=True,exist_ok=True)
            (ROOT/args.output).write_text(json.dumps({'complete':False,'rows':rows},ensure_ascii=False,indent=2)+'\n')
    finally: engine.close()
    output={'complete':True,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'engine_sha256':hashlib.sha256(engine_path.read_bytes()).hexdigest(),
            'probe_sha256':hashlib.sha256(probe_path.read_bytes()).hexdigest(),
            'conditions':{'book':False,'experience':False,'production_mate_assist':True,'seed':5489,
                          'core_ms_includes_io_margin':[45,490],
                          'root_trace':'build-only callback; non-forced returned scores may be bounds',
                          'positions':'synthetic sparse boards with both colors; not a strength benchmark'},
            'rows':rows}
    (ROOT/args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__': main()
