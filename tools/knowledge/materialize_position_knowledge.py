#!/usr/bin/env python3
"""Build an adopted, compact position-knowledge snapshot from candidate JSONL."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

MOVE_RE = re.compile(r"^(?:[1-9][a-i][1-9][a-i]\+?|[PLNSGBR]\*[1-9][a-i])$")


def read_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt"
    with opener(path, mode, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield lineno, json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--accept-status", action="append", default=[])
    p.add_argument("--min-evidence", type=int, default=1)
    p.add_argument("--source-label", default="")
    args = p.parse_args()

    accepted_status = set(args.accept_status or ["adopted"])
    by_position = defaultdict(list)
    rejected = defaultdict(int)

    for lineno, row in read_rows(args.input):
        if row.get("schema") != "position-knowledge-v1":
            rejected["schema"] += 1
            continue
        handling = row.get("handling") or {}
        if handling.get("mode") != "move_order_hint":
            rejected["mode"] += 1
            continue
        status = str(handling.get("status", ""))
        if status not in accepted_status:
            rejected["status:" + status] += 1
            continue
        evidence = row.get("evidence") or []
        if len(evidence) < args.min_evidence:
            rejected["evidence"] += 1
            continue
        key = str(row.get("position_key", "")).strip()
        move = str(row.get("selected_move", "")).strip()
        if len(key.split()) != 3:
            rejected["position_key"] += 1
            continue
        if not MOVE_RE.match(move):
            rejected["move"] += 1
            continue
        by_position[key].append({
            "move": move,
            "knowledge_version": str(row.get("knowledge_version", "")),
            "evidence": evidence,
            "line": lineno,
        })

    adopted = []
    conflicts = 0
    duplicates = 0
    for key in sorted(by_position):
        rows = by_position[key]
        moves = {r["move"] for r in rows}
        if len(moves) != 1:
            conflicts += 1
            continue
        if len(rows) > 1:
            duplicates += len(rows) - 1
        best = max(rows, key=lambda r: (len(r["evidence"]), r["knowledge_version"], -r["line"]))
        adopted.append((key, best["move"], best["knowledge_version"], len(best["evidence"])))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# position-knowledge-v1-active",
        "# mode=move_order_hint",
        "# columns: position_key<TAB>selected_move<TAB>knowledge_version<TAB>evidence_count",
    ]
    lines = header + [
        f"{key}\t{move}\t{version}\t{evidence_count}"
        for key, move, version, evidence_count in adopted
    ]
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    input_sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
    output_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = {
        "schema": "position-knowledge-active-manifest-v1",
        "source_label": args.source_label,
        "source_file": args.input.name,
        "source_sha256": input_sha,
        "accept_status": sorted(accepted_status),
        "min_evidence": args.min_evidence,
        "adopted_positions": len(adopted),
        "conflicting_positions_excluded": conflicts,
        "duplicate_same_move_records_collapsed": duplicates,
        "rejected": dict(sorted(rejected.items())),
        "output_file": args.output.name,
        "output_sha256": output_sha,
        "policy": (
            "Only explicitly accepted move_order_hint candidates are materialized. "
            "Conflicting moves are excluded; this script never auto-promotes a new candidate source."
        ),
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    if not adopted:
        raise SystemExit("no adopted position knowledge records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
