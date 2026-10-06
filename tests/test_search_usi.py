"""Production protocol: score/PV, real limits, responsive commands and one bestmove."""
import queue
import subprocess
import sys
import threading
import time
import shogi

binary = sys.argv[1]
proc = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
lines = queue.Queue()
def reader():
    for line in proc.stdout:
        lines.put(line.strip())
threading.Thread(target=reader, daemon=True).start()
def send(command):
    proc.stdin.write(command + '\n'); proc.stdin.flush()
def until(prefix, timeout=10):
    seen = []; end = time.monotonic() + timeout
    while True:
        line = lines.get(timeout=max(0.001, end - time.monotonic())); seen.append(line)
        if line.startswith(prefix): return line, seen
def no_best(duration=0.05):
    end = time.monotonic() + duration
    while time.monotonic() < end:
        try: line = lines.get(timeout=end-time.monotonic())
        except queue.Empty: break
        assert not line.startswith('bestmove '), line
def search(sf, command, limit=10):
    send('position sfen ' + sf); start = time.monotonic(); send(command)
    best, seen = until('bestmove ', limit)
    elapsed = time.monotonic() - start
    move = best.split()[1]; board = shogi.Board(sf)
    assert shogi.Move.from_usi(move) in board.legal_moves, (move, sf, seen)
    infos = [line.split() for line in seen if line.startswith('info depth ')]
    for tokens in infos:
        if 'pv' in tokens:
            pv_board = shogi.Board(sf)
            for m in tokens[tokens.index('pv')+1:]:
                assert shogi.Move.from_usi(m) in pv_board.legal_moves, (m, tokens, pv_board.sfen())
                pv_board.push_usi(m)
    assert infos[-1][infos[-1].index('pv')+1] == move, (infos, move)
    return move, infos, elapsed

try:
    send('usi'); until('usiok')
    send('setoption name ExperienceCache value false')
    # This test verifies the search protocol itself. Disable the opening book so
    # start-position book hits cannot legitimately bypass iterative-search info.
    send('setoption name OpeningBook value false')
    send('isready'); until('readyok')
    sf = shogi.Board().sfen()
    _, infos, _ = search(sf, 'go depth 3')
    assert [int(t[t.index('depth')+1]) for t in infos] == [1, 2, 3], infos
    assert all('score' in t and 'cp' in t for t in infos), infos
    # Material-only fixture keeps score fixed across quiet king moves. Score is
    # side-to-move relative; eval breakdown remains Black-relative.
    send('setoption name EvalProfile value material')
    for turn, expected in [('b',100),('w',-100)]:
        _, infos, _ = search('8k/9/9/9/9/9/2P6/9/K8 '+turn+' - 1', 'go depth 1')
        assert int(infos[-1][infos[-1].index('cp')+1]) == expected, infos
    send('setoption name EvalProfile value features')
    _, infos, _ = search('2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1',
                         'go searchmoves 5c5b 5i4i depth 3')
    assert infos[-1][infos[-1].index('mate')+1] == '3', infos
    print('PASS iterative score/PV output, both-color perspective, mate distance')
    # The shallow fixed horizon wins a pawn and overlooks the rook recapture.
    # Toggle the production option in both directions, checking PV and depth.
    poison = '4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1'
    send('setoption name EvalProfile value material')
    for enabled, expected in [('false','5h5d'),('true','5h4h'),('false','5h5d'),('true','5h4h')]:
        send('setoption name Quiescence value ' + enabled)
        move, infos, _ = search(poison, 'go searchmoves 5h5d 5h4h depth 1')
        assert move == expected, (enabled, move, infos)
        if enabled == 'true':
            assert int(infos[-1][infos[-1].index('seldepth')+1]) > 1, infos
    # Stop and clock tests also exercise a position with checks and blocking drops.
    tactical = '3lkl3/3p1p3/9/9/9/9/9/5R3/K8 b g 1'
    for command in ('go nodes 2', 'go movetime 1', 'go movetime 80'):
        _, _, elapsed = search(tactical, command, 2)
        assert elapsed < 0.5, (command, elapsed)
    send('setoption name EvalProfile value features')
    print('PASS quiescence toggle, poisoned capture, seldepth and tactical time/node limits')
    for command in ('go movetime 0', 'go movetime 1', 'go movetime 80', 'go btime 0 wtime 0 byoyomi 80', 'go nodes 1'):
        _, infos, elapsed = search(sf, command, 2)
        assert elapsed < 0.5, (command, elapsed)
        if command in ('go movetime 0', 'go nodes 1'):
            assert infos[-1][infos[-1].index('depth')+1] == '0' and 'score' not in infos[-1], infos
    print('PASS real movetime/byoyomi/zero-time/node limits and legal fallback')

    # Adopted time allocation: a 200ms fixed request may continue the SAME
    # iterative search up to ~1s, at most ten times per game. Use move number 54
    # so the first reserved coupon window reaches its fallback deterministically.
    long_sf = '3lkl3/3p1p3/9/9/9/9/9/5R3/K8 b g 54'
    send('setoption name AdaptiveLongThink value false')
    _, _, plain_elapsed = search(long_sf, 'go movetime 200', 2)
    assert plain_elapsed < 0.55, plain_elapsed

    send('usinewgame')
    send('setoption name AdaptiveLongThink value true')
    send('position sfen ' + long_sf)
    long_started = time.monotonic()
    send('go movetime 200')
    long_best, long_seen = until('bestmove ', 2)
    long_elapsed = time.monotonic() - long_started
    long_move = long_best.split()[1]
    assert shogi.Move.from_usi(long_move) in shogi.Board(long_sf).legal_moves, (long_move, long_seen)
    long_lines = [line for line in long_seen if line.startswith('info string long_think ')]
    assert len(long_lines) == 1, long_seen
    assert 'used 1/10' in long_lines[0], long_lines
    valid_reasons = {
        'in_check', 'score_drop_150', 'iteration_score_change_150',
        'iteration_move_change', 'unfinished_depth2', 'window_fallback',
    }
    reason = long_lines[0].split(' reason ', 1)[1].split()[0]
    assert reason in valid_reasons, long_lines
    assert 0.70 < long_elapsed < 1.50, long_elapsed
    print('PASS adaptive long-think continues 200ms search to one-second ceiling')

    send('position startpos'); send('go infinite')
    send('isready'); until('readyok', 1)
    no_best(); started = time.monotonic(); send('stop'); until('bestmove ', 1)
    assert time.monotonic()-started < 0.5
    no_best(); send('stop'); no_best()
    send('position startpos'); send('go ponder depth 1')
    until('info depth 1 '); no_best(); send('ponderhit'); until('bestmove ', 1); no_best()
    send('position startpos'); send('go ponder movetime 80')
    send('isready'); until('readyok', 1); no_best()
    started = time.monotonic(); send('ponderhit'); until('bestmove ', 1)
    assert time.monotonic()-started < 0.5
    no_best()
    # Superseding a live search must not emit its old bestmove.
    send('position startpos'); send('go infinite')
    send('isready'); until('readyok', 1)
    send('position startpos moves 7g7f'); send('isready'); until('readyok', 1); no_best()
    send('go searchmoves 3c3d depth 2'); best, _ = until('bestmove ')
    assert best == 'bestmove 3c3d'; no_best()
    print('PASS responsive isready/stop/ponderhit, no duplicate or stale bestmove')
    send('position startpos moves 7g7f 7g7f'); until('info string illegal move')
    send('go'); best, _ = until('bestmove '); assert best == 'bestmove resign'
    send('position startpos'); send('go infinite'); send('quit'); proc.wait(timeout=1)
    assert proc.returncode == 0
    print('PASS invalid-position recovery and quit during active search')
finally:
    if proc.poll() is None:
        send('quit'); proc.wait(timeout=3)

# Closing stdin is another shutdown path and must join the active worker.
eof = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
eof.communicate('setoption name ExperienceCache value false\nsetoption name OpeningBook value false\nposition startpos\ngo infinite\n', timeout=2)
assert eof.returncode == 0
print('PASS EOF during active search')
