#!/usr/bin/env python3
"""Build/dedupe a compact position bank from arena JSON outputs."""
import argparse, json, hashlib
from pathlib import Path
import shogi

VALUES={shogi.PAWN:100,shogi.LANCE:300,shogi.KNIGHT:300,shogi.SILVER:400,
        shogi.GOLD:500,shogi.BISHOP:700,shogi.ROOK:800,
        shogi.PROM_PAWN:500,shogi.PROM_LANCE:500,shogi.PROM_KNIGHT:500,
        shogi.PROM_SILVER:500,shogi.PROM_BISHOP:900,shogi.PROM_ROOK:1000}

def material(board):
    score=0
    for sq in shogi.SQUARES:
        p=board.piece_at(sq)
        if p and p.piece_type!=shogi.KING:
            score+=(1 if p.color==shogi.BLACK else -1)*VALUES.get(p.piece_type,0)
    for color,sign in ((shogi.BLACK,1),(shogi.WHITE,-1)):
        for kind,n in board.pieces_in_hand[color].items(): score+=sign*n*VALUES.get(kind,0)
    return score

def tags(board,ply):
    out=[]
    pieces=sum(1 for s in shogi.SQUARES if board.piece_at(s))
    if ply<30: out.append("opening")
    elif pieces<=16 or ply>=100: out.append("endgame")
    else: out.append("middlegame")
    if abs(material(board))>=500: out.append("material-imbalance")
    # King danger proxy: enemy attacks on king-neighbour squares.
    for color in (shogi.BLACK,shogi.WHITE):
        king=board.king_squares[color]
        if king is None: continue
        kf,kr=shogi.square_file(king),shogi.square_rank(king)
        attacked=0
        for df in (-1,0,1):
            for dr in (-1,0,1):
                if not (df or dr): continue
                f,r=kf+df,kr+dr
                if 0<=f<9 and 0<=r<9:
                    sq=shogi.SQUARE_NAMES.index(str(9-f)+chr(ord('a')+r)) if False else None
        if board.is_check(): out.append("king-danger"); break
    return sorted(set(out))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",required=True)
    p.add_argument("--stride",type=int,default=20); p.add_argument("--min-ply",type=int,default=20)
    args=p.parse_args(); existing={}
    outp=Path(args.output)
    if outp.exists():
        for line in outp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row=json.loads(line); existing[row["id"]]=row
    files=list(Path(args.input).rglob("*.json"))
    for file in files:
        try: data=json.loads(file.read_text(encoding="utf-8"))
        except Exception: continue
        for gi,g in enumerate(data.get("details",[])):
            seq=list(g.get("opening_moves",[]))+list(g.get("moves",[]))
            board=shogi.Board()
            for ply,token in enumerate(seq,1):
                try: move=shogi.Move.from_usi(token)
                except Exception: break
                if move not in board.legal_moves: break
                board.push(move)
                if ply<args.min_ply or ply%args.stride: continue
                key=" ".join(board.sfen().split()[:3])
                rid=hashlib.sha256(key.encode()).hexdigest()[:20]
                if rid in existing: continue
                existing[rid]={"id":rid,"moves":seq[:ply],"sfen":board.sfen(),"ply":ply,
                    "tags":tags(board,ply),"source":{"file":file.name,"game":gi},
                    "final_result":g.get("winner"),"use_count":0,"last_used":None}
    outp.parent.mkdir(parents=True,exist_ok=True)
    rows=sorted(existing.values(),key=lambda r:(r.get("ply",0),r["id"]))
    outp.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")
    print(json.dumps({"positions":len(rows),"sources":len(files)},ensure_ascii=False))
if __name__=="__main__": main()
