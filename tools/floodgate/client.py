#!/usr/bin/env python3
"""KUMOJI Floodgate client.

The default mode is deliberately offline.  Pass --live explicitly to open a
TCP connection to Floodgate.  The Floodgate trip is read from an environment
variable so it never needs to be stored in this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
from typing import TextIO

from protocol import Clock, CSA_MOVE_RE, StartposBoard, SummaryParser

DEFAULT_HOST = "wdoor.c.u-tokyo.ac.jp"
DEFAULT_PORT = 4081
DEFAULT_GAME = "floodgate-300-10F"
DEFAULT_OPTIONS = {}
RESULT_RE = re.compile(r"^#(WIN|LOSE|DRAW)$")
CAUSE_RE = re.compile(r"^#")


def parse_setoptions(values: list[str]) -> dict[str, str]:
    out = dict(DEFAULT_OPTIONS)
    for item in values:
        if "=" not in item:
            raise ValueError(f"--setoption requires NAME=VALUE: {item}")
        name, value = item.split("=", 1)
        name = name.strip()
        if not name or "\n" in value or "\r" in value:
            raise ValueError(f"invalid --setoption: {item}")
        out[name] = value.strip()
    return out


def validate_identity(username: str, trip: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", username):
        raise ValueError("username must be 1-32 ASCII letters, digits, '_' or '-'")
    try:
        encoded = trip.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Floodgate trip must be ASCII") from exc
    if not encoded or len(encoded) > 32 or any(c in trip for c in " \t\r\n,"):
        raise ValueError("Floodgate trip must be 1-32 non-space ASCII characters without comma")


class UsiEngine:
    def __init__(self, path: str, options: dict[str, str]) -> None:
        binary = Path(path).resolve()
        self.path = str(binary)
        self.working_directory = str(binary.parent)
        self.proc = subprocess.Popen(
            [self.path],
            cwd=self.working_directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self.options: set[str] = set()
        self.id_name = ""
        self.id_author = ""
        self.applied_options: dict[str, str] = {}
        self._handshake(options)

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            self._lines.put(raw.rstrip("\r\n"))

    def send(self, line: str) -> None:
        if self.proc.poll() is not None:
            raise RuntimeError(f"engine exited with code {self.proc.returncode}")
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def _next(self, deadline: float, purpose: str) -> str:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout {purpose}")
            try:
                return self._lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"engine exited while {purpose}: {self.proc.returncode}")

    def _handshake(self, requested: dict[str, str]) -> None:
        self.send("usi")
        deadline = time.monotonic() + 10
        while True:
            line = self._next(deadline, "waiting for usiok")
            if line.startswith("id name "):
                self.id_name = line[len("id name "):].strip()
            elif line.startswith("id author "):
                self.id_author = line[len("id author "):].strip()
            elif line.startswith("option name "):
                body = line[len("option name "):]
                name = body.split(" type ", 1)[0].strip()
                self.options.add(name)
            if line == "usiok":
                break
        missing = [name for name in requested if name not in self.options]
        if missing:
            raise ValueError(f"unsupported USI options: {', '.join(missing)}")
        for name, value in requested.items():
            self.send(f"setoption name {name} value {value}")
            self.applied_options[name] = value
        self.send("isready")
        deadline = time.monotonic() + 15
        while self._next(deadline, "waiting for readyok") != "readyok":
            pass

    def new_game(self) -> None:
        self.send("usinewgame")
        self.send("isready")
        deadline = time.monotonic() + 10
        while self._next(deadline, "waiting for readyok after usinewgame") != "readyok":
            pass

    def bestmove(self, moves: list[str], go_command: str, hard_timeout_s: float) -> str:
        position = "position startpos"
        if moves:
            position += " moves " + " ".join(moves)
        self.send(position)
        self.send(go_command)
        deadline = time.monotonic() + max(1.0, hard_timeout_s)
        try:
            while True:
                line = self._next(deadline, "waiting for bestmove")
                if line.startswith("bestmove "):
                    return line.split()[1]
        except TimeoutError:
            self.send("stop")
            grace = time.monotonic() + 2.0
            while True:
                line = self._next(grace, "waiting for bestmove after stop")
                if line.startswith("bestmove "):
                    return line.split()[1]

    def metadata(self) -> dict:
        return {
            "path": self.path,
            "working_directory": self.working_directory,
            "sha256": hashlib.sha256(Path(self.path).read_bytes()).hexdigest(),
            "usi_name": self.id_name,
            "usi_author": self.id_author,
            "supported_options": sorted(self.options),
            "applied_options": dict(self.applied_options),
        }

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            self.send("quit")
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=3)


class CsaSocket:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=15)
        # A client may connect shortly after a pairing boundary and wait nearly
        # 30 minutes for the next :00/:30 Floodgate pairing.
        self.sock.settimeout(2100)
        self.reader: TextIO = self.sock.makefile("r", encoding="utf-8", errors="replace", newline="\n")
        self.writer: TextIO = self.sock.makefile("w", encoding="utf-8", newline="\n")

    def send(self, line: str) -> None:
        self.writer.write(line + "\n")
        self.writer.flush()

    def recv(self) -> str:
        raw = self.reader.readline()
        if raw == "":
            raise ConnectionError("Floodgate closed the connection")
        return raw.rstrip("\r\n")

    def close(self) -> None:
        try:
            self.writer.close()
        finally:
            try:
                self.reader.close()
            finally:
                self.sock.close()


class FloodgateClient:
    def __init__(self, engine: UsiEngine, username: str, trip: str,
                 host: str, port: int, game_name: str) -> None:
        validate_identity(username, trip)
        self.engine = engine
        self.username = username
        self.game_name = game_name
        self.password = f"{game_name},{trip}"
        self.host = host
        self.port = port

    @staticmethod
    def _watchdog_seconds(clock: Clock, side: str) -> float:
        if not clock.has_total:
            return max(5.0, clock.byoyomi_ms / 1000.0 + 3.0)
        # Do not grant an unearned Fischer increment to the local watchdog.
        own = max(0, clock.remaining[side]) / 1000.0
        return max(5.0, min(120.0, own + clock.byoyomi_ms / 1000.0 + 3.0))

    def play_one(self) -> dict:
        conn = CsaSocket(self.host, self.port)
        summary_parser = SummaryParser()
        board = StartposBoard()
        moves: list[str] = []
        summary = None
        cause = ""
        result = ""
        started = time.time()
        try:
            conn.send(f"LOGIN {self.username} {self.password}")
            while True:
                line = conn.recv()
                if line.startswith("LOGIN:"):
                    if not line.endswith(" OK"):
                        raise RuntimeError(f"Floodgate login failed: {line}")
                    continue
                parsed = summary_parser.feed(line)
                if parsed is not None:
                    summary = parsed
                    for csa in summary.position_moves:
                        usi = board.csa_to_usi(csa)
                        moves.append(usi)
                        board.apply_csa(csa)
                    self.engine.new_game()
                    conn.send(f"AGREE {summary.game_id}")
                    continue
                if line.startswith("REJECT:"):
                    raise RuntimeError(f"game rejected: {line}")
                if line.startswith("START:"):
                    if summary is None:
                        raise RuntimeError("START before Game_Summary")
                    break

            assert summary is not None
            clock = Clock(summary)
            my_side = summary.your_turn
            to_move = summary.to_move
            max_moves = summary.max_moves or (512 if self.game_name == DEFAULT_GAME else 0)

            def make_our_move() -> None:
                go = clock.usi_go()
                token = self.engine.bestmove(
                    moves, go, self._watchdog_seconds(clock, my_side)
                )
                if token == "resign":
                    conn.send("%TORYO")
                    return
                if token == "win":
                    conn.send("%KACHI")
                    return
                conn.send(board.usi_to_csa(token, my_side))

            if to_move == my_side:
                make_our_move()

            while True:
                line = conn.recv()
                if CSA_MOVE_RE.match(line):
                    usi = board.csa_to_usi(line)
                    board.apply_csa(line)
                    moves.append(usi)
                    clock.observe(line)
                    # Floodgate itself adjudicates fourfold repetition and the
                    # 512-ply limit. If the opponent move just reached either
                    # condition, do not race the server by sending another move;
                    # wait for its #DRAW/#LOSE result instead.
                    if line[0] != my_side and not board.server_terminal_pending(len(moves), max_moves):
                        make_our_move()
                    continue
                m = RESULT_RE.match(line)
                if m:
                    result = m.group(1).lower()
                    break
                if CAUSE_RE.match(line):
                    cause = line
                    continue
                if line.startswith("LOGOUT:"):
                    break

            return {
                "kind": "floodgate_external_match",
                "learning_eligible": False,
                "game_id": summary.game_id,
                "username": self.username,
                "engine": self.engine.metadata(),
                "your_turn": summary.your_turn,
                "name_black": summary.name_black,
                "name_white": summary.name_white,
                "time_control": {
                    "total_time": summary.total_time,
                    "byoyomi": summary.byoyomi,
                    "increment": summary.increment,
                    "max_moves": max_moves,
                    "time_unit": summary.time_unit,
                },
                "result": result or "unknown",
                "cause": cause,
                "plies": len(moves),
                "moves_usi": moves,
                "started_unix": started,
                "finished_unix": time.time(),
            }
        finally:
            conn.close()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="KUMOJI Floodgate CSA bridge")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--username", default="KUMOJI")
    parser.add_argument("--trip-env", default="FLOODGATE_TRIP")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--game-name", default=DEFAULT_GAME)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--reconnect-delay", type=float, default=3.0)
    parser.add_argument("--setoption", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--result-log", type=Path, default=Path("floodgate-results.jsonl"))
    parser.add_argument("--expect-engine-name", default="",
                        help="fail if the USI id name does not exactly match this generation label")
    parser.add_argument("--clock-probe", action="store_true",
                        help="in dry-run mode, verify a short btime/wtime search and legal startpos move")
    parser.add_argument("--live", action="store_true",
                        help="actually connect to Floodgate; omitted by default for safety")
    args = parser.parse_args()
    if args.games < 1:
        raise SystemExit("--games must be >= 1")
    try:
        options = parse_setoptions(args.setoption)
        engine = UsiEngine(args.engine, options)
        if args.expect_engine_name and engine.id_name != args.expect_engine_name:
            engine.close()
            raise ValueError(
                f"engine identity mismatch: expected {args.expect_engine_name!r}, got {engine.id_name!r}"
            )
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from exc

    try:
        if not args.live:
            print("Floodgate bridge dry-run OK: engine handshake and safe options applied.")
            print(json.dumps(engine.metadata(), ensure_ascii=False, sort_keys=True))
            if args.clock_probe:
                engine.new_game()
                token = engine.bestmove([], "go btime 3000 wtime 3000", 5.0)
                StartposBoard().usi_to_csa(token, "+")
                print(f"Floodgate clock probe OK: bestmove {token}")
            print("No network connection was opened. Add --live only for an intentional debut.")
            return

        trip = os.environ.get(args.trip_env, "")
        try:
            validate_identity(args.username, trip)
        except ValueError as exc:
            raise SystemExit(
                f"{exc}. Set a unique non-sensitive trip in environment variable {args.trip_env}."
            ) from exc

        client = FloodgateClient(
            engine, args.username, trip, args.host, args.port, args.game_name
        )
        for index in range(args.games):
            if index:
                time.sleep(max(0.0, args.reconnect_delay))
            record = client.play_one()
            append_jsonl(args.result_log, record)
            print(json.dumps(
                {k: record[k] for k in ("game_id", "result", "cause", "plies")},
                ensure_ascii=False,
            ))
    finally:
        engine.close()


if __name__ == "__main__":
    main()
