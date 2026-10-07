#!/usr/bin/env python3
"""Run shogi-ai against an arbitrary external USI engine.

This runner is deliberately separated from benchmarks/arena.py and from the
self-play corpus used by opening-book / learning pipelines. External games are
benchmark evidence only: opponent scores, PVs and choices are never fed back
into shogi-ai.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import shogi

from arena import Adjudicator, can_declare_win, parse_info_line, compact_search_telemetry


REPO_ROOT = Path(__file__).resolve().parents[1]
SELFPLAY_RESULTS = (REPO_ROOT / "benchmarks" / "results").resolve()
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks" / "external-results" / "external-match.json"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_path(path: Path) -> Path:
    resolved = path.resolve()
    if _is_relative_to(resolved, SELFPLAY_RESULTS):
        raise ValueError(
            "external benchmark output must not be written under benchmarks/results; "
            "that directory is reserved for self-play data"
        )
    return resolved


def validate_go_command(command: str) -> str:
    if not command.startswith("go ") or "\n" in command or "\r" in command:
        raise ValueError("go command must be one USI go command")
    return command


def parse_option_name(line: str) -> str | None:
    prefix = "option name "
    if not line.startswith(prefix):
        return None
    body = line[len(prefix):]
    name, sep, _ = body.partition(" type ")
    name = name.strip()
    return name if sep and name else None


def usi_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class UsiEngine:
    RESPONSE_TIMEOUT = 30

    def __init__(self, path: str, label: str, options: dict, go_command: str,
                 capture_info: bool = False):
        self.path = str(Path(path).resolve())
        self.label = label
        self.requested_options = dict(options)
        self.go_command = validate_go_command(go_command)
        self.capture_info = capture_info
        self.elapsed: list[float] = []
        self.last_search: dict = {}
        self.id_name = ""
        self.id_author = ""
        self.option_names: dict[str, str] = {}
        self.applied_options: dict[str, str] = {}

        self.proc = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self._handshake()

    def _reader(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))

    def send(self, command: str):
        if self.proc.poll() is not None:
            raise RuntimeError(f"{self.label} exited with {self.proc.returncode}")
        assert self.proc.stdin is not None
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _next_line(self, deadline: float, purpose: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{self.label}: timeout while {purpose}")
        try:
            return self.lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(f"{self.label}: timeout while {purpose}") from exc

    def _handshake(self):
        self.send("usi")
        deadline = time.monotonic() + 10
        while True:
            line = self._next_line(deadline, "waiting for usiok")
            if line.startswith("id name "):
                self.id_name = line[len("id name "):].strip()
            elif line.startswith("id author "):
                self.id_author = line[len("id author "):].strip()
            else:
                option_name = parse_option_name(line)
                if option_name:
                    self.option_names[option_name.lower()] = option_name
            if line == "usiok":
                break

        unsupported = []
        for requested_name, value in self.requested_options.items():
            actual = self.option_names.get(str(requested_name).lower())
            if actual is None:
                unsupported.append(str(requested_name))
                continue
            encoded = usi_value(value)
            self.send(f"setoption name {actual} value {encoded}")
            self.applied_options[actual] = encoded

        if unsupported:
            self.close()
            raise ValueError(
                f"{self.label}: unsupported USI options: {', '.join(unsupported)}; "
                f"available={sorted(self.option_names.values())}"
            )

        self.send("isready")
        deadline = time.monotonic() + 15
        while self._next_line(deadline, "waiting for readyok") != "readyok":
            pass

    def new_game(self, seed: int):
        random_seed = self.option_names.get("randomseed")
        if random_seed is not None:
            self.send(f"setoption name {random_seed} value {seed}")
            self.send("isready")
            deadline = time.monotonic() + 10
            while self._next_line(deadline, "waiting for readyok after RandomSeed") != "readyok":
                pass
        self.send("usinewgame")

    def bestmove(self, moves: list[str]) -> str:
        command = "position startpos"
        if moves:
            command += " moves " + " ".join(moves)
        self.send(command)
        started = time.monotonic()
        self.send(self.go_command)
        deadline = time.monotonic() + self.RESPONSE_TIMEOUT
        info: dict = {}
        while True:
            line = self._next_line(deadline, "waiting for bestmove")
            if line.startswith("info "):
                # Only KUMOJI's own search telemetry is retained.  Opponent
                # score/PV remains intentionally discarded and never becomes a
                # teacher signal.
                if self.capture_info:
                    info.update(parse_info_line(line))
                continue
            if line.startswith("bestmove "):
                elapsed_s = time.monotonic() - started
                self.elapsed.append(elapsed_s)
                token = line.split(maxsplit=1)[1].strip().split()[0]
                if self.capture_info:
                    self.last_search = dict(info)
                    self.last_search["bestmove"] = token
                    self.last_search["elapsed_ms"] = round(elapsed_s * 1000, 3)
                else:
                    self.last_search = {}
                return token

    def metadata(self) -> dict:
        binary = Path(self.path)
        return {
            "path": self.path,
            "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "usi_name": self.id_name,
            "usi_author": self.id_author,
            "go_command": self.go_command,
            "options": self.applied_options,
        }

    def close(self):
        if getattr(self, "proc", None) is not None and self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


def play_game(self_engine: UsiEngine, opponent: UsiEngine, game_index: int,
              max_plies: int, seed_base: int, game_offset: int = 0) -> dict:
    self_black = (game_offset + game_index) % 2 == 0
    black = self_engine if self_black else opponent
    white = opponent if self_black else self_engine
    self_engine.new_game(seed_base + game_index * 2)
    opponent.new_game(seed_base + game_index * 2 + 1)

    board = shogi.Board()
    moves: list[str] = []
    move_records: list[dict] = []
    adjudicator = Adjudicator(board)

    def result(winner: str | None, reason: str, **extra) -> dict:
        return {
            "winner": winner,
            "reason": reason,
            "plies": len(moves),
            "self_black": self_black,
            "moves": moves,
            "move_records": move_records,
            "final_sfen": board.sfen(),
            **extra,
        }

    for _ in range(max_plies):
        engine = black if board.turn == shogi.BLACK else white
        side_to_move = board.turn
        in_check_before = board.is_check()
        legal_moves_before = sum(1 for _ in board.legal_moves)
        token = engine.bestmove(moves)
        other = white if engine is black else black
        self_search = (compact_search_telemetry(engine.last_search, side_to_move)
                       if engine is self_engine else {})

        if token == "resign":
            return result(other.label, "resign", terminal_self_search=self_search)
        if token == "win":
            if not can_declare_win(board):
                return result(other.label, "invalid_declaration", illegal_by=engine.label,
                              terminal_self_search=self_search)
            return result(engine.label, "declare_win", terminal_self_search=self_search)

        try:
            move = shogi.Move.from_usi(token)
        except Exception:
            return result(other.label, f"invalid_usi:{token}", illegal_by=engine.label)
        if move not in board.legal_moves:
            return result(other.label, f"illegal_move:{token}", illegal_by=engine.label,
                          terminal_self_search=self_search)

        record = {
            "ply": len(moves) + 1,
            "side_to_move": "black" if side_to_move == shogi.BLACK else "white",
            "actor": "self" if engine is self_engine else "opponent",
            "move": token,
            "in_check_before": in_check_before,
            "legal_moves_before": legal_moves_before,
            "is_capture": board.piece_at(move.to_square) is not None,
            "is_promotion": bool(move.promotion),
            "is_drop": move.drop_piece_type is not None,
            "self_search": self_search,
        }
        board.push(move)
        moves.append(token)
        record["gave_check"] = board.is_check()
        move_records.append(record)
        terminal = adjudicator.after_move(board)
        if terminal is not None:
            color, reason = terminal
            winner = None if color is None else (black.label if color == shogi.BLACK else white.label)
            return result(winner, reason)

    return result(None, "move_limit")


def timing(engine: UsiEngine) -> dict:
    if not engine.elapsed:
        return {"moves": 0, "mean_ms": 0.0, "max_ms": 0.0}
    return {
        "moves": len(engine.elapsed),
        "mean_ms": round(1000 * sum(engine.elapsed) / len(engine.elapsed), 3),
        "max_ms": round(1000 * max(engine.elapsed), 3),
    }


def parse_json_object(text: str, label: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if any("\n" in str(k) + str(v) or "\r" in str(k) + str(v) for k, v in value.items()):
        raise ValueError(f"{label} must not contain newlines")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-engine", required=True)
    parser.add_argument("--opponent-engine", required=True)
    parser.add_argument("--self-options", default='{"ExperienceCache":"false","OpeningBook":"false"}')
    parser.add_argument("--opponent-options", default="{}")
    parser.add_argument("--self-go", default="go movetime 50")
    parser.add_argument("--opponent-go", default="go nodes 300")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--game-offset", type=int, default=0,
                        help="Number of games in preceding shards; controls color alternation")
    parser.add_argument("--max-plies", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.games < 1 or args.max_plies < 1 or args.game_offset < 0:
        raise SystemExit("games/max-plies must be positive and game-offset nonnegative")
    if not 0 <= args.seed <= 2147483647 - args.games * 2:
        raise SystemExit("seed is outside the supported USI integer range")

    try:
        output = validate_output_path(args.output)
        self_options = parse_json_object(args.self_options, "self-options")
        opponent_options = parse_json_object(args.opponent_options, "opponent-options")
        validate_go_command(args.self_go)
        validate_go_command(args.opponent_go)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc

    self_engine = UsiEngine(args.self_engine, "self", self_options, args.self_go,
                            capture_info=True)
    opponent = UsiEngine(args.opponent_engine, "opponent", opponent_options, args.opponent_go,
                         capture_info=False)
    games: list[dict] = []
    started = time.monotonic()
    try:
        for index in range(args.games):
            game = play_game(self_engine, opponent, index, args.max_plies, args.seed, args.game_offset)
            games.append(game)
            print(
                f"game {index + 1:03d}/{args.games}: {game['winner'] or 'draw'} "
                f"{game['reason']} {game['plies']} plies"
            )
    finally:
        self_engine.close()
        opponent.close()

    wins = sum(g["winner"] == "self" for g in games)
    losses = sum(g["winner"] == "opponent" for g in games)
    draws = args.games - wins - losses
    illegal = [g for g in games if "illegal_by" in g]
    summary = {
        "kind": "external_engine_benchmark",
        "telemetry_schema_version": 1,
        "learning_eligible": False,
        "diagnosis_eligible": True,
        "opening_book_eligible": False,
        "experience_eligible": usi_value(self_options.get("ExperienceCache", False)).lower() == "true",
        "policy": {
            "purpose": "strength measurement only",
            "opponent_scores_and_pv_ignored": True,
            "self_search_telemetry_recorded": True,
            "opponent_games_must_not_feed_training": True,
            "opponent_games_must_not_feed_opening_book": True,
            "self_authored_experience_may_persist": usi_value(self_options.get("ExperienceCache", False)).lower() == "true",
        },
        "self_engine": self_engine.metadata(),
        "opponent_engine": opponent.metadata(),
        "seed": args.seed,
        "game_offset": args.game_offset,
        "games": args.games,
        "max_plies": args.max_plies,
        "wins_self": wins,
        "draws": draws,
        "losses_self": losses,
        "score_self": (wins + 0.5 * draws) / args.games,
        "average_plies": sum(g["plies"] for g in games) / args.games,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "illegal_games": len(illegal),
        "timing": {
            "self": timing(self_engine),
            "opponent": timing(opponent),
        },
        "details": games,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("---")
    print(f"self {wins} - {draws} - {losses} opponent; score={summary['score_self']:.3f}")
    print(f"result: {output}")
    if illegal:
        raise SystemExit("illegal move detected during external benchmark")


if __name__ == "__main__":
    main()
