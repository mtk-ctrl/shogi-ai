"""Floodgate専用の読み時間の配分（2026-11-15オーナー指示）。

接続層だけで働く。自己対局・比較対局・梯子では使わない。雲路本体の探索・評価は変えない。
接続層が `go movetime 上限` を送り、雲路の途中経過（info）を見て `stop` を送ることで時間を決める。

配分（加算 I 秒、自分の残り R 秒。300秒＋10秒なら I=10）:
  序盤（自分の1〜8手目）   基本 0.5*I            （5秒。貯金を増やす）
  中盤（9〜40手目）        基本 0.8*I + R/20     （最初は約23秒）
  終盤（41手目以降）       基本 0.8*I + R/30
  残りが 3*I 未満（30秒）  基本 0.8*I のみ、延長なし（時間切れ防止）
伸び縮み:
  縮める（基本の1/3で止める）: 最善手が4回続けて同じで、評価値もほぼ動かないとき。
  伸ばす（最大 基本の3倍、かつ 残りの1/5+0.8*I まで）: 最善手が直前に変わったとき、評価値が100以上落ちたとき。
  自分の勝ちの詰みを読み切ったら、すぐ指す。
どの場合も、残り時間から安全の余裕（3秒）を引いた時間を超えない。
"""
from __future__ import annotations

from dataclasses import dataclass, field

OPENING_OWN_MOVES = 8
MIDDLE_OWN_MOVES = 40
SAFETY_MARGIN_MS = 3000
STABLE_DEPTHS = 4
STABLE_SCORE_SWING = 50
DROP_TRIGGER = 100


@dataclass
class TimePlan:
    base_ms: int
    min_ms: int
    max_ms: int
    stage: str

    def as_dict(self) -> dict:
        return {"stage": self.stage, "base_ms": self.base_ms, "min_ms": self.min_ms, "max_ms": self.max_ms}


def make_plan(remaining_ms: int, increment_ms: int, own_move_number: int) -> TimePlan:
    """Plan for one move. `remaining_ms` already contains every increment granted so far."""
    inc = max(0, increment_ms)
    rem = max(0, remaining_ms)
    spend = inc * 8 // 10
    ceiling = max(100, rem - SAFETY_MARGIN_MS)
    if rem < 3 * inc:
        stage, base, extend = "reserve", spend, False
    elif own_move_number <= OPENING_OWN_MOVES:
        stage, base, extend = "opening", inc // 2, True
    elif own_move_number <= MIDDLE_OWN_MOVES:
        stage, base, extend = "middle", spend + rem // 20, True
    else:
        stage, base, extend = "end", spend + rem // 30, True
    base = max(100, min(base, ceiling))
    longest = min(base * 3, rem // 5 + spend) if extend else base
    longest = max(base, min(longest, ceiling))
    return TimePlan(base_ms=base, min_ms=max(100, base // 3), max_ms=longest, stage=stage)


@dataclass
class StopController:
    """Decides when to send `stop`, from KUMOJI's own info lines only."""
    plan: TimePlan
    previous_score: int | None = None  # KUMOJI's score for its previous move (own view)
    history: list = field(default_factory=list)  # (depth, first pv move, own-view score)
    reason: str = ""

    def observe(self, info: dict) -> None:
        depth, pv = info.get("depth"), info.get("pv") or []
        if depth is None or not pv:
            return
        score = _own_score(info)
        if self.history and self.history[-1][0] == depth:
            self.history[-1] = (depth, pv[0], score)
        else:
            self.history.append((depth, pv[0], score))

    def _stable(self) -> bool:
        tail = self.history[-STABLE_DEPTHS:]
        if len(tail) < STABLE_DEPTHS or len({m for _, m, _ in tail}) != 1:
            return False
        a, b = tail[-2][2], tail[-1][2]
        return a is not None and b is not None and abs(a - b) < STABLE_SCORE_SWING

    def _unstable(self) -> bool:
        if not self.history:
            return True
        last = self.history[-1]
        if len(self.history) >= 2 and self.history[-2][1] != last[1]:
            return True
        if last[2] is None:
            return False
        refs = [s for s in (self.previous_score, self.history[0][2],
                            self.history[-3][2] if len(self.history) >= 3 else None) if s is not None]
        return any(last[2] <= ref - DROP_TRIGGER for ref in refs)

    def should_stop(self, elapsed_ms: int) -> bool:
        if elapsed_ms >= self.plan.max_ms:
            self.reason = "max"
            return True
        if self.history and (self.history[-1][2] or 0) >= MATE_OWN and elapsed_ms >= 200:
            self.reason = "mate_found"
            return True
        if elapsed_ms >= self.plan.base_ms:
            if self._unstable() and self.plan.max_ms > self.plan.base_ms:
                return False
            self.reason = "base"
            return True
        if elapsed_ms >= self.plan.min_ms and self._stable():
            self.reason = "stable"
            return True
        return False


MATE_OWN = 30000


def _own_score(info: dict) -> int | None:
    kind, raw = info.get("score_kind"), info.get("score_raw")
    if kind == "cp":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if kind == "mate":
        return -MATE_OWN if str(raw).startswith("-") else MATE_OWN
    return None
