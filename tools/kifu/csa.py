#!/usr/bin/env python3
"""CSA notation reader for the offline learning pipeline.

This module converts notation only. Every normalized move is revalidated later
by engine/rules/Position, so the pinned YaneuraOu rule layer remains the source
of truth for legality and position reconstruction.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

START_SFEN = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"

CSA_TO_BASE = {
    "FU": "P", "KY": "L", "KE": "N", "GI": "S", "KI": "G",
    "KA": "B", "HI": "R", "OU": "K",
}
PROMOTED_FROM = {"TO": "FU", "NY": "KY", "NK": "KE", "NG": "GI", "UM": "KA", "RY": "HI"}
ALL_CODES = set(CSA_TO_BASE) | set(PROMOTED_FROM)
TOTAL_PIECES = {"FU": 18, "KY": 4, "KE": 4, "GI": 4, "KI": 4, "KA": 2, "HI": 2, "OU": 2}
LOSS_CODES = {"TORYO", "TSUMI", "TIME_UP", "ILLEGAL_MOVE"}
DRAW_CODES = {"SENNICHITE", "JISHOGI", "HIKIWAKE", "MAX_MOVES"}


def opposite(side: str) -> str:
    return "-" if side == "+" else "+"


def square_to_usi(square: str) -> str:
    if len(square) != 2 or square == "00":
        raise ValueError(f"invalid CSA square: {square!r}")
    file_no, rank_no = square
    if file_no not in "123456789" or rank_no not in "123456789":
        raise ValueError(f"invalid CSA square: {square!r}")
    return file_no + chr(ord("a") + int(rank_no) - 1)


def square_index(square: str) -> int:
    file_no, rank_no = int(square[0]), int(square[1])
    if not 1 <= file_no <= 9 or not 1 <= rank_no <= 9:
        raise ValueError(f"invalid CSA square: {square!r}")
    return (file_no - 1) * 9 + (rank_no - 1)


def base_code(code: str) -> str:
    return PROMOTED_FROM.get(code, code)


def code_to_sfen_piece(code: str, side: str) -> str:
    base = CSA_TO_BASE[base_code(code)]
    piece = base if side == "+" else base.lower()
    return ("+" if code in PROMOTED_FROM else "") + piece


def empty_board() -> List[Optional[Tuple[str, str]]]:
    return [None] * 81


def standard_board() -> List[Optional[Tuple[str, str]]]:
    board = empty_board()
    back = ["KY", "KE", "GI", "KI", "OU", "KI", "GI", "KE", "KY"]
    for file_no, code in zip(range(9, 0, -1), back):
        board[square_index(f"{file_no}1")] = ("-", code)
        board[square_index(f"{file_no}9")] = ("+", code)
    board[square_index("82")] = ("-", "HI")
    board[square_index("22")] = ("-", "KA")
    board[square_index("88")] = ("+", "KA")
    board[square_index("28")] = ("+", "HI")
    for file_no in range(1, 10):
        board[square_index(f"{file_no}3")] = ("-", "FU")
        board[square_index(f"{file_no}7")] = ("+", "FU")
    return board


def board_to_sfen(board, hands: Dict[str, Dict[str, int]], turn: str) -> str:
    rows = []
    for rank_no in range(1, 10):
        row, empties = "", 0
        for file_no in range(9, 0, -1):
            piece = board[square_index(f"{file_no}{rank_no}")]
            if piece is None:
                empties += 1
                continue
            if empties:
                row += str(empties)
                empties = 0
            row += code_to_sfen_piece(piece[1], piece[0])
        if empties:
            row += str(empties)
        rows.append(row)

    hand_order = [("+", "HI"), ("+", "KA"), ("+", "KI"), ("+", "GI"),
                  ("+", "KE"), ("+", "KY"), ("+", "FU"),
                  ("-", "HI"), ("-", "KA"), ("-", "KI"), ("-", "GI"),
                  ("-", "KE"), ("-", "KY"), ("-", "FU")]
    hand = ""
    for side, code in hand_order:
        count = hands[side].get(code, 0)
        if not count:
            continue
        if count > 1:
            hand += str(count)
        piece = CSA_TO_BASE[code]
        hand += piece if side == "+" else piece.lower()
    return f"{'/'.join(rows)} {'b' if turn == '+' else 'w'} {hand or '-'} 1"


@dataclass
class CsaGame:
    start_sfen: str
    moves_usi: List[str]
    raw_result: str = ""
    winner: Optional[str] = None  # black / white / draw / None
    black: str = ""
    white: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
    source: str = ""
    source_record: int = 1


class CsaParser:
    def __init__(self):
        self.board = standard_board()
        self.hands = {"+": {}, "-": {}}
        self.turn: Optional[str] = None
        self.moves: List[str] = []
        self.black = ""
        self.white = ""
        self.metadata: Dict[str, str] = {}
        self.result = ""
        self.initialized = False

    def _set_hand(self, side: str, code: str, count: int = 1):
        base = base_code(code)
        if base == "OU":
            raise ValueError("king cannot be in hand")
        self.hands[side][base] = self.hands[side].get(base, 0) + count

    def _remaining_nonking_pieces(self) -> Dict[str, int]:
        used = {code: 0 for code in TOTAL_PIECES}
        for piece in self.board:
            if piece is not None:
                used[base_code(piece[1])] += 1
        for side in ("+", "-"):
            for code, count in self.hands[side].items():
                used[base_code(code)] += count
        remaining = {}
        for code, total in TOTAL_PIECES.items():
            left = total - used[code]
            if left < 0:
                raise ValueError(f"too many {code} pieces in initial position")
            if code != "OU" and left:
                remaining[code] = left
        return remaining

    def _parse_piece_list(self, side: str, payload: str):
        if len(payload) % 4:
            raise ValueError(f"invalid CSA piece-list: {payload!r}")
        for i in range(0, len(payload), 4):
            square, code = payload[i:i+2], payload[i+2:i+4]
            if code == "AL":
                if square != "00" or i + 4 != len(payload):
                    raise ValueError("00AL must be the final item of a piece-list")
                for remaining_code, count in self._remaining_nonking_pieces().items():
                    self._set_hand(side, remaining_code, count)
                continue
            if code not in ALL_CODES:
                raise ValueError(f"unknown CSA piece code: {code}")
            if square == "00":
                if code in PROMOTED_FROM:
                    raise ValueError("promoted piece cannot be in hand")
                self._set_hand(side, code)
            else:
                idx = square_index(square)
                if self.board[idx] is not None:
                    raise ValueError(f"duplicate initial piece at {square}")
                self.board[idx] = (side, code)

    def _parse_board_row(self, line: str):
        rank_no = int(line[1])
        payload = line[2:]
        if len(payload) < 27:
            payload = payload.ljust(27)
        for column in range(9):
            token = payload[column * 3:(column + 1) * 3]
            file_no = 9 - column
            idx = square_index(f"{file_no}{rank_no}")
            if token == " * " or not token.strip():
                self.board[idx] = None
                continue
            if len(token) != 3 or token[0] not in "+-" or token[1:] not in ALL_CODES:
                raise ValueError(f"invalid CSA board token: {token!r}")
            self.board[idx] = (token[0], token[1:])

    def _parse_move(self, line: str):
        if self.turn is None:
            raise ValueError("CSA move before side-to-move declaration")
        if len(line) < 7:
            raise ValueError(f"short CSA move: {line!r}")
        side, src, dst, result_code = line[0], line[1:3], line[3:5], line[5:7]
        if side != self.turn:
            raise ValueError(f"wrong side to move: expected {self.turn}, got {side}")
        if result_code not in ALL_CODES:
            raise ValueError(f"unknown CSA move piece: {result_code}")
        dst_idx = square_index(dst)
        captured = self.board[dst_idx]
        if captured is not None and captured[0] == side:
            raise ValueError(f"cannot capture own piece at {dst}")
        if captured is not None:
            self._set_hand(side, captured[1])

        if src == "00":
            if result_code in PROMOTED_FROM:
                raise ValueError("cannot drop promoted piece")
            base = base_code(result_code)
            if self.hands[side].get(base, 0) <= 0:
                raise ValueError(f"drop without piece in hand: {result_code}")
            self.hands[side][base] -= 1
            move = f"{CSA_TO_BASE[base]}*{square_to_usi(dst)}"
        else:
            src_idx = square_index(src)
            before = self.board[src_idx]
            if before is None or before[0] != side:
                raise ValueError(f"no moving piece at {src}")
            before_code = before[1]
            if base_code(before_code) != base_code(result_code):
                raise ValueError(f"piece mismatch {before_code}->{result_code}")
            promoted = before_code not in PROMOTED_FROM and result_code in PROMOTED_FROM
            if before_code in PROMOTED_FROM and result_code not in PROMOTED_FROM:
                raise ValueError("piece cannot unpromote")
            move = square_to_usi(src) + square_to_usi(dst) + ("+" if promoted else "")
            self.board[src_idx] = None
        self.board[dst_idx] = (side, result_code)
        self.moves.append(move)
        self.turn = opposite(side)

    def parse(self, text: str, source: str = "", source_record: int = 1) -> CsaGame:
        initial_sfen: Optional[str] = None
        for raw in text.splitlines():
            line = raw.lstrip("\ufeff")
            if not line.strip():
                continue
            if line.startswith("'") or line.startswith("V") or line.startswith("T"):
                continue
            if line.startswith("N+"):
                self.black = line[2:].strip()
            elif line.startswith("N-"):
                self.white = line[2:].strip()
            elif line.startswith("$"):
                key, sep, value = line[1:].partition(":")
                self.metadata[key.strip()] = value.strip() if sep else ""
            elif line.startswith("PI"):
                self.board = standard_board()
                self.hands = {"+": {}, "-": {}}
                payload = line[2:].strip()
                if len(payload) % 4:
                    raise ValueError(f"invalid PI removals: {payload!r}")
                for i in range(0, len(payload), 4):
                    square = payload[i:i+2]
                    code = payload[i+2:i+4]
                    idx = square_index(square)
                    if self.board[idx] is None or self.board[idx][1] != code:
                        raise ValueError(f"PI removal mismatch at {square}: {code}")
                    self.board[idx] = None
                self.initialized = True
            elif len(line) >= 2 and line[0] == "P" and line[1] in "123456789":
                if not self.initialized:
                    self.board = empty_board()
                    self.hands = {"+": {}, "-": {}}
                    self.initialized = True
                self._parse_board_row(line)
            elif line.startswith("P+") or line.startswith("P-"):
                if not self.initialized:
                    self.board = empty_board()
                    self.hands = {"+": {}, "-": {}}
                    self.initialized = True
                self._parse_piece_list(line[1], line[2:].replace(" ", ""))
            elif line in ("+", "-"):
                if not self.initialized:
                    self.board = standard_board()
                    self.hands = {"+": {}, "-": {}}
                    self.initialized = True
                self.turn = line
                initial_sfen = board_to_sfen(self.board, self.hands, self.turn)
            elif line.startswith("+") or line.startswith("-"):
                if initial_sfen is None:
                    raise ValueError("CSA move before initial position was completed")
                self._parse_move(line.strip())
            elif line.startswith("%"):
                self.result = line[1:].strip().upper()
            else:
                raise ValueError(f"unsupported CSA line: {line!r}")

        if initial_sfen is None:
            raise ValueError("CSA side-to-move declaration not found")
        winner: Optional[str] = None
        if self.result in LOSS_CODES:
            winner = "white" if self.turn == "+" else "black"
        elif self.result == "+ILLEGAL_ACTION":
            winner = "white"
        elif self.result == "-ILLEGAL_ACTION":
            winner = "black"
        elif self.result == "KACHI":
            winner = "black" if self.turn == "+" else "white"
        elif self.result in DRAW_CODES:
            winner = "draw"
        return CsaGame(initial_sfen, self.moves, self.result, winner,
                       self.black, self.white, dict(self.metadata), source, source_record)


def split_records(text: str) -> List[str]:
    records, current = [], []
    for raw in text.splitlines():
        if raw.strip() == "/":
            if any(line.strip() for line in current):
                records.append("\n".join(current))
            current = []
        else:
            current.append(raw)
    if any(line.strip() for line in current):
        records.append("\n".join(current))
    return records


def parse_csa_games(text: str, source: str = "") -> List[CsaGame]:
    records = split_records(text)
    return [CsaParser().parse(record, source, i + 1) for i, record in enumerate(records)]


def parse_csa(text: str, source: str = "") -> CsaGame:
    games = parse_csa_games(text, source)
    if len(games) != 1:
        raise ValueError(f"expected one CSA game, found {len(games)}")
    return games[0]


def decode_csa(data: bytes) -> str:
    prefix = data[:256].decode("ascii", errors="ignore").upper()
    if "'CSA ENCODING=UTF-8" in prefix:
        return data.decode("utf-8-sig")
    if "'CSA ENCODING=SHIFT_JIS" in prefix:
        return data.decode("cp932")
    # Old CSA files default to Shift_JIS; tolerate common UTF-8 files without
    # an encoding declaration so small modern corpora are still ingestible.
    for encoding in ("cp932", "utf-8-sig"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("cannot decode CSA bytes as Shift_JIS or UTF-8")


def parse_csa_file_games(path: Path) -> List[CsaGame]:
    return parse_csa_games(decode_csa(path.read_bytes()), str(path))


def parse_csa_file(path: Path) -> CsaGame:
    games = parse_csa_file_games(path)
    if len(games) != 1:
        raise ValueError(f"expected one CSA game in {path}, found {len(games)}")
    return games[0]
