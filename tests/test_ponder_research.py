#!/usr/bin/env python3
"""Research-only integration check for actual USI ponder hit/miss transitions.

Uses an unrestricted fixed-depth search to test protocol correctness, not
playing strength. A production match keeps the adopted position knowledge.
"""
import sys
from pathlib import Path

import shogi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine

if len(sys.argv) != 2:
    raise SystemExit("usage: test_ponder_research.py ENGINE")
engine = Engine(sys.argv[1], "ponder-protocol",
                {"USI_Ponder": True, "RiskVerify": True,
                 "OpeningRandomNonLance": False,
                 "PositionKnowledge": False}, "go depth 3")
try:
    engine.configure_game(5489)
    board = shogi.Board()
    first = engine.bestmove([])
    assert shogi.Move.from_usi(first) in board.legal_moves, first
    board.push_usi(first)
    engine.begin_ponder([first], board)
    prediction = engine.pending_ponder
    assert prediction, "search did not return a predicted legal reply"
    assert shogi.Move.from_usi(prediction) in board.legal_moves
    board.push_usi(prediction)
    second = engine.bestmove([first, prediction])
    assert engine.last_ponder_hit and engine.ponder_hits == 1
    assert shogi.Move.from_usi(second) in board.legal_moves, second

    # The same predicted position must be discarded on an unexpected reply.
    engine.configure_game(5489)
    board = shogi.Board()
    first = engine.bestmove([])
    board.push_usi(first)
    engine.begin_ponder([first], board)
    prediction = engine.pending_ponder
    assert prediction
    alternate = next(m.usi() for m in board.legal_moves if m.usi() != prediction)
    board.push_usi(alternate)
    second = engine.bestmove([first, alternate])
    assert not engine.last_ponder_hit and engine.ponder_misses == 1
    assert shogi.Move.from_usi(second) in board.legal_moves, second
    print("PASS ponder research: legal prediction, hit, miss, no stale move")
finally:
    engine.close()
