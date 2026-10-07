#!/usr/bin/env python3
"""Ten-minute deep research for Prophylaxis candidate positions.

Each process analyzes exactly one fixed position for a long, fixed movetime.
Book, Experience and AdaptiveLongThink stay disabled so the result reflects
ordinary KUMOJI search/evaluation only.
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
import sys

import shogi

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.research.evaluation_concept_diagnosis import state_concepts  # noqa: E402


VALUES = {
    shogi.PAWN: 100,
    shogi.LANCE: 300,
    shogi.KNIGHT: 300,
    shogi.SILVER: 500,
    shogi.GOLD: 600,
    shogi.BISHOP: 800,
    shogi.ROOK: 1000,
    shogi.PROM_PAWN: 600,
    shogi.PROM_LANCE: 600,
    shogi.PROM_KNIGHT: 600,
    shogi.PROM_SILVER: 600,
    shogi.PROM_BISHOP: 1000,
    shogi.PROM_ROOK: 1200,
}


def usi_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_info(line: str) -> dict:
    parts = line.split()
    if not parts or parts[0] != "info":
        return {}
    out = {}
    for name in ("depth", "seldepth", "time", "nodes", "nps", "hashfull"):
        if name in parts:
            try:
                out[name] = int(parts[parts.index(name) + 1])
            except (ValueError, IndexError):
                pass
    if "score" in parts:
        try:
            i = parts.index("score")
            kind = parts[i + 1]
            value = int(parts[i + 2])
            if kind == "cp":
                out["score_cp_stm"] = value
            elif kind == "mate":
                out["score_mate_stm"] = value
            out["score_kind"] = kind
        except (ValueError, IndexError):
            pass
    if "pv" in parts:
        i = parts.index("pv")
        out["pv"] = parts[i + 1:]
    return out


class USIEngine:
    def __init__(self, path: str, options: dict):
        self.path = str(Path(path).resolve())
        self.proc = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("usi")
        self.wait_prefix("usiok", 15)
        for name, value in options.items():
            self.send(f"setoption name {name} value {usi_value(value)}")
        self.send("isready")
        self.wait_prefix("readyok", 15)
        self.send("usinewgame")

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))

    def send(self, command: str):
        if self.proc.poll() is not None:
            raise RuntimeError(f"engine exited with {self.proc.returncode}")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait_prefix(self, prefix: str, timeout: float):
        deadline = time.monotonic() + timeout
        seen = []
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-10:]}")
            try:
                line = self.lines.get(timeout=remain)
            except queue.Empty as exc:
                raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-10:]}") from exc
            seen.append(line)
            if line.startswith(prefix):
                return line

    def analyze_sfen(self, sfen: str, movetime_ms: int) -> dict:
        self.send(f"position sfen {sfen}")
        self.send(f"go movetime {movetime_ms}")
        deadline = time.monotonic() + movetime_ms / 1000.0 + 90.0
        started = time.monotonic()
        latest = {}
        max_depth = -1
        deepest = {}
        info_lines = 0
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise TimeoutError(f"long search exceeded watchdog; latest={latest}")
            try:
                line = self.lines.get(timeout=remain)
            except queue.Empty as exc:
                raise TimeoutError(f"long search stalled; latest={latest}") from exc
            if line.startswith("info "):
                info_lines += 1
                parsed = parse_info(line)
                latest.update(parsed)
                depth = parsed.get("depth", latest.get("depth", -1))
                if "pv" in parsed and depth >= max_depth:
                    max_depth = depth
                    deepest = dict(latest)
                continue
            if line.startswith("bestmove "):
                bestmove = line.split(maxsplit=1)[1].strip()
                break
        elapsed = time.monotonic() - started
        chosen = dict(deepest or latest)
        chosen["bestmove"] = bestmove
        chosen["elapsed_ms"] = round(elapsed * 1000, 3)
        chosen["info_lines"] = info_lines
        return chosen

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


def piece_value(piece) -> int:
    if piece is None or piece.piece_type == shogi.KING:
        return 0
    return VALUES.get(piece.piece_type, 0)


def board_after(sfen: str, move_token: str) -> shogi.Board:
    b = shogi.Board(sfen)
    move = shogi.Move.from_usi(move_token)
    if move not in b.legal_moves:
        raise ValueError(f"illegal move {move_token} in fixture")
    b.push(move)
    return b


def forcing_moves_for_side_to_move(board: shogi.Board) -> dict:
    rows = []
    for move in list(board.legal_moves):
        victim = board.piece_at(move.to_square)
        capture = victim is not None and victim.color != board.turn
        capture_value = piece_value(victim) if capture else 0
        promotion = bool(move.promotion)
        board.push(move)
        gives_check = board.is_check()
        board.pop()
        if not (capture or promotion or gives_check):
            continue
        score = 0
        if gives_check:
            score += 1200
        if capture:
            score += capture_value + 100
        if promotion:
            score += 300
        rows.append({
            "move": move.usi(),
            "check": gives_check,
            "capture": capture,
            "capture_value": capture_value,
            "promotion": promotion,
            "forcing_score": score,
        })
    rows.sort(key=lambda r: (-r["forcing_score"], r["move"]))
    return {
        "count": len(rows),
        "checks": sum(r["check"] for r in rows),
        "captures": sum(r["capture"] for r in rows),
        "promotions": sum(r["promotion"] for r in rows),
        "forcing_score_sum": sum(r["forcing_score"] for r in rows),
        "top": rows[:20],
    }


def observe_after(sfen: str, move_token: str, actor: int) -> dict:
    b = board_after(sfen, move_token)
    return {
        "move": move_token,
        "concepts": state_concepts(b, actor),
        "opponent_forcing_resources": forcing_moves_for_side_to_move(b),
        "sfen_after": b.sfen(),
    }


def render_markdown(result: dict) -> str:
    row = result["fixture"]
    search = result["search_10m"]
    a = result["after_actual"]
    d30 = result["after_30s"]
    d10 = result["after_10m"]
    same = result["stability"]["same_as_30s"]
    delta = result["prophylaxis_comparison_10m_vs_actual"]
    lines = [
        f"# Prophylaxis 10分研究 — source index {row['source_index']}",
        "",
        f"- 手数: {row['ply']}",
        f"- 手番: {row['side_to_move']}",
        f"- 200ms実戦手: **{row['actual_move']}**",
        f"- 30秒最善手: **{row['deep_bestmove']}**",
        f"- 10分最善手: **{search['bestmove']}**",
        f"- 30秒最善手と10分最善手: **{'一致' if same else '不一致'}**",
        f"- 10分探索深さ: {search.get('depth','?')} / seldepth {search.get('seldepth','?')}",
        f"- 10分評価: {search.get('score_cp_stm', search.get('score_mate_stm','?'))}",
        f"- nodes: {search.get('nodes','?')}",
        "",
        "## 10分PV",
        "",
        " ".join(search.get("pv", [])) or "(PVなし)",
        "",
        "## 相手に残る即時強制手",
        "",
        "|比較|強制手|王手|駒取り|成り|合計forcing score|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, obs in (
        ("200ms実戦手後", a),
        ("30秒最善手後", d30),
        ("10分最善手後", d10),
    ):
        f = obs["opponent_forcing_resources"]
        lines.append(
            f"|{label}|{f['count']}|{f['checks']}|{f['captures']}|"
            f"{f['promotions']}|{f['forcing_score_sum']}|"
        )
    lines += [
        "",
        f"- 10分最善手は実戦手比で、相手forcing scoreを **{delta['forcing_score_reduction']}** 減らした。",
        f"- 王手候補差: **{delta['checks_reduction']}**",
        f"- 駒取り候補差: **{delta['captures_reduction']}**",
        f"- 成り候補差: **{delta['promotions_reduction']}**",
        "",
        "### 実戦手後の相手上位強制手",
        "",
    ]
    for x in a["opponent_forcing_resources"]["top"][:8]:
        tags = ",".join(k for k,v in (("王手",x["check"]),("駒取り",x["capture"]),("成り",x["promotion"])) if v)
        lines.append(f"- {x['move']} — {tags} / score {x['forcing_score']}")
    lines += ["", "### 10分最善手後の相手上位強制手", ""]
    for x in d10["opponent_forcing_resources"]["top"][:8]:
        tags = ",".join(k for k,v in (("王手",x["check"]),("駒取り",x["capture"]),("成り",x["promotion"])) if v)
        lines.append(f"- {x['move']} — {tags} / score {x['forcing_score']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--source-index", type=int, required=True)
    ap.add_argument("--movetime-ms", type=int, default=600000)
    ap.add_argument("--output", required=True)
    ap.add_argument("--markdown-output", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    matches = [r for r in payload["positions"] if r["source_index"] == args.source_index]
    if len(matches) != 1:
        raise SystemExit(f"expected one fixture row for source_index={args.source_index}, got {len(matches)}")
    row = matches[0]
    actor = shogi.BLACK if row["side_to_move"] == "black" else shogi.WHITE

    options = {
        "OpeningBook": False,
        "ExperienceCache": False,
        "AdaptiveLongThink": False,
        "RandomSeed": 20261008 + args.source_index,
    }
    engine = USIEngine(args.engine, options)
    try:
        search = engine.analyze_sfen(row["sfen_before"], args.movetime_ms)
    finally:
        engine.close()

    move10 = search["bestmove"]
    after_actual = observe_after(row["sfen_before"], row["actual_move"], actor)
    after_30s = observe_after(row["sfen_before"], row["deep_bestmove"], actor)
    after_10m = observe_after(row["sfen_before"], move10, actor)

    f_actual = after_actual["opponent_forcing_resources"]
    f_10m = after_10m["opponent_forcing_resources"]
    comparison = {
        "forcing_score_reduction": f_actual["forcing_score_sum"] - f_10m["forcing_score_sum"],
        "forcing_move_count_reduction": f_actual["count"] - f_10m["count"],
        "checks_reduction": f_actual["checks"] - f_10m["checks"],
        "captures_reduction": f_actual["captures"] - f_10m["captures"],
        "promotions_reduction": f_actual["promotions"] - f_10m["promotions"],
    }

    result = {
        "schema_version": 1,
        "purpose": "10-minute per-position research of Prophylaxis candidates",
        "search_conditions": {
            "movetime_ms": args.movetime_ms,
            "OpeningBook": False,
            "ExperienceCache": False,
            "AdaptiveLongThink": False,
        },
        "fixture": row,
        "search_10m": search,
        "stability": {
            "same_as_30s": move10 == row["deep_bestmove"],
            "same_as_200ms_actual": move10 == row["actual_move"],
        },
        "after_actual": after_actual,
        "after_30s": after_30s,
        "after_10m": after_10m,
        "prophylaxis_comparison_10m_vs_actual": comparison,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = Path(args.markdown_output)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({
        "source_index": args.source_index,
        "actual": row["actual_move"],
        "best_30s": row["deep_bestmove"],
        "best_10m": move10,
        "same_as_30s": move10 == row["deep_bestmove"],
        "depth": search.get("depth"),
        "nodes": search.get("nodes"),
        "prophylaxis": comparison,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
