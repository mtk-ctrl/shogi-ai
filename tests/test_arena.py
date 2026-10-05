"""Regression tests for the match judge, separate from both playing engines."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from benchmarks.arena import Adjudicator, can_declare_win


def fixture(pieces, hand="-", turn="b"):
    board = shogi.Board()
    board.clear()
    for square, piece in pieces.items():
        board.set_piece_at(shogi.SQUARE_NAMES.index(square), shogi.Piece.from_symbol(piece))
    fields = board.sfen().split()
    return shogi.Board(f"{fields[0]} {turn} {hand} 1")


for pieces, cycle, expected in [
    ({"5i":"K", "5a":"k"}, ["5i6i","5a6a","6i5i","6a5a"], (None,"fourfold_repetition")),
    ({"9i":"K", "5a":"k", "4b":"R"}, ["4b5b","5a4a","5b4b","4a5a"], (shogi.WHITE,"perpetual_check")),
]:
    board = fixture(pieces)
    judge = Adjudicator(board)
    for i, move in enumerate(cycle * 3):
        assert shogi.Move.from_usi(move) in board.legal_moves
        board.push_usi(move)
        result = judge.after_move(board)
        assert result == (expected if i == 11 else None), (i, result)

board = fixture({"1a":"k", "5i":"K", "6h":"r"}, turn="w")
judge = Adjudicator(board)
for i, move in enumerate(["6h5h","5i6i","5h6h","6i5i"] * 3):
    assert shogi.Move.from_usi(move) in board.legal_moves
    board.push_usi(move)
    assert judge.after_move(board) == ((shogi.BLACK,"perpetual_check") if i == 11 else None)

board = fixture({"9i":"K","5a":"k","4a":"l","6a":"l","4b":"p","6b":"p","5c":"P","4c":"G"})
judge = Adjudicator(board)
board.push_usi("5c5b")
assert judge.after_move(board) == (shogi.BLACK, "checkmate")

camp = {f"{i}c":"P" for i in range(1, 10)}
camp.update({"5b":"K", "4b":"G", "9i":"k"})
assert can_declare_win(fixture(camp, "R2B3P"))  # exactly 28
assert not can_declare_win(fixture(camp, "R2B2P"))  # only 27
rotated = {f"{10-int(s[0])}{chr(ord('i')-(ord(s[1])-ord('a')))}": p.swapcase()
           for s,p in camp.items()}
assert can_declare_win(fixture(rotated, "r2b2p", "w"))  # White needs 27
assert not can_declare_win(fixture(rotated, "r2bp", "w"))
del camp["9c"]
assert not can_declare_win(fixture(camp, "2R2B"))  # only nine pieces in camp
assert not can_declare_win(shogi.Board())
print("PASS arena: mate, exact fourfold, perpetual check for both colors and 27-point declarations")
