#!/usr/bin/env python3
"""Reconstruct and validate ONLY same-binary KUMOJI self-play into research samples."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shogi


def convert(inputs: list[Path], output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    games = samples = skipped = duplicates = 0
    seen_games = set()
    with output.open("w", encoding="utf-8") as out:
        for path in inputs:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Never silently use human games, external opponents or cross-version games
            # as supervised labels. This strict first version only accepts identical
            # engine binaries and explicitly labelled, trustworthy self-play files.
            if data.get("learning_origin") != "kumoji_selfplay":
                raise ValueError(f"{path}: missing explicit kumoji_selfplay provenance")
            sha_a, sha_b = data.get("sha256_a"), data.get("sha256_b")
            if not sha_a or sha_a != sha_b or len(sha_a) != 64:
                raise ValueError(f"{path}: both players must be same KUMOJI binary")
            if not isinstance(data.get("details"), list):
                raise ValueError(f"{path}: missing match details")
            for game in data["details"]:
                moves = game.get("moves")
                if not isinstance(moves, list) or game.get("illegal_by"):
                    skipped += 1
                    continue
                reason = game.get("reason")
                winner = game.get("winner")
                if winner in ("A", "B") and reason in (
                    "resign", "checkmate", "no_legal_moves", "declare_win",
                    "perpetual_check"):
                    black_won = (winner == "A") == bool(game.get("a_black"))
                    outcome = 1.0 if black_won else 0.0
                elif winner is None and reason == "fourfold_repetition":
                    outcome = 0.5
                else:
                    # Unresolved move limits are *not* treated as draws.
                    skipped += 1
                    continue
                start = game.get("start_sfen")
                board = shogi.Board(start) if start else shogi.Board()
                identity = hashlib.sha256(
                    (board.sfen() + "\n" + " ".join(moves)).encode()).hexdigest()
                if identity in seen_games:
                    duplicates += 1
                    continue
                seen_games.add(identity)
                records = game.get("move_records") or []
                if records and len(records) != len(moves):
                    raise ValueError(f"{path}: inconsistent per-move observations")
                rows = []
                for i, token in enumerate(moves):
                    move = shogi.Move.from_usi(token)
                    if move not in board.legal_moves:
                        raise ValueError(f"{path}: illegal recorded move at ply {i+1}")
                    row = {"source": "kumoji_selfplay", "game_id": identity,
                           "sfen": board.sfen(), "ply": i + 1,
                           "target_black": outcome}
                    if records:
                        record = records[i]
                        if record.get("move") != token:
                            raise ValueError(f"{path}: mismatched move observation")
                        score = (record.get("search") or {}).get("phase_static_cp_black")
                        if type(score) is int:
                            row["static_cp_black"] = score
                    rows.append(row)
                    board.push(move)
                for row in rows:
                    out.write(json.dumps(row, separators=(",", ":")) + "\n")
                games += 1
                samples += len(rows)
    if games < 3 or samples < 20:
        raise ValueError("need at least 3 completed self-play games and 20 positions")
    return {"games": games, "positions": samples,
            "excluded_games": skipped, "duplicate_games": duplicates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = convert(args.input, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
