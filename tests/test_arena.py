"""Regression tests for the match judge, separate from both playing engines."""
import sys
import queue
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from benchmarks.arena import (Adjudicator, Engine, can_declare_win, play_game,
                              parse_info_line, merge_info_line, compact_search_telemetry)


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


info = parse_info_line(
    "info depth 7 seldepth 10 score cp -123 nodes 4567 nps 90000 "
    "tt_probes 100 tt_hits 40 knowledge_probes 9 knowledge_hits 3 knowledge_promotions 2 "
    "qnodes 88 pv 7g7f 3c3d 2g2f"
)
assert info["depth"] == 7
assert info["seldepth"] == 10
assert info["score_cp"] == -123
assert info["nodes"] == 4567
assert info["tt_hits"] == 40
assert info["pv"] == ["7g7f", "3c3d", "2g2f"]
black_view = compact_search_telemetry(info, shogi.BLACK)
white_view = compact_search_telemetry(info, shogi.WHITE)
assert black_view["score_black_cp"] == -123
assert white_view["score_black_cp"] == 123
assert black_view["tt_probes"] == 100

mate = parse_info_line("info depth 5 score mate -3 nodes 99 pv 5a5b")
assert compact_search_telemetry(mate, shogi.WHITE)["score_black_mate"] == 3

# Exercise the actual multi-line reader: the final score owns its type and
# bounds, while a separate statistics line must leave that observation intact.
reader = Engine.__new__(Engine)
reader.label = "replay"
reader.go_command = "go movetime 200"
reader.send = lambda command: None
reader.elapsed = []
reader.search_stats = []
reader.lines = queue.Queue()
for line in (
    "info depth 2 score cp 120 upperbound pv 7g7f",
    "info depth 5 score mate 3 pv 7g7f",
    "info string tt_hits 7",
    "bestmove 7g7f",
):
    reader.lines.put(line)
assert reader.bestmove([]) == "7g7f"
record = compact_search_telemetry(reader.last_search, shogi.BLACK)
assert record["score_mate_stm"] == 3 and record["tt_hits"] == 7
assert "score_cp_stm" not in record and "score_upperbound" not in record
for line in (
    "info depth 6 score mate -5 lowerbound pv 7g7f",
    "info depth 7 score cp -20 pv 7g7f",
    "bestmove 7g7f",
):
    reader.lines.put(line)
reader.bestmove([])
assert reader.last_search["score_cp"] == -20
assert "score_mate" not in reader.last_search and "score_lowerbound" not in reader.last_search
merge_info_line(reader.last_search, "info depth 8 score cp 0 lowerbound pv 7g7f")
merge_info_line(reader.last_search, "info string nodes 99")
assert reader.last_search["score_cp"] == 0 and reader.last_search["score_lowerbound"]
merge_info_line(reader.last_search, "info depth 9 score cp 10 upperbound pv 7g7f")
assert reader.last_search["score_upperbound"] and "score_lowerbound" not in reader.last_search


class FakeEngine:
    def __init__(self, label):
        self.label = label
        self.last_search = {}

    def configure_game(self, seed):
        pass

    def bestmove(self, moves):
        sequence = ["7g7f", "3c3d", "2g2f", "8c8d"]
        token = sequence[len(moves)]
        self.last_search = {
            "depth": 3,
            "seldepth": 4,
            "score_cp": 10 * (len(moves) + 1),
            "nodes": 100 + len(moves),
            "pv": [token],
            "elapsed_ms": 1.5,
        }
        return token


game = play_game(FakeEngine("A"), FakeEngine("B"), 0, 4, 1234)
assert game["reason"] == "move_limit"
assert len(game["move_records"]) == 4
assert game["move_records"][0]["move"] == "7g7f"
assert game["move_records"][0]["side_to_move"] == "black"
assert game["move_records"][0]["search"]["score_black_cp"] == 10
assert game["move_records"][1]["side_to_move"] == "white"
assert game["move_records"][1]["search"]["score_black_cp"] == -20
assert game["move_records"][0]["legal_moves_before"] > 0
assert "gave_check" in game["move_records"][0]

print("PASS arena: judge, declarations and per-move telemetry parsing")
