#!/usr/bin/env python3
"""Add validated original research PVs only to already accepted position keys."""
import argparse
import hashlib
import json
from pathlib import Path
import shogi

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--research", type=Path, required=True)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--source-label", required=True)
    ap.add_argument("--expect", type=int, default=0)
    a = ap.parse_args()
    sources = {}
    for n, line in enumerate(a.research.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("schema") != "position-knowledge-v1-candidate":
            continue
        key = r.get("position_key")
        if key in sources:
            raise SystemExit(f"duplicate research position at line {n}")
        sources[key] = r
    lines = []
    count = 0
    minimum = 999
    for line in a.snapshot.read_text(encoding="utf-8").splitlines():
        if line.startswith("# mode=move_order_hint"):
            lines.append("# mode=research_decision (adopted long-search results)")
            continue
        if line.startswith("# columns:"):
            lines.append("# columns: position_key<TAB>selected_move<TAB>knowledge_version<TAB>evidence_count<TAB>research_ms<TAB>research_depth<TAB>research_nodes<TAB>score_kind<TAB>score_value<TAB>stable_ms<TAB>mode<TAB>research_id<TAB>research_pv")
            continue
        if not line or line.startswith("#"):
            lines.append(line)
            continue
        fields = line.split("\t")
        if len(fields) < 4:
            raise SystemExit("invalid adopted knowledge row")
        key, move, version, evidence = fields[:4]
        r = sources.get(key)
        if r is None or r.get("selected_move") != move:
            raise SystemExit(f"adopted move has no matching original research: {key}")
        info = r.get("research") or {}
        pv = info.get("pv") or []
        if not pv or pv[0] != move or not all(isinstance(m, str) for m in pv):
            raise SystemExit(f"invalid research PV: {key}")
        if not (isinstance(info.get("depth"), int) and info["depth"] > 0
                and isinstance(info.get("nodes"), int) and info["nodes"] > 0
                and isinstance(info.get("elapsed_ms"), (int, float))
                and info["elapsed_ms"] >= 59000):
            raise SystemExit(f"not a complete sixty-second study: {key}")
        board = shogi.Board(key + " 1")
        if " ".join(board.sfen().split()[:3]) != key:
            raise SystemExit(f"research key mismatch: {key}")
        for i, m in enumerate(pv):
            try:
                candidate = shogi.Move.from_usi(m)
                if candidate not in board.legal_moves:
                    raise ValueError("illegal move")
                board.push(candidate)
            except (ValueError, TypeError, IndexError) as e:
                raise SystemExit(f"invalid research line at {key} ply {i+1}: {m}: {e}") from e
        kind = ("cp" if info.get("score_cp_stm") is not None else
                "mate" if info.get("score_mate_stm") is not None else "")
        score = info.get("score_cp_stm") if kind == "cp" else info.get("score_mate_stm", "")
        fields = [key, move, version, evidence, str(int(info["elapsed_ms"])),
                  str(info["depth"]), str(info["nodes"]), kind,
                  "" if score is None else str(score), "",
                  "research_decision", str(r["position_id"]), " ".join(pv)]
        lines.append("\t".join(fields))
        count += 1
        minimum = min(minimum, len(pv))
    if a.expect and count != a.expect:
        raise SystemExit(f"expected {a.expect} eligible studies, found {count}")
    if not count:
        raise SystemExit("no eligible studied lines")
    a.snapshot.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
    manifest["research_lines"] = {
        "source": a.source_label, "source_sha256": sha(a.research),
        "adopted": count, "minimum_pv_plies": minimum,
        "policy": "Only previously adopted, non-disputed studies; legal completed research PV.",
    }
    manifest["policy"] = "Adopted long-search positions are direct decisions with validated saved PV; new candidates are never auto-promoted."
    manifest["output_sha256"] = sha(a.snapshot)
    a.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["research_lines"], ensure_ascii=False))

if __name__ == "__main__":
    main()
