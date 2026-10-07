#!/usr/bin/env python3
"""Floodgate CSA protocol helpers for KUMOJI.

This module translates notation, time information, and just enough exact game
state to recognize server-adjudicated fourfold repetition / max-move endings.
It never decides legality; KUMOJI's rules layer and Floodgate remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

RANK_TO_NUM = {c: str(i + 1) for i, c in enumerate("abcdefghi")}
NUM_TO_RANK = {v: k for k, v in RANK_TO_NUM.items()}
USI_TO_CSA = {"P":"FU","L":"KY","N":"KE","S":"GI","G":"KI","B":"KA","R":"HI"}
CSA_TO_USI = {v:k for k,v in USI_TO_CSA.items()}
PROMOTE = {"FU":"TO","KY":"NY","KE":"NK","GI":"NG","KA":"UM","HI":"RY"}
DEMOTE = {v:k for k,v in PROMOTE.items()}

CSA_MOVE_RE = re.compile(r"^([+-])(\d{2})(\d{2})([A-Z]{2})(?:,T(\d+))?$")
USI_MOVE_RE = re.compile(r"^([1-9][a-i])([1-9][a-i])(\+)?$")
USI_DROP_RE = re.compile(r"^([PLNSGBR])\*([1-9][a-i])$")


def csa_square_to_usi(square: str) -> str:
    if square == "00":
        return square
    if len(square) != 2 or square[0] not in "123456789" or square[1] not in NUM_TO_RANK:
        raise ValueError(f"invalid CSA square: {square}")
    return square[0] + NUM_TO_RANK[square[1]]


def usi_square_to_csa(square: str) -> str:
    if len(square) != 2 or square[0] not in "123456789" or square[1] not in RANK_TO_NUM:
        raise ValueError(f"invalid USI square: {square}")
    return square[0] + RANK_TO_NUM[square[1]]


class StartposBoard:
    """Exact startpos-derived state needed for conversion and repetition waiting."""

    def __init__(self) -> None:
        self.squares: dict[str, str] = {}
        self.owners: dict[str, str] = {}
        self.hands = {"+": {p: 0 for p in CSA_TO_USI}, "-": {p: 0 for p in CSA_TO_USI}}
        self.to_move = "+"
        back = ["KY","KE","GI","KI","OU","KI","GI","KE","KY"]
        for file_, piece in zip("987654321", back):
            for square, owner in ((file_+"a","-"), (file_+"i","+")):
                self.squares[square] = piece
                self.owners[square] = owner
            for square, owner in ((file_+"c","-"), (file_+"g","+")):
                self.squares[square] = "FU"
                self.owners[square] = owner
        for square, piece, owner in (
            ("8b","HI","-"),("2b","KA","-"),("8h","KA","+"),("2h","HI","+")
        ):
            self.squares[square] = piece
            self.owners[square] = owner
        self._counts = {self.position_key(): 1}

    def csa_to_usi(self, line: str) -> str:
        m = CSA_MOVE_RE.match(line)
        if not m:
            raise ValueError(f"invalid CSA move: {line}")
        sign, src_raw, dst_raw, result_piece, _time = m.groups()
        dst = csa_square_to_usi(dst_raw)
        if src_raw == "00":
            base = CSA_TO_USI.get(result_piece)
            if base is None:
                raise ValueError(f"invalid CSA drop piece: {result_piece}")
            return f"{base}*{dst}"

        src = csa_square_to_usi(src_raw)
        before = self.squares.get(src)
        if before is None or self.owners.get(src) != sign:
            raise ValueError(f"no own piece at CSA source: {src_raw}")
        if result_piece == before:
            suffix = ""
        elif PROMOTE.get(before) == result_piece:
            suffix = "+"
        else:
            raise ValueError(f"unexpected CSA transition: {before}->{result_piece}")
        return f"{src}{dst}{suffix}"

    def usi_to_csa(self, move: str, sign: str) -> str:
        if sign not in {"+","-"}:
            raise ValueError(f"invalid side: {sign}")
        drop = USI_DROP_RE.match(move)
        if drop:
            piece, dst = drop.groups()
            return f"{sign}00{usi_square_to_csa(dst)}{USI_TO_CSA[piece]}"

        normal = USI_MOVE_RE.match(move)
        if not normal:
            raise ValueError(f"invalid USI move: {move}")
        src, dst, promotion = normal.groups()
        before = self.squares.get(src)
        if before is None or self.owners.get(src) != sign:
            raise ValueError(f"no own piece at USI source: {src}")
        result = PROMOTE.get(before) if promotion else before
        if result is None:
            raise ValueError(f"piece cannot promote: {before}")
        return f"{sign}{usi_square_to_csa(src)}{usi_square_to_csa(dst)}{result}"

    def apply_csa(self, line: str) -> None:
        m = CSA_MOVE_RE.match(line)
        if not m:
            raise ValueError(f"invalid CSA move: {line}")
        sign, src_raw, dst_raw, result_piece, _time = m.groups()
        if sign != self.to_move:
            raise ValueError(f"unexpected side to move: got {sign}, expected {self.to_move}")
        dst = csa_square_to_usi(dst_raw)

        captured = self.squares.get(dst)
        captured_owner = self.owners.get(dst)
        if captured is not None:
            if captured_owner == sign:
                raise ValueError(f"destination occupied by own piece: {dst_raw}")
            raw = DEMOTE.get(captured, captured)
            if raw == "OU":
                raise ValueError("king capture is not a legal CSA move")
            self.hands[sign][raw] += 1

        if src_raw == "00":
            raw = DEMOTE.get(result_piece, result_piece)
            if raw not in self.hands[sign]:
                raise ValueError(f"invalid drop piece: {result_piece}")
            if self.hands[sign][raw] <= 0:
                # Initial Floodgate games are startpos-derived.  Requiring the
                # captured piece here prevents silently corrupting repetition state.
                raise ValueError(f"drop without piece in hand: {result_piece}")
            self.hands[sign][raw] -= 1
        else:
            src = csa_square_to_usi(src_raw)
            if src not in self.squares or self.owners.get(src) != sign:
                raise ValueError(f"no own piece at CSA source: {src_raw}")
            del self.squares[src]
            del self.owners[src]

        self.squares[dst] = result_piece
        self.owners[dst] = sign
        self.to_move = "-" if sign == "+" else "+"
        key = self.position_key()
        self._counts[key] = self._counts.get(key, 0) + 1

    def position_key(self) -> tuple:
        board = tuple(sorted((sq, self.owners[sq], piece) for sq, piece in self.squares.items()))
        hands = tuple(
            (sign, piece, self.hands[sign][piece])
            for sign in ("+","-") for piece in sorted(self.hands[sign])
        )
        return board, hands, self.to_move

    def repetition_count(self) -> int:
        return self._counts.get(self.position_key(), 0)

    def server_terminal_pending(self, plies: int, max_moves: int) -> bool:
        return self.repetition_count() >= 4 or (max_moves > 0 and plies >= max_moves)


def parse_time_unit_ms(value: str | None) -> int:
    if not value:
        return 1000
    m = re.fullmatch(r"(?:(\d+))?(msec|sec|min)", value.strip())
    if not m:
        raise ValueError(f"unsupported Time_Unit: {value}")
    amount = int(m.group(1) or "1")
    scale = {"msec":1,"sec":1000,"min":60000}[m.group(2)]
    return amount * scale


@dataclass
class GameSummary:
    game_id: str
    your_turn: str
    to_move: str
    name_black: str = ""
    name_white: str = ""
    total_time: int = 0
    byoyomi: int = 0
    increment: int = 0
    least_time_per_move: int = 0
    max_moves: int = 0
    time_unit: str = "1sec"
    position_moves: list[str] = field(default_factory=list)

    @property
    def unit_ms(self) -> int:
        return parse_time_unit_ms(self.time_unit)


class SummaryParser:
    def __init__(self) -> None:
        self.active = False
        self.lines: list[str] = []

    def feed(self, line: str) -> GameSummary | None:
        if line == "BEGIN Game_Summary":
            self.active = True
            self.lines = []
            return None
        if not self.active:
            return None
        if line == "END Game_Summary":
            self.active = False
            return self.parse(self.lines)
        self.lines.append(line)
        return None

    @staticmethod
    def parse(lines: Iterable[str]) -> GameSummary:
        fields: dict[str,str] = {}
        position_moves: list[str] = []
        in_position = False
        for line in lines:
            if line == "BEGIN Position":
                in_position = True
                continue
            if line == "END Position":
                in_position = False
                continue
            if in_position and CSA_MOVE_RE.match(line):
                position_moves.append(line.split(",",1)[0])
                continue
            if ":" in line:
                key, value = line.split(":",1)
                fields[key] = value

        missing = [k for k in ("Game_ID","Your_Turn","To_Move") if k not in fields]
        if missing:
            raise ValueError("game summary missing: " + ", ".join(missing))
        return GameSummary(
            game_id=fields["Game_ID"],
            your_turn=fields["Your_Turn"],
            to_move=fields["To_Move"],
            name_black=fields.get("Name+",""),
            name_white=fields.get("Name-",""),
            total_time=int(fields.get("Total_Time","0")),
            byoyomi=int(fields.get("Byoyomi","0")),
            increment=int(fields.get("Increment","0")),
            least_time_per_move=int(fields.get("Least_Time_Per_Move","0")),
            max_moves=int(fields.get("Max_Moves","0")),
            time_unit=fields.get("Time_Unit","1sec"),
            position_moves=position_moves,
        )


class Clock:
    """Tracks server-reported consumption and granted Fischer increment."""

    def __init__(self, summary: GameSummary) -> None:
        self.unit_ms = summary.unit_ms
        self.remaining = {"+":summary.total_time*self.unit_ms, "-":summary.total_time*self.unit_ms}
        self.increment_ms = summary.increment*self.unit_ms
        self.byoyomi_ms = summary.byoyomi*self.unit_ms
        self.has_total = summary.total_time > 0

    def observe(self, move_line: str) -> None:
        m = CSA_MOVE_RE.match(move_line)
        if not m or not self.has_total or m.group(5) is None:
            return
        sign = m.group(1)
        spent = int(m.group(5))*self.unit_ms
        self.remaining[sign] = max(0, self.remaining[sign]-spent) + self.increment_ms

    def usi_go(self) -> str:
        if not self.has_total and not self.byoyomi_ms:
            return "go movetime 1000"
        parts = [
            "go","btime",str(max(0,self.remaining["+"])),
            "wtime",str(max(0,self.remaining["-"])),
        ]
        if self.byoyomi_ms:
            parts += ["byoyomi",str(self.byoyomi_ms)]
        # KUMOJI currently budgets part of binc/winc before that future increment
        # is actually granted. Floodgate's increment is therefore folded into
        # remaining time only after the server echoes each completed move.
        return " ".join(parts)
