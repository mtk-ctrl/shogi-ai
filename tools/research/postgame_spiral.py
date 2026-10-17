#!/usr/bin/env python3
"""Prepare a bounded, leakage-aware postgame learning proposal.

Uses selected own-engine diagnosis, never opponent scores or winner imitation.
An insufficient-data result is a successful guarded run, not a learned engine.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp, compare_children, OPTIONS as ANALYSIS_OPTIONS
from tools.research.postgame_candidates import accepted_record, replay
from tools.research.postgame_cases import position_command, sha256
from tools.research.postgame_ranker import AXES, BASE, OPTIONS, digest, fit, require, validate_terms, parent_values


def group_rows(rows, seed, registry=None):
    """Union connected games/exact positions/coarse non-pawn piece formations.

    Compute ALL connected components before assigning any split. Overmerged
    groups reduce available data rather than manufacturing independence.
    """
    registry = registry if registry is not None else {}
    require(all(r.get("split") in ("train", "validation", "heldout", "quarantine")
                and isinstance(r.get("group"), str) for r in registry.values()), "invalid split registry")
    parents = list(range(len(rows)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    owners = {}
    for i, row in enumerate(rows):
        keys = ["game:" + row["game"], *row["leakage_keys"]]
        old_groups = ["prior:" + registry[k]["group"] for k in keys if k in registry]
        for token in keys + old_groups:
            if token in owners:
                parents[find(i)] = find(owners[token])
            else:
                owners[token] = i
    members = collections.defaultdict(list)
    for i, row in enumerate(rows):
        members[find(i)].append(row)
    for component in members.values():
        keys = {k for r in component for k in ["game:"+r["game"], *r["leakage_keys"]]}
        old_groups = {registry[k]["group"] for k in keys if k in registry}
        keys |= {k for k, v in registry.items() if v["group"] in old_groups}
        prior_splits = {registry[k]["split"] for k in keys if k in registry}
        consumed = any(registry[k].get("heldout_consumed", False) for k in keys if k in registry)
        group = digest(sorted(keys))
        bucket = int(digest([seed, group])[:8], 16) % 100
        split = (next(iter(prior_splits)) if len(prior_splits) == 1 else "quarantine") if prior_splits else (
            "train" if bucket < 60 else "validation" if bucket < 80 else "heldout")
        if consumed:
            split = "quarantine"
        for row in component:
            row.update(group=group, split=split)
        for key in keys:
            registry[key] = dict(group=group, split=split, heldout_consumed=consumed)
    return rows


def leakage_keys(board):
    pieces = tuple((sq, p.piece_type, p.color) for sq in range(81)
                   if (p := board.piece_at(sq)) and p.piece_type != shogi.PAWN)
    mirror = tuple(sorted((80-sq, kind, 1-color) for sq, kind, color in pieces))
    # Coarse key intentionally ignores pawns, hands and side. It overgroups.
    return ["position:" + digest(" ".join(board.sfen().split()[:3])),
            "formation:" + digest(min(pieces, mirror))]


def actor_terms(terms, sign):
    result = {k: sign*terms[k] for k in (*AXES, "material_term", "total", "clamp")}
    validate_terms(result)
    return result


def check_result(row):
    accepted_record(row, "spiral-evidence")
    case = row["case"]
    require(exact_cp(row["root_short"]) and exact_cp(row["root_deep"]), "inexact root research")
    command = position_command(case["start_sfen"], tuple(case["history_moves"]))
    require(sha256(command.encode()) == case["history_key"], "case history hash mismatch")
    for result in (row["root_short"], row["root_deep"]):
        require(result["history_key"] == case["history_key"] and result["position_command"] == command,
                "root diagnosis lost actual history")
    follow = row["followup"]
    for side, move in (("actual", case["actual_move"]), ("research", row["research_move"])):
        child_command = position_command(case["start_sfen"], tuple(case["history_moves"]) + (move,))
        require(follow[side]["position_command"] == child_command
                and follow[side]["history_key"] == sha256(child_command.encode()), "child history mismatch")
    comparison = compare_children(follow["actual"], follow["research"])
    require(comparison == follow["comparison"], "comparison inconsistent with own exact scores")
    board, _ = replay(case)
    require(shogi.Move.from_usi(case["actual_move"]) in board.legal_moves, "actual move illegal")
    outcome = case["outcome"]
    reward = outcome["terminal_reward_stm"]
    if outcome["status"] == "unresolved":
        require(reward is None, "unresolved game must not teach a draw")
    elif outcome["status"] == "verified_draw":
        require(reward == 0 and outcome["winner"] is None, "draw reward mismatch")
    else:
        require(outcome["status"] == "verified_win_loss" and reward in (-1, 1), "unverified reward")
        expected = 1 if outcome["winner"] == case["actor"] else -1
        require(reward == expected, "actor outcome sign mismatch")
    return board


def parent_effect(moves, research_move):
    require(len(moves) == 2, "two frozen parent probes required")
    if moves[0] != moves[1]:
        return "unstable_parent"
    return "already_correct" if moves[0] == research_move else "current_parent_miss"


def prepare(diagnosis, probe, static, split_seed, registry=None, parent_options=None):
    """probe(case)->two results; static(sfen)->fixed-parent breakdown."""
    require(0 < len(diagnosis) <= 96, "selected-case budget exceeded/empty")
    counts = collections.Counter((str(r["case"]["source"]["run_id"]), r["case"]["source"]["game_id"]) for r in diagnosis)
    require(max(counts.values()) <= 4, "per-game case budget exceeded")
    require(len({r["case"]["case_id"] for r in diagnosis}) == len(diagnosis), "duplicate selected case")
    # Split all selected roots and legal compared children BEFORE inspecting any
    # preference magnitude, terminal reward, current-parent choice or static rank.
    registry = dict(registry or {})
    split_rows = []
    for row in diagnosis:
        case = row["case"]; board, _ = replay(case)
        keys = leakage_keys(board)
        for token in (case["actual_move"], row["research_move"]):
            if token in ("win", "resign"):
                continue
            move = shogi.Move.from_usi(token)
            require(move in board.legal_moves, "illegal selected branch")
            child = shogi.Board(board.sfen()); child.push(move)
            keys.extend(leakage_keys(child))
        split_rows.append(dict(case_id=case["case_id"],
                               game=f'{case["source"]["run_id"]}:{case["source"]["game_id"]}',
                               leakage_keys=sorted(set(keys))))
    group_rows(split_rows, split_seed, registry)
    split_by_case = {r["case_id"]: r for r in split_rows}
    routes, rejected, examples, knowledge, observations = collections.Counter(), collections.Counter(), [], [], []
    for row in diagnosis:
        routes[row["route"]] += 1
        if row["route"] != "stable_research_move_candidate":
            rejected["not_stable_evaluation_pair"] += 1
            continue
        board = check_result(row)
        case = row["case"]
        split_row = split_by_case[case["case_id"]]
        if split_row["split"] == "quarantine":
            rejected["prior_split_collision"] += 1
            continue
        probes = probe(case)
        require(all(exact_cp(p) for p in probes), "incomplete parent probe")
        command = position_command(case["start_sfen"], tuple(case["history_moves"]))
        require(all(p["position_command"] == command for p in probes), "parent probe history mismatch")
        reason = parent_effect([p["bestmove"] for p in probes], row["research_move"])
        observations.append(dict(case_id=case["case_id"], parent_moves=[p["bestmove"] for p in probes],
                                 research_move=row["research_move"], effect=reason))
        if reason != "current_parent_miss":
            rejected[reason] += 1
            continue
        # Even stable research is provisional. New knowledge is a research asset.
        if split_row["split"] == "train":
            knowledge.append(dict(case_id=case["case_id"], research_move=row["research_move"],
                                  status="requires_targeted_preflight_and_live_use_audit"))
        else:
            rejected["knowledge_excluded_validation_or_heldout"] += 1
        sign = 1 if board.turn == shogi.BLACK else -1
        root = static(board.sfen())
        keys = leakage_keys(board)
        children = {}
        for kind, token in (("actual", case["actual_move"]), ("research", row["research_move"])):
            child = shogi.Board(board.sfen())
            child.push_usi(token)
            children[kind] = static(child.sfen())
            keys.extend(leakage_keys(child))
        try:
            terms = {k: actor_terms(v, sign) for k, v in dict(root=root, **children).items()}
        except ValueError:
            rejected["clamped_static_terms"] += 1
            continue
        if terms["research"]["total"] > terms["actual"]["total"]:
            rejected["no_static_rank_error_search_problem"] += 1
            continue
        examples.append(dict(split_row, reward=case["outcome"]["terminal_reward_stm"], **terms))
    learning = fit(examples, parent_options)
    if learning["status"] != "needs_data":
        exposed = {r["group"] for r in examples if r["split"] == "heldout"}
        for record in registry.values():
            if record["group"] in exposed:
                record["heldout_consumed"] = True
    return dict(schema="postgame-spiral-preparation-v1", routes=dict(routes), rejected=dict(rejected),
                parent_probes=observations, examples=examples, learning=learning,
                split_registry=registry,
                candidate_knowledge=knowledge, formal_adoption=False,
                next_action="collect_independent_current_parent_errors" if learning["status"] != "requires_engine_validation"
                    else "validate_live_engine_on_frozen_unused_cases")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--diagnosis", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--knowledge", type=Path, required=True)
    p.add_argument("--parent-ref", required=True)
    p.add_argument("--generation", type=int, default=1)
    p.add_argument("--split-registry", type=Path, help="Previous generation split_registry JSON; never reset heldout to training")
    p.add_argument("--parent-options", type=Path, help="Complete nine-axis options of the actual research parent")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    require(re.fullmatch("[0-9a-f]{40}", args.parent_ref), "fixed parent commit required")
    require(not args.output.exists(), "preserve prior research output")
    require(args.generation >= 1 and (args.generation == 1 or args.split_registry is not None),
            "later generation requires the preserved split registry")
    summary = json.loads(args.summary.read_bytes())
    require(summary["options"] == ANALYSIS_OPTIONS, "diagnosis settings differ")
    binary_hash, knowledge_hash = sha256(args.binary.read_bytes()), sha256(args.knowledge.read_bytes())
    require(summary["analyzer_binary_sha256"] == binary_hash, "analyzer binary mismatch")
    require(summary["knowledge_sha256"] == knowledge_hash, "adopted knowledge mismatch")
    parent_options = json.loads(args.parent_options.read_bytes()) if args.parent_options else dict(zip(OPTIONS, BASE))
    parent_values(parent_options)
    require(summary.get("evaluation_options", dict(zip(OPTIONS, BASE))) == parent_options,
            "diagnosis uses different parent evaluation parameters")
    def configured_engine():
        engine = Analyzer(args.binary, args.knowledge)
        for key, value in parent_options.items():
            engine.send(f"setoption name {key} value {value}")
        engine.send("isready"); engine.until("readyok", 15)
        return engine
    def probe(case):
        results = []
        for _ in range(2):
            engine = configured_engine()
            try:
                # Standalone recurrence diagnostic: 200ms, no opponent to ponder.
                # Full-game long-think/Ponder remain required at match validation.
                results.append(engine.search(case["start_sfen"], tuple(case["history_moves"]), 200))
            finally:
                engine.close()
        return results
    engine = configured_engine()
    try:
        registry = json.loads(args.split_registry.read_bytes()) if args.split_registry else {}
        report = prepare(json.loads(args.diagnosis.read_bytes()), probe, engine.static,
                         "spiral-core-20261017-v1", registry, parent_options)
    finally:
        engine.close()
    report["provenance"] = dict(parent_ref=args.parent_ref, binary_sha256=binary_hash,
                                 knowledge_sha256=knowledge_hash,
                                 diagnosis_sha256=sha256(args.diagnosis.read_bytes()),
                                 parent_parameters_sha256=digest(parent_options),
                                 summary_sha256=sha256(args.summary.read_bytes()),
                                 parent_probe="200ms standalone no longthink/ponder, twice; not formal match")
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("examples", "split_registry")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
