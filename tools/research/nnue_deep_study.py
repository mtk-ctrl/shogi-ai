#!/usr/bin/env python3
"""Budgeted, resumable own-engine deep study for NNUE teacher generation.

A case is selected from fully verified played games. Normal 50ms preliminary
search identifies a disagreement; 10-minute research follows; only cases whose
preferred move changes get the additional 50-minute stage. Independent
candidate-child refutations use fresh processes and symmetric time budgets.
Research observations are not presumed true, nor directly added to the
formal position-knowledge archive.

The state is single-worker and atomic per finished case. It can be resumed
after cancellation: no duplicate *completed* case is reread, but an interrupted
uncheckpointed analysis may be repeated; such repeats must not be counted as
independent evidence.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp
from tools.research.postgame_cases import load_archive, make_case
from tools.research.nnue_split import allocate_roots, position_identity


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def atomic_write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    staging = p.with_name(p.name + ".tmp")
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staging.replace(p)


def choose(games, max_cases, per_game, eligible_roots=None):
    if not (1 <= max_cases <= 96 and 1 <= per_game <= 4):
        raise ValueError("research case budget must meet bounded postgame scope")
    candidates = []
    for game in games:
        if eligible_roots is not None and game.row["game_id"] not in eligible_roots:
            continue
        # Unresolved endings may still have diagnostic interest, but are not
        # outcome teachers. Do not put them in this first complete-game study.
        if game.outcome_status == "unresolved" or len(game.moves) < 8:
            continue
        n = len(game.moves)
        # spread case selection across game phases, with bounded examples/game
        chosen = sorted({max(1, min(n - 1, (k + 1) * n // (per_game + 1)))
                         for k in range(per_game)})
        for ply in chosen:
            case = make_case(game, ply)
            rank = digest((str(game.row["game_id"]) + ":" + str(ply)).encode())
            candidates.append((rank, case))
    # round robin across original games, then deterministically within group
    buckets = {}
    for rank, case in candidates:
        buckets.setdefault(case["source"]["game_id"], []).append((rank, case))
    for group in buckets.values():
        group.sort()
    selected = []
    seen_positions = set()
    for index in range(per_game):
        for gid in sorted(buckets):
            if index < len(buckets[gid]) and len(selected) < max_cases:
                candidate = buckets[gid][index][1]
                key = candidate["position_key"]
                if key not in seen_positions:
                    selected.append(candidate)
                    seen_positions.add(key)
    return selected


def analyze(binary, knowledge, case, short_ms, medium_ms, long_ms, branch_ms,
            expected_positions):
    def search(history, ms):
        instance = Analyzer(binary, knowledge, expected_positions=expected_positions)
        try:
            return instance.search(case["start_sfen"], history, ms)
        finally:
            instance.close()

    history = tuple(case["history_moves"])
    fast = search(history, short_ms)
    medium = search(history, medium_ms)
    # A study that was just a preapproved, immediate position-knowledge move
    # offers no deep-search teacher. Preserve the observation but do not assign
    # deep budget or a confident neural label.
    if medium.get("research_decision_id"):
        return {"case": case, "root_short": fast, "root_deep": medium,
                "status": "preapproved_decision_not_deep_search",
                "additional_ms": 0, "branches": {}}
    moved = (fast.get("bestmove") != medium.get("bestmove")
             and medium.get("bestmove") not in ("resign", "win"))
    deep = search(history, long_ms) if moved else medium
    additional = long_ms if moved else 0
    children = {}
    best = deep.get("bestmove")
    original = case["actual_move"]
    # A changed choice is a hypothesis, not correctness. Evaluate both branches
    # with separate equal-budget subprocesses and full pre-move histories.
    if best not in ("resign", "win") and best != original:
        board = shogi.Board(case["start_sfen"])
        for token in history:
            board.push_usi(token)
        if shogi.Move.from_usi(best) in board.legal_moves:
            children = {
                "actual": search(history + (original,), branch_ms),
                "research": search(history + (best,), branch_ms)
            }
    status = ("studied_and_compared" if children else "studied")
    return {"case": case, "root_short": fast, "root_medium": medium,
            "root_deep": deep, "branches": children, "status": status,
            "additional_ms": additional,
            "teacher_candidate_status": "own_search_uncertain",
            "analysis_consistent": exact_cp(deep),
            "research_budget_requested_ms": short_ms + medium_ms + additional
                                          + (2 * branch_ms if children else 0)}


def execute(archives, binary, knowledge, output, max_cases=4, per_game=4,
            short_ms=50, medium_ms=600000, long_ms=3000000,
            branch_ms=600000, expected_positions=163, split_seed=20261021):
    if not (1 <= max_cases <= 96 and 1 <= per_game <= 4):
        raise ValueError("invalid selection")
    if not (1 <= short_ms <= medium_ms <= long_ms <= 86400000
            and 1 <= branch_ms <= 86400000):
        raise ValueError("invalid study budgets")
    games = [game for directory in archives for game in load_archive(directory)]
    if len({g.row["game_id"] for g in games}) != len(games):
        raise ValueError("duplicate original game identity")
    binary = Path(binary)
    knowledge = Path(knowledge)
    if not binary.is_file() or not knowledge.is_file():
        raise ValueError("engine binary and adopted knowledge both required")
    params = {"archives": [str(d) for d in archives],
              "source_archive_hashes": sorted({g.archive_sha256 for g in games}),
              "engine_sha256": digest(binary.read_bytes()),
              "knowledge_sha256": digest(knowledge.read_bytes()),
              "max_cases": max_cases, "per_game": per_game,
              "short_ms": short_ms, "medium_ms": medium_ms,
              "long_ms": long_ms, "branch_ms": branch_ms,
              "expected_positions": expected_positions,
              "split_seed": split_seed, "split_rule": "root_sha256_train_only"}
    train_roots = (allocate_roots((g.row["game_id"] for g in games), split_seed)["train"]
                   if len(games) >= 3 else {g.row["game_id"] for g in games})
    case_list = choose(games, max_cases, per_game, train_roots)
    if not case_list:
        raise ValueError("no eligible original cases")
    input_hash = digest(json.dumps(params, sort_keys=True).encode())
    state_path = Path(output)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("input_hash") != input_hash or state.get("case_ids") != [c["case_id"] for c in case_list]:
            raise ValueError("resume input hash or selected cases changed")
    else:
        state = {"schema": "nnue-deep-study-v1", "input_hash": input_hash,
                 "parameters": params,
                 "case_ids": [c["case_id"] for c in case_list], "results": [],
                 "status": "running"}
        atomic_write(state_path, state)
    done = {r["case"]["case_id"] for r in state["results"]}
    if len(done) != len(state["results"]):
        raise ValueError("duplicate saved research result")
    for case in case_list:
        if case["case_id"] in done:
            continue
        row = analyze(binary, knowledge, case, short_ms, medium_ms, long_ms,
                      branch_ms, expected_positions)
        state["results"].append(row)
        atomic_write(state_path, state)
        print(json.dumps({"research": len(state["results"]), "total": len(case_list),
                          "case_id": case["case_id"], "status": row["status"]}),
              flush=True)
    state["status"] = "analysis_complete_not_training_or_strength"
    state["label_ready"] = sum(exact_cp(r["root_deep"]) and
                               not r["root_deep"].get("research_decision_id")
                               for r in state["results"])
    state["routes"] = dict(Counter(r["status"] for r in state["results"]))
    state["total_requested_ms"] = sum(r.get("research_budget_requested_ms", 0)
                                      for r in state["results"])
    atomic_write(state_path, state)
    return state


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-dir", type=Path, action="append", required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--knowledge", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-cases", type=int, default=4)
    ap.add_argument("--per-game", type=int, default=4)
    ap.add_argument("--short-ms", type=int, default=50)
    ap.add_argument("--medium-ms", type=int, default=600000)
    ap.add_argument("--long-ms", type=int, default=3000000)
    ap.add_argument("--branch-ms", type=int, default=600000)
    ap.add_argument("--expected-positions", type=int, default=163)
    ap.add_argument("--split-seed", type=int, default=20261021)
    args = ap.parse_args()
    execute(args.archive_dir, args.engine, args.knowledge, args.output,
            args.max_cases, args.per_game, args.short_ms,
            args.medium_ms, args.long_ms, args.branch_ms, args.expected_positions,
            args.split_seed)


if __name__ == "__main__":
    main()
