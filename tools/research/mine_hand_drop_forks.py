#!/usr/bin/env python3
"""Screen self-play positions for drop forks and skewers, then diagnose.

Geometry is a candidate screen, not a proof of advantage. Preserve source
game/ply and its actual move; do not treat a different engine choice as a miss.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shogi
from diagnose_hand_drops import ROOT, delta, full_search
from diagnose_positions import Usi


def drop_targets(board, move):
    """All enemy kinds; also the first enemy behind each sliding target.

    Rear targets are potential pressure, not simultaneous legal captures.
    """
    enemy=1-board.turn
    targets=sum(1<<s for s in shogi.SQUARES
                if board.piece_at(s) and board.piece_at(s).color==enemy)
    attack=board.attacks_from(move.drop_piece_type,move.to_square,board.occupied,board.turn)&targets
    rear=0
    if move.drop_piece_type in (shogi.LANCE,shogi.BISHOP,shogi.ROOK):
        for square in shogi.SQUARES:
            if attack&(1<<square):
                occupied=shogi.Occupied(board.occupied[shogi.BLACK]&~(1<<square),
                                        board.occupied[shogi.WHITE]&~(1<<square))
                rear |= board.attacks_from(move.drop_piece_type,move.to_square,occupied,board.turn)&targets&~attack
    return attack,rear


def immediate_capture_screen(board, move):
    """Reject free drops and unfavorable immediate capture/recapture trades.

    Geometric attacks include pinned pieces. Check actual legal captures after
    the drop, and legal recaptures if needed. This is a candidate filter only:
    it does not establish safety after subsequent replies or defender removal.
    """
    root=board.turn
    if not board.is_attacked_by(1-root,move.to_square):
        return {'accepted':True,'legal_captures':0,'scope':'immediate capture/recapture only'}
    board.push(move)
    captures=[m for m in board.legal_moves if m.to_square==move.to_square and m.from_square is not None]
    worst=None
    for reply in captures:
        loss=delta(board,reply,root)
        board.push(reply)
        recaptures=[m for m in board.legal_moves if m.to_square==move.to_square and m.from_square is not None]
        gain=loss+max([delta(board,m,root) for m in recaptures],default=0)
        board.pop()
        worst=gain if worst is None else min(worst,gain)
    board.pop()
    return {'accepted':worst is None or worst>=0,'legal_captures':len(captures),
            'worst_immediate_exchange':worst,'scope':'immediate capture/recapture only'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--games',default='benchmarks/results/2026-10-05_v019-mate-assist-50ms-100games-run2.json')
    p.add_argument('--limit',type=int,default=12)
    p.add_argument('--output',default='benchmarks/results/2026-10-06_broad-hand-drop-screen.json')
    args=p.parse_args()
    source=ROOT/args.games; games=json.loads(source.read_text())['details']
    bank=[]; seen=set(); examined=0
    for game_index,game in enumerate(games):
        board=shogi.Board()
        for ply,played in enumerate(game['moves']):
            examined+=1
            if ply>=30 and board.pieces_in_hand[board.turn] and board.sfen() not in seen:
                king=0
                for square in shogi.SQUARES:
                    piece=board.piece_at(square)
                    if piece and piece.color!=board.turn and piece.piece_type==shogi.KING:
                        king=1<<square
                candidates=[]
                for move in board.legal_moves:
                    if not move.drop_piece_type: continue
                    attack,rear=drop_targets(board,move)
                    if (attack|rear).bit_count()<2: continue
                    safety=immediate_capture_screen(board,move)
                    if not safety['accepted']: continue
                    candidates.append((bool(attack&king),(attack|rear).bit_count(),move.usi(),
                                       [shogi.SQUARE_NAMES[s] for s in shogi.SQUARES if attack&(1<<s)],
                                       [shogi.SQUARE_NAMES[s] for s in shogi.SQUARES if rear&(1<<s)],safety))
                if candidates:
                    candidates.sort(key=lambda c:(-c[0],-c[1],c[2]))
                    _,_,target,attacked,rear,safety=candidates[0]
                    bank.append({'game_index':game_index,'ply':ply,'sfen':board.sfen(),
                                 'history':game['moves'][:ply],'played':played,'target':target,
                                 'attacked_squares':attacked,'rear_squares':rear,
                                 'immediate_capture_screen':safety,'royal_fork':candidates[0][0]})
                    seen.add(board.sfen())
            board.push_usi(played)
            if len(bank)>=args.limit: break
        if len(bank)>=args.limit: break
    engine_path=ROOT/'build/shogi-ai'; probe_path=ROOT/'build/hand-drop-probe'
    engine=Usi(str(engine_path),{'OpeningBook':False,'ExperienceCache':False})
    rows=[]
    try:
        for index,case in enumerate(bank):
            full={str(ms):full_search(engine,case['sfen'],ms) for ms in (50,500)}
            # Exact-root diagnosis at depth 3 is only usable when completed.
            # Allow up to 5 seconds for each forced candidate, not indefinitely.
            modes={'50ms':(45,64,False),'500ms':(490,64,False),'target_depth3':(5000,3,True)}
            commands=''.join('|'.join(map(str,[case['sfen'],case['target'],ms,depth,0,1,int(forced)]))+'\n'
                             for ms,depth,forced in modes.values())
            result=subprocess.run([str(probe_path)],input=commands,capture_output=True,text=True,timeout=25,check=True)
            core=dict(zip(modes,[json.loads(line) for line in result.stdout.splitlines()]))
            selected_commands=''.join('|'.join(map(str,[case['sfen'],move,5000,3,0,1,1]))+'\n'
                                      for move in sorted({v['bestmove'] for v in full.values()}))
            selected_result=subprocess.run([str(probe_path)],input=selected_commands,capture_output=True,text=True,timeout=25,check=True)
            selected=dict(zip(sorted({v['bestmove'] for v in full.values()}),
                              [json.loads(line) for line in selected_result.stdout.splitlines()]))
            board=shogi.Board(case['sfen'])
            for result in [*full.values(),*core.values(),*selected.values()]:
                replay=shogi.Board(case['sfen'])
                assert shogi.Move.from_usi(result['bestmove']) in replay.legal_moves
                for move in result.get('pv',[]):
                    parsed=shogi.Move.from_usi(move); assert parsed in replay.legal_moves; replay.push(parsed)
            row=dict(case,production=full,core=core,selected_depth3=selected)
            if core['50ms']['depth']==0:
                command='|'.join(map(str,[case['sfen'],case['target'],45,64,0,1,0]))+'\n'
                repeated=subprocess.run([str(probe_path)],input=command*5,capture_output=True,text=True,timeout=10,check=True)
                row['repeat_50ms_core']=[json.loads(line) for line in repeated.stdout.splitlines()]
            rows.append(row)
            print(index,case['target'],case['attacked_squares'],full['50']['bestmove'],full['500']['bestmove'],flush=True)
            output={'complete':len(rows)==len(bank),'source':args.games,
                    'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    'engine_sha256':hashlib.sha256(engine_path.read_bytes()).hexdigest(),
                    'screened_position_occurrences':examined,'limit':args.limit,
                    'conditions':{'book':False,'experience':False,'history':'fresh SFEN for tactical isolation; original history retained',
                                  'selection':'first qualifying positions in source order; not a random or exhaustive sample',
                                  'target_kinds':'all enemy pieces including pawn, lance, knight and promoted pieces',
                                  'candidates':'forks or sliding rear-target pressure; non-losing immediate capture/recapture screen; not certified safe or optimal'},'rows':rows}
            (ROOT/args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    finally: engine.close()


if __name__=='__main__': main()
