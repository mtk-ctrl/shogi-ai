#!/usr/bin/env python3
"""Experimental coupon limits and real USI clock/reset verification."""
import sys
from pathlib import Path
import time
import shogi

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from bonus_time_match import BonusEngine, select_bonus

b = shogi.Board()
probe = {"depth": 2, "score_cp": 0, "elapsed_ms": 50}
assert select_bonus("adaptive", 24, 5, 300, probe, [], b, 50) is None
assert select_bonus("adaptive", 23, 0, 300, probe, [], b, 50) is None
assert select_bonus("adaptive", 24, 0, 300, {**probe, "depth": 0}, [], b, 50) is None
assert select_bonus("adaptive", 24, 0, 300, {**probe, "score_mate": 3}, [], b, 50) is None
assert select_bonus("adaptive", 24, 1, 300, probe, [], b, 50) is None
assert select_bonus("none", 100, 0, 300, probe, [], b, 50) is None

if len(sys.argv) > 1:
    e = BonusEngine(sys.argv[1], "test", {"OpeningBook": False,
                    "MateAssist": False, "ExperienceCache": False},
                    "scheduled", 100, normal_ms=50, bonus_ms=250)
    try:
        e.configure_game(100)
        # Legal 24-ply prefix: distinct lateral pawn moves plus minor pieces.
        moves = []
        for _ in range(24):
            move = next(iter(b.legal_moves))
            moves.append(move.usi())
            b.push(move)
        token = e.bestmove(moves)
        assert shogi.Move.from_usi(token) in b.legal_moves
        assert e.used == 1 and e.decisions[-1]["extended"]
        assert e.decisions[-1]["final"]["elapsed_ms"] < 500
        e.used = 5
        e.bestmove(moves)
        assert e.used == 5 and not e.decisions[-1]["extended"]
        e.configure_game(103)
        assert e.used == 0 and e.previous is None and not e.decisions
        # Actual 30-second request: confirms the watchdog does not fail at 30s.
        e.bonus_ms = 30000
        e.used = 0
        started = time.monotonic()
        e.bestmove(moves)
        assert e.decisions[-1]["extended"] and e.used == 1
        elapsed = time.monotonic() - started
        assert 29 <= elapsed <= 30.5, elapsed
    finally:
        e.close()
print("PASS bonus-time: cap, stage reservation, Book/mate exclusions, USI clock and reset")
