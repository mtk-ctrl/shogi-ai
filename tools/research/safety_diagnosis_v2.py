#!/usr/bin/env python3
"""Safety-focused diagnosis for Evaluation-v2 self-play records.

This tool does not learn weights automatically. It uses ordinary match telemetry
only to select suspicious quiet positions, then re-analyzes those positions with
the same KUMOJI engine at a deeper fixed time and records the static evaluation
breakdown, including detailed Safety internals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import shogi

from benchmarks.arena import Engine


SAFETY_FIELDS = (
    "safety_black_points",
    "safety_white_points",
    "safety_black_gold_guards",
    "safety_black_silver_guards",
    "safety_black_pawn_guards",
    "safety_white_gold_guards",
    "safety_white_silver_guards",
    "safety_white_pawn_guards",
)


def static_eval(engine: Engine, moves: list[str]) -> dict[str, int]:
    command = "position startpos"
    if moves:
        command += " moves " + " ".join(moves)
    engine.send(command)
    engine.send("eval")
    line = engine.wait_prefix("info string evaluation ", 10)
    tokens = line.split()[3:]
    if len(tokens) % 2:
        raise RuntimeError(f"unexpected eval output: {line}")
    out: dict[str, int] = {}
    for i in range(0, len(tokens), 2):
        out[tokens[i]] = int(tokens[i + 1])
    return out


def analyze(engine: Engine, moves: list[str]) -> dict:
    best = engine.bestmove(moves)
    search = dict(engine.last_search)
    return {
        "bestmove": best,
        "score_cp_stm": search.get("score_cp"),
        "score_mate_stm": search.get("score_mate"),
        "depth": search.get("depth"),
        "seldepth": search.get("seldepth"),
        "nodes": search.get("nodes"),
        "elapsed_ms": search.get("elapsed_ms"),
        "pv": search.get("pv", []),
    }


def actor_value(value_black: int, black_to_move: bool) -> int:
    return value_black if black_to_move else -value_black


def own_safety(detail: dict[str, int], black_to_move: bool) -> dict[str, int]:
    side = "black" if black_to_move else "white"
    return {
        "points": detail[f"safety_{side}_points"],
        "gold_guards": detail[f"safety_{side}_gold_guards"],
        "silver_guards": detail[f"safety_{side}_silver_guards"],
        "pawn_guards": detail[f"safety_{side}_pawn_guards"],
    }


def opponent_safety(detail: dict[str, int], black_to_move: bool) -> dict[str, int]:
    side = "white" if black_to_move else "black"
    return {
        "points": detail[f"safety_{side}_points"],
        "gold_guards": detail[f"safety_{side}_gold_guards"],
        "silver_guards": detail[f"safety_{side}_silver_guards"],
        "pawn_guards": detail[f"safety_{side}_pawn_guards"],
    }


def collect_candidates(payload: dict, min_ply: int) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    for game_index, game in enumerate(payload.get("details", [])):
        records = game.get("move_records", [])
        board = shogi.Board()
        moves: list[str] = []

        for index, record in enumerate(records):
            pre_moves = list(moves)
            pre_sfen = board.sfen()
            side_black = board.turn == shogi.BLACK

            if index + 1 < len(records):
                nxt = records[index + 1]
                s0 = record.get("search", {}).get("score_cp_stm")
                s1 = nxt.get("search", {}).get("score_cp_stm")
                if s0 is not None and s1 is not None:
                    actor_after_live = -s1
                    live_drop = s0 - actor_after_live
                    quiet = not any((
                        record.get("in_check_before"),
                        record.get("is_capture"),
                        record.get("is_promotion"),
                        record.get("gave_check"),
                    ))
                    if record.get("ply", 0) >= min_ply and quiet:
                        key = " ".join(pre_sfen.split()[:3])
                        if key not in seen:
                            seen.add(key)
                            candidates.append({
                                "game_index": game_index,
                                "ply": record.get("ply"),
                                "side_to_move": "black" if side_black else "white",
                                "move": record.get("move"),
                                "moves_before": pre_moves,
                                "sfen_before": pre_sfen,
                                "live_score_before_cp": s0,
                                "live_actor_after_cp": actor_after_live,
                                "live_drop_cp": live_drop,
                                "live_depth": record.get("search", {}).get("depth"),
                                "live_nodes": record.get("search", {}).get("nodes"),
                            })

            try:
                board.push_usi(record["move"])
                moves.append(record["move"])
            except Exception:
                break

    candidates.sort(key=lambda x: x["live_drop_cp"], reverse=True)
    return candidates


def diagnose_one(engine: Engine, row: dict) -> dict:
    moves = row["moves_before"]
    move = row["move"]
    black_to_move = row["side_to_move"] == "black"

    static_before = static_eval(engine, moves)
    static_after = static_eval(engine, moves + [move])
    deep_before = analyze(engine, moves)
    deep_after = analyze(engine, moves + [move])

    before_cp = deep_before.get("score_cp_stm")
    after_cp_opp = deep_after.get("score_cp_stm")
    actor_after_cp = None if after_cp_opp is None else -after_cp_opp
    deep_loss = None
    if before_cp is not None and actor_after_cp is not None:
        deep_loss = before_cp - actor_after_cp

    own_before = own_safety(static_before, black_to_move)
    own_after = own_safety(static_after, black_to_move)
    opp_before = opponent_safety(static_before, black_to_move)
    opp_after = opponent_safety(static_after, black_to_move)

    out = dict(row)
    out.update({
        "deep_before": deep_before,
        "deep_after_actual_move": deep_after,
        "deep_actor_after_actual_cp": actor_after_cp,
        "deep_loss_cp": deep_loss,
        "actual_is_deep_bestmove": move == deep_before.get("bestmove"),
        "static_before": static_before,
        "static_after": static_after,
        "static_total_actor_before": actor_value(static_before["total"], black_to_move),
        "static_total_actor_after": actor_value(static_after["total"], black_to_move),
        "static_safety_term_actor_before": actor_value(static_before["safety"], black_to_move),
        "static_safety_term_actor_after": actor_value(static_after["safety"], black_to_move),
        "own_safety_before": own_before,
        "own_safety_after": own_after,
        "opponent_safety_before": opp_before,
        "opponent_safety_after": opp_after,
        "own_safety_points_change": own_after["points"] - own_before["points"],
        "opponent_safety_points_change": opp_after["points"] - opp_before["points"],
    })
    return out


def render_markdown(result: dict) -> str:
    rows = result["diagnoses"]
    lines = [
        "# 玉の守り（Safety）初回棋譜診断",
        "",
        f"- 元対局: {result['source_games']}局",
        f"- Book（定跡）: OFF",
        f"- Experience（経験）: OFF",
        f"- 通常対局: {result['live_go_command']}",
        f"- 深読み: 1局面あたり {result['deep_ms']}ms × 着手前後",
        f"- 診断局面: {len(rows)}",
        "",
        "## 見方",
        "",
        "- live drop: 通常対局時に、指す前の期待と指した直後の相手側評価の間に生じた落差。",
        "- deep loss: 深読みで見た最善値と、実戦手を指した後の値との差。大きいほど実戦手が深読みでは悪い。",
        "- 玉の守り（Safety）は現行定義の金・銀・歩による守り点を、そのまま分解して表示する。",
        "- ここでは重みを変更しない。『計算式が何を見落としているか』を見つけるための診断である。",
        "",
        "## 深読み損失が大きい局面",
        "",
        "|順位|局|手数|手番|実戦手|深読み最善手|live drop|deep loss|自玉Safety点 前→後|金/銀/歩 前→後|",
        "|---:|---:|---:|---|---|---|---:|---:|---:|---|",
    ]
    ranked = sorted(
        rows,
        key=lambda r: -10**9 if r["deep_loss_cp"] is None else r["deep_loss_cp"],
        reverse=True,
    )
    for rank, row in enumerate(ranked[:20], 1):
        b = row["own_safety_before"]
        a = row["own_safety_after"]
        loss = "mate/NA" if row["deep_loss_cp"] is None else str(row["deep_loss_cp"])
        lines.append(
            f"|{rank}|{row['game_index']+1}|{row['ply']}|{row['side_to_move']}|"
            f"{row['move']}|{row['deep_before']['bestmove']}|{row['live_drop_cp']}|{loss}|"
            f"{b['points']}→{a['points']}|"
            f"{b['gold_guards']}/{b['silver_guards']}/{b['pawn_guards']}→"
            f"{a['gold_guards']}/{a['silver_guards']}/{a['pawn_guards']}|"
        )

    bad = [r for r in rows if r["deep_loss_cp"] is not None and r["deep_loss_cp"] >= 100]
    same_best = sum(1 for r in rows if r["actual_is_deep_bestmove"])
    lines += [
        "",
        "## 自動集計",
        "",
        f"- deep loss 100以上: **{len(bad)} / {len(rows)}局面**",
        f"- 通常200msの実戦手が深読み最善手と一致: **{same_best} / {len(rows)}局面**",
        "",
        "次段階では、deep lossが大きい局面を盤面形で読み、玉の守り（Safety）の定義不足を",
        "『逃げ道』『守備駒の連結』『飛車角の射線』『外周の守り』などに分類する。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--markdown-output", default="")
    ap.add_argument("--deep-ms", type=int, default=1000)
    ap.add_argument("--candidates", type=int, default=24)
    ap.add_argument("--min-ply", type=int, default=12)
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    selected = collect_candidates(payload, args.min_ply)[: args.candidates]

    options = {
        "OpeningBook": False,
        "ExperienceCache": False,
        "AdaptiveLongThink": False,
    }
    engine = Engine(args.engine, "SafetyAnalyzer", options, f"go movetime {args.deep_ms}")
    diagnoses: list[dict] = []
    try:
        for i, row in enumerate(selected, 1):
            diag = diagnose_one(engine, row)
            diagnoses.append(diag)
            print(
                f"{i:02d}/{len(selected)} game={row['game_index']+1} ply={row['ply']} "
                f"move={row['move']} live_drop={row['live_drop_cp']} "
                f"deep_loss={diag['deep_loss_cp']} deep_best={diag['deep_before']['bestmove']}"
            )
    finally:
        engine.close()

    result = {
        "schema_version": 1,
        "purpose": "Safety definition diagnosis; not automatic tuning",
        "source_games": payload.get("games", len(payload.get("details", []))),
        "live_go_command": payload.get("go_command"),
        "source_options_a": payload.get("options_a"),
        "source_options_b": payload.get("options_b"),
        "deep_ms": args.deep_ms,
        "selection": {
            "min_ply": args.min_ply,
            "candidate_limit": args.candidates,
            "quiet_only": True,
            "rank_key": "live_drop_cp",
        },
        "diagnoses": diagnoses,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.markdown_output:
        md = Path(args.markdown_output)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(result), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
