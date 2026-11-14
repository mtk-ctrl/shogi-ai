#!/usr/bin/env python3
"""Floodgate(CSA)の模擬サーバ。リハーサル専用。python-shogiで合法性を独立に検査し、相手役はランダム合法手。"""
import argparse, random, socket, time
import shogi
CSA = {1:"FU",2:"KY",3:"KE",4:"GI",5:"KI",6:"KA",7:"HI",8:"OU",9:"TO",10:"NY",11:"NK",12:"NG",13:"UM",14:"RY"}
def sq(s): return f"{9 - s % 9}{s // 9 + 1}"
def to_csa(board, mv, sign):
    if mv.from_square is None:
        return f"{sign}00{sq(mv.to_square)}{CSA[mv.drop_piece_type]}"
    pt = board.piece_at(mv.from_square).piece_type
    if mv.promotion: pt = shogi.PIECE_PROMOTED[pt]
    return f"{sign}{sq(mv.from_square)}{sq(mv.to_square)}{CSA[pt]}"
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=4081)
    ap.add_argument("--client-side", default="+"); ap.add_argument("--total", type=int, default=60)
    ap.add_argument("--inc", type=int, default=2); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--opponent-engine", default=""); ap.add_argument("--opponent-go", default="go nodes 9545")
    a = ap.parse_args(); rng = random.Random(a.seed)
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", a.port)); srv.listen(1)
    c, _ = srv.accept(); f = c.makefile("rw", encoding="utf-8", newline="\n")
    def send(s): f.write(s + "\n"); f.flush()
    login = f.readline().split(); assert login[0] == "LOGIN" and login[2].startswith("floodgate-300-10F,"), login
    name = login[1]; send(f"LOGIN:{name} OK")
    gid = "wdoor+floodgate-300-10F+mock+test+20261114000000"
    nb, nw = (name, "mock_random") if a.client_side == "+" else ("mock_random", name)
    for l in ["BEGIN Game_Summary","Protocol_Version:1.2","Protocol_Mode:Server","Format:Shogi 1.0","Declaration:Jishogi 1.1",
              f"Game_ID:{gid}",f"Name+:{nb}",f"Name-:{nw}",f"Your_Turn:{a.client_side}","Rematch_On_Draw:NO","To_Move:+","Max_Moves:512",
              "BEGIN Time","Time_Unit:1sec",f"Total_Time:{a.total}","Byoyomi:0",f"Increment:{a.inc}","Least_Time_Per_Move:0","END Time",
              "BEGIN Position","P1-KY-KE-GI-KI-OU-KI-GI-KE-KY","P2 * -HI *  *  *  *  * -KA * ","P3-FU-FU-FU-FU-FU-FU-FU-FU-FU",
              "P4 *  *  *  *  *  *  *  *  * ","P5 *  *  *  *  *  *  *  *  * ","P6 *  *  *  *  *  *  *  *  * ",
              "P7+FU+FU+FU+FU+FU+FU+FU+FU+FU","P8 * +KA *  *  *  *  * +HI * ","P9+KY+KE+GI+KI+OU+KI+GI+KE+KY","+","END Position","END Game_Summary"]:
        send(l)
    assert f.readline().strip() == f"AGREE {gid}"; send(f"START:{gid}")
    eng = None
    if a.opponent_engine:
        import subprocess
        eng = subprocess.Popen([a.opponent_engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        def ecmd(x, until=None):
            eng.stdin.write(x + "\n"); eng.stdin.flush()
            while until:
                l = eng.stdout.readline().strip()
                if l.startswith(until): return l
        ecmd("usi", "usiok"); ecmd("setoption name Threads value 1"); ecmd("setoption name USI_Hash value 16"); ecmd("setoption name USI_OwnBook value false"); ecmd("isready", "readyok"); ecmd("usinewgame")
    usi_moves = []
    board = shogi.Board(); remain = {"+": a.total, "-": a.total}; maxt = 0; n = 0
    while True:
        sign = "+" if board.turn == shogi.BLACK else "-"
        if sign == a.client_side:
            t0 = time.monotonic(); line = f.readline().strip(); used = int(time.monotonic() - t0)
            maxt = max(maxt, used); remain[sign] -= used
            if remain[sign] < 0: send("#TIME_UP"); send("#LOSE"); print("MOCK client TIME_UP"); break
            remain[sign] += a.inc
            if line == "%TORYO": send("%TORYO,T%d" % used); send("#RESIGN"); send("#LOSE"); print("MOCK client resigned"); break
            if line == "%KACHI": send("%KACHI,T%d" % used); send("#JISHOGI"); send("#WIN"); print("MOCK client declared"); break
            legal = {to_csa(board, m, sign): m for m in board.legal_moves}
            if line not in legal: send("#ILLEGAL_MOVE"); send("#LOSE"); print("MOCK ILLEGAL", line); break
            usi_moves.append(legal[line].usi()); board.push(legal[line]); send(f"{line},T{used}"); n += 1
        else:
            ms = list(board.legal_moves)
            if not ms: send("%TORYO,T0"); send("#RESIGN"); send("#WIN"); print(f"MOCK opponent mated after {n} client moves, max client think {maxt}s, client clock {remain[a.client_side]}s"); break
            m = rng.choice(ms)
            if eng:
                bm = ecmd("position startpos moves " + " ".join(usi_moves), None) or ecmd(a.opponent_go, "bestmove").split()[1]
                if bm in ("resign", "win"): send("%TORYO,T0"); send("#RESIGN"); send("#WIN"); print(f"MOCK opponent engine resigned after {n} client moves, max client think {maxt}s, client clock {remain[a.client_side]}s"); break
                m = shogi.Move.from_usi(bm)
            usi_moves.append(m.usi()); line = to_csa(board, m, sign); board.push(m); send(f"{line},T1")
    f.close(); c.close(); srv.close()
main()
