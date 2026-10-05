"""Find a real-game position with an exact forced mate in five plies."""
import json
from pathlib import Path
import shogi

SOURCE = Path("benchmarks/results/2026-10-05_quiescence-light-order-100-50ms.json")


def attack(board, remaining):
    if remaining <= 0 or board.is_checkmate():
        return None
    best = None
    for move in list(board.legal_moves):
        usi = move.usi()
        board.push(move)
        try:
            if not board.is_check():
                continue
            if board.is_checkmate():
                candidate = [usi]
            elif remaining > 1:
                child = defend(board, remaining - 1)
                candidate = [usi] + child if child is not None else None
            else:
                candidate = None
        finally:
            board.pop()
        if candidate is not None and (best is None or len(candidate) < len(best)):
            best = candidate
    return best


def defend(board, remaining):
    if board.is_checkmate():
        return []
    if remaining <= 0 or not board.is_check():
        return None
    replies = list(board.legal_moves)
    if not replies:
        return None
    hardest = []
    for move in replies:
        usi = move.usi()
        board.push(move)
        try:
            child = attack(board, remaining - 1)
        finally:
            board.pop()
        if child is None:
            return None
        line = [usi] + child
        if len(line) > len(hardest):
            hardest = line
    return hardest


data = json.loads(SOURCE.read_text())
for game_index, game in enumerate(data["details"]):
    moves = game["moves"]
    # Mates are most likely near the end. Search backwards to keep this cheap.
    for ply in range(len(moves) - 1, max(-1, len(moves) - 50), -1):
        board = shogi.Board()
        for usi in moves[:ply]:
            board.push_usi(usi)
        if board.is_checkmate():
            continue
        one = attack(board, 1)
        if one is not None:
            continue
        three = attack(board, 3)
        if three is not None:
            continue
        five = attack(board, 5)
        if five is not None:
            print(json.dumps({
                "game": game_index,
                "ply": ply,
                "sfen": board.sfen(),
                "line": five,
            }, ensure_ascii=False))
            raise SystemExit(0)
raise SystemExit("no exact mate-in-five found in scanned game positions")
