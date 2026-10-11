#!/usr/bin/env python3
"""Validate, run and audit 30 independent 50-minute position studies.

Uses existing KUMOJI research implementation. Never changes the playing engine,
automatically adds position knowledge, or labels deep search as absolute truth.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
from pathlib import Path
import sys

import shogi

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "research"))
from run_opening20 import Usi

STAGES = ("opening", "middle", "end")


def norm(value: str):
    return " ".join(value.split()[:3])


def read_selection(path: Path):
    metadata = json.loads(path.read_text(encoding="utf8"))
    rows = metadata.get("positions")
    if metadata.get("schema") != "nn-disagreement-selection-v1" or not isinstance(rows, list) or len(rows) != 30:
        raise ValueError("30 candidate positions from verified NN screening are required")
    seen = set()
    group = {name: 0 for name in STAGES}
    for row in rows:
        if row.get("stage") not in group or row.get("id") in seen:
            raise ValueError("invalid stage or duplicate research ID")
        if not isinstance(row.get("history_moves"), list):
            raise ValueError("history required")
        group[row["stage"]] += 1
        seen.add(row["id"])
        board = shogi.Board()
        for m in row["history_moves"]:
            parsed = shogi.Move.from_usi(m)
            if parsed not in board.legal_moves:
                raise ValueError("nonlegal move found in historical record")
            board.push(parsed)
        if norm(board.sfen()) != row["sfen"]:
            raise ValueError("source position does not match replayed history")
    if group != {name: 10 for name in STAGES}:
        raise ValueError("research positions must be 10 each in opening, middle and end")
    return metadata


def study(selection: Path, lane: int, engine: Path, knowledge: Path, output: Path):
    metadata = read_selection(selection)
    if not 0 <= lane < 30:
        raise ValueError("lane must be in range 0..29")
    row = metadata["positions"][lane]
    research_row = {"id": row["id"], "sfen": row["sfen"],
                    "moves": row["history_moves"]}
    engine_obj = Usi(engine, knowledge)
    try:
        result = engine_obj.research(research_row, 3000000, output)
    finally:
        engine_obj.close()
    if result.get("id") != row["id"] or not result.get("completed"):
        raise RuntimeError("long research finished without a complete record")
    return {"lane": lane, "id": row["id"],
            "bestmove": result.get("bestmove"), "elapsed_seconds": result.get("elapsed_seconds")}


def aggregate(selection: Path, results_dir: Path, output_dir: Path):
    source = read_selection(selection)
    expected = {r["id"]: r for r in source["positions"]}
    files = sorted(results_dir.glob("**/result.json"))
    rows = []
    received = set()
    per_stage = {stage: {"expected": 10, "completed": 0,
                         "nn_deep_same_sign": 0, "static_deep_same_sign": 0,
                         "deep_cp_available": 0} for stage in STAGES}
    for file in files:
        outcome = json.loads(file.read_text(encoding="utf8"))
        rid = outcome.get("id")
        if rid not in expected or rid in received:
            raise ValueError("unknown or duplicate research result " + str(rid))
        received.add(rid)
        selected = expected[rid]
        if norm(outcome.get("sfen", "")) != selected["sfen"]:
            raise ValueError("returned research SFEN mismatches selected position")
        if outcome.get("history_moves") != selected["history_moves"]:
            raise ValueError("returned study has different move history")
        result = dict(
            selection=selected,
            research=outcome,
            stage=selected["stage"],
            empirical_winner_is_not_ground_truth=True,
            deep_research_is_not_absolute_ground_truth=True,
            adopted=False,
        )
        summary = per_stage[selected["stage"]]
        if outcome.get("completed") is True and outcome.get("bestmove"):
            summary["completed"] += 1
            final = outcome.get("final", {})
            if final.get("score_type") == "cp" and type(final.get("score_value")) is int:
                # In USI the search score is relative to side to move; NN and
                # static eval used absolute Black viewpoint.
                side_is_black = selected["sfen"].split()[1] == "b"
                deep_cp_black = final["score_value"] * (1 if side_is_black else -1)
                summary["deep_cp_available"] += 1
                result["deep_cp_black"] = deep_cp_black
                deep_sign = (deep_cp_black > 0) - (deep_cp_black < 0)
                nn_sign = (selected["nn_probability_black"] > .5) - (
                    selected["nn_probability_black"] < .5)
                static_sign = (selected["static_cp_black"] > 0) - (
                    selected["static_cp_black"] < 0)
                summary["nn_deep_same_sign"] += deep_sign == nn_sign
                summary["static_deep_same_sign"] += deep_sign == static_sign
                result["nn_matches_deep_sign"] = deep_sign == nn_sign
                result["static_matches_deep_sign"] = deep_sign == static_sign
        rows.append(result)
    missing = sorted(set(expected) - received)
    report = dict(
        schema="nn-disagreement-long-research-v1",
        source_selection_sha256=hashlib.sha256(selection.read_bytes()).hexdigest(),
        expected=30, received=len(received),
        completed=sum(x["completed"] for x in per_stage.values()),
        missing=missing, per_stage=per_stage,
        candidate_evaluator_automatically_adopted=False,
        position_knowledge_automatically_adopted=False,
        interpretation=(
            "These are candidate discrepancies, not proof of which evaluator is "
            "correct. Long search still uses KUMOJI's own evaluation function. "
            "Sign agreement is only a preliminary observation; no training labels "
            "or production changes are produced automatically."),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    with gzip.open(output_dir / "research.json.gz", "wt", encoding="utf8") as fp:
        json.dump({"summary": report, "results": rows}, fp, ensure_ascii=False)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("validate", "study", "aggregate"))
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--lane", type=int, default=0)
    p.add_argument("--engine", type=Path, default=Path("build/kumoji"))
    p.add_argument("--knowledge", type=Path, default=Path("build/position-knowledge-v1.tsv"))
    p.add_argument("--output", type=Path, default=Path("result.json"))
    p.add_argument("--results", type=Path, default=Path("research-results"))
    p.add_argument("--output-dir", type=Path, default=Path("build/nn-disagreement-final"))
    a = p.parse_args()
    if a.mode == "validate":
        record = read_selection(a.selection)
        print(json.dumps({"valid_positions": len(record["positions"])}, ensure_ascii=False))
    elif a.mode == "study":
        print(json.dumps(study(a.selection, a.lane, a.engine, a.knowledge, a.output)))
    else:
        print(json.dumps(aggregate(a.selection, a.results, a.output_dir),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
