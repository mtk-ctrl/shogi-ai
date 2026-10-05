#!/usr/bin/env python3
"""Extract games and exact OpeningBook hits from arena JSON for feedback learning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

START_SFEN = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"


def winner_color(detail: dict) -> str:
    winner = detail.get("winner")
    if winner not in ("A", "B"):
        return "draw"
    a_black = bool(detail.get("a_black"))
    if winner == "A":
        return "black" if a_black else "white"
    return "white" if a_black else "black"


def collect(root: Path):
    games = []
    hits = []
    stats = {
        "files_scanned": 0,
        "games_scanned": 0,
        "games_with_book_hits": 0,
        "book_hits": 0,
        "skipped_illegal_games": 0,
        "malformed_hits": 0,
    }
    for path in sorted(root.rglob("*.json")):
        stats["files_scanned"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        details = data.get("details") if isinstance(data, dict) else None
        if not isinstance(details, list):
            continue
        for index, detail in enumerate(details, 1):
            if not isinstance(detail, dict):
                continue
            stats["games_scanned"] += 1
            reason = str(detail.get("reason", ""))
            if "illegal_by" in detail or reason.startswith("illegal_") or reason.startswith("invalid_"):
                stats["skipped_illegal_games"] += 1
                continue
            moves = detail.get("moves")
            book_hits = detail.get("book_hits")
            if not isinstance(moves, list) or not moves or not isinstance(book_hits, list) or not book_hits:
                continue
            game_id = f"feedback-{path.stem}-{index}"
            valid_hits = []
            for hit in book_hits:
                if not isinstance(hit, dict):
                    stats["malformed_hits"] += 1
                    continue
                try:
                    ply = int(hit["ply"])
                    engine = str(hit["engine"])
                    move = str(hit["move"])
                except (KeyError, TypeError, ValueError):
                    stats["malformed_hits"] += 1
                    continue
                if ply < 1 or ply > len(moves) or moves[ply - 1] != move:
                    stats["malformed_hits"] += 1
                    continue
                samples = str(hit.get("samples", ""))
                score_milli = str(hit.get("score_milli", ""))
                valid_hits.append((game_id, ply, engine, move, samples, score_milli))
            if not valid_hits:
                continue
            games.append((game_id, winner_color(detail), moves))
            hits.extend(valid_hits)
            stats["games_with_book_hits"] += 1
            stats["book_hits"] += len(valid_hits)
    return games, hits, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--games-output", type=Path, required=True)
    parser.add_argument("--hits-output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    games, hits, stats = collect(args.input)
    args.games_output.parent.mkdir(parents=True, exist_ok=True)
    with args.games_output.open("w", encoding="utf-8", newline="\n") as out:
        for game_id, winner, moves in games:
            out.write("\t".join([game_id, "book-feedback", winner, START_SFEN, " ".join(moves)]) + "\n")
    args.hits_output.parent.mkdir(parents=True, exist_ok=True)
    with args.hits_output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# game_id\tply\tengine\tmove\tprior_samples\tprior_score_milli\n")
        for row in hits:
            out.write("\t".join(map(str, row)) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
