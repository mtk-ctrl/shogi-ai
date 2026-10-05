#!/usr/bin/env python3
"""Paired arena from stored startpos move prefixes for Nightly Research.

The bank is JSONL. Each row needs `moves` (list of legal USI moves) and may
contain `id` and `tags`. Every selected position is played twice with A/B
colors reversed. This runner intentionally reuses the production arena Engine
and adjudication code instead of creating a second USI implementation.
"""
import argparse
import json
from pathlib import Path

import shogi

from arena import Engine, Adjudicator, can_declare_win


def load_bank(path, limit):
    rows=[]
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row=json.loads(line)
        moves=row.get("moves")
        if not isinstance(moves,list):
            continue
        board=shogi.Board()
        valid=True
        for token in moves:
            try:
                move=shogi.Move.from_usi(token)
            except Exception:
                valid=False; break
            if move not in board.legal_moves:
                valid=False; break
            board.push(move)
        if valid:
            rows.append(row)
        if len(rows)>=limit:
            break
    return rows


def play(a,b,row,a_black,max_plies,seed):
    black=a if a_black else b
    white=b if a_black else a
    black.configure_game(seed)
    white.configure_game(seed+1)
    prefix=list(row.get("moves",[]))
    board=shogi.Board()
    for token in prefix:
        board.push(shogi.Move.from_usi(token))
    moves=[]
    adjudicator=Adjudicator(board)

    def result(winner,reason,**extra):
        return {"position_id":row.get("id"),"tags":row.get("tags",[]),
                "opening_moves":prefix,"winner":winner,"reason":reason,
                "plies":len(moves),"a_black":a_black,"moves":moves,
                "final_sfen":board.sfen(),**extra}

    for _ in range(max_plies):
        engine=black if board.turn==shogi.BLACK else white
        token=engine.bestmove(prefix+moves)
        if token=="resign":
            return result(white.label if engine is black else black.label,"resign")
        if token=="win":
            if not can_declare_win(board):
                return result(white.label if engine is black else black.label,
                              "invalid_declaration",illegal_by=engine.label)
            return result(engine.label,"declare_win")
        try:
            move=shogi.Move.from_usi(token)
        except Exception:
            return result(white.label if engine is black else black.label,
                          f"invalid_usi:{token}",illegal_by=engine.label)
        if move not in board.legal_moves:
            return result(white.label if engine is black else black.label,
                          f"illegal_move:{token}",illegal_by=engine.label)
        board.push(move); moves.append(token)
        terminal=adjudicator.after_move(board)
        if terminal is not None:
            color,reason=terminal
            winner=None if color is None else (black.label if color==shogi.BLACK else white.label)
            return result(winner,reason)
    return result(None,"move_limit")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--engine-a",required=True); p.add_argument("--engine-b",required=True)
    p.add_argument("--options-a",default="{}"); p.add_argument("--options-b",default="{}")
    p.add_argument("--bank",required=True); p.add_argument("--positions",type=int,default=20)
    p.add_argument("--max-plies",type=int,default=300); p.add_argument("--seed",type=int,default=20261006)
    p.add_argument("--go-command",default="go movetime 50"); p.add_argument("--output",required=True)
    args=p.parse_args()
    rows=load_bank(args.bank,args.positions)
    if not rows:
        raise SystemExit("position bank has no valid rows")
    oa=json.loads(args.options_a); ob=json.loads(args.options_b)
    oa.setdefault("ExperienceCache","false"); ob.setdefault("ExperienceCache","false")
    a=Engine(args.engine_a,"A",oa,args.go_command); b=Engine(args.engine_b,"B",ob,args.go_command)
    games=[]
    try:
        for i,row in enumerate(rows):
            for side in (True,False):
                r=play(a,b,row,side,args.max_plies,args.seed+i*4+(0 if side else 2))
                games.append(r)
                print(row.get("id",i),"A-black" if side else "B-black",r["winner"] or "draw",r["reason"])
    finally:
        a.close(); b.close()
    wa=sum(g["winner"]=="A" for g in games); wb=sum(g["winner"]=="B" for g in games)
    draws=len(games)-wa-wb
    out={"positions":len(rows),"games":len(games),"wins_a":wa,"draws":draws,"wins_b":wb,
         "score_a":(wa+0.5*draws)/len(games),"illegal_games":sum("illegal_by" in g for g in games),
         "go_command":args.go_command,"details":games}
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
