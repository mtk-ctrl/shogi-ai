#!/usr/bin/env python3
"""Diagnose missing evaluation concepts from deep-search correction positions.

The candidate concepts are observation-only. They are NOT added to KUMOJI's
static score and therefore cannot affect move selection. The goal is to ask:
after the 30s best move versus the 200ms actual move, which human-style
positional facts improved?

Candidate concepts:
- prophylaxis: opponent forcing resources removed
- initiative: own forcing resources created
- enablement: quiet legal options / active pieces made available
- king safety quality: actual escape/control/line exposure around the king
- piece placement: defended, advanced, centrally/king-relevant piece placement
- promotion potential: legal promotion and promotion-zone access
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import shogi


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

MAJORS = {shogi.BISHOP, shogi.ROOK, shogi.PROM_BISHOP, shogi.PROM_ROOK}
GOLDLIKE = {
    shogi.GOLD, shogi.PROM_PAWN, shogi.PROM_LANCE,
    shogi.PROM_KNIGHT, shogi.PROM_SILVER,
}
FEATURES = (
    "prophylaxis",
    "initiative",
    "enablement",
    "king_safety_quality",
    "piece_placement",
    "promotion_potential",
)

def square_file(square: int) -> int:
    # python-shogi 1.1.1 exposes SQUARE_NAMES but no square_file helper.
    return 9 - int(shogi.SQUARE_NAMES[square][0])


def square_rank(square: int) -> int:
    return ord(shogi.SQUARE_NAMES[square][1]) - ord("a")


SQUARE_AT = {
    (square_file(sq), square_rank(sq)): sq
    for sq in shogi.SQUARES
}


def other(color: int) -> int:
    return shogi.WHITE if color == shogi.BLACK else shogi.BLACK


def clone_for_turn(board: shogi.Board, color: int) -> shogi.Board:
    b = shogi.Board(board.sfen())
    b.turn = color
    return b


def piece_value(piece) -> int:
    if piece is None or piece.piece_type == shogi.KING:
        return 0
    return VALUES.get(piece.piece_type, 0)


def is_promotion_zone(color: int, square: int) -> bool:
    rank = square // 9
    return rank < 3 if color == shogi.BLACK else rank >= 6


def legal_facts(board: shogi.Board, color: int) -> dict:
    """One-ply legal resources for one side in the current board geometry."""
    b = clone_for_turn(board, color)
    facts = {
        "legal_moves": 0,
        "checks": 0,
        "captures": 0,
        "capture_value": 0,
        "promotions": 0,
        "quiet_moves": 0,
        "quiet_sources": 0,
        "promotion_zone_entries": 0,
        "forcing_score": 0,
    }
    quiet_sources = set()
    for move in list(b.legal_moves):
        facts["legal_moves"] += 1
        victim = b.piece_at(move.to_square)
        capture = victim is not None and victim.color != color
        value = piece_value(victim) if capture else 0
        promotion = bool(move.promotion)
        if capture:
            facts["captures"] += 1
            facts["capture_value"] += value
        if promotion:
            facts["promotions"] += 1
        if is_promotion_zone(color, move.to_square):
            facts["promotion_zone_entries"] += 1

        b.push(move)
        gives_check = b.is_check()
        b.pop()
        if gives_check:
            facts["checks"] += 1

        forcing = capture or promotion or gives_check
        if not forcing:
            facts["quiet_moves"] += 1
            if move.from_square is not None:
                quiet_sources.add(move.from_square)
            elif move.drop_piece_type is not None:
                quiet_sources.add(("drop", move.drop_piece_type))

    facts["quiet_sources"] = len(quiet_sources)
    # Diagnostic scale only: one pawn=100 remains intuitive.
    facts["forcing_score"] = (
        600 * facts["checks"]
        + facts["capture_value"]
        + 80 * facts["captures"]
        + 220 * facts["promotions"]
    )
    return facts


def ring_squares(king: int) -> list[int]:
    if king is None:
        return []
    f0, r0 = square_file(king), square_rank(king)
    out = []
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if not (df or dr):
                continue
            sq = SQUARE_AT.get((f0 + df, r0 + dr))
            if sq is not None:
                out.append(sq)
    return out


def open_line_risk(board: shogi.Board, color: int) -> int:
    king = board.king_squares[color]
    if king is None:
        return 0
    enemy = other(color)
    kf, kr = square_file(king), square_rank(king)
    risk = 0
    for df, dr in (
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    ):
        step = 1
        while True:
            sq = SQUARE_AT.get((kf + df * step, kr + dr * step))
            if sq is None:
                break
            p = board.piece_at(sq)
            if p is None:
                step += 1
                continue
            if p.color == color:
                break
            if p.color == enemy:
                diagonal = bool(df and dr)
                if diagonal and p.piece_type in (shogi.BISHOP, shogi.PROM_BISHOP):
                    risk += 3
                elif not diagonal and p.piece_type in (shogi.ROOK, shogi.PROM_ROOK):
                    risk += 4
                elif df == 0 and p.piece_type == shogi.LANCE:
                    enemy_forward = -1 if enemy == shogi.BLACK else 1
                    # From the lance to our king is the opposite of the scan.
                    if -dr == enemy_forward:
                        risk += 2
            break
    return risk


def king_safety_detail(board: shogi.Board, color: int) -> dict:
    enemy = other(color)
    king = board.king_squares[color]
    if king is None:
        return {
            "safe_escapes": 0, "attacked_ring": 8, "defended_ring": 0,
            "open_line_risk": 8, "in_check": 1, "score": -200,
        }

    attacked_ring = 0
    defended_ring = 0
    safe_escapes = 0
    for sq in ring_squares(king):
        if board.is_attacked_by(enemy, sq):
            attacked_ring += 1
        if board.is_attacked_by(color, sq):
            defended_ring += 1
        occupant = board.piece_at(sq)
        own_occupied = occupant is not None and occupant.color == color
        if not own_occupied and not board.is_attacked_by(enemy, sq):
            safe_escapes += 1

    # board.is_check() is side-to-move dependent. Build a copy with our turn.
    own_view = clone_for_turn(board, color)
    in_check = int(own_view.is_check())
    line_risk = open_line_risk(board, color)
    score = (
        15 * safe_escapes
        + 4 * defended_ring
        - 8 * attacked_ring
        - 14 * line_risk
        - 50 * in_check
    )
    return {
        "safe_escapes": safe_escapes,
        "attacked_ring": attacked_ring,
        "defended_ring": defended_ring,
        "open_line_risk": line_risk,
        "in_check": in_check,
        "score": score,
    }


def chebyshev(a: int, b: int) -> int:
    if a is None or b is None:
        return 9
    return max(
        abs(square_file(a) - square_file(b)),
        abs(square_rank(a) - square_rank(b)),
    )


def piece_placement_detail(board: shogi.Board, color: int) -> dict:
    enemy = other(color)
    enemy_king = board.king_squares[enemy]
    defended = attacked_loose = advanced = central = king_relevant = 0

    for sq in shogi.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.color != color or p.piece_type == shogi.KING:
            continue
        is_defended = board.is_attacked_by(color, sq)
        is_attacked = board.is_attacked_by(enemy, sq)
        if is_defended:
            defended += 1
        if is_attacked and not is_defended:
            attacked_loose += 1

        rank = sq // 9
        progress = 8 - rank if color == shogi.BLACK else rank
        if progress >= 5:
            advanced += 1

        f = square_file(sq)
        if 2 <= f <= 6 and 2 <= square_rank(sq) <= 6:
            central += 1

        d = chebyshev(sq, enemy_king)
        if d <= 3:
            # Major/minor pieces close to the enemy king are especially relevant.
            king_relevant += 2 if p.piece_type in MAJORS else 1

    score = (
        3 * defended
        - 6 * attacked_loose
        + 2 * advanced
        + central
        + 3 * king_relevant
    )
    return {
        "defended_pieces": defended,
        "loose_attacked_pieces": attacked_loose,
        "advanced_pieces": advanced,
        "central_pieces": central,
        "enemy_king_relevant": king_relevant,
        "score": score,
    }


def promotion_detail(board: shogi.Board, color: int, legal: dict | None = None) -> dict:
    legal = legal or legal_facts(board, color)
    unpromoted_in_zone = 0
    near_zone = 0
    for sq in shogi.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.color != color or p.piece_type == shogi.KING:
            continue
        if p.piece_type in (shogi.GOLD, shogi.PROM_PAWN, shogi.PROM_LANCE,
                            shogi.PROM_KNIGHT, shogi.PROM_SILVER,
                            shogi.PROM_BISHOP, shogi.PROM_ROOK):
            continue
        rank = sq // 9
        if is_promotion_zone(color, sq):
            unpromoted_in_zone += 1
        elif (color == shogi.BLACK and rank == 3) or (color == shogi.WHITE and rank == 5):
            near_zone += 1
    score = (
        8 * legal["promotions"]
        + 3 * legal["promotion_zone_entries"]
        + 3 * unpromoted_in_zone
        + near_zone
    )
    return {
        "legal_promotions": legal["promotions"],
        "zone_entries": legal["promotion_zone_entries"],
        "unpromoted_in_zone": unpromoted_in_zone,
        "near_zone": near_zone,
        "score": score,
    }


def initiative_detail(board: shogi.Board, actor: int) -> dict:
    enemy = other(actor)
    enemy_king = board.king_squares[enemy]
    current_check = int(
        enemy_king is not None and board.is_attacked_by(actor, enemy_king)
    )
    ring_control = sum(
        board.is_attacked_by(actor, sq)
        for sq in ring_squares(enemy_king)
    )
    attacked_pieces = 0
    attacked_value = 0
    loose_target_value = 0
    for sq in shogi.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.color != enemy or p.piece_type == shogi.KING:
            continue
        if not board.is_attacked_by(actor, sq):
            continue
        attacked_pieces += 1
        value = piece_value(p)
        attacked_value += value
        if not board.is_attacked_by(enemy, sq):
            loose_target_value += value

    # If the move gives check, fewer legal replies means greater forcing power.
    reply_count = sum(1 for _ in board.legal_moves)
    reply_restriction = max(0, 12 - reply_count) if current_check else 0
    score = (
        1000 * current_check
        + 60 * ring_control
        + attacked_value
        + loose_target_value
        + 120 * reply_restriction
    )
    return {
        "current_check": current_check,
        "enemy_king_ring_control": ring_control,
        "attacked_enemy_pieces": attacked_pieces,
        "attacked_enemy_value": attacked_value,
        "loose_target_value": loose_target_value,
        "opponent_reply_count": reply_count,
        "score": score,
    }


def state_concepts(board: shogi.Board, actor: int) -> dict:
    enemy = other(actor)
    own_legal = legal_facts(board, actor)
    opp_legal = legal_facts(board, enemy)

    # Higher is always better for actor. Prophylaxis is interpreted only for
    # non-checking moves; a checking move restricts replies through initiative,
    # not through preventive defence.
    prophylaxis = -opp_legal["forcing_score"]
    initiative = initiative_detail(board, actor)

    # Quiet choices are the closest cheap proxy for "what can I prepare next?"
    enablement = (
        own_legal["quiet_moves"]
        + 4 * own_legal["quiet_sources"]
    )

    safety = king_safety_detail(board, actor)
    placement = piece_placement_detail(board, actor)
    promotion = promotion_detail(board, actor, own_legal)

    return {
        "prophylaxis": prophylaxis,
        "initiative": initiative["score"],
        "enablement": enablement,
        "king_safety_quality": safety["score"],
        "piece_placement": placement["score"],
        "promotion_potential": promotion["score"],
        "detail": {
            "own_legal": own_legal,
            "opponent_legal": opp_legal,
            "initiative": initiative,
            "king_safety": safety,
            "piece_placement": placement,
            "promotion_potential": promotion,
            "actor_just_gave_check": initiative["current_check"],
        },
    }


def result_after(sfen: str, move_token: str) -> shogi.Board:
    b = shogi.Board(sfen)
    move = shogi.Move.from_usi(move_token)
    if move not in b.legal_moves:
        raise ValueError(f"illegal fixture move {move_token} in {sfen}")
    b.push(move)
    return b


def compare_position(row: dict) -> dict:
    actor = shogi.BLACK if row["side_to_move"] == "black" else shogi.WHITE
    actual_board = result_after(row["sfen_before"], row["actual_move"])
    best_board = result_after(row["sfen_before"], row["deep_bestmove"])
    actual = state_concepts(actual_board, actor)
    best = state_concepts(best_board, actor)
    delta = {name: best[name] - actual[name] for name in FEATURES}
    # A checking move shrinks the opponent reply set by force. Do not call that
    # prophylaxis; classify it under Initiative / Forcing Power instead.
    if actual["detail"]["actor_just_gave_check"] or best["detail"]["actor_just_gave_check"]:
        delta["prophylaxis"] = None
    support = [name for name in FEATURES if delta[name] is not None and delta[name] > 0]
    oppose = [name for name in FEATURES if delta[name] is not None and delta[name] < 0]
    return {
        **row,
        "actual_concepts": actual,
        "deep_best_concepts": best,
        "delta_best_minus_actual": delta,
        "supports_deep_best": support,
        "opposes_deep_best": oppose,
    }


def render_markdown(result: dict) -> str:
    rows = result["positions"]
    agg = result["aggregate"]
    labels = {
        "prophylaxis": "先回りの守り（Prophylaxis）",
        "initiative": "主導権・強制力（Initiative）",
        "enablement": "次の展開を作る力（Enablement）",
        "king_safety_quality": "玉の実際の安全度（King Safety Quality）",
        "piece_placement": "駒の配置価値（Piece Placement）",
        "promotion_potential": "成りへの可能性（Promotion Potential）",
    }
    lines = [
        "# 評価関数・新しい感覚の診断",
        "",
        f"- 元データ: Actions run {result['source_run']}",
        f"- 対象: {len(rows)}局面 — {result.get('selection','deep-search correction positions')}",
        "- 重要: 下記6項目は診断値であり、KUMOJIの評価値にはまだ1点も加算していない。",
        "",
        "## 候補定義",
        "",
        "- **先回りの守り（Prophylaxis）**: 相手の次の王手・駒取り・成り等の強制的選択肢が少ないほど高い。",
        "- **主導権・強制力（Initiative）**: 自分が次に王手・駒取り・成り等を作れるほど高い。直前の着手で王手なら追加評価。",
        "- **次の展開を作る力（Enablement）**: 自分の静かな合法手と、それを持つ駒の種類が多いほど高い。",
        "- **玉の実際の安全度（King Safety Quality）**: 安全な逃げ道、周辺の敵味方の効き、飛車角香の直線的な危険を見る。",
        "- **駒の配置価値（Piece Placement）**: 守られた駒、前進した駒、中央配置、敵玉への関与を加点し、浮いて攻められる駒を減点。",
        "- **成りへの可能性（Promotion Potential）**: 現在可能な成り、敵陣への進入、敵陣内・直前にいる未成駒を見る。",
        "",
        "## 12局面での説明力",
        "",
        "|候補|30秒最善手を支持|同値|実戦手側を支持|対象外|",
        "|---|---:|---:|---:|---:|",
    ]
    for name in FEATURES:
        a = agg[name]
        lines.append(
            f"|{labels[name]}|{a['positive']}|{a['zero']}|{a['negative']}|{a.get('not_applicable',0)}|"
        )
    lines += [
        "",
        f"- 6候補のうち1つ以上が30秒最善手を支持: **{agg['coverage']['any_positive']} / {len(rows)}局面**",
        f"- 3項目以上が同時に30秒最善手を支持: **{agg['coverage']['three_or_more']} / {len(rows)}局面**",
        "",
        "## 局面別",
        "",
        "|元index|手数|実戦手|30秒最善手|deep loss|支持した新しい感覚|",
        "|---:|---:|---|---|---:|---|",
    ]
    for row in rows:
        support = "、".join(labels[n].split("（", 1)[0] for n in row["supports_deep_best"]) or "なし"
        lines.append(
            f"|{row['source_index']}|{row['ply']}|{row['actual_move']}|{row['deep_bestmove']}|"
            f"{row['deep_loss_cp']}|{support}|"
        )
    lines += [
        "",
        "## 判定ルール",
        "",
        "この段階では『支持数が多い＝採用』とはしない。重複して同じ現象を数えていないか、",
        "局面固有の偶然ではないかを確認した後、説明力の高い定義だけを100局面以上へ拡張して検証する。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--markdown-output", default="")
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = [compare_position(row) for row in payload["positions"]]

    aggregate = {}
    for name in FEATURES:
        vals = [row["delta_best_minus_actual"][name] for row in rows]
        observed = [v for v in vals if v is not None]
        aggregate[name] = {
            "positive": sum(v > 0 for v in observed),
            "zero": sum(v == 0 for v in observed),
            "negative": sum(v < 0 for v in observed),
            "not_applicable": len(vals) - len(observed),
            "deltas": vals,
        }
    aggregate["coverage"] = {
        "any_positive": sum(bool(row["supports_deep_best"]) for row in rows),
        "three_or_more": sum(len(row["supports_deep_best"]) >= 3 for row in rows),
    }

    result = {
        "schema_version": 1,
        "source_run": payload.get("source_run"),
        "source_engine": payload.get("source_engine"),
        "selection": payload.get("selection"),
        "note": "Diagnostic concepts only; none are included in KUMOJI evaluation.",
        "positions": rows,
        "aggregate": aggregate,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(result), encoding="utf-8")

    print(json.dumps({
        "positions": len(rows),
        "aggregate": {
            name: {k: v for k, v in aggregate[name].items() if k != "deltas"}
            for name in FEATURES
        },
        "coverage": aggregate["coverage"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
