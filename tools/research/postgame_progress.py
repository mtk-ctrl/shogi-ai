#!/usr/bin/env python3
"""Measure research yield and stop unchanged selfplay at a frozen plateau.

This does not manufacture teachers, execute queued research or adopt knowledge.
Work items refer only to training groups and retain the actual position history.
"""
from __future__ import annotations

from collections import Counter
import copy
import math

from tools.research.postgame_ranker import POLICY, digest, require
from tools.research.postgame_cases import position_command, sha256

POLICY_PROGRESS = dict(schema="postgame-progress-policy-v1", max_stagnant_preparations=2)
ROUTES = {"hold", "mixed_or_unstable", "search_horizon_candidate",
          "knowledge_reference_candidate", "stable_research_move_candidate"}


def diagnosis_detail(row):
    """Describe observed exclusions without claiming a move was a mistake."""
    short, deep = row["root_short"], row["root_deep"]
    if deep.get("kind") == "mate":
        return "mate_requires_separate_verification"
    if deep.get("status") != "recorded":
        return "deep_observation_missing"
    if short.get("status") != "recorded":
        return "short_observation_missing"
    if row["research_move"] == row["case"]["actual_move"]:
        return ("actual_move_supported" if short.get("bestmove") == row["research_move"]
                else "actual_move_supported_with_search_disagreement")
    pair = row.get("followup") or row.get("child_pairs", {}).get("500")
    if not pair:
        return "no_child_comparison"
    comparison = pair["comparison"]
    if comparison["status"] != "comparable":
        return "child_" + comparison["status"]
    if comparison["improvement_cp"] < 150:
        return "improvement_below_150cp"
    return {"search_horizon_candidate":"long_search_only_preference",
            "mixed_or_unstable":"root_search_disagreement"}.get(row["route"], "stable_preference_needs_parent_check")


def validate_policy(policy):
    require(set(policy) == set(POLICY_PROGRESS) and policy["schema"] == POLICY_PROGRESS["schema"],
            "unknown progress policy")
    require(type(policy["max_stagnant_preparations"]) is int
            and 1 <= policy["max_stagnant_preparations"] <= 5, "bounded stagnation threshold required")


def statistics(preparation, analysis):
    decisions = preparation["case_decisions"]
    require(isinstance(decisions, list) and len(decisions) <= 96, "invalid decision ledger")
    require(len({r["case_id"] for r in decisions}) == len(decisions), "duplicate decision")
    routes = dict(Counter(r["route"] for r in decisions))
    require(set(routes) <= ROUTES and routes == preparation["routes"], "decision routes differ")
    require(analysis["selected_cases"] == len(decisions) and analysis["routes"] == routes,
            "analysis selected cases/routes differ")
    for key in ("source_games", "source_plies", "verification_pairs"):
        require(type(analysis[key]) is int and analysis[key] >= 0, "missing observed " + key)
    require(type(analysis["seconds"]) in (int, float) and math.isfinite(analysis["seconds"])
            and analysis["seconds"] >= 0, "invalid measured analysis time")
    require(analysis["source_games"] > 0 and analysis["source_plies"] > 0, "empty source observation")
    require(analysis["verification_pairs"] <= len(decisions), "invalid fixed-depth pair count")
    new_ids = {r["case_id"] for r in decisions if r["reason"] == "evaluation_eligible"}
    examples = preparation["examples"]
    require(new_ids <= {r["case_id"] for r in examples}, "eligible decision absent from bank")
    require(len(examples) == len(new_ids) + preparation["bank_pairs_reused"], "new/reused pair counts differ")
    groups = {s: len({r["group"] for r in examples if r["split"] == s})
              for s in ("train", "validation", "heldout")}
    require(groups == preparation["learning"]["split_groups"], "independent group counts differ")
    deficits = dict(pairs=max(0, POLICY["min_pairs"] - len(examples)),
                    **{s: max(0, minimum - groups[s]) for s, minimum in zip(groups, POLICY["min_groups"])})
    return dict(source_games=analysis["source_games"], source_plies=analysis["source_plies"],
                analysis_seconds=analysis["seconds"], selected_cases=len(decisions),
                diagnosis_routes=routes, fixed_depth_pairs=analysis["verification_pairs"],
                research_matches_actual=sum(d["research_matches_actual"] for d in decisions),
                decision_reasons=dict(Counter(r["reason"] for r in decisions)),
                selection_details=dict(Counter(r["detail"] for r in decisions)),
                new_evaluation_pairs=len(new_ids), reused_evaluation_pairs=preparation["bank_pairs_reused"],
                evaluation_bank_pairs=len(examples), independent_groups=groups, deficits=deficits,
                observed_selected_yield=(len(new_ids)/len(decisions) if decisions else None),
                limitation="Selected-case observation, not an independent probability or a forecast of games to learning.")


def describe(preparation, analysis, diagnosis, parent):
    """Build bounded research requests; selecting a task is not executing it."""
    stats = statistics(preparation, analysis)
    rows = {r["case"]["case_id"]: r for r in diagnosis}
    require(len(rows) == len(diagnosis) == stats["selected_cases"], "diagnosis/decision count mismatch")
    knowledge = {r["case_id"] for r in preparation["candidate_knowledge"]}
    tasks = []
    for d in preparation["case_decisions"]:
        row = rows[d["case_id"]]; case = row["case"]
        require(d["route"] == row["route"] and d["source"] == case["source"]
                and d["research_matches_actual"] == (row["research_move"] == case["actual_move"]),
                "decision source differs")
        # A validation/test/quarantined case may not become next-generation
        # training knowledge or a targeted practice task through this queue.
        if d["split"] != "train":
            continue
        reason = d["reason"]
        kind = None
        if d["case_id"] in knowledge:
            kind = "validate_research_knowledge"
        elif reason == "needs_fixed_depth_verification":
            kind = "verify_same_depth"
        elif reason == "unstable_parent":
            kind = "resolve_parent_instability"
        elif reason == "clamped_static_terms":
            kind = "inspect_evaluation_representation"
        elif d["route"] in ("hold", "mixed_or_unstable", "search_horizon_candidate"):
            kind = {"mate_requires_separate_verification":"verify_mate_research",
                    "short_observation_missing":"repeat_missing_observation",
                    "deep_observation_missing":"repeat_missing_observation",
                    "actual_move_supported_with_search_disagreement":"review_search_stability",
                    "improvement_below_150cp":None}.get(d["detail"], "extend_own_analysis")
        if kind is None:
            continue
        command = position_command(case["start_sfen"], tuple(case["history_moves"]))
        require(sha256(command.encode()) == case["history_key"], "research task lost actual history")
        identity = dict(parent=parent, position_key=case["position_key"], history_key=case["history_key"],
                        kind=kind, research_move=row["research_move"])
        priority = {"validate_research_knowledge":0,"verify_same_depth":1,"verify_mate_research":1,
                    "repeat_missing_observation":2,"review_search_stability":3}.get(kind,4)
        tasks.append(dict(task_id=digest(identity), kind=kind, priority=priority, status="requires_bounded_research_plan",
                          executor_connected=False, formal_adoption=False, parent=copy.deepcopy(parent),
                          split="train", reason=reason, case=copy.deepcopy(case), research_move=row["research_move"],
                          evidence=dict(file="analysis/diagnosis.json", case_id=d["case_id"], row_sha256=digest(row))))
    unique = {t["task_id"]: t for t in tasks}
    tasks = sorted(unique.values(), key=lambda t:(t["priority"],t["task_id"]))
    return dict(schema="postgame-progress-v1", preparation_sha256=digest(preparation),
                analysis=copy.deepcopy(analysis), statistics=stats, work_items=tasks,
                task_counts=dict(Counter(t["kind"] for t in tasks)), formal_adoption=False,
                strength_improvement_demonstrated=False)


def record(state, preparation):
    """Append measured progress and decide whether unchanged collection may run.

    Improvement here means reduced DATA deficits, never demonstrated strength.
    The unchanged comparison/confirmation gates decide research-parent updates.
    """
    policy = state["plan"]["progress_policy"]; validate_policy(policy)
    feedback = preparation["progress"]
    bare = {k: v for k, v in preparation.items() if k != "progress"}
    require(feedback["preparation_sha256"] == digest(bare), "progress refers to different preparation")
    stats = statistics(bare, feedback["analysis"])
    require(stats == feedback["statistics"], "progress measurements differ")
    tasks = feedback["work_items"]
    require(len({t["task_id"] for t in tasks}) == len(tasks), "duplicate research task")
    require(dict(Counter(t["kind"] for t in tasks)) == feedback["task_counts"], "task counts differ")
    require(all(t["split"] == "train" and t["parent"] == state["parent"]
                and t["executor_connected"] is False and t["formal_adoption"] is False for t in tasks),
            "research queue leaked test data or adoption")
    decisions = {d["case_id"]: d for d in preparation["case_decisions"]}
    for task in tasks:
        case = task["case"]; decision = decisions.get(case["case_id"])
        require(decision is not None and decision["split"] == "train"
                and decision["source"] == case["source"], "task is not from the training decision ledger")
        command = position_command(case["start_sfen"], tuple(case["history_moves"]))
        identity = dict(parent=task["parent"], position_key=case["position_key"], history_key=case["history_key"],
                        kind=task["kind"], research_move=task["research_move"])
        require(task["task_id"] == digest(identity) and sha256(command.encode()) == case["history_key"],
                "research task input was changed")
    history = copy.deepcopy(state.get("progress_history", []))
    old = [r for r in history if r["parent"] == state["parent"]]
    previous = old[-1] if old else None
    before = previous["statistics"]["deficits"] if previous else dict(
        pairs=POLICY["min_pairs"], **dict(zip(("train", "validation", "heldout"), POLICY["min_groups"])))
    material_progress = any(stats["deficits"][k] < before[k] for k in before)
    stagnant = 0 if material_progress else (previous["stagnant_preparations"] if previous else 0) + 1
    item = dict(cycle_id=state["plan"]["cycle_id"], generation=state["generation"], parent=copy.deepcopy(state["parent"]), statistics=stats,
                stagnant_preparations=stagnant, data_deficits_reduced=material_progress,
                task_counts=feedback["task_counts"], preparation_sha256=feedback["preparation_sha256"])
    history.append(item)
    carried = copy.deepcopy(state.get("research_followup", {}).get("work_items", []))
    for task in carried:
        if task["parent"] != state["parent"]:
            task["status"] = "requires_parent_reanalysis"
    all_tasks = {t["task_id"]: t for t in carried + copy.deepcopy(tasks)}
    require(len(all_tasks) <= 512, "research queue capacity needs review; do not truncate")
    knowledge_pending = feedback["task_counts"].get("validate_research_knowledge", 0) > 0
    halt = knowledge_pending or stagnant >= policy["max_stagnant_preparations"]
    action = ("validate_research_knowledge" if knowledge_pending else
              "review_data_yield_and_queued_research" if halt else "collect_within_frozen_budget")
    return dict(history=history, halt_collection=halt, next_action=action,
                reason="knowledge_executor_not_connected" if knowledge_pending else
                       "data_deficits_stagnant" if halt else None,
                work_items=sorted(all_tasks.values(), key=lambda t:(t["priority"],t["task_id"])), formal_adoption=False)
