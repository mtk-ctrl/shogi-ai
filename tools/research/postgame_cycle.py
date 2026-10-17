#!/usr/bin/env python3
"""Bounded research cycle state machine; has no dispatch/adoption credentials.

The caller is a verified execution adapter. Evidence files must be bound to
the pending input hash and stored/retrieved before accepting a stage result.
This module never treats a launcher response as a finished experiment.
"""
from __future__ import annotations

import copy
import argparse
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.research.postgame_ranker import digest, require


def fixed_parent(parent):
    require(re.fullmatch("[0-9a-f]{40}", parent.get("engine_ref", "")), "parent engine must be fixed")
    for key in ("knowledge_sha256", "parameters_sha256"):
        require(re.fullmatch("[0-9a-f]{64}", parent.get(key, "")), "missing fixed " + key)


def start(plan):
    fixed_parent(plan["parent"])
    require(type(plan["max_generations"]) is int and 1 <= plan["max_generations"] <= 5, "generation cap required")
    require(type(plan["max_new_games"]) is int and 0 <= plan["max_new_games"] <= 3000, "explicit game budget required")
    require(len(plan["seeds"]) == plan["max_generations"], "freeze seeds for every generation")
    seeds = [s[k] for s in plan["seeds"] for k in ("screen", "confirm", "source")]
    require(all(type(x) is int and 0 < x < 2**31-2000000 for x in seeds), "invalid seed")
    require(len(set(seeds)) == len(seeds), "reuse of a split/confirmation seed")
    require(plan["candidate_kind"] in ("evaluation", "knowledge", "combined"), "unknown candidate kind")
    source_games = plan.get("source_games", 100)
    require(type(source_games) is int and 1 <= source_games <= 100, "bounded source size required")
    if source_games != 100:
        require(plan.get("purpose") == "integration_smoke", "small source size is an explicit integration test")
    return dict(schema="postgame-cycle-v1", plan=copy.deepcopy(plan), plan_sha256=digest(plan),
                parent=copy.deepcopy(plan["parent"]), generation=1, revision=0,
                stage="initial_source" if plan.get("generate_initial_source") is True else "prepare",
                used_games=0, pending=None, history=[], formal_adoption=False,
                result=None, external_execution_adapter="required")


def request(state, inputs, expected_revision):
    require(state["revision"] == expected_revision, "stale cycle revision")
    require(state["stage"] != "complete", "cycle already stopped")
    require(state["plan_sha256"] == digest(state["plan"]), "frozen policy was edited")
    require(inputs.get("parent") == state["parent"], "execution parent differs from research parent")
    stage = state["stage"]
    if stage == "prepare" and state["generation"] > 1:
        require(inputs.get("split_registry_sha256") == state["split_registry_sha256"],
                "next generation must preserve split/exposure registry")
        require(inputs.get("example_bank_sha256") == state.get("example_bank_sha256"),
                "next generation must preserve the eligible example bank")
    games = {"screen": 100, "confirm": 200, "collect_source": state["plan"].get("source_games", 100),
             "initial_source": state["plan"].get("source_games", 100)}.get(stage, 0)
    if stage in ("preflight", "screen", "confirm"):
        fixed_parent(inputs["candidate"])
        require(inputs["candidate"] != state["parent"], "candidate is identical to parent")
        require(inputs["candidate"]["parameters_sha256"] == state["expected_parameters_sha256"],
                "candidate differs from the fixed learning proposal")
        if state["plan"]["candidate_kind"] == "knowledge":
            require(all(inputs["candidate"][k] == state["parent"][k]
                        for k in ("engine_ref", "parameters_sha256")), "knowledge-only candidate changed engine/evaluation")
        elif state["plan"]["candidate_kind"] == "evaluation":
            require(inputs["candidate"]["knowledge_sha256"] == state["parent"]["knowledge_sha256"],
                    "evaluation-only candidate changed knowledge")
    if stage in ("screen", "confirm"):
        require(inputs["candidate"] == state["candidate"], "candidate changed after preflight")
    require(state["used_games"] + games <= state["plan"]["max_new_games"], "game budget exhausted")
    seed_key = "source" if stage in ("initial_source", "collect_source") else stage
    # A post-generation source belongs to the NEXT generation. Reusing the
    # initial source seed here would silently repeat the same experimental seed.
    seed_index = state["generation"] if stage == "collect_source" else state["generation"]-1
    require(seed_index < len(state["plan"]["seeds"]), "generation budget exhausted")
    seed = state["plan"]["seeds"][seed_index].get(seed_key)
    payload = dict(cycle=state["plan"]["cycle_id"], generation=state["generation"], stage=stage,
                   policy=state["plan_sha256"], inputs=copy.deepcopy(inputs), games=games, seed=seed)
    operation = digest(payload)
    if state["pending"]:
        require(state["pending"]["operation_id"] == operation, "different request already pending")
        return copy.deepcopy(state)  # A retry returns the same intent, not another run.
    out = copy.deepcopy(state)
    out["pending"] = dict(operation_id=operation, input_sha256=digest(inputs),
                          payload=payload, launcher_run=None, body_run=None, started_lanes=0)
    out["revision"] += 1
    return out


def observe_start(state, operation, launcher_run, body_run, started_lanes):
    p = state["pending"]
    require(p and p["operation_id"] == operation, "unknown operation start")
    require(all(type(x) is int and x > 0 for x in (launcher_run, body_run, started_lanes)),
            "launcher success and real body start required")
    require(p["body_run"] in (None, body_run), "duplicate/changed body run")
    out = copy.deepcopy(state)
    out["pending"].update(launcher_run=launcher_run, body_run=body_run, started_lanes=started_lanes)
    out["revision"] += 1
    return out


def score_interval(wins, losses, draws):
    require(all(type(n) is int and n >= 0 for n in (wins, losses, draws)), "invalid outcome counts")
    n = wins + losses + draws
    require(n > 0, "empty match")
    p = (wins + .5*draws)/n
    radius = 1.96*math.sqrt(p*(1-p)/n)
    return p, max(0., p-radius), min(1., p+radius)


def audited_match(evidence, games):
    result, audit = evidence["result"], evidence["audit"]
    require(sum(result[k] for k in ("wins", "losses", "draws")) == games, "match game count mismatch")
    for key in ("all_moves_legal", "all_terminations_verified", "conditions_verified", "binary_verified",
                "knowledge_snapshot_verified", "duplicates_checked"):
        require(audit.get(key) is True, "missing audit: " + key)
    require(audit.get("games") == games, "audit covers different game count")
    actual = score_interval(result["wins"], result["losses"], result["draws"])
    unique = audit["prior_and_internal_duplicates_excluded"]
    unique_n = sum(unique[k] for k in ("wins", "losses", "draws"))
    require(0 <= unique_n <= games and all(unique[k] <= result[k] for k in ("wins", "losses", "draws")),
            "invalid duplicate exclusion counts")
    return actual, score_interval(unique["wins"], unique["losses"], unique["draws"]) if unique_n else None


def finish(state, operation, evidence):
    require(state["plan_sha256"] == digest(state["plan"]), "frozen policy was edited")
    receipt_hash = digest(evidence)
    prior = [r for r in state["history"] if r["operation_id"] == operation]
    if prior:
        require(prior[0]["evidence_sha256"] == receipt_hash, "same operation has conflicting result")
        return copy.deepcopy(state)
    p = state["pending"]
    require(p and p["operation_id"] == operation, "no matching pending operation")
    require(digest(p["payload"]) == operation, "pending intent was edited")
    require(evidence["input_sha256"] == p["input_sha256"], "receipt is for different inputs")
    require(evidence["parent"] == state["parent"], "receipt parent changed")
    saved = evidence["publication"]
    require(saved.get("readback_verified") is True and saved.get("api_digest_verified") is True,
            "result is not durably saved/retrieved")
    require(type(saved.get("bytes")) is int and saved["bytes"] > 0
            and re.fullmatch("[0-9a-f]{64}", saved.get("sha256", "")), "invalid publication receipt")
    stage = state["stage"]
    games = p["payload"]["games"]
    if games:
        require(p["body_run"] and p["started_lanes"] > 0, "launcher alone is not real match start")
        require(evidence["body_run"] == p["body_run"], "receipt run does not match actual started run")
        require(evidence["seed"] == p["payload"]["seed"], "match seed differs from frozen seed")
    out = copy.deepcopy(state)
    out["used_games"] += games
    if stage == "prepare":
        report = evidence["preparation"]
        ready_eval = report["learning"]["status"] == "requires_engine_validation"
        ready_knowledge = bool(report["candidate_knowledge"])
        kind = state["plan"]["candidate_kind"]
        out["split_registry_sha256"] = digest(report["split_registry"])
        out["example_bank_sha256"] = digest(report.get("example_bank", {}))
        out["expected_parameters_sha256"] = (digest(report["learning"]["options"])
                                              if ready_eval and kind != "knowledge"
                                              else state["parent"]["parameters_sha256"])
        ready = ready_eval if kind == "evaluation" else ready_knowledge if kind == "knowledge" else ready_eval and ready_knowledge
        out["stage"] = "preflight" if ready else "collect_source"
        out["result"] = None if ready else "needs_independent_current_parent_errors"
    elif stage == "preflight":
        require(evidence["candidate"] == p["payload"]["inputs"]["candidate"], "preflight candidate mismatch")
        check = evidence["preflight"]
        require(type(check.get("disabled_exact")) is bool and type(check.get("regressions")) is int
                and check["regressions"] >= 0, "incomplete equality/regression measurements")
        require(type(check.get("depth_ratio")) in (int, float) and math.isfinite(check["depth_ratio"])
                and check["depth_ratio"] >= 0, "invalid speed measurement")
        passed = check["disabled_exact"] and check["regressions"] == 0 and check["depth_ratio"] >= .9
        if state["plan"]["candidate_kind"] != "knowledge":
            require(type(check.get("heldout_improved")) is int and check["heldout_improved"] >= 0,
                    "missing real-engine unused-case measurement")
            passed &= check["heldout_improved"] > 0
        if state["plan"]["candidate_kind"] != "evaluation":
            require(type(check.get("targeted_corrections")) is int and check["targeted_corrections"] >= 0
                    and type(check.get("candidate_knowledge_hits")) is int and check["candidate_knowledge_hits"] >= 0,
                    "missing targeted knowledge measurement")
            passed &= check["targeted_corrections"] > 0 and check["candidate_knowledge_hits"] > 0
        # A measured candidate rejection is a normal cycle outcome. Missing or
        # unexecuted measurements still fail closed instead of masquerading as one.
        require(passed or check.get("completed") is True, "preflight gates failed without completed measurement")
        if passed:
            out["candidate"] = evidence["candidate"]
            out["stage"] = "screen"
        else:
            out.update(stage="collect_source", result="retain_parent_preflight_rejected")
    elif stage in ("screen", "confirm"):
        require(evidence["candidate"] == state["candidate"], "candidate changed in comparison")
        raw, unique = audited_match(evidence, games)
        uses = evidence["audit"]["candidate_knowledge_uses"]
        require(type(uses) is int and uses >= 0, "missing actual candidate knowledge use")
        knowledge_effect = state["plan"]["candidate_kind"] != "knowledge" or uses > 0
        if stage == "screen" and raw[0] >= .5 and knowledge_effect:
            out["stage"] = "confirm"
        else:
            passed = stage == "confirm" and raw[1] > .5 and unique is not None and unique[1] > .5 and knowledge_effect
            if passed:
                out["parent"] = copy.deepcopy(state["candidate"])  # Research parent ONLY.
            out["result"] = "research_child_validated" if passed else "retain_parent"
            out["stage"] = "collect_source"
    elif stage in ("initial_source", "collect_source"):
        audited_match(evidence, games)
        if stage == "collect_source":
            require(state["generation"] < state["plan"]["max_generations"], "generation budget exhausted")
            out["generation"] += 1
        out["stage"] = "prepare"
        out.pop("candidate", None)
    else:
        raise ValueError("unknown stage")
    if out["stage"] == "collect_source" and (out["generation"] >= state["plan"]["max_generations"]
            or out["used_games"] + state["plan"].get("source_games", 100) > state["plan"]["max_new_games"]):
        out["stage"] = "complete"
    next_cost = {"screen": 100, "confirm": 200}.get(out["stage"], 0)
    if out["used_games"] + next_cost > state["plan"]["max_new_games"]:
        out.update(stage="complete", result="retain_parent_budget_exhausted")
    out["history"].append(dict(operation_id=operation, stage=stage, evidence_sha256=receipt_hash,
                                publication=saved, body_run=p["body_run"]))
    out["pending"] = None
    out["revision"] += 1
    return out


def eta(lanes, now, postprocess_seconds):
    """One ETA for the slowest actual lane + aggregation/save/audit allowance."""
    require(now.tzinfo is not None, "timezone-aware observation required")
    require(type(postprocess_seconds) in (int, float) and math.isfinite(postprocess_seconds)
            and postprocess_seconds >= 0, "invalid postprocessing estimate")
    if not lanes or any(not lane["started"] for lane in lanes):
        return dict(kind="start_checkpoint_required", finish_at=None, recurring=False)
    samples = []
    for lane in lanes:
        done, total = lane["completed"], lane["games"]
        require(type(done) is int and type(total) is int and 0 <= done <= total and total > 0,
                "invalid lane counts")
        seconds = lane["completed_game_seconds"]
        require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
                "invalid measured duration")
        if done:
            require(seconds > 0, "completed games need real duration")
            samples.append(seconds/done)
    if not samples:
        return dict(kind="measurement_required", finish_at=None, recurring=False)
    fallback = statistics.median(samples)
    seconds = max((lane["games"]-lane["completed"])*
                  (lane["completed_game_seconds"]/lane["completed"] if lane["completed"] else fallback)
                  for lane in lanes)
    finish_at = now + timedelta(seconds=seconds*1.2 + postprocess_seconds)
    return dict(kind="one_time_eta", finish_at=finish_at.isoformat(), recurring=False,
                slowest_lane_remaining_seconds=seconds, postprocess_seconds=postprocess_seconds)


def save_state(path, state, expected_sha256):
    """Local CAS + exclusive writer lock. A stale lock requires investigation."""
    path = Path(path)
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("x"):
        try:
            current = path.read_bytes() if path.exists() else None
            actual = __import__("hashlib").sha256(current).hexdigest() if current is not None else None
            require(actual == expected_sha256, "state changed since read")
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("x", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.write("\n"); f.flush(); os.fsync(f.fileno())
            temporary.replace(path)
        finally:
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "request", "started", "finish", "eta"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--input", type=Path, required=True, help="Frozen plan, inputs, start observation, receipt or lane progress JSON")
    parser.add_argument("--expected-state-sha256", help="CAS hash from the last read; required for every state update")
    args = parser.parse_args()
    payload = json.loads(args.input.read_bytes())
    if args.command == "eta":
        from datetime import datetime
        result = eta(payload["lanes"], datetime.fromisoformat(payload["observed_at"]), payload["postprocess_seconds"])
    else:
        require(args.state is not None, "state path required")
        if args.command == "init":
            require(not args.state.exists() and args.expected_state_sha256 is None, "initial state already exists")
            result = start(payload)
        else:
            require(re.fullmatch("[0-9a-f]{64}", args.expected_state_sha256 or ""), "expected state hash required")
            raw = args.state.read_bytes()
            require(__import__("hashlib").sha256(raw).hexdigest() == args.expected_state_sha256, "state changed since read")
            state = json.loads(raw)
            if args.command == "request":
                result = request(state, payload, state["revision"])
            elif args.command == "started":
                result = observe_start(state, payload["operation_id"], payload["launcher_run"],
                                       payload["body_run"], payload["started_lanes"])
            else:
                result = finish(state, payload["operation_id"], payload["evidence"])
        save_state(args.state, result, args.expected_state_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
