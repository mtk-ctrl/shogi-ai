#!/usr/bin/env python3
"""Build an opening book (YaneuraOu DB2016 text format) from move lines.

The source is a plain text file, one variation per line, written in USI
moves from the initial position:

    # 相掛かり 本線（浮き飛車）
    2g2f 8c8d 2f2e 8d8e 6i7h 4a3b 2e2d 2c2d 2h2d P*2c 2d2f

* `startpos moves` at the beginning of a line is accepted and ignored.
* `#` starts a comment. Blank lines are ignored.
* Every position on a line gets the next move registered (both sides), so the
  book works whether KUMOJI plays sente or gote.
* `count` = how many lines pass through that position/move. When several
  moves exist in one position, the engine picks by count
  (BookSelect=weighted) or the most counted one (BookSelect=best).
* Lines that share positions by a different move order (transpositions)
  merge automatically, because positions are keyed by board+side+hands.

Optional `--think-ms N --engine PATH` asks KUMOJI to search every book move
(`go movetime N searchmoves <move>`) and stores its score and depth in the
eval/depth columns, the same idea as YaneuraOu's `makebook think`. Without it
eval/depth are 0. The engine itself only uses eval as a tie-breaker.

Every move is validated with the python-shogi rule implementation; an
illegal move aborts with its file and line number.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import shogi

HEADER = "#YANEURAOU-DB2016 1.00"


@dataclass
class BookMove:
    move: str
    ponder: str = "none"
    eval: int = 0
    depth: int = 0
    count: int = 0


@dataclass
class BookPosition:
    sfen: str            # board turn hand (no ply)
    ply: int             # first ply at which it was reached
    moves: dict[str, BookMove] = field(default_factory=dict)


def position_key(board: shogi.Board) -> str:
    return " ".join(board.sfen().split()[:3])


def parse_line(raw: str) -> list[str]:
    text = raw.split("#", 1)[0].strip()
    if not text:
        return []
    tokens = text.split()
    if tokens[:2] == ["startpos", "moves"]:
        tokens = tokens[2:]
    elif tokens[:1] == ["moves"]:
        tokens = tokens[1:]
    return tokens


def add_lines(book: dict[str, BookPosition], path: Path, max_ply: int) -> int:
    added = 0
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        moves = parse_line(raw)
        if not moves:
            continue
        board = shogi.Board()
        for index, usi in enumerate(moves[:max_ply]):
            try:
                move = shogi.Move.from_usi(usi)
            except ValueError:
                raise SystemExit(f"{path}:{line_no}: unreadable move {usi!r} (#{index + 1})")
            if move not in board.legal_moves:
                raise SystemExit(f"{path}:{line_no}: illegal move {usi} at ply {index + 1}")
            key = position_key(board)
            entry = book.setdefault(key, BookPosition(key, index + 1))
            entry.ply = min(entry.ply, index + 1)
            bm = entry.moves.setdefault(usi, BookMove(usi))
            bm.count += 1
            if index + 1 < len(moves) and bm.ponder == "none":
                bm.ponder = moves[index + 1]
            board.push(move)
        added += 1
    return added


def read_db(book: dict[str, BookPosition], path: Path) -> None:
    key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = line.split()
        if parts[0] == "sfen":
            board = shogi.Board(" ".join(parts[1:4]) + " 1")
            key = position_key(board)
            ply = int(parts[4]) if len(parts) > 4 else 1
            book.setdefault(key, BookPosition(key, ply))
            continue
        if key is None:
            raise SystemExit(f"{path}: move line before sfen")
        move, ponder, ev, depth, count = (parts + ["none", "0", "0", "1"])[:5]
        bm = book[key].moves.setdefault(move, BookMove(move))
        bm.count += int(count)
        if bm.ponder == "none":
            bm.ponder = ponder
        bm.eval, bm.depth = int(ev), int(depth)


class Engine:
    def __init__(self, path: str):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.q: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.send("usi"); self.wait("usiok")
        # Fresh search of the book move only: no knowledge, no random opening.
        for name, value in (("OpeningRandomNonLance", "false"), ("PositionKnowledge", "false"),
                            ("USI_Ponder", "false"), ("BookFile", "<empty>")):
            self.send(f"setoption name {name} value {value}")
        self.send("isready"); self.wait("readyok")

    def _read(self):
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))

    def send(self, s: str):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()

    def wait(self, prefix: str, timeout: float = 60) -> list[str]:
        seen, end = [], time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                line = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            seen.append(line)
            if line.startswith(prefix):
                return seen
        raise RuntimeError(f"engine timeout waiting for {prefix}")

    def think(self, sfen: str, move: str, ms: int) -> tuple[int, int]:
        self.send("usinewgame")
        self.send(f"position sfen {sfen} 1")
        self.send(f"go movetime {ms} searchmoves {move}")
        score, depth = 0, 0
        for line in self.wait("bestmove", timeout=ms / 1000 + 30):
            t = line.split()
            if t[:1] == ["info"] and "score" in t and "depth" in t:
                depth = int(t[t.index("depth") + 1])
                kind, value = t[t.index("score") + 1], int(t[t.index("score") + 2])
                score = value if kind == "cp" else (32000 - abs(value)) * (1 if value > 0 else -1)
        return score, depth

    def close(self):
        if self.p.poll() is None:
            self.send("quit")
            self.p.wait(timeout=5)


def write_db(book: dict[str, BookPosition], path: Path) -> None:
    lines = [HEADER, f"# NOE:{len(book)}"]
    for key in sorted(book):           # sorted by sfen, as BookOnTheFly expects
        pos = book[key]
        lines.append(f"sfen {pos.sfen} {pos.ply}")
        for bm in sorted(pos.moves.values(), key=lambda m: (-m.count, -m.eval, m.move)):
            lines.append(f"{bm.move} {bm.ponder} {bm.eval} {bm.depth} {bm.count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", type=Path, help="move-line .txt files (or .db to merge)")
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--max-ply", type=int, default=60, help="register moves up to this ply")
    ap.add_argument("--engine", help="KUMOJI binary for --think-ms")
    ap.add_argument("--think-ms", type=int, default=0, help="search each book move this long")
    args = ap.parse_args()

    book: dict[str, BookPosition] = {}
    lines = 0
    for src in args.sources:
        if src.suffix == ".db":
            read_db(book, src)
        else:
            lines += add_lines(book, src, args.max_ply)

    if args.think_ms > 0:
        if not args.engine:
            raise SystemExit("--think-ms needs --engine")
        engine = Engine(args.engine)
        try:
            total = sum(len(p.moves) for p in book.values())
            done = 0
            for pos in book.values():
                for bm in pos.moves.values():
                    bm.eval, bm.depth = engine.think(pos.sfen, bm.move, args.think_ms)
                    done += 1
                    print(f"think {done}/{total} {bm.move} eval {bm.eval} depth {bm.depth}", file=sys.stderr)
        finally:
            engine.close()

    write_db(book, args.output)
    moves = sum(len(p.moves) for p in book.values())
    print(f"{args.output}: {lines} lines, {len(book)} positions, {moves} moves")


if __name__ == "__main__":
    main()
