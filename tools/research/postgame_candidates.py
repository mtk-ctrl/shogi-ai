#!/usr/bin/env python3
"""Gate postgame diagnosis and build a research-only knowledge snapshot.

The adopted snapshot is never edited.  Only independently replayed cases whose
50 ms and 500 ms root searches agree, and whose fixed-depth child comparison
confirms at least 150 cp, are appended to a separate candidate snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import shogi


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replay(case):
    board = shogi.Board(case["start_sfen"])
    seen = {" ".join(board.sfen().split()[:3]): 1}
    for token in case["history_moves"]:
        move = shogi.Move.from_usi(token)
        require(move in board.legal_moves, f"illegal history move: {token}")
        board.push(move)
        key = " ".join(board.sfen().split()[:3])
        seen[key] = seen.get(key, 0) + 1
    key = " ".join(board.sfen().split()[:3])
    require(key == case["position_key"], "position key/history mismatch")
    return board, seen[key]


def accepted_record(result, cycle_id):
    require(result.get("route") == "stable_research_move_candidate", "route is not stable")
    case = result["case"]
    board, occurrences = replay(case)
    require(occurrences == 1, "repeated position is not eligible for direct research use")
    move = shogi.Move.from_usi(result["research_move"])
    require(move in board.legal_moves, "research move is illegal")
    require(result["root_short"]["bestmove"] == result["research_move"], "50 ms disagreement")
    require(result["root_deep"]["bestmove"] == result["research_move"], "500 ms disagreement")
    follow = result.get("followup") or {}
    comparison = follow.get("comparison") or {}
    require(comparison.get("status") == "comparable", "fixed-depth comparison is not exact/comparable")
    require(comparison.get("improvement_cp", 0) >= 150, "confirmed improvement below gate")
    depth = int(follow["requested_depth"])
    require(depth > 0 and follow["actual"].get("depth") == depth
            and follow["research"].get("depth") == depth, "fixed depth was not completed")
    require(follow["actual"].get("kind") == "cp" and follow["research"].get("kind") == "cp",
            "mate/cp comparison is not eligible")
    require(follow["actual"].get("bound") == "exact" and follow["research"].get("bound") == "exact",
            "bounded score is not eligible")
    rid = f"{cycle_id}-{case['case_id'][:16]}"
    fields = [
        case["position_key"], result["research_move"], cycle_id, "1", "500", str(depth), "0",
        result["root_deep"]["kind"], str(result["root_deep"]["value_stm"]), "500",
        "research_decision", rid, result["research_move"],
        " ".join(case["history_moves"]) or "-",
    ]
    return "\t".join(fields), {
        "research_id": rid,
        "case_id": case["case_id"],
        "source": case["source"],
        "position_key": case["position_key"],
        "selected_move": result["research_move"],
        "actual_move": case["actual_move"],
        "confirmed_improvement_cp": comparison["improvement_cp"],
        "fixed_depth": depth,
        "terminal_reward_stm": case["outcome"]["terminal_reward_stm"],
    }


def build(diagnosis_path, base_path, output_path, manifest_path, cycle_id):
    diagnosis_raw = Path(diagnosis_path).read_bytes()
    diagnosis = json.loads(diagnosis_raw)
    require(isinstance(diagnosis, list) and diagnosis, "empty diagnosis")
    base_raw = Path(base_path).read_bytes()
    base_text = base_raw.decode("utf-8")
    require(base_text.startswith("# position-knowledge-v1-active\n"), "invalid base snapshot")
    base_rows = [line for line in base_text.splitlines() if line and not line.startswith("#")]
    require(len(base_rows) == 163, "base snapshot is not the fixed 163-position parent")
    base_keys = {line.split("\t", 1)[0] for line in base_rows}
    require(len(base_keys) == len(base_rows), "duplicate base position")

    records = []
    for result in diagnosis:
        if result.get("route") != "stable_research_move_candidate":
            continue
        line, evidence = accepted_record(result, cycle_id)
        require(evidence["position_key"] not in base_keys, "candidate conflicts with adopted snapshot")
        records.append((line, evidence))
    records.sort(key=lambda item: item[1]["position_key"])
    require(records, "no stable candidate knowledge")
    require(len({r[1]["position_key"] for r in records}) == len(records), "duplicate candidate position")

    header = (
        "# postgame-pilot research snapshot; adopted base plus unadopted candidates\n"
        f"# base_sha256={sha256(base_raw)} candidate_count={len(records)} formal_adoption=false\n"
    )
    output = base_text.rstrip("\n") + "\n" + header + "\n".join(r[0] for r in records) + "\n"
    Path(output_path).write_text(output, encoding="utf-8")
    output_raw = Path(output_path).read_bytes()
    route_counts = {}
    for row in diagnosis:
        route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    manifest = {
        "schema": "postgame-candidate-snapshot-v1",
        "cycle_id": cycle_id,
        "formal_adoption": False,
        "diagnosis_file": Path(diagnosis_path).name,
        "diagnosis_sha256": sha256(diagnosis_raw),
        "base_file": Path(base_path).name,
        "base_sha256": sha256(base_raw),
        "base_positions": len(base_rows),
        "candidate_positions": len(records),
        "combined_positions": len(base_rows) + len(records),
        "candidate_evidence": [r[1] for r in records],
        "route_counts": dict(sorted(route_counts.items())),
        "evaluation_candidate": {
            "created": False,
            "reason": "Only two stable paired examples; no defensible adjustment/selection/unused split.",
        },
        "output_file": Path(output_path).name,
        "output_sha256": sha256(output_raw),
        "policy": "Research-only K1; does not replace or modify the adopted 163-position K0 snapshot.",
    }
    Path(manifest_path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--diagnosis", type=Path, required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--cycle-id", default="postgame-pilot-g1-k1")
    args = p.parse_args()
    require(not args.output.exists() and not args.manifest.exists(), "preserve prior candidate outputs")
    print(json.dumps(build(args.diagnosis, args.base, args.output, args.manifest, args.cycle_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
