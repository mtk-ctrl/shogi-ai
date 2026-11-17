#!/usr/bin/env python3
"""USI checks for the YaneuraOu-format opening book (BookFile).

usage: python3 tests/test_opening_book_usi.py build/shogi-ai
"""
from collections import Counter
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
ENGINE = str(Path(sys.argv[1]).resolve())
BOOK = str(ROOT / "books/aigakari.db")
PLY10 = "position startpos moves 2g2f 8c8d 2f2e 8d8e 6i7h 4a3b 2e2d 2c2d 2h2d P*2c"


def play(setup, position, go="go movetime 100", extra=()):
    p = subprocess.Popen([ENGINE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=ROOT)
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l.rstrip("\n")) for l in p.stdout], daemon=True).start()

    def send(*lines):
        for line in lines:
            p.stdin.write(line + "\n")
        p.stdin.flush()

    def until(prefix):
        seen, end = [], time.monotonic() + 15
        while time.monotonic() < end:
            try:
                line = q.get(timeout=0.2)
            except queue.Empty:
                continue
            seen.append(line)
            if line.startswith(prefix):
                return seen
        raise RuntimeError(f"timeout {prefix}: {seen[-5:]}")

    send("usi", "setoption name OpeningRandomNonLance value false",
         f"setoption name BookFile value {BOOK}", *setup, "isready")
    loaded = until("readyok")
    send("usinewgame", position, go, *extra)
    seen = until("bestmove")
    send("quit")
    p.wait(timeout=5)
    return loaded + seen


def best(lines):
    return next(l for l in lines if l.startswith("bestmove")).split()[1]


def hit(lines):
    return any(l.startswith("info string book hit") for l in lines)


def main():
    lines = play([], "position startpos")
    assert any("book loaded 26 positions" in l for l in lines), lines
    assert best(lines) == "2g2f" and hit(lines)
    # Gote side and transposition (different move order, same position).
    assert best(play([], "position startpos moves 2g2f")) == "8c8d"
    assert best(play([], "position startpos moves 2g2f 8c8d 6i7h 4a3b 2f2e 8d8e")) == "2e2d"
    # Ponder: book move is still returned after ponderhit.
    assert best(play([], "position startpos moves 2g2f", "go ponder movetime 100", ("ponderhit",))) == "8c8d"
    # Out of book and over BookMoves fall back to normal search.
    assert not hit(play([], "position startpos moves 7g7f"))
    assert not hit(play(["setoption name BookMoves value 2"], "position startpos moves 2g2f 8c8d 2f2e"))
    # searchmoves restriction always wins over the book.
    assert best(play([], "position startpos", "go movetime 100 searchmoves 7g7f")) == "7g7f"
    # best = most counted (2d2h: 3 lines vs 2d2f: 1 line); weighted mixes both.
    assert best(play(["setoption name BookSelect value best"], PLY10)) == "2d2h"
    picks = Counter(best(play([f"setoption name RandomSeed value {s}"], PLY10, "go movetime 20"))
                    for s in range(1, 17))
    assert set(picks) == {"2d2h", "2d2f"} and picks["2d2h"] > picks["2d2f"], picks
    # Missing / malformed file: book off, engine still plays.
    with tempfile.NamedTemporaryFile("w", suffix=".db", delete=False) as bad:
        bad.write("sfen x\n")
    lines = play([f"setoption name BookFile value {bad.name}"], "position startpos")
    assert any("book unavailable" in l for l in lines) and not hit(lines)
    print("opening book USI tests passed", dict(picks))


if __name__ == "__main__":
    main()
