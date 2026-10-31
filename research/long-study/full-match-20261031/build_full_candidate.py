#!/usr/bin/env python3
"""Make an isolated KUMOJI playing-knowledge candidate from the entire verified research catalog.

Previously vetted 163+227 are preserved byte-for-byte. All 1,079 source
observations are inspected. Older completed, replay-valid 50-minute studies not
already represented are allowed as *move-order hints*, never unreviewed forced
decisions. Negative/inconclusive/validation evidence stays in the audit ledger.
No formally adopted production snapshot is changed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import shogi

CORPUS_SHA = "0ed369e563f1575d013c736eef1de1966ab76a8144a952b09fb4cec2ce0544cc"
OLD_390_SHA = "45f8bcc6115e0fadc1030c5d1967551d27b377d5e0b2d007798ee61428da276e"
CATEGORIES = {
    "neural_long_study": 520, "legacy_long_study": 180,
    "legacy_60s_observation": 91, "integration_short_test": 40,
    "legacy_postgame_analysis": 232, "legacy_followup": 16,
}

def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()

def key(board) -> str:
    return " ".join(board.sfen().split()[:3])

def clean(value):
    return isinstance(value, str) and bool(value) and "\t" not in value and "\n" not in value

def extract_legacy(row):
    """Return a conservative hint only for a verifiable completed long search."""
    item = row["record"]
    if not isinstance(item, dict):
        return None, "record_not_object"
    if isinstance(item.get("selection"), dict) and isinstance(item.get("research"), dict):
        selected, study = item["selection"], item["research"]
        history = selected.get("history_moves")
        recorded_position = selected.get("sfen")
    else:
        study = item
        history = item.get("history_moves")
        recorded_position = item.get("sfen")
    if study.get("completed") is not True:
        return None, "unconfirmed_completion"
    if study.get("research_ms_requested") != 3000000:
        return None, "not_50_minute_study"
    seconds = study.get("elapsed_seconds")
    if type(seconds) not in (float, int) or not 2990 <= seconds <= 3090:
        return None, "search_duration_unconfirmed"
    last = study.get("final", {})
    move = study.get("bestmove")
    if (not isinstance(last, dict) or not isinstance(last.get("depth"), int)
        or last["depth"] <= 0 or last.get("score_type") not in ("cp", "mate")
        or type(last.get("score_value")) is not int or not clean(move)):
        return None, "insufficient_final_search_evidence"
    if not isinstance(history, list) or not history or not clean(recorded_position):
        return None, "no_replayable_history"
    board = shogi.Board()
    try:
        for word in history:
            if not clean(word): raise ValueError("malformed source move")
            legal = shogi.Move.from_usi(word)
            if legal not in board.legal_moves: raise ValueError("illegal source history")
            board.push(legal)
        if key(board) != recorded_position:
            return None, "position_history_mismatch"
        proposed = shogi.Move.from_usi(move)
        if proposed not in board.legal_moves:
            return None, "illegal_research_move"
    except (TypeError, ValueError, AssertionError):
        return None, "nonlegal_or_unreplayable_source"
    return dict(position=recorded_position, move=move, history=history,
                elapsed_ms=round(seconds*1000), depth=last["depth"],
                nodes=last.get("nodes") if type(last.get("nodes")) is int else None,
                kind=last["score_type"], score=last["score_value"]), None

def build(corpus, existing, result, report):
    raw = Path(corpus).read_bytes()
    if digest(raw) != CORPUS_SHA:
        raise ValueError("catalog corpus bytes do not match independently verified export")
    old = Path(existing).read_bytes()
    if digest(old) != OLD_390_SHA:
        raise ValueError("existing 163+227 candidate changed; refusing to overwrite")
    old_rows = [x for x in old.decode("utf-8").splitlines() if x and not x.startswith("#")]
    if len(old_rows) != 390:
        raise ValueError("expected precisely 390 prevalidated knowledge rows")
    known = {}
    for line in old_rows:
        fields = line.split("\t")
        if len(fields) != 14 or fields[0] in known:
            raise ValueError("malformed prior knowledge snapshot")
        known[fields[0]] = fields[1]
    reasons, categories = Counter(), Counter()
    pending = defaultdict(list)
    records = [json.loads(line) for line in raw.splitlines() if line]
    if len(records) != 1079:
        raise ValueError("entire catalog was not exported")
    observation_ids = set()
    for row in records:
        oid, gid = row.get("observation_id"), row.get("group_id", "")
        if not isinstance(oid,str) or oid in observation_ids:
            raise ValueError("duplicate or missing source observation id")
        observation_ids.add(oid)
        cat = ("neural_long_study" if gid.startswith(("neural20-standard-","neural20-correction-","neural20-repaired-"))
               else "legacy_long_study" if any(gid.startswith(x) for x in
                    ("research-opening20-","timebox40-records-","research10-","nn-disagreement-research-"))
               else "legacy_60s_observation" if gid.startswith("research-records-")
               else "integration_short_test" if gid.startswith("neural20-integration-")
               else "legacy_postgame_analysis" if any(gid.startswith(x) for x in
                    ("postgame-diagnosis-","postgame-practice-","postgame-diverse-practice-","spiral-sixhour-recovery-")) and ("followup/result" not in gid)
               else "legacy_followup")
        categories[cat] += 1
        if cat == "neural_long_study":
            # The exact 520-record selection, its 227 eligible positions, and
            # all its rejection reasons are frozen in candidate.manifest.json.
            reasons["520_neural_previously_reviewed"] += 1
            continue
        if cat != "legacy_long_study":
            # Retain all diagnostics and negative evidence in the report, but
            # never turn them into unsupported unconditional playing moves.
            reasons["retained_non_candidate_"+cat] += 1
            continue
        parsed, error = extract_legacy(row)
        if error:
            reasons[error] += 1
            continue
        if parsed["position"] in known:
            reasons["already_in_390"] += 1
            continue
        pending[parsed["position"]].append((oid, parsed))
    if dict(categories) != CATEGORIES:
        raise ValueError("the catalog categories/counts no longer match the frozen inventory")
    added = []
    entries = []
    for position, group in sorted(pending.items()):
        if len({p["move"] for _,p in group}) > 1:
            reasons["conflicting_old_studies"] += len(group)
            continue
        oid, p = sorted(group,key=lambda x:x[0])[-1]
        fields = [position,p["move"],"all-archive-research-hint-20261031",
                  str(len(group)),str(p["elapsed_ms"]),str(p["depth"]),
                  str(p["nodes"]) if p["nodes"] is not None else "",
                  p["kind"],str(p["score"]),"","move_order_hint",
                  "longarchive-"+digest(oid.encode())[:20],p["move"],
                  " ".join(p["history"])]
        if len(fields)!=14 or not all(clean(x) or x=="" for x in fields):
            raise ValueError("unrepresentable knowledge candidate")
        added.append("\t".join(fields))
        entries.append(dict(position_key=position,move=p["move"],source_ids=[i for i,_ in group],
                            mode="move_order_hint"))
        reasons["new_legacy_hint"] += len(group)
    if not added:
        raise ValueError("no new whole-archive research use; this would repeat the 390 candidate")
    materialized = old.rstrip(b"\n")+b"\n"+("\n".join(added)+"\n").encode("utf-8")
    result = Path(result)
    report = Path(report)
    result.parent.mkdir(parents=True,exist_ok=True)
    report.parent.mkdir(parents=True,exist_ok=True)
    result.write_bytes(materialized)
    audit = dict(schema="kumoji-entire-research-corpus-v1",
      formal_adoption=False, research_only=True,
      source_observations=len(records), corpus_sha256=CORPUS_SHA,
      category_counts=dict(categories), reason_counts=dict(reasons),
      prior_positions=390, prior_adopted_positions=163,
      prior_research_direct_candidates=227, newly_validated_hints=len(added),
      playable_positions=390+len(added), candidate_sha256=digest(materialized),
      old_long_study_evidence_is_not_automatically_trusted=True,
      diagnostic_or_validation_records_are_not_forced_moves=True,
      entries=entries)
    report.write_text(json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in audit.items() if k!="entries"},ensure_ascii=False),flush=True)
    return audit

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--corpus",required=True)
    parser.add_argument("--existing",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--report",required=True)
    a=parser.parse_args()
    build(a.corpus,a.existing,a.output,a.report)
