#!/usr/bin/env python3
"""Derive NNUE labels from verified OWN played-move archives and postgame research.

Never promotes newly researched unplayed moves to persistent position knowledge.
Diagnosis observations remain a separate, versioned derivative of the played
archive. Every derived label retains its group and exact source hashes.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shogi
from tools.research.postgame_cases import load_archive, make_case, position_command


def verified_outcome(game):
    if game.outcome_status == "unresolved":
        return None
    if game.row["winner"] is None:
        return 0
    a_won = game.row["winner"] == "A"
    return 1 if a_won == game.row["a_black"] else -1


def source_is_owned_selfplay(directory, games):
    # The normal arena calls the two own binaries build/engine-a and
    # build/engine-b, not KUMOJI. Trust those names only together with a
    # manifest proving the *same immutable source commit* was built on both
    # sides and binary SHA256 values are recorded.
    manifest = json.loads((Path(directory) / "manifest.json").read_text())
    ref = manifest.get("requested_ref_a")
    fixed_same_parent = (isinstance(ref, str) and
                         re.fullmatch(r"[0-9a-f]{40}", ref) is not None and
                         ref == manifest.get("requested_ref_b"))
    for game in games:
        a = str(game.metadata.get("engine_a", "")).lower()
        b = str(game.metadata.get("engine_b", "")).lower()
        direct_own = all(("kumoji" in name or "shogi-ai" in name)
                         for name in (a, b))
        built_own = (fixed_same_parent and
                     a.endswith("engine-a") and b.endswith("engine-b") and
                     all(re.fullmatch(r"[0-9a-f]{64}",
                                      str(game.metadata.get("sha256_" + side, "")))
                         for side in ("a", "b")))
        if not (direct_own or built_own):
            return False
    return bool(games)


def labels_from_games(games, per_game):
    labels = []
    for game in games:
        outcome = verified_outcome(game)
        if outcome is None or not game.moves:
            continue
        board = shogi.Board(game.start_sfen)
        n = len(game.moves)
        # Uniform stratification, capped per game. All positions inherit the
        # original game split; game outcome is *not* a per-move correctness tag.
        chosen = {min(n - 1, (k * n + n // 2) // per_game)
                  for k in range(per_game)}
        for ply, token in enumerate(game.moves):
            if ply in chosen:
                labels.append({
                    "root_game_id": game.row["game_id"],
                    "sfen": board.sfen(),
                    "origin": "selfplay_result",
                    "terminal_confirmed": True,
                    "outcome_black": outcome,
                    "confidence": round(0.45 / max(1, len(chosen)), 6),
                    "evidence": {
                        "archive_sha256": game.archive_sha256,
                        "manifest_sha256": game.manifest_sha256,
                        "game_id": game.row["game_id"],
                        "ply": ply + 1,
                        "verification": game.outcome_status,
                    },
                })
            board.push_usi(token)
    return labels


def labels_from_diagnosis(diagnosis, games_by_id):
    labels, rejected = [], {}
    for result in diagnosis:
        case = result["case"]
        source = case["source"]
        game = games_by_id.get(source["game_id"])
        if not game:
            raise ValueError("diagnosis references non-source game")
        ply = source["ply"]
        original_case = make_case(game, ply)
        if any(case.get(field) != original_case[field] for field in original_case):
            # Selection can add triage metadata, but not change the original.
            raise ValueError("diagnosis case does not match verified game history")
        obs = result.get("root_deep", {})
        reason = None
        if not (obs.get("status") == "recorded" and obs.get("kind") == "cp"
                and obs.get("bound") == "exact" and obs.get("pv_head_matches") is True
                and type(obs.get("depth")) is int and obs["depth"] > 0
                and type(obs.get("value_stm")) is int):
            reason = "incomplete_or_non_cp"
        elif (obs.get("position_command") != case["analysis_position_command"]
              or obs.get("history_key") != case["history_key"]):
            reason = "mismatched_history"
        elif obs.get("research_decision_id"):
            reason = "preapproved_knowledge_not_fresh_search"
        elif not (type(obs.get("requested_ms")) is int and obs["requested_ms"] > 0):
            reason = "missing_time"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        board = shogi.Board(game.start_sfen)
        for token in game.moves[:ply - 1]:
            board.push_usi(token)
        best = obs.get("bestmove")
        if best in ("resign", "win") or not isinstance(best, str) or shogi.Move.from_usi(best) not in board.legal_moves:
            rejected["nonlegal_study_move"] = rejected.get("nonlegal_study_move", 0) + 1
            continue
        milliseconds = obs["requested_ms"]
        # Not a truth probability: a conservative training weight, never an
        # independently proven correct move. 10-50min studies get more weight.
        confidence = min(.85, .2 + .1 * (milliseconds / 60000) ** .5)
        labels.append({
            "root_game_id": game.row["game_id"],
            "sfen": board.sfen(),
            "origin": "own_search",
            "cp_black": obs["value_stm"] * (1 if board.turn == shogi.BLACK else -1),
            "confidence": round(confidence, 6),
            "score_bound": "exact", "score_type": "cp",
            "evidence": {
                "archive_sha256": game.archive_sha256,
                "manifest_sha256": game.manifest_sha256,
                "case_id": case["case_id"],
                "history_key": case["history_key"],
                "requested_ms": milliseconds,
                "completed_depth": obs["depth"],
                "studied_move": best,
            },
        })
    return labels, rejected


def convert(archives, diagnosis, per_game):
    if not 1 <= per_game <= 16:
        raise ValueError("per-game cap must be 1..16")
    games = []
    for directory in archives:
        verified = load_archive(directory)
        if not source_is_owned_selfplay(directory, verified):
            raise ValueError("not a proven all-KUMOJI self-play archive")
        games.extend(verified)
    ids = {g.row["game_id"]: g for g in games}
    if len(ids) != len(games):
        raise ValueError("repeated original game among archives")
    labels = labels_from_games(games, per_game)
    rejected = {}
    if diagnosis:
        diag = json.loads(Path(diagnosis).read_text(encoding="utf-8"))
        if isinstance(diag, dict) and diag.get("schema") == "nnue-deep-study-v1":
            if diag.get("status") != "analysis_complete_not_training_or_strength":
                raise ValueError("incomplete deep-study checkpoint cannot become training data")
            diag = diag.get("results")
        if not isinstance(diag, list):
            raise ValueError("diagnosis must be a completed research list")
        focused, rejected = labels_from_diagnosis(diag, ids)
        labels.extend(focused)
    if not labels:
        raise ValueError("no verified training labels")
    return labels, {
        "schema": "nnue-label-extract-v1",
        "source_archive_sha256": sorted({g.archive_sha256 for g in games}),
        "source_manifest_sha256": sorted({g.manifest_sha256 for g in games}),
        "verified_game_count": len(games),
        "independent_source_games": len({s["root_game_id"] for s in labels}),
        "label_count": len(labels),
        "labels_by_origin": {
            origin: sum(s["origin"] == origin for s in labels)
            for origin in ("selfplay_result", "own_search")
        },
        "diagnosis_rejection_reasons": rejected,
        "source_constraint": "verified_played_games_and_own_postgame_search",
        "strength_improvement_verified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-dir", type=Path, action="append", required=True)
    p.add_argument("--diagnosis", type=Path)
    p.add_argument("--per-game", type=int, default=8)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() or args.manifest.exists():
        p.error("will not overwrite derived artifacts")
    labels, meta = convert(args.archive_dir, args.diagnosis, args.per_game)
    payload = "".join(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n" for s in labels)
    meta["label_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    args.manifest.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
