#!/usr/bin/env python3
"""Budgeted, resumable own-engine deep study for NNUE teacher generation.

A case is selected from fully verified played games. Normal 50ms preliminary
search identifies a disagreement; 10-minute research follows; changed choices
and an explicit priority quota get the additional 50-minute stage. Independent
candidate-child refutations use fresh processes and symmetric time budgets.
Research observations are not presumed true, nor directly added to the
formal position-knowledge archive.

The state is single-worker and atomic per completed stage and case, with the
latest completed-depth observation saved during search. Completed stages are
reused after cancellation, but the interrupted stage restarts its search; such repeats must not be counted as
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


def observed_actor_drop(game, ply):
    """Diagnostic-only disagreement across turns, never a teacher score."""
    if ply >= len(game.moves) or ply < 1:
        return None
    before = game.row["moves"][ply - 1].get("search", {})
    after = game.row["moves"][ply].get("search", {})
    def exact(record):
        return (record.get("score_status") == "recorded"
                and type(record.get("score_cp_stm")) is int
                and not record.get("score_lowerbound")
                and not record.get("score_upperbound"))
    if not exact(before) or not exact(after):
        return None
    # Both search scores are side-to-move relative; the next mover is the
    # opposite side. A positive sum means the mover's position deteriorated.
    return before["score_cp_stm"] + after["score_cp_stm"]


def choose(games, max_cases, per_game, eligible_roots=None, excluded_positions=None,
           selection_seed=None):
    if not (1 <= max_cases <= 96 and 1 <= per_game <= 4):
        raise ValueError("research case budget must meet bounded postgame scope")
    # Sample uncertainty/loss signatures, not simply the first sorted game.
    # An unchanged short search is never treated as proof of a good move.
    buckets = {}
    for game in games:
        gid = game.row["game_id"]
        if eligible_roots is not None and gid not in eligible_roots:
            continue
        n = len(game.moves)
        if game.outcome_status == "unresolved" or n < 10:
            continue
        candidate_plies = set()
        drops = [(observed_actor_drop(game, ply), ply)
                 for ply in range(8, n - 3)]
        sharp = [(drop, ply) for drop, ply in drops
                 if drop is not None and drop >= 100]
        sharp.sort(key=lambda x: (-x[0], digest(f"{gid}:{x[1]}".encode())))
        for drop, ply in sharp[:min(2, per_game)]:
            candidate_plies.add(ply)
        # Complement dramatic cases with spaced control positions, not an
        # entire game of late losing moves. Never label a move correct because
        # its game was won; this triage signal only allocates research time.
        for k in range(1, per_game + 1):
            candidate_plies.add(max(8, min(n - 4, k * n // (per_game + 1))))
        records = []
        for ply in sorted(candidate_plies):
            case = make_case(game, ply)
            drop = observed_actor_drop(game, ply)
            case["triage"] = {
                "reason": "suspected_loss" if drop is not None and drop >= 100 else "phase_control",
                "observed_actor_drop_cp": drop,
                "only_for_case_selection": True,
            }
            priority = (0 if drop is not None and drop >= 100 else 1,
                        -drop if drop is not None else 0,
                        digest(f"{gid}:{ply}".encode()))
            records.append((priority, case))
        records.sort(key=lambda entry: entry[0])
        buckets[gid] = records[:per_game]
    selected = []
    seen_positions = set(excluded_positions or ())
    ordered_roots = sorted(buckets, key=(lambda gid: digest(f'{selection_seed}:{gid}'.encode()))
                           if selection_seed is not None else None)
    for index in range(per_game):
        for gid in ordered_roots:
            if index < len(buckets[gid]) and len(selected) < max_cases:
                candidate = buckets[gid][index][1]
                key = candidate["position_key"]
                if key not in seen_positions:
                    selected.append(candidate)
                    seen_positions.add(key)
    return selected


def analyze(binary, knowledge, case, short_ms, medium_ms, long_ms, branch_ms,
            expected_positions, checkpoint=None, persist=None, force_long=False,
            neural_options=None):
    checkpoint = checkpoint if checkpoint is not None else {}
    def search(stage, history, ms):
        if stage in checkpoint.get('completed', {}):
            return checkpoint['completed'][stage]
        kwargs = {'neural_options': neural_options} if neural_options else {}
        instance = Analyzer(binary, knowledge, expected_positions=expected_positions, **kwargs)
        def iteration(frame):
            checkpoint['active'] = {'stage': stage, 'latest_completed_iteration': frame,
                                    'stage_complete': False}
            if persist:
                persist()
        try:
            kwargs = {'on_iteration': iteration} if persist else {}
            result = instance.search(case['start_sfen'], history, ms, **kwargs)
            checkpoint.setdefault('completed', {})[stage] = result
            checkpoint.pop('active', None)
            if persist:
                persist()
            return result
        finally:
            instance.close()

    history = tuple(case["history_moves"])
    fast = search('short', history, short_ms)
    medium = search('medium', history, medium_ms)
    # A study that was just a preapproved, immediate position-knowledge move
    # offers no deep-search teacher. Preserve the observation but do not assign
    # deep budget or a confident neural label.
    if medium.get("research_decision_id"):
        return {"case": case, "root_short": fast, "root_deep": medium,
                "status": "preapproved_decision_not_deep_search",
                "additional_ms": 0, "branches": {}}
    moved = (fast.get("bestmove") != medium.get("bestmove")
             and medium.get("bestmove") not in ("resign", "win"))
    use_long = moved or force_long
    deep = search('long', history, long_ms) if use_long else medium
    additional = long_ms if use_long else 0
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
                "actual": search('actual_child', history + (original,), branch_ms),
                "research": search('research_child', history + (best,), branch_ms)
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
            branch_ms=600000, expected_positions=163, split_seed=20261021,
            force_long_cases=0, neural_options=None, eligible_roots=None):
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
    if force_long_cases < 0 or force_long_cases > max_cases:
        raise ValueError('invalid long-analysis quota')
    params.update(force_long_cases=force_long_cases, neural_options=neural_options,
                  eligible_roots=sorted(eligible_roots) if eligible_roots is not None else None)
    if neural_options and neural_options.get('EvalNeuralFile'):
        params['model_sha256'] = digest(Path(neural_options['EvalNeuralFile']).read_bytes())
    train_roots = (allocate_roots((g.row["game_id"] for g in games), split_seed)["train"]
                   if len(games) >= 3 else {g.row["game_id"] for g in games})
    if eligible_roots is not None:
        train_roots = set(eligible_roots)
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
    for case_index, case in enumerate(case_list):
        if case["case_id"] in done:
            continue
        partial = state.setdefault('partial', {}).setdefault(case['case_id'], {})
        row = analyze(binary, knowledge, case, short_ms, medium_ms, long_ms,
                      branch_ms, expected_positions, checkpoint=partial,
                      persist=lambda: atomic_write(state_path, state),
                      force_long=case_index < force_long_cases, neural_options=neural_options)
        state["results"].append(row)
        state['partial'].pop(case['case_id'], None)
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
