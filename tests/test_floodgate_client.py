#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "floodgate"))

import protocol as fg
import client as fc
import timeplan as tp


class FloodgateProtocolTest(unittest.TestCase):
    def test_startpos_move_roundtrip(self):
        board = fg.StartposBoard()
        self.assertEqual(board.usi_to_csa("7g7f", "+"), "+7776FU")
        self.assertEqual(board.csa_to_usi("+7776FU"), "7g7f")
        board.apply_csa("+7776FU")
        self.assertEqual(board.usi_to_csa("3c3d", "-"), "-3334FU")

    def test_promotion_and_drop(self):
        board = fg.StartposBoard()
        self.assertEqual(board.usi_to_csa("8h2b+", "+"), "+8822UM")
        self.assertEqual(board.csa_to_usi("+8822UM"), "8h2b+")
        self.assertEqual(board.usi_to_csa("P*5e", "+"), "+0055FU")
        self.assertEqual(board.csa_to_usi("+0055FU"), "P*5e")

    def test_summary_parser_floodgate_increment(self):
        parser = fg.SummaryParser()
        lines = [
            "BEGIN Game_Summary",
            "Protocol_Version:1.1",
            "Protocol_Mode:Server",
            "Format:Shogi 1.0",
            "Game_ID:test-001",
            "Name+:KUMOJI",
            "Name-:Opponent",
            "Your_Turn:+",
            "Rematch_On_Draw:NO",
            "To_Move:+",
            "BEGIN Time",
            "Time_Unit:1sec",
            "Total_Time:300",
            "Byoyomi:0",
            "Increment:10",
            "Max_Moves:512",
            "END Time",
            "BEGIN Position",
            "P1-KY-KE-GI-KI-OU-KI-GI-KE-KY",
            "+",
            "END Position",
            "END Game_Summary",
        ]
        summary = None
        for line in lines:
            value = parser.feed(line)
            if value is not None:
                summary = value
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.game_id, "test-001")
        self.assertEqual(summary.increment, 10)
        self.assertEqual(summary.total_time, 300)
        self.assertEqual(summary.max_moves, 512)
        self.assertEqual(summary.unit_ms, 1000)


    def test_fourfold_repetition_waits_for_server(self):
        board = fg.StartposBoard()
        cycle = ["+5958OU", "-5152OU", "+5859OU", "-5251OU"]
        for _ in range(3):
            for move in cycle:
                board.csa_to_usi(move)
                board.apply_csa(move)
        self.assertEqual(board.repetition_count(), 4)
        self.assertTrue(board.server_terminal_pending(12, 512))

    def test_max_moves_waits_for_server(self):
        board = fg.StartposBoard()
        self.assertFalse(board.server_terminal_pending(511, 512))
        self.assertTrue(board.server_terminal_pending(512, 512))

    def test_capture_and_drop_keep_exact_hand_state(self):
        board = fg.StartposBoard()
        for move in ["+7776FU", "-3334FU", "+8822UM", "-3122GI"]:
            board.csa_to_usi(move)
            board.apply_csa(move)
        self.assertEqual(board.hands["+"]["KA"], 1)
        self.assertEqual(board.csa_to_usi("+0055KA"), "B*5e")
        board.apply_csa("+0055KA")
        self.assertEqual(board.hands["+"]["KA"], 0)

    def test_clock_folds_fischer_increment_after_server_echo(self):
        summary = fg.GameSummary(
            game_id="g", your_turn="+", to_move="+",
            total_time=300, increment=10, time_unit="1sec",
        )
        clock = fg.Clock(summary)
        self.assertEqual(clock.usi_go(), "go btime 300000 wtime 300000")
        clock.observe("+7776FU,T4")
        self.assertEqual(clock.remaining["+"], 306000)
        self.assertEqual(clock.remaining["-"], 300000)
        self.assertEqual(clock.usi_go(), "go btime 306000 wtime 300000")
        self.assertNotIn("binc", clock.usi_go())

    def test_time_unit(self):
        self.assertEqual(fg.parse_time_unit_ms("1sec"), 1000)
        self.assertEqual(fg.parse_time_unit_ms("100msec"), 100)
        self.assertEqual(fg.parse_time_unit_ms("2min"), 120000)

        with self.assertRaises(ValueError):
            fc.parse_setoptions(["broken"])

    def test_identity_validation(self):
        fc.validate_identity("KUMOJI_1", "private-trip-123")
        with self.assertRaises(ValueError):
            fc.validate_identity("bad name", "trip")
        with self.assertRaises(ValueError):
            fc.validate_identity("KUMOJI", "")

    def test_usi_info_score_is_parsed_and_turned_to_black_view(self):
        info = fc.parse_usi_info("info depth 10 seldepth 20 time 7944 nodes 3244314 score cp 13 pv 8h2b+ 3a2b")
        self.assertEqual((info["depth"], info["score_kind"], info["score_raw"], info["pv"]),
                         (10, "cp", "13", ["8h2b+", "3a2b"]))
        self.assertEqual(fc.score_for_black(info, "+"), 13)
        self.assertEqual(fc.score_for_black(info, "-"), -13)
        mate = fc.parse_usi_info("info depth 5 score mate -3 pv 5a4b")
        self.assertEqual(fc.score_for_black(mate, "+"), -fc.MATE_COMMENT_CP)
        self.assertEqual(fc.score_for_black(mate, "-"), fc.MATE_COMMENT_CP)
        self.assertIsNone(fc.parse_usi_info("info nodes 10 string cutoffs 3 score"))
        self.assertIsNone(fc.parse_usi_info("info string opening_random_non_lance move 5i4h"))
        self.assertIsNone(fc.score_for_black({}, "+"))

    def test_time_plan_stages_for_300_plus_10(self):
        opening = tp.make_plan(300000, 10000, 1)
        self.assertEqual((opening.stage, opening.base_ms), ("opening", 5000))
        middle = tp.make_plan(340000, 10000, 9)
        self.assertEqual((middle.stage, middle.base_ms, middle.max_ms), ("middle", 25000, 75000))
        end = tp.make_plan(120000, 10000, 41)
        self.assertEqual((end.stage, end.base_ms), ("end", 12000))
        low = tp.make_plan(25000, 10000, 30)
        self.assertEqual((low.stage, low.base_ms, low.max_ms), ("reserve", 8000, 8000))
        # never plans beyond the clock minus the safety margin
        for rem in (500, 3000, 5000, 12000, 31000, 600000):
            for n in (1, 9, 41):
                plan = tp.make_plan(rem, 10000, n)
                self.assertLessEqual(plan.max_ms, max(100, rem - tp.SAFETY_MARGIN_MS))
                self.assertLessEqual(plan.min_ms, plan.base_ms)
                self.assertLessEqual(plan.base_ms, plan.max_ms)

    def test_stop_controller_shortens_extends_and_caps(self):
        plan = tp.make_plan(340000, 10000, 9)  # base 25s, min 8.3s, max 75s
        info = lambda d, mv, cp: {"depth": d, "pv": [mv], "score_kind": "cp", "score_raw": str(cp)}
        stable = tp.StopController(plan)
        for d in range(5, 9):
            stable.observe(info(d, "7g7f", 30))
        self.assertFalse(stable.should_stop(plan.min_ms - 1))
        self.assertTrue(stable.should_stop(plan.min_ms))
        self.assertEqual(stable.reason, "stable")
        changing = tp.StopController(plan)
        changing.observe(info(8, "7g7f", 30)); changing.observe(info(9, "2g2f", 35))
        self.assertFalse(changing.should_stop(plan.base_ms))
        self.assertTrue(changing.should_stop(plan.max_ms))
        self.assertEqual(changing.reason, "max")
        dropped = tp.StopController(plan, previous_score=200)
        dropped.observe(info(8, "7g7f", 60)); dropped.observe(info(9, "7g7f", 50))
        self.assertFalse(dropped.should_stop(plan.base_ms))
        calm = tp.StopController(plan, previous_score=40)
        calm.observe(info(8, "7g7f", 30)); calm.observe(info(9, "7g7f", 35))
        self.assertTrue(calm.should_stop(plan.base_ms))
        self.assertEqual(calm.reason, "base")
        mate = tp.StopController(plan)
        mate.observe({"depth": 7, "pv": ["5b5a"], "score_kind": "mate", "score_raw": "3"})
        self.assertTrue(mate.should_stop(300))
        reserve = tp.StopController(tp.make_plan(25000, 10000, 30))
        reserve.observe(info(8, "7g7f", 30)); reserve.observe(info(9, "2g2f", -300))
        self.assertTrue(reserve.should_stop(8000))


class KeepaliveTest(unittest.TestCase):
    def test_seconds_until_login(self):
        # 12:00 JST = 03:00 UTC。epoch秒の1800秒区切りが組み合わせの時刻
        slot = 1800 * 1_000_000
        self.assertAlmostEqual(fc.seconds_until_login(slot + 60), 1800 - 60 - 180)
        self.assertEqual(fc.seconds_until_login(slot - 100), 0.0)    # 組み合わせの100秒前: すぐログイン
        self.assertEqual(fc.seconds_until_login(slot - 180), 0.0)
        self.assertAlmostEqual(fc.seconds_until_login(slot - 600), 420.0)

    def test_keepalive_lines_sent_and_blank_replies_ignored(self):
        import socket as sk
        import threading
        srv = sk.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        got = []

        def serve():
            c, _ = srv.accept()
            f = c.makefile("rw", encoding="utf-8", newline="\n")
            c.settimeout(3)
            try:
                while len(got) < 3:
                    got.append(f.readline())
                f.write("\n"); f.write(" \n"); f.write("LOGIN:x OK\n"); f.flush()   # 空行の返事のあとに実メッセージ
            finally:
                c.close()
        t = threading.Thread(target=serve, daemon=True); t.start()
        conn = fc.CsaSocket("127.0.0.1", port, keepalive_s=0.1)
        try:
            conn.send("LOGIN x y")
            self.assertEqual(conn.recv(), "LOGIN:x OK")   # 空行・空白だけの行は読み飛ばされる
        finally:
            conn.close(); srv.close()
        t.join(timeout=3)
        self.assertEqual(got[0], "LOGIN x y\n")
        self.assertTrue(all(g == "\n" for g in got[1:3]), got)  # 以降は生存信号の空行


if __name__ == "__main__":
    unittest.main()
