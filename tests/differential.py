"""Independent legal-move/SFEN oracle. python-shogi is test-only."""
import random
import subprocess
import sys
import shogi

rng = random.Random(20261003)
proc = subprocess.Popen([sys.argv[1], "--probe"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, text=True, bufsize=1)

def exchange(command):
    proc.stdin.write(command + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    if not line or line.startswith("ERROR"):
        raise AssertionError((command, line, proc.poll()))
    sfen, check, outcome, moves = line.split("|")
    return sfen, check == "1", int(outcome), set(moves.split())

def verify(board, actual):
    sfen, check, outcome, moves = actual
    expected = {m.usi() for m in board.legal_moves}
    assert moves == expected, (board.sfen(), "missing", expected-moves, "extra", moves-expected)
    assert sfen == board.sfen(), (sfen, board.sfen())
    assert check == board.is_check(), sfen
    return outcome

count = 0
try:
    for game in range(20):
        board = shogi.Board()
        actual = exchange("position startpos")
        for ply in range(250):
            outcome = verify(board, actual)
            count += 1
            moves = sorted(actual[3])
            if outcome or not moves:
                break
            move = rng.choice(moves)
            previous = board.sfen()
            board.push_usi(move)
            actual = exchange("play " + move)
            if ply % 17 == 0:
                verify(board, actual)
                board.pop()
                verify(board, exchange("undo"))
                assert board.sfen() == previous
                board.push_usi(move)
                actual = exchange("play " + move)
    print(f"PASS independent python-shogi 1.1.1 comparison: {count} positions, exact legal moves/SFEN/check and undo")
finally:
    proc.stdin.write("quit\n")
    proc.stdin.flush()
    proc.wait(timeout=5)
