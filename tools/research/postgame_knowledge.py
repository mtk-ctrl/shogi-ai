#!/usr/bin/env python3
"""Research-only knowledge preparation, live checks and A/B file staging.

Uses the existing TSV loader, Analyzer and arena. Never edits the adopted
snapshot, dispatches matches or treats a wiring fixture as strength evidence.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp, OPTIONS as ANALYSIS_OPTIONS
from tools.research.postgame_candidates import accepted_record
from tools.research.postgame_cases import sha256, position_command
from tools.research.postgame_spiral import check_result, parent_effect
from tools.research.postgame_progress import describe
from tools.research.postgame_ranker import digest, parent_values, require, OPTIONS as OPTIONS_NAMES
from tools.research.postgame_eval_preflight import tactical_cases
from tools.research.postgame_bridge import FORMAL_DEFAULTS

POLICY_KNOWLEDGE = dict(schema="postgame-knowledge-policy-v1", max_tasks=8, parent_probe_ms=200,
                        parent_repeats=2, fixed_depth=2, fixed_timeout_ms=5000,
                        tactical_controls=12, min_depth_ratio=.9)


def snapshot_rows(data):
    text = data.decode("utf-8")
    require(text.startswith("# position-knowledge-v1-active\n"), "unknown base snapshot")
    rows = [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]
    require(rows and len({r[0] for r in rows}) == len(rows), "empty/duplicate base positions")
    return rows


def verified_tasks(preparation, diagnosis, parent):
    require(preparation["example_bank"]["parent_context"] == parent, "knowledge belongs to another research parent")
    progress = preparation["progress"]
    params=preparation['learning']['parent_options'];parent_values(params)
    require(digest(params) == parent['parameters_sha256']
            and progress['analysis']['evaluation_options'] == params
            and progress['analysis']['options'] == ANALYSIS_OPTIONS,
            'research evaluation/search options differ from the fixed parent')
    bare = {k:v for k,v in preparation.items() if k != "progress"}
    require(progress == describe(bare, progress["analysis"], diagnosis, parent),
            "research queue differs from original diagnosis/decision ledger")
    tasks = [t for t in progress["work_items"] if t["kind"] == "validate_research_knowledge"]
    require(len(tasks) <= POLICY_KNOWLEDGE["max_tasks"], "knowledge task budget requires review; do not truncate")
    rows = {r["case"]["case_id"]:r for r in diagnosis}
    for task in tasks:
        row = rows[task["case"]["case_id"]]
        require(task["split"] == "train" and task["parent"] == parent and task["case"] == row["case"],
                "knowledge task changed split/parent/history")
        require(task["evidence"]["row_sha256"] == digest(row), "research evidence hash differs")
        check_result(row)
        require(row['root_short'].get('requested_ms') == 50 and row['root_deep'].get('requested_ms') == 500,
                'research timing differs from the verified 50/500ms protocol')
        # The existing research_decision TSV stores an arrival prefix from
        # startpos. Reject unsupported inputs instead of creating an unloadable
        # file or silently dropping its history.
        require(task["case"]["start_sfen"] == shogi.STARTING_SFEN,
                "direct knowledge needs the existing loader's standard-start history")
    return [(t, rows[t["case"]["case_id"]]) for t in sorted(tasks,key=lambda t:t["task_id"])]


def propose(base, preparation, diagnosis, parent, cycle_id, probe, purpose="research"):
    require(purpose in ("research","integration_smoke"), "unknown knowledge purpose")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}",cycle_id), "unsafe research identifier")
    require(sha256(base) == parent["knowledge_sha256"], "base knowledge differs from fixed parent")
    rows = snapshot_rows(base); keys = {r[0] for r in rows}; ids = {r[11] for r in rows if len(r)>11}
    tasks = verified_tasks(preparation,diagnosis,parent)
    targets={}
    for _,row in tasks:targets.setdefault(row['case']['position_key'],set()).add(row['research_move'])
    accepted=[]; rejected=[]; additions=[]
    for task,row in tasks:
        case=row["case"]
        require(purpose == "integration_smoke" or case.get("evidence_purpose") != "synthetic_fixture",
                "synthetic wiring fixture cannot become research knowledge")
        if len(targets[case['position_key']]) > 1:
            rejected.append(dict(case_id=case['case_id'],reason='conflicting_research_moves'));continue
        if case["position_key"] in keys:
            rejected.append(dict(case_id=case["case_id"],reason="base_position_preserved"));continue
        observations=[probe(case) for _ in range(POLICY_KNOWLEDGE["parent_repeats"])]
        command=position_command(case["start_sfen"],tuple(case["history_moves"]))
        require(all(exact_cp(p) and p["position_command"] == command and p["history_key"] == case["history_key"]
                    for p in observations), "current-parent observation incomplete/history differs")
        effect=parent_effect([p["bestmove"] for p in observations],row["research_move"])
        # If today's parent chooses a third move, the saved comparison of the
        # OLD actual move vs research does not establish an improvement over it.
        if effect == "current_parent_miss" and observations[0]["bestmove"] != case["actual_move"]:
            effect="parent_changed_to_uncompared_move"
        if effect != "current_parent_miss":
            rejected.append(dict(case_id=case["case_id"],reason=effect,parent_observations=observations));continue
        line,evidence=accepted_record(row,cycle_id)
        require(evidence["research_id"] not in ids, "research ID collision")
        ids.add(evidence["research_id"]); keys.add(case["position_key"])
        additions.append(line)
        accepted.append(dict(evidence,task_id=task["task_id"],parent_observations=observations,
                             case=copy.deepcopy(case),research_row_sha256=digest(row)))
    candidate = (base + (b"" if base.endswith(b"\n") else b"\n")
                 + ("# unadopted research additions; formal_adoption=false\n"+"\n".join(additions)+"\n").encode()) if additions else None
    manifest=dict(schema="postgame-knowledge-proposal-v1",purpose=purpose,cycle_id=cycle_id,parent=copy.deepcopy(parent),
                  policy=POLICY_KNOWLEDGE,preparation_sha256=digest(preparation),diagnosis_sha256=digest(diagnosis),
                  base_sha256=sha256(base),base_positions=len(rows),candidate_positions=len(accepted),
                  combined_positions=len(rows)+len(accepted),candidate_sha256=sha256(candidate) if candidate else None,
                  accepted=accepted,rejected=rejected,status="requires_live_preflight" if candidate else "no_effective_candidate",
                  formal_adoption=False,strength_improvement_demonstrated=False,
                  production_match_eligible=purpose == "research")
    return candidate,manifest


def validate_snapshot(base, candidate, manifest):
    require(manifest["formal_adoption"] is False and manifest["policy"] == POLICY_KNOWLEDGE,
            "knowledge policy/adoption boundary differs")
    require(sha256(base) == manifest["base_sha256"] == manifest["parent"]["knowledge_sha256"], "base bytes changed")
    require(sha256(candidate) == manifest["candidate_sha256"] and candidate.startswith(base), "candidate bytes/base preservation differs")
    a,b=snapshot_rows(candidate),snapshot_rows(base)
    require(len(a) == manifest["combined_positions"] and len(b) == manifest["base_positions"]
            and len(a)-len(b) == len(manifest["accepted"]) == manifest["candidate_positions"] > 0,
            "knowledge counts differ")
    require(a[:len(b)] == b, "parent knowledge was edited")
    for row,evidence in zip(a[len(b):],manifest["accepted"]):
        require(len(row) == 14 and row[0] == evidence["position_key"] and row[1] == evidence["selected_move"]
                and row[10] == "research_decision" and row[11] == evidence["research_id"]
                and row[12] == evidence['selected_move']
                and row[13] == (' '.join(evidence['case']['history_moves']) or '-'), "materialized research differs")


def signature(result):
    return tuple(result.get(k) for k in ("status","kind","value_stm","depth","bound","bestmove"))


def preflight(manifest, probe):
    """probe(case, which_snapshot, milliseconds, depth, knowledge_enabled)."""
    require(manifest['accepted'], 'no knowledge targets to validate')
    controls=tactical_cases();require(len(controls) == POLICY_KNOWLEDGE["tactical_controls"], "controls changed")
    observations=[];off_exact=True;regressions=0;depths=[0,0]
    for case in controls:
        off=[probe(case,k,5000,2,False) for k in ("base","candidate")]
        off_exact &= all(exact_cp(p) and p["depth"] == 2 for p in off) and signature(off[0]) == signature(off[1])
        pair=[probe(case,k,200,None,True) for k in ("base","candidate")]
        good=[p["bestmove"].startswith(case["expected_prefix"]) for p in pair]
        regressions += int(not all(good))
        for i,p in enumerate(pair):
            if type(p.get("depth")) is int and p["depth"] > 0:depths[i]+=p["depth"]
            else:regressions+=1
        observations.append(dict(case_id=case["case_id"],kind="tactical",disabled=off,parent=pair[0],candidate=pair[1]))
    corrections=0;hits=0
    for evidence in manifest["accepted"]:
        case=evidence["case"];target=evidence["selected_move"]
        off=[probe(case,k,5000,2,False) for k in ("base","candidate")]
        off_exact &= all(exact_cp(p) and p["depth"] == 2 for p in off) and signature(off[0]) == signature(off[1])
        pair=[probe(case,k,200,None,True) for k in ("base","candidate")]
        require(all(p["history_key"] == case["history_key"] for p in pair), "target history changed")
        hit=pair[1].get("research_decision_id") == evidence["research_id"] and pair[1]["bestmove"] == target
        require(pair[0].get("research_decision_id") != evidence["research_id"], "new research leaked into base")
        hits+=int(hit);corrections+=int(hit and pair[0]["bestmove"] == evidence['actual_move'])
        observations.append(dict(case_id=case["case_id"],kind="target",disabled=off,parent=pair[0],candidate=pair[1]))
    ratio=depths[1]/depths[0] if depths[0] else 0.
    passed=off_exact and regressions == 0 and ratio >= POLICY_KNOWLEDGE["min_depth_ratio"] and corrections == len(manifest["accepted"]) > 0
    return dict(schema="postgame-knowledge-preflight-v1",completed=True,passed=bool(passed),disabled_exact=bool(off_exact),
                regressions=regressions,depth_ratio=ratio,depth_sum_parent=depths[0],depth_sum_candidate=depths[1],
                targeted_corrections=corrections,candidate_knowledge_hits=hits,observations=observations,
                candidate_sha256=manifest["candidate_sha256"],formal_adoption=False,
                limitation="Targeted and small regression measurements, not proof of strength or generalization.")


def stage(base, candidate, manifest, check, directory, options):
    """Create separate immutable A/B inputs; no shared/adopted path overwrite."""
    validate_snapshot(base,candidate,manifest);parent_values(options)
    require(digest(options) == manifest["parent"]["parameters_sha256"], "staged evaluation differs")
    require(check["passed"] is True and check["completed"] is True
            and check["candidate_sha256"] == manifest["candidate_sha256"], "candidate did not pass live checks")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    (directory/"A.tsv").write_bytes(candidate);(directory/"B.tsv").write_bytes(base)
    package=dict(schema="postgame-knowledge-staging-v1",parent=manifest["parent"],purpose=manifest["purpose"],
                 snapshots=dict(A=dict(file="A.tsv",sha256=sha256(candidate),positions=manifest["combined_positions"]),
                                B=dict(file="B.tsv",sha256=sha256(base),positions=manifest["base_positions"])),
                 common_options=dict(FORMAL_DEFAULTS,**options),go_command="go movetime 200",
                 preflight_sha256=digest(check),manifest_sha256=digest(manifest),formal_adoption=False,
                 match_dispatch_connected=False,production_match_eligible=manifest["production_match_eligible"])
    (directory/"stage.json").write_text(json.dumps(package,indent=2)+"\n")
    return package


def staged_options(directory, package):
    require(package["formal_adoption"] is False and package["match_dispatch_connected"] is False, "unexpected deployment claim")
    require(package['go_command'] == 'go movetime 200' and package['purpose'] in ('research','integration_smoke'),
            'staged execution conditions differ')
    params={k:package['common_options'][k] for k in OPTIONS_NAMES}
    parent_values(params)
    require(package['common_options'] == dict(FORMAL_DEFAULTS,**params)
            and digest(params) == package['parent']['parameters_sha256'], 'staged parent/search options differ')
    result={}
    for side in ("A","B"):
        row=package["snapshots"][side]
        require(row["file"] == side+".tsv", "unsafe staged path")
        path=Path(directory)/row["file"];data=path.read_bytes()
        require(sha256(data) == row["sha256"] and len(snapshot_rows(data)) == row["positions"], "staged knowledge changed")
        result[side]=dict(package["common_options"],PositionKnowledgeFile=str(path.resolve()))
    require(package['snapshots']['B']['sha256'] == package['parent']['knowledge_sha256'], 'staged parent knowledge differs')
    return result


def run(binary, base_file, preparation, diagnosis, parent, options, cycle_id, output, purpose="research"):
    """Bounded complete preparation; no screen/confirm/game dispatch."""
    parent_values(options);require(digest(options) == parent["parameters_sha256"], "parent evaluation differs")
    raw=Path(base_file).read_bytes();count=len(snapshot_rows(raw));binary_hash=sha256(Path(binary).read_bytes())
    require(binary_hash == preparation["progress"]["analysis"]["analyzer_binary_sha256"], "actual analyzer binary differs from diagnosis")
    output=Path(output);require(not output.exists(), "preserve previous knowledge stage")
    output.mkdir(parents=True)
    def probe(case,which="base",ms=200,depth=None,enabled=True):
        path=Path(base_file) if which == "base" else output/"candidate.tsv"
        expected=count if which == "base" else count+manifest["candidate_positions"]
        engine=Analyzer(binary,path,expected,evaluation_options=options)
        try:
            if not enabled:
                engine.send("setoption name PositionKnowledge value false");engine.send("isready");engine.until("readyok",15)
            return engine.search(case["start_sfen"],tuple(case["history_moves"]),ms,depth)
        finally:engine.close()
    candidate,manifest=propose(raw,preparation,diagnosis,parent,cycle_id,probe,purpose)
    result=dict(schema="postgame-knowledge-stage-v1",manifest=manifest,binary_sha256=binary_hash,
                status=manifest["status"],formal_adoption=False,strength_improvement_demonstrated=False)
    if candidate is not None:
        validate_snapshot(raw,candidate,manifest);(output/"candidate.tsv").write_bytes(candidate)
        check=preflight(manifest,probe);result["preflight"]=check
        result["status"]="ready_for_separate_match_adapter" if check["passed"] else "retain_parent_preflight_rejected"
        if check["passed"]:result["staging"]=stage(raw,candidate,manifest,check,output/"staged",options)
    (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    return result
