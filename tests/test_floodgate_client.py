#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "floodgate"))

import protocol as fg
import client as fc


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
        self.assertEqual(summary.unit_ms, 1000)

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

    def test_external_options_are_safe_by_default(self):
        options = fc.parse_setoptions([])
        self.assertEqual(options["ExperienceCache"], "false")
        self.assertEqual(options["OpeningBook"], "true")
        changed = fc.parse_setoptions(["OpeningBook=false"])
        self.assertEqual(changed["OpeningBook"], "false")
        with self.assertRaises(ValueError):
            fc.parse_setoptions(["broken"])

    def test_identity_validation(self):
        fc.validate_identity("KUMOJI_1", "private-trip-123")
        with self.assertRaises(ValueError):
            fc.validate_identity("bad name", "trip")
        with self.assertRaises(ValueError):
            fc.validate_identity("KUMOJI", "")


if __name__ == "__main__":
    unittest.main()
