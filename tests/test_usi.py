import queue
import subprocess
import sys
import threading
import shogi

engine = subprocess.Popen([sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True, bufsize=1)
lines = queue.Queue()
def reader():
    for line in engine.stdout:
        lines.put(line.strip())
threading.Thread(target=reader, daemon=True).start()
def send(command):
    engine.stdin.write(command + "\n")
    engine.stdin.flush()
def until(prefix):
    while True:
        line = lines.get(timeout=30)
        if line.startswith(prefix): return line
def best():
    return until("bestmove ").split()[1]
def no_output():
    # Thinking may emit progress info while ponder/infinite still withhold bestmove.
    import time
    end = time.monotonic() + 0.1
    while time.monotonic() < end:
        try: line = lines.get(timeout=end-time.monotonic())
        except queue.Empty: return
        assert line.startswith('info '), f"Unexpected output: {line}"

try:
    send("usi"); until("usiok")
    send("isready"); until("readyok")
    send("setoption name RandomSeed value 12345")
    send("usinewgame"); send("position startpos"); send("go")
    seeded = best()
    send("usinewgame"); send("position startpos"); send("go")
    assert best() == seeded
    send("setoption name RandomSeed value 5489")
    print("PASS RandomSeed reproducibility across usinewgame")

    # Production strategy legal-move integration. Rule-layer stress/perft coverage is
    # separate, so this stays bounded as search depth increases.
    board = shogi.Board()
    moves = []
    for ply in range(120):
        send("position startpos moves " + " ".join(moves))
        send("go depth 3")
        move = best()
        if move == "resign":
            assert not list(board.legal_moves)
            break
        assert shogi.Move.from_usi(move) in board.legal_moves, (ply, move, board.sfen())
        board.push_usi(move); moves.append(move)
        if board.is_game_over(): break
    assert len(moves) > 2
    print(f"PASS USI game against independent legal-move validation: {len(moves)} plies")

    send("usinewgame")
    send("position startpos")
    for mode, release in [("ponder", "ponderhit"), ("infinite", "stop"), ("ponder", "stop")]:
        send("go " + mode + " depth 3")
        no_output()
        send("isready"); until("readyok")
        send(release)
        assert shogi.Move.from_usi(best()) in shogi.Board().legal_moves
        send("stop"); no_output()
    send("go searchmoves 7g7f depth 1")
    assert best() == "7g7f"
    send("go searchmoves 7g7g")
    assert best() == "resign"

    # go mate is now a bounded self-authored solver. The initial position has no
    # mate proven inside its horizon, so USI reports timeout rather than the old
    # pre-v0.0.16 "notimplemented" placeholder. Dedicated mate fixtures live in
    # test_mate_usi.py; here we only verify that the command is wired into USI.
    send("position startpos")
    send("go mate 1000")
    assert until("checkmate ") == "checkmate timeout"

    send("position startpos moves 7g7f 7g7f")
    until("info string illegal move")
    send("go"); assert best() == "resign"
    send("position startpos")
    send("go searchmoves 2g2f"); assert best() == "2g2f"

    # The prior poisoned-pawn regression remains covered at the production USI layer.
    send("position sfen 4r3k/9/9/4p4/4R4/9/9/9/K8 b - 1")
    send("go"); assert best() != "5e5d"
    send("go searchmoves 5e5d"); assert best() == "5e5d"
    print("PASS deeper strategy still avoids the documented poisoned pawn")

    # v0.0.6 must see the forced mate on its third ply. 5c5b checks, K6a is
    # forced, and G7c6b mates; B9e protects the mating gold.
    # 9i8i also forces mate; move R5i4i instead to remove the file support.
    send("position sfen 2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1")
    send("go searchmoves 5c5b 5i4i")
    assert best() == "5c5b"
    print("PASS three-ply strategy finds the forced third-ply mate through USI")
    print("PASS position recovery, searchmoves, bounded mate, ponder, stop and infinite")
finally:
    send("quit")
    engine.wait(timeout=5)
    assert engine.returncode == 0
