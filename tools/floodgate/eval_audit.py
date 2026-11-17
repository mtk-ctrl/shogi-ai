#!/usr/bin/env python3
"""Floodgate eval audit: collect KUMOJI's own evaluations with game results.

Reads the Floodgate workflow run logs (``gh run view <id> --log``), which
contain ``FLOODGATE_RESULT`` followed by one ``FLOODGATE_MOVE`` line per ply,
replays every game with python-shogi and writes one row per KUMOJI move:

  game_id, opponent, side, result, ply, sfen (before the move), usi, eval
  (KUMOJI's own view, cp), depth, wall_ms, stop

Only KUMOJI's own observations and the game outcome are used. Opponent
evaluations/PVs are never read (R50).

usage:
  python3 tools/floodgate/eval_audit.py logs/*.txt -o research/eval-calibration/moves.tsv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import shogi

RESULT = re.compile(r"FLOODGATE_RESULT (\S+) \| (\S+) vs (\S+) \| we=([+-]) \| (\w+) (\S+) \| (\d+) plies")
MOVE = re.compile(r"FLOODGATE_MOVE (\d+) ([+-]\d{4}[A-Z]{2}),T\d+ eval_black=(\S*) depth=(\S*) wall_ms=(\S*) plan=\S* stop=(\S*)")
CSA_PIECE = {"FU": shogi.PAWN, "KY": shogi.LANCE, "KE": shogi.KNIGHT, "GI": shogi.SILVER,
             "KI": shogi.GOLD, "KA": shogi.BISHOP, "HI": shogi.ROOK, "OU": shogi.KING,
             "TO": shogi.PROM_PAWN, "NY": shogi.PROM_LANCE, "NK": shogi.PROM_KNIGHT,
             "NG": shogi.PROM_SILVER, "UM": shogi.PROM_BISHOP, "RY": shogi.PROM_ROOK}
USI_DROP = {shogi.PAWN: "P", shogi.LANCE: "L", shogi.KNIGHT: "N", shogi.SILVER: "S",
            shogi.GOLD: "G", shogi.BISHOP: "B", shogi.ROOK: "R"}


def sq(file: str, rank: str) -> str:
    return file + "abcdefghi"[int(rank) - 1]


def csa_to_usi(board: shogi.Board, csa: str) -> str:
    f1, r1, f2, r2, piece = csa[1], csa[2], csa[3], csa[4], CSA_PIECE[csa[5:7]]
    to = sq(f2, r2)
    if f1 == "0":
        return f"{USI_DROP[piece]}*{to}"
    frm = sq(f1, r1)
    moving = board.piece_type_at(shogi.SQUARE_NAMES.index(frm))
    return frm + to + ("+" if moving != piece else "")


def parse_log(path: Path):
    games, current = [], None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[36;1m" in raw:      # echoed workflow script, not output
            continue
        m = RESULT.search(raw)
        if m:
            gid, black, white, we, result, cause, plies = m.groups()
            current = dict(game_id=gid, side="sente" if we == "+" else "gote",
                           opponent=white if we == "+" else black, result=result,
                           cause=cause, plies=int(plies), moves=[])
            games.append(current)
            continue
        m = MOVE.search(raw)
        if m and current is not None:
            current["moves"].append(m.groups())
    return games


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    seen, rows = set(), []
    for path in args.logs:
        for g in parse_log(path):
            if g["game_id"] in seen or not g["moves"]:
                continue
            seen.add(g["game_id"])
            board = shogi.Board()
            ours = "+" if g["side"] == "sente" else "-"
            for n, csa, ev, depth, wall, stop in g["moves"]:
                usi = csa_to_usi(board, csa)
                move = shogi.Move.from_usi(usi)
                if move not in board.legal_moves:
                    print(f"{g['game_id']} ply {n}: illegal {csa}->{usi}", file=sys.stderr)
                    break
                if csa[0] == ours and ev not in ("", "None"):
                    e = int(ev) if ours == "+" else -int(ev)
                    rows.append([g["game_id"], g["opponent"], g["side"], g["result"], n,
                                 board.sfen(), usi, e, depth, wall, stop])
                board.push(move)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["game_id", "opponent", "side", "result", "ply", "sfen", "usi",
                    "eval_ours", "depth", "wall_ms", "stop"])
        w.writerows(rows)
    print(f"{args.output}: {len(seen)} games, {len(rows)} KUMOJI moves with eval")


if __name__ == "__main__":
    main()
