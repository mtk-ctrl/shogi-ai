#!/usr/bin/env python3
"""Small reproducible USI match runner for comparing two engine revisions."""

import argparse
import hashlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

import shogi


class Adjudicator:
    """Track actual fourfold repetition, including continuous-check losses."""
    def __init__(self, board):
        self.positions = [self.key(board)]
        self.checks = []  # (mover, whether that move gave check)

    @staticmethod
    def key(board):
        return " ".join(board.sfen().split()[:3])

    def after_move(self, board):
        self.checks.append((board.turn ^ 1, board.is_check()))
        self.positions.append(self.key(board))
        occurrences = [i for i, key in enumerate(self.positions) if key == self.positions[-1]]
        if len(occurrences) >= 4:
            interval = self.checks[occurrences[-4]:]
            for color in (shogi.BLACK, shogi.WHITE):
                checks = [check for mover, check in interval if mover == color]
                if checks and all(checks):
                    return color ^ 1, "perpetual_check"
            return None, "fourfold_repetition"
        if not any(board.legal_moves):
            return board.turn ^ 1, "checkmate" if board.is_check() else "no_legal_moves"
        return None


def can_declare_win(board):
    """Independent CSA 27-point check; match uses a separate response watchdog."""
    color = board.turn
    in_camp = lambda square: square // 9 < 3 if color == shogi.BLACK else square // 9 >= 6
    king = board.king_squares[color]
    if king is None or not in_camp(king) or board.is_check():
        return False
    camp = [board.piece_at(s) for s in shogi.SQUARES if in_camp(s)]
    pieces = [p for p in camp if p and p.color == color and p.piece_type != shogi.KING]
    if len(pieces) < 10:
        return False
    majors = (shogi.BISHOP, shogi.ROOK, shogi.PROM_BISHOP, shogi.PROM_ROOK)
    points = sum(5 if p.piece_type in majors else 1 for p in pieces)
    points += sum(n * (5 if kind in majors else 1)
                  for kind, n in board.pieces_in_hand[color].items())
    return points >= (28 if color == shogi.BLACK else 27)


SEARCH_STAT_NAMES = (
    "nodes", "full_nodes", "cutoffs", "min_cutoffs", "max_cutoffs",
    "leaves", "terminals", "ply1", "ply2", "ply3",
    "order_calls", "ordered_moves", "tt_probes", "tt_hits",
    "tt_exact_hits", "tt_bound_cutoffs", "tt_stores", "tt_replacements",
    "tt_move_first", "tt_disabled_repetition", "experience_probes",
    "experience_hits", "experience_move_first", "experience_stores",
    "experience_replacements", "experience_disabled_repetition",
    "qnodes", "qcutoffs", "qlimit_leaves",
)

USI_INFO_INTEGER_NAMES = (
    "depth", "seldepth", "time", "nodes", "nps", "hashfull", "multipv",
)

PER_MOVE_SEARCH_FIELDS = (
    "depth", "seldepth", "time", "nodes", "nps",
    "full_nodes", "cutoffs", "tt_probes", "tt_hits",
    "experience_probes", "experience_hits", "qnodes", "qcutoffs",
)


def parse_info_line(line):
    """Parse the reusable part of one USI info line.

    Scores are kept from the side-to-move point of view here.  A game record
    later adds a Black-normalized score so evaluation trajectories remain
    comparable across alternating turns.
    """
    parts = line.split()
    if not parts or parts[0] != "info":
        return {}
    info = {}
    for name in USI_INFO_INTEGER_NAMES + SEARCH_STAT_NAMES:
        if name in parts:
            try:
                info[name] = int(parts[parts.index(name) + 1])
            except (ValueError, IndexError):
                pass
    if "score" in parts:
        try:
            i = parts.index("score")
            kind, value = parts[i + 1], int(parts[i + 2])
            if kind == "cp":
                info["score_cp"] = value
            elif kind == "mate":
                info["score_mate"] = value
            if "lowerbound" in parts[i + 3:]:
                info["score_lowerbound"] = True
            if "upperbound" in parts[i + 3:]:
                info["score_upperbound"] = True
        except (ValueError, IndexError):
            pass
    if "pv" in parts:
        i = parts.index("pv")
        info["pv"] = parts[i + 1:i + 9]
    if len(parts) >= 3 and parts[1:3] == ["string", "long_think"]:
        for name in ("used", "base_ms", "max_ms"):
            if name in parts:
                try:
                    value = parts[parts.index(name) + 1]
                    info["long_think_" + name] = int(value.split("/", 1)[0])
                except (ValueError, IndexError):
                    pass
        if "reason" in parts:
            try:
                info["long_think_reason"] = parts[parts.index("reason") + 1]
            except IndexError:
                pass
    return info


def compact_search_telemetry(info, side_to_move):
    """Keep enough per-move search data for later diagnosis without huge logs."""
    out = {name: info[name] for name in PER_MOVE_SEARCH_FIELDS if name in info}
    if "elapsed_ms" in info:
        out["elapsed_ms"] = info["elapsed_ms"]
    if "pv" in info:
        out["pv"] = info["pv"]
    if "score_cp" in info:
        out["score_cp_stm"] = info["score_cp"]
        out["score_black_cp"] = info["score_cp"] if side_to_move == shogi.BLACK else -info["score_cp"]
    if "score_mate" in info:
        out["score_mate_stm"] = info["score_mate"]
        out["score_black_mate"] = info["score_mate"] if side_to_move == shogi.BLACK else -info["score_mate"]
    if info.get("score_lowerbound"):
        out["score_lowerbound"] = True
    if info.get("score_upperbound"):
        out["score_upperbound"] = True
    for name in ("long_think_used", "long_think_reason", "long_think_base_ms", "long_think_max_ms"):
        if name in info:
            out[name] = info[name]
    return out


def usi_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class Engine:
    RESPONSE_TIMEOUT = 30

    def __init__(self, path, label, options=None, go_command="go depth 3"):
        self.path = str(Path(path).resolve())
        self.label = label
        self.options = dict(options or {})
        self.go_command = go_command
        self.elapsed = []
        self.search_stats = []
        self.last_search = {}
        self.proc = subprocess.Popen(
            [self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("usi")
        self.wait_prefix("usiok", 10)
        for name, value in self.options.items():
            self.send(f"setoption name {name} value {usi_value(value)}")
        self.send("isready")
        self.wait_prefix("readyok", 10)

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))

    def send(self, command):
        if self.proc.poll() is not None:
            raise RuntimeError(f"{self.label} exited with {self.proc.returncode}")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait_prefix(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        seen = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.label}: waiting for {prefix!r}; seen={seen[-8:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"{self.label}: waiting for {prefix!r}; seen={seen[-8:]}") from exc
            seen.append(line)
            if line.startswith(prefix):
                return line

    def configure_game(self, seed):
        self.send(f"setoption name RandomSeed value {seed}")
        self.send("isready")
        self.wait_prefix("readyok", 10)
        self.send("usinewgame")

    def bestmove(self, moves):
        started = time.monotonic()
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
                info.update(parse_info_line(line))
                continue
            if line.startswith("bestmove "):
                token = line.split(maxsplit=1)[1].strip()
                break

        elapsed_s = time.monotonic() - started
        self.elapsed.append(elapsed_s)
        self.last_search = dict(info)
        self.last_search["bestmove"] = token
        self.last_search["elapsed_ms"] = round(elapsed_s * 1000, 3)
        if info:
            self.search_stats.append(info)
        return token

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


def play_game(a, b, game_index, max_plies, seed_base):
    a_black = (game_index % 2 == 0)
    black = a if a_black else b
    white = b if a_black else a
    black.configure_game(seed_base + game_index * 2)
    white.configure_game(seed_base + game_index * 2 + 1)

    board = shogi.Board()
    moves = []
    move_records = []
    adjudicator = Adjudicator(board)
    def result(winner, reason, **extra):
        return {"winner": winner, "reason": reason, "plies": len(moves),
                "a_black": a_black, "moves": moves, "move_records": move_records,
                "final_sfen": board.sfen(), **extra}
    for ply in range(max_plies):
        engine = black if board.turn == shogi.BLACK else white
        side_to_move = board.turn
        in_check_before = board.is_check()
        legal_moves_before = sum(1 for _ in board.legal_moves)
        token = engine.bestmove(moves)
        search = compact_search_telemetry(engine.last_search, side_to_move)

        if token == "resign":
            return result(white.label if engine is black else black.label, "resign",
                          terminal_search=search)
        if token == "win":
            if not can_declare_win(board):
                return result(white.label if engine is black else black.label,
                              "invalid_declaration", illegal_by=engine.label,
                              terminal_search=search)
            return result(engine.label, "declare_win", terminal_search=search)

        try:
            move = shogi.Move.from_usi(token)
        except Exception:
            return result(white.label if engine is black else black.label,
                          f"invalid_usi:{token}", illegal_by=engine.label)
        if move not in board.legal_moves:
            return result(white.label if engine is black else black.label,
                          f"illegal_move:{token}", illegal_by=engine.label,
                          terminal_search=search)

        record = {
            "ply": len(moves) + 1,
            "side_to_move": "black" if side_to_move == shogi.BLACK else "white",
            "engine": engine.label,
            "move": token,
            "in_check_before": in_check_before,
            "legal_moves_before": legal_moves_before,
            "is_capture": board.piece_at(move.to_square) is not None,
            "is_promotion": bool(move.promotion),
            "is_drop": move.drop_piece_type is not None,
            "search": search,
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


def search_summary(engine):
    rows = [row for row in engine.search_stats if "nodes" in row]
    if not rows:
        return None
    summary = {
        "samples": len(rows),
        "nodes_total": sum(row["nodes"] for row in rows),
    }
    for name in SEARCH_STAT_NAMES:
        if name in ("nodes", "full_nodes"):
            continue
        values = [row[name] for row in rows if name in row]
        if values:
            summary[name + "_total"] = sum(values)
    if summary.get("tt_probes_total"):
        summary["tt_hit_rate"] = summary.get("tt_hits_total", 0) / summary["tt_probes_total"]
    if summary.get("experience_probes_total"):
        summary["experience_hit_rate"] = (
            summary.get("experience_hits_total", 0) / summary["experience_probes_total"])
    long_rows = [row for row in rows if "long_think_used" in row]
    if long_rows:
        summary["long_think_moves"] = len(long_rows)
        reasons = {}
        for row in long_rows:
            reason = row.get("long_think_reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        summary["long_think_reasons"] = reasons
    if all("full_nodes" in row for row in rows):
        full = sum(row["full_nodes"] for row in rows)
        nodes = summary["nodes_total"]
        summary.update({
            "full_nodes_total": full,
            "visited_fraction": nodes / full if full else 1.0,
            "saved_fraction": 1.0 - nodes / full if full else 0.0,
        })
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-a", required=True)
    parser.add_argument("--engine-b", required=True)
    parser.add_argument("--options-a", default="{}", help="JSON USI options for engine A")
    parser.add_argument("--options-b", default="{}", help="JSON USI options for engine B")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--max-plies", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--go-command", default="go depth 3", help="Explicit equal search limit for both engines")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.go_command.startswith("go ") or "\n" in args.go_command or "\r" in args.go_command:
        raise SystemExit("go-command must be one USI go command")
    if args.games < 1 or args.max_plies < 1 or not 0 <= args.seed <= 2147483647 - args.games * 2:
        raise SystemExit("positive games/max-plies and seeds within the USI range are required")

    options_a, options_b = json.loads(args.options_a), json.loads(args.options_b)
    for options in (options_a, options_b):
        if not isinstance(options, dict) or any("\n" in str(k) + str(v) or "\r" in str(k) + str(v) for k, v in options.items()):
            raise SystemExit("options must be JSON objects without newlines")
        # Production engines may enable long-lived experience by default, but
        # controlled benchmarks must stay cold/reproducible unless a test
        # explicitly opts into ExperienceCache.
        options.setdefault("ExperienceCache", "false")
    a = Engine(args.engine_a, "A", options_a, args.go_command)
    b = Engine(args.engine_b, "B", options_b, args.go_command)
    started = time.monotonic()
    games = []
    try:
        for i in range(args.games):
            result = play_game(a, b, i, args.max_plies, args.seed)
            games.append(result)
            print(f"game {i+1:03d}/{args.games}: {result['winner'] or 'draw'} "
                  f"{result['reason']} {result['plies']} plies")
    finally:
        a.close()
        b.close()

    wins_a = sum(g["winner"] == "A" for g in games)
    wins_b = sum(g["winner"] == "B" for g in games)
    draws = args.games - wins_a - wins_b
    illegal = [g for g in games if "illegal_by" in g]
    summary = {
        "telemetry_schema_version": 1,
        "telemetry_note": ("Every played move carries side/engine/tactical facts plus compact live-search "
                           "telemetry. Live scores are evidence, not causal labels; selective fixed-analyzer "
                           "re-analysis is required before learning."),
        "engine_a": str(Path(args.engine_a)),
        "engine_b": str(Path(args.engine_b)),
        "sha256_a": hashlib.sha256(Path(args.engine_a).read_bytes()).hexdigest(),
        "sha256_b": hashlib.sha256(Path(args.engine_b).read_bytes()).hexdigest(),
        "options_a": options_a,
        "options_b": options_b,
        "seed": args.seed,
        "max_plies": args.max_plies,
        "go_command": args.go_command,
        "response_watchdog_seconds": Engine.RESPONSE_TIMEOUT,
        "timing_note": "wall time includes position reconstruction and USI I/O; depth-limited and timed trials must be interpreted separately",
        "games": args.games,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "draws": draws,
        "score_a": (wins_a + 0.5 * draws) / args.games,
        "average_plies": sum(g["plies"] for g in games) / args.games,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "illegal_games": len(illegal),
        "timing_ms": {e.label: {"moves": len(e.elapsed),
                               "mean": round(1000 * sum(e.elapsed) / len(e.elapsed), 3) if e.elapsed else 0,
                               "max": round(1000 * max(e.elapsed), 3) if e.elapsed else 0}
                      for e in (a, b)},
        "search": {e.label: search_summary(e) for e in (a, b)},
        "details": games,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print("---")
    print(f"A {wins_a} - {draws} - {wins_b} B; score(A)={summary['score_a']:.3f}; "
          f"avg={summary['average_plies']:.1f} plies")
    for engine in (a, b):
        stats = summary["search"][engine.label]
        if not stats:
            continue
        if "full_nodes_total" in stats:
            print(f"{engine.label} search: {stats['nodes_total']}/{stats['full_nodes_total']} nodes "
                  f"({stats['saved_fraction']:.1%} saved), cutoffs={stats.get('cutoffs_total', 0)}")
        else:
            extra = ""
            if "ordered_moves_total" in stats:
                extra += f", ordered_moves={stats['ordered_moves_total']}"
            if "tt_hits_total" in stats:
                extra += (f", tt={stats['tt_hits_total']}/{stats.get('tt_probes_total', 0)}"
                          f" ({stats.get('tt_hit_rate', 0):.1%})")
            if "experience_hits_total" in stats:
                extra += (f", experience={stats['experience_hits_total']}/"
                          f"{stats.get('experience_probes_total', 0)}"
                          f" ({stats.get('experience_hit_rate', 0):.1%})")
            print(f"{engine.label} search: {stats['nodes_total']} nodes, "
                  f"cutoffs={stats.get('cutoffs_total', 0)}{extra}")
    if illegal:
        raise SystemExit("Illegal move detected during benchmark")


if __name__ == "__main__":
    main()
