#!/usr/bin/env python3
"""Book-vs-Core arena that records only exact OpeningBook hits for learning."""

import argparse
import hashlib
import json
import queue
import time
from pathlib import Path

import shogi

from arena import Adjudicator, Engine, SEARCH_STAT_NAMES, can_declare_win, search_summary


def parse_book_hit_info(line):
    parts = line.split()
    if len(parts) < 6 or parts[:4] != ["info", "string", "opening_book", "hit"]:
        return None
    try:
        return {
            "move": parts[parts.index("move") + 1],
            "samples": int(parts[parts.index("samples") + 1]),
            "score_milli": int(parts[parts.index("score_milli") + 1]),
        }
    except (ValueError, IndexError):
        return None


class FeedbackEngine(Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_book_hit = None

    def bestmove(self, moves):
        started = time.monotonic()
        self.last_book_hit = None
        command = "position startpos"
        if moves:
            command += " moves " + " ".join(moves)
        self.send(command)
        self.send(self.go_command)

        deadline = time.monotonic() + self.RESPONSE_TIMEOUT
        info = {}
        seen = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.label}: waiting for bestmove; seen={seen[-8:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"{self.label}: waiting for bestmove; seen={seen[-8:]}") from exc
            seen.append(line)
            if line.startswith("info "):
                hit = parse_book_hit_info(line)
                if hit is not None:
                    self.last_book_hit = hit
                parts = line.split()
                for name in SEARCH_STAT_NAMES:
                    if name in parts:
                        try:
                            info[name] = int(parts[parts.index(name) + 1])
                        except (ValueError, IndexError):
                            pass
                continue
            if line.startswith("bestmove "):
                token = line.split(maxsplit=1)[1].strip()
                break

        self.elapsed.append(time.monotonic() - started)
        if info:
            self.search_stats.append(info)
        return token


def play_game(a, b, game_index, max_plies, seed_base):
    a_black = game_index % 2 == 0
    black = a if a_black else b
    white = b if a_black else a
    black.configure_game(seed_base + game_index * 2)
    white.configure_game(seed_base + game_index * 2 + 1)

    board = shogi.Board()
    moves = []
    book_hits = []
    adjudicator = Adjudicator(board)

    def result(winner, reason, **extra):
        return {
            "winner": winner,
            "reason": reason,
            "plies": len(moves),
            "a_black": a_black,
            "moves": moves,
            "book_hits": book_hits,
            "final_sfen": board.sfen(),
            **extra,
        }

    for ply in range(max_plies):
        engine = black if board.turn == shogi.BLACK else white
        token = engine.bestmove(moves)
        other = white if engine is black else black

        if token == "resign":
            return result(other.label, "resign")
        if token == "win":
            if not can_declare_win(board):
                return result(other.label, "invalid_declaration", illegal_by=engine.label)
            return result(engine.label, "declare_win")
        try:
            move = shogi.Move.from_usi(token)
        except Exception:
            return result(other.label, f"invalid_usi:{token}", illegal_by=engine.label)
        if move not in board.legal_moves:
            return result(other.label, f"illegal_move:{token}", illegal_by=engine.label)

        if engine.last_book_hit is not None and engine.last_book_hit.get("move") == token:
            book_hits.append({"ply": ply + 1, "engine": engine.label, **engine.last_book_hit})

        board.push(move)
        moves.append(token)
        terminal = adjudicator.after_move(board)
        if terminal is not None:
            color, reason = terminal
            winner = None if color is None else (black.label if color == shogi.BLACK else white.label)
            return result(winner, reason)
    return result(None, "move_limit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--book-seed", type=int, default=5489)
    parser.add_argument("--core-seed", type=int, default=5490)
    parser.add_argument("--go-command", default="go movetime 50")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.games < 1 or args.max_plies < 1:
        raise SystemExit("games and max-plies must be positive")

    common = {"ExperienceCache": "false"}
    a = FeedbackEngine(args.engine, "A", {**common, "OpeningBook": "true",
                       "OpeningBookFile": args.book, "RandomSeed": args.book_seed}, args.go_command)
    b = FeedbackEngine(args.engine, "B", {**common, "OpeningBook": "false",
                       "RandomSeed": args.core_seed}, args.go_command)
    games = []
    started = time.monotonic()
    try:
        for i in range(args.games):
            game = play_game(a, b, i, args.max_plies, args.seed)
            games.append(game)
            print(f"game {i+1:03d}/{args.games}: {game['winner'] or 'draw'} {game['reason']} "
                  f"{game['plies']} plies book_hits={len(game['book_hits'])}")
    finally:
        a.close(); b.close()

    wins_a = sum(g["winner"] == "A" for g in games)
    wins_b = sum(g["winner"] == "B" for g in games)
    draws = args.games - wins_a - wins_b
    illegal = [g for g in games if "illegal_by" in g]
    summary = {
        "engine": str(Path(args.engine)),
        "sha256": hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
        "book": str(Path(args.book)),
        "seed": args.seed,
        "go_command": args.go_command,
        "games": args.games,
        "wins_a": wins_a,
        "draws": draws,
        "wins_b": wins_b,
        "score_a": (wins_a + 0.5 * draws) / args.games,
        "book_hits": sum(len(g["book_hits"]) for g in games),
        "average_plies": sum(g["plies"] for g in games) / args.games,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "illegal_games": len(illegal),
        "search": {e.label: search_summary(e) for e in (a, b)},
        "details": games,
    }
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"A(Book) {wins_a} - {draws} - {wins_b} B(Core); score={summary['score_a']:.3f}; "
          f"book_hits={summary['book_hits']}")
    if illegal:
        raise SystemExit("Illegal move detected during book feedback arena")


if __name__ == "__main__":
    main()
