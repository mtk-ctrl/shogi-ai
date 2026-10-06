#!/usr/bin/env python3
"""Screen self-play positions for safe geometric drop forks, then diagnose.

Geometry is a candidate screen, not a proof of advantage. Preserve source
game/ply and its actual move; do not treat a different engine choice as a miss.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shogi
from diagnose_hand_drops import ROOT, VALUES, full_search
from diagnose_positions import Usi


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--games',default='benchmarks/results/2026-10-05_v019-mate-assist-50ms-100games-run2.json')
    p.add_argument('--limit',type=int,default=12)
    p.add_argument('--output',default='benchmarks/results/2026-10-06_real-hand-drop-screen.json')
    args=p.parse_args()
    source=ROOT/args.games; games=json.loads(source.read_text())['details']
    bank=[]; seen=set(); examined=0
    for game_index,game in enumerate(games):
        board=shogi.Board()
        for ply,played in enumerate(game['moves']):
            examined+=1
            if ply>=30 and board.pieces_in_hand[board.turn] and board.sfen() not in seen:
                targets=0; enemy=1-board.turn; king=0
                for square in shogi.SQUARES:
                    piece=board.piece_at(square)
                    if piece and piece.color==enemy and (VALUES[piece.piece_type]>=500 or piece.piece_type==shogi.KING):
                        targets |= 1<<square
                        if piece.piece_type==shogi.KING: king=1<<square
                candidates=[]
                for move in board.legal_moves:
                    if not move.drop_piece_type: continue
                    attack=board.attacks_from(move.drop_piece_type,move.to_square,board.occupied,board.turn)&targets
                    if attack.bit_count()<2 or board.is_attacked_by(enemy,move.to_square): continue
                    candidates.append((bool(attack&king),attack.bit_count(),move.usi(),
                                       [shogi.SQUARE_NAMES[s] for s in shogi.SQUARES if attack&(1<<s)]))
                if candidates:
                    candidates.sort(key=lambda c:(-c[0],-c[1],c[2]))
                    _,_,target,attacked=candidates[0]
                    bank.append({'game_index':game_index,'ply':ply,'sfen':board.sfen(),
                                 'history':game['moves'][:ply],'played':played,'target':target,
                                 'attacked_squares':attacked,'royal_fork':candidates[0][0]})
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
                                  'candidates':'geometric forks not immediately attacked; not certified optimal'},'rows':rows}
            (ROOT/args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    finally: engine.close()


if __name__=='__main__': main()
