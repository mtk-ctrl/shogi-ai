#!/usr/bin/env python3
"""Verified generic-match source -> parent-aware postgame preparation adapter.

Does not change engine source or adopted knowledge. Raw PVs stay transient.
This adapter is for source generation, not a candidate strength audit.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import shogi
from tools.records.archive_played_moves import archive
from tools.research.postgame_analyze import Analyzer, run_analysis
from tools.research.postgame_cases import load_archive, sha256
from tools.research.postgame_ranker import BASE, OPTIONS, digest, require
from tools.research.postgame_spiral import prepare

FORMAL_DEFAULTS = dict(SearchResearchMask=23, SearchEfficiencyMask=8, SearchReuseMask=6,
                       SearchNextMask=4, SearchProbeMask=7, SearchThreads=2,
                       RiskVerify=True, USI_Ponder=True, OpeningRandomNonLance=True,
                       AdaptiveLongThink=True, PositionKnowledge=True)


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def match_request(state, parent_options, free_runners):
    """Map a source intent to the existing match input; never dispatch itself."""
    pending = state["pending"]
    require(pending and state["stage"] in ("initial_source", "collect_source"), "not a source request")
    require(digest(parent_options) == state["parent"]["parameters_sha256"], "research parent parameters differ")
    require(type(free_runners) is int and 1 <= free_runners <= 20, "actual free runner count required")
    games = pending["payload"]["games"]
    base = dict(AdaptiveLongThink=True, PositionKnowledge=True,
                PositionKnowledgeFile="build/position-knowledge-v1.tsv", OpeningRandomNonLance=True)
    standard = parent_options == dict(zip(OPTIONS, BASE))
    if not standard:
        base.update(parent_options)
    return dict(request_id=pending["operation_id"], ref_a=state["parent"]["engine_ref"],
                ref_b=state["parent"]["engine_ref"], games=games, shards=min(free_runners, games),
                go_command="go movetime 200", max_plies=300, seed=pending["payload"]["seed"],
                options_a=json.dumps(base, sort_keys=True), options_b=json.dumps(base, sort_keys=True),
                entry="owner_issue" if standard else "existing_request_file")


def validate_shard(row, number, request, binary_sha, knowledge_sha):
    binaries = binary_sha if isinstance(binary_sha, dict) else dict(A=binary_sha, B=binary_sha)
    n, lanes = request["games"], request["shards"]
    q, r = divmod(n, lanes)
    require(row["games"] == q+(number < r) and len(row["details"]) == row["games"], "shard count")
    require(row["game_offset"] == q*number+min(number, r), "shard offset")
    require(row["seed"] == request["seed"]+number*100000, "shard seed")
    require(row["go_command"] == request["go_command"] and row["max_plies"] == request["max_plies"], "time/ply settings")
    require(row["illegal_games"] == 0 and row["sha256_a"] == binaries["A"]
            and row["sha256_b"] == binaries["B"], "illegal/binary mismatch")
    for side in ("a", "b"):
        expected = json.loads(request["options_"+side])
        expected.setdefault("PositionKnowledge", True)
        expected.setdefault("PositionKnowledgeFile", "position-knowledge-v1.tsv")
        expected.setdefault("RiskVerify", True)
        expected.setdefault("USI_Ponder", True)
        require(row["options_"+side] == expected, "actual USI request differs")
        meta = row["position_knowledge"][side.upper()]
        require(meta.get("enabled") is True and meta.get("available") is True
                and meta["sha256"] == knowledge_sha and meta["positions"] == 163, "adopted knowledge unavailable/different")
    for i, game in enumerate(row["details"]):
        require(game["a_black"] == ((row["game_offset"]+i) % 2 == 0), "unbalanced color assignment")
        records = game["move_records"]
        require(len(records) == len(game["moves"]) and [m["move"] for m in records] == game["moves"], "actual telemetry mismatch")
        long = Counter()
        for record in records:
            require("phase_maturity" in record["search"], "missing actual phase observation")
            if record["search"].get("long_think_used"):
                long[record["engine"]] += 1
        require(all(v <= 10 for v in long.values()), "long-think cap exceeded")


def verify_source(source, request, parent_options, build_log, expected_knowledge_sha256,
                  candidate_options=None, prior_signatures=None):
    source = Path(source)
    build = source/"binaries/build"
    binary, knowledge = build/"engine-a", build/"position-knowledge-v1.tsv"
    binaries = {"A": sha256(binary.read_bytes()), "B": sha256((build/"engine-b").read_bytes())}
    binary_sha = binaries["A"]; knowledge_sha = sha256(knowledge.read_bytes())
    require(knowledge_sha == expected_knowledge_sha256, "source differs from frozen adopted knowledge")
    for side, params in (("a", candidate_options or parent_options), ("b", parent_options)):
        actual = json.loads(request["options_"+side])
        require(all(actual.get(k, b) == params[k] for k, b in zip(OPTIONS, BASE)),
                "request uses different evaluation parameters")
        require(set(actual) <= set(FORMAL_DEFAULTS) | set(OPTIONS) | {"PositionKnowledgeFile"},
                "unexpected comparison option")
        for key, value in FORMAL_DEFAULTS.items():
            require(actual.get(key, value) == value, "comparison changed formal search conditions")
    parent = request["ref_a"]
    require(parent == request["ref_b"] and len(re.findall(r'git checkout --progress --force '+parent, build_log)) >= 2,
            "actual fixed source checkouts not proved")
    for side in ("a", "b"):
        hashes = re.findall(r'([0-9a-f]{64})  build/engine-'+side, build_log)
        require(len(hashes) == 1 and hashes[0] == binaries[side.upper()], "actual source binary not proved")
    for row in sorted((source/"shards").glob("shard-*.json")):
        validate_shard(json.loads(row.read_bytes()), int(row.stem.split("-")[-1]), request, binaries, knowledge_sha)
    rows = sorted((source/"shards").glob("shard-*.json"))
    require(sorted(int(p.stem.split("-")[-1]) for p in rows) == list(range(request["shards"])), "missing/duplicate source lane")
    original = load_archive(source)
    manifest = json.loads((source/"manifest.json").read_bytes())
    require(manifest["requested_ref_a"] == manifest["requested_ref_b"] == parent, "archive fixed parent mismatch")
    rebuilt = source/"verified-archive"
    archive(rows, rebuilt, manifest["run_id"], parent, parent)
    games = load_archive(rebuilt)
    require([g.row for g in games] == [g.row for g in original], "played archive differs from raw original")
    require(len(games) == request["games"], "source game count mismatch")
    # Generic match builds in two source directories; debug paths may make the
    # bytes differ even for the same fixed commit. Verify each actual artifact.
    for executable, params in ((binary, candidate_options or parent_options), (build/"engine-b", parent_options)):
        executable.chmod(0o755)
        engine = Analyzer(executable, knowledge, evaluation_options=params)
        try:
            for name, value in dict(FORMAL_DEFAULTS, **dict(zip(OPTIONS, BASE))).items():
                expected = str(value).lower() if type(value) is bool else str(value)
                require(engine.option_defaults.get(name) == expected, "saved engine has unexpected default: "+name)
        finally:
            engine.close()
    signatures = [trajectory(g.start_sfen, g.moves) for g in games]
    unique = {}
    for game, signature in zip(games, signatures):
        if signature not in (prior_signatures or set()):
            unique.setdefault(signature, game)
    def counts(gs):
        gs = list(gs)
        return dict(wins=sum(g.row["winner"] == "A" for g in gs), losses=sum(g.row["winner"] == "B" for g in gs),
                    draws=sum(g.row["winner"] is None for g in gs))
    audit = dict(schema="postgame-source-bridge-audit-v1", games=len(games), plies=sum(len(g.moves) for g in games),
                 all_moves_legal=True, all_terminations_verified=True, conditions_verified=True,
                 binary_verified=True, knowledge_snapshot_verified=True, duplicates_checked=True,
                 prior_and_internal_duplicates_excluded=counts(unique.values()), candidate_knowledge_uses=0,
                 parent_ref=parent, binary_sha256=binary_sha, knowledge_sha256=knowledge_sha,
                 actual_binary_sha256=binaries,
                 parent_parameters_sha256=digest(parent_options), internal_duplicates=len(games)-len(set(signatures)),
                 prior_trajectory_overlap=sum(s in (prior_signatures or set()) for s in signatures),
                 trajectory_outcomes=[dict(sha256=s, winner=g.row["winner"], a_black=g.row["a_black"],
                                           game_id=g.row["game_id"]) for s, g in zip(signatures, games)],
                 reward_status=dict(Counter(g.outcome_status for g in games)),
                 loader_reproduced=True, original_loader_handshake_retained=False,
                 candidate_parameters_sha256=digest(candidate_options or parent_options),
                 limitation="Complete-trajectory sensitivity only; partial-game overlap is not a proof of independence.")
    return games, audit, counts(games), binary, knowledge



def trajectory(start, moves):
    return sha256((" ".join(start.split()[:3])+"\n"+" ".join(moves)).encode())

def analyze_source(source, request, parent_options, build_log, output, expected_knowledge_sha256,
                   previous_preparation=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    games, audit, outcome, binary, knowledge = verify_source(source, request, parent_options, build_log, expected_knowledge_sha256)
    dump(output/"source-audit.json", audit)
    analysis = output/"analysis"
    summary = run_analysis([Path(source)/"verified-archive"], binary, knowledge, analysis, parent_options)
    def probe(case):
        results = []
        for _ in range(2):
            e = Analyzer(binary, knowledge, evaluation_options=parent_options)
            try: results.append(e.search(case["start_sfen"], tuple(case["history_moves"]), 200))
            finally: e.close()
        return results
    e = Analyzer(binary, knowledge, evaluation_options=parent_options)
    try:
        previous = previous_preparation or {}
        context = dict(engine_ref=request["ref_a"], knowledge_sha256=expected_knowledge_sha256,
                       parameters_sha256=digest(parent_options))
        report = prepare(json.loads((analysis/"diagnosis.json").read_bytes()), probe, e.static,
                         "spiral-bridge-20261017-v1", registry=previous.get("split_registry"),
                         parent_options=parent_options, example_bank=previous.get("example_bank"),
                         parent_context=context)
    finally:
        e.close()
    dump(output/"preparation.json", report)
    return dict(audit=audit, result=outcome, analysis=summary, preparation=report)
