#!/usr/bin/env python3
"""Extract unique decisive self-play games from arena JSON files.

This tool uses only shogi-ai's own benchmark records. It does not import moves
from another engine or an external opening database. Output is the simple TSV
format consumed by tools/kifu/validate_games.cpp:

    game_id  split  winner  start_sfen  moves
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

START_SFEN = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"


def winner_color(detail: dict) -> str | None:
    winner = detail.get("winner")
    if winner not in ("A", "B"):
        return None
    a_black = bool(detail.get("a_black"))
    if winner == "A":
        return "black" if a_black else "white"
    return "white" if a_black else "black"


def fingerprint(moves: list[str]) -> str:
    return hashlib.sha256((START_SFEN + "\n" + " ".join(moves)).encode("utf-8")).hexdigest()


def collect(root: Path) -> tuple[list[tuple[str, str, list[str]]], dict]:
    rows: dict[str, tuple[str, list[str]]] = {}
    stats = {
        "files_scanned": 0,
        "files_with_games": 0,
        "raw_games": 0,
        "accepted_unique_decisive_games": 0,
        "duplicates": 0,
        "skipped_nondecisive": 0,
        "skipped_illegal": 0,
        "moves": 0,
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
        stats["files_with_games"] += 1
        for detail in details:
            if not isinstance(detail, dict):
                continue
            stats["raw_games"] += 1
            reason = str(detail.get("reason", ""))
            if "illegal_by" in detail or reason.startswith("illegal_") or reason.startswith("invalid_"):
                stats["skipped_illegal"] += 1
                continue
            color = winner_color(detail)
            if color is None:
                stats["skipped_nondecisive"] += 1
                continue
            moves = detail.get("moves")
            if not isinstance(moves, list) or not moves or not all(isinstance(m, str) and m for m in moves):
                stats["skipped_illegal"] += 1
                continue
            fp = fingerprint(moves)
            if fp in rows:
                stats["duplicates"] += 1
                continue
            rows[fp] = (color, moves)

    result = []
    for fp in sorted(rows):
        color, moves = rows[fp]
        result.append(("arena-" + fp[:16], color, moves))
    stats["accepted_unique_decisive_games"] = len(result)
    stats["moves"] = sum(len(moves) for _, _, moves in result)
    return result, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("benchmarks/results"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    games, stats = collect(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for game_id, color, moves in games:
            fields = [game_id, "book", color, START_SFEN, " ".join(moves)]
            out.write("\t".join(fields) + "\n")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
