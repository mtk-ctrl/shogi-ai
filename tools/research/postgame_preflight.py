#!/usr/bin/env python3
"""Preflight a research-only K1 snapshot before any screening games."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.research.postgame_analyze import Analyzer


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(binary, knowledge, case, expected_positions, ms=None, depth=None):
    engine = Analyzer(binary, knowledge, expected_positions)
    try:
        return engine.search(case["start_sfen"], tuple(case["history_moves"]), ms or 5000, depth)
    finally:
        engine.close()


def preflight(binary, base, candidate, diagnosis, manifest, limit=32):
    report = json.loads(Path(manifest).read_text())
    if sha256(base) != report["base_sha256"] or sha256(candidate) != report["output_sha256"]:
        raise ValueError("snapshot hash mismatch")
    if report["base_positions"] != 163 or report["candidate_positions"] <= 0:
        raise ValueError("unexpected snapshot counts")
    rows = json.loads(Path(diagnosis).read_text())
    candidate_ids = {x["case_id"] for x in report["candidate_evidence"]}
    base_keys = {line.split("\t", 1)[0] for line in Path(base).read_text().splitlines()
                 if line and not line.startswith("#")}
    controls = sorted((r["case"] for r in rows
                       if r["case"]["case_id"] not in candidate_ids
                       and r["case"]["position_key"] not in base_keys
                       and r["route"] != "knowledge_reference_candidate"
                       and r["root_deep"].get("status") == "recorded"
                       and r["root_deep"].get("kind") == "cp"
                       and r["root_deep"].get("depth")), key=lambda c: c["case_id"])[:limit]
    if len(controls) != limit:
        raise ValueError("insufficient control positions")

    # With knowledge disabled, changing only the file must not change fixed-depth output.
    disabled = []
    for case in controls[:8]:
        a = Analyzer(binary, base, report["base_positions"])
        b = Analyzer(binary, candidate, report["combined_positions"])
        try:
            for engine in (a, b):
                engine.send("setoption name PositionKnowledge value false")
                engine.send("isready")
                engine.until("readyok", 15)
            x = a.search(case["start_sfen"], tuple(case["history_moves"]), 5000, 2)
            y = b.search(case["start_sfen"], tuple(case["history_moves"]), 5000, 2)
        finally:
            a.close(); b.close()
        signature = lambda z: (z["status"], z["kind"], z["value_stm"], z["depth"],
                               z["bound"], z["bestmove"])
        if signature(x) != signature(y):
            raise ValueError("disabled fixed-depth mismatch")
        disabled.append(case["case_id"])

    base_depth = candidate_depth = 0
    paired_missing = 0
    speed_rows = []
    for case in controls:
        x = run(binary, base, case, report["base_positions"], ms=200)
        y = run(binary, candidate, case, report["combined_positions"], ms=200)
        if bool(x.get("depth")) != bool(y.get("depth")):
            raise ValueError("unpaired missing completed depth")
        if not x.get("depth"):
            paired_missing += 1
        base_depth += x.get("depth") or 0
        candidate_depth += y.get("depth") or 0
        speed_rows.append({"case_id": case["case_id"], "base_depth": x["depth"],
                           "candidate_depth": y["depth"]})
    if len(controls) - paired_missing < 24 or base_depth <= 0:
        raise ValueError("insufficient completed speed controls")
    ratio = candidate_depth / base_depth
    if ratio < .9:
        raise ValueError(f"candidate depth ratio below gate: {ratio}")

    direct = []
    by_id = {r["case"]["case_id"]: r for r in rows}
    for evidence in report["candidate_evidence"]:
        row = by_id[evidence["case_id"]]
        result = run(binary, candidate, row["case"], report["combined_positions"], depth=1)
        if result["bestmove"] != evidence["selected_move"]:
            raise ValueError("candidate direct decision not observed")
        base_result = run(binary, base, row["case"], report["base_positions"], depth=1)
        if result.get("research_decision_id") != evidence["research_id"]:
            raise ValueError("candidate research provenance not observed")
        if base_result.get("research_decision_id") == evidence["research_id"]:
            raise ValueError("candidate leaked into adopted base")
        direct.append({"case_id": evidence["case_id"], "candidate_move": result["bestmove"],
                       "base_move": base_result["bestmove"],
                       "candidate_research_id": result["research_decision_id"],
                       "base_research_id": base_result.get("research_decision_id")})
    return {
        "status": "pass", "binary_sha256": sha256(binary), "base_sha256": sha256(base),
        "candidate_sha256": sha256(candidate), "disabled_fixed_depth_cases": disabled,
        "speed_cases": len(controls), "base_depth_sum": base_depth,
        "candidate_depth_sum": candidate_depth, "depth_ratio": ratio,
        "paired_missing_depth": paired_missing,
        "candidate_direct_checks": direct, "speed_rows": speed_rows,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--diagnosis", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("preserve prior preflight")
    result = preflight(args.binary, args.base, args.candidate, args.diagnosis, args.manifest)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "speed_rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
