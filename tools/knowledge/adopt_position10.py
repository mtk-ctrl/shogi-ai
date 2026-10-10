#!/usr/bin/env python3
"""Adopt precisely the owner's ten completed 50-minute studies (run 38091143128).

Input is the original per-lane Actions artifacts, never re-run or inferred scores.
No change to the current evaluation or search engine is made here.
"""
import gzip
import hashlib
import json
from pathlib import Path
import shogi

RUN = "38091143128"
ENGINE = "c84ea3ff0ba3a34f06cb29d7c891365854a8ca27"
OLD_KNOWLEDGE = "234173daefd3d0f8ccb205776b5c71ed8e875b5446b3620196cf91a3067b4b1c"
EXPECTED = {
    "kumoji-20261011a-E08": "9e873ff35b443b50695c7b6a39b1c0e8bbed620eeedb957421c5726e80d75303",
    "kumoji-20261011a-E09": "fa752e69263b334af2180c025d8b9a53c129f29d6131180e1a7a1cae595d129c",
    "kumoji-20261011a-E10": "690b29a73ea7069b19524d275940007eaadb9574ea92f69a804aacaa304a1587",
    "kumoji-20261011a-M04": "72e149aeef34cdf1d5c3766765145ffb79fca68b1df1f383386063f521d0c334",
    "kumoji-20261011a-M05": "8a80d1969edec3300194594748e53f047206c00923bae61209fffd6c8b9a8c95",
    "kumoji-20261011a-M06": "f440837800b7ee81c38d4c6f2e6f4a7cb775c5bca19de9b9b01ba58ec04ff5b7",
    "kumoji-20261011a-M07": "f39d1d9dc7a60bec1cc6d2cc8ac58808bf57c727add46c56a0e514f1e514e",
    "kumoji-20261011a-O01": "e6240e8b698a7a34640c1f37fbb5676c341b1a1a0517c2e2f9f214ce40705f1d",
    "kumoji-20261011a-O02": "9418b53739cab20fd2744b7eed034dd55a35ddedbd67e6e6253651b04d0462b6",
    "kumoji-20261011a-O03": "99e7026510978bd4513821a87c9e0fdd57482a97ca2897551ddbcd2876c9b13e",
}
BASE = Path("position-knowledge-v1.tsv")
MANIFEST = Path("position-knowledge-v1.manifest.json")
RECORD = Path("build") / ("research10-" + RUN + ".json.gz")
AUDIT = Path("build") / ("research10-adoption-audit-" + RUN + ".json")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def legal_history(moves, label):
    board = shogi.Board()
    for i, name in enumerate(moves, 1):
        move = shogi.Move.from_usi(name)
        if move not in board.legal_moves:
            raise ValueError(f"{label}: illegal history ply {i}: {name}")
        board.push(move)
    return board


def main():
    old = BASE.read_text(encoding="utf8")
    old_manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    known = {line.split("\t", 1)[0] for line in old.splitlines() if line and not line.startswith("#")}
    assert len(known) == old_manifest["adopted_positions"] == 153
    assert old_manifest["output_sha256"] == sha(BASE) == OLD_KNOWLEDGE
    files = sorted(Path("build/position10-source").rglob("result.json"))
    assert len(files) == 10, f"expected exactly ten independent artifacts, got {len(files)}"
    records = [json.loads(p.read_text(encoding="utf8")) for p in files]
    assert {r["id"] for r in records} == set(EXPECTED)
    for path, row in zip(files, records):
        assert sha(path) == EXPECTED[row["id"]], "original result SHA256 mismatch"
    selection = json.loads(Path("selection10.json").read_text(encoding="utf8"))
    positions = {p["id"]: p for p in selection["positions"]}
    assert set(positions) == set(EXPECTED)
    assert selection["engine_commit"] == ENGINE
    assert selection["knowledge_sha256"] == OLD_KNOWLEDGE
    assert selection["source_run"] == 38037253689
    assert selection["request"]["positions"] == 10
    assert selection["request"]["minutes"] == 50
    assert selection["request"]["adopt"] is False
    added, audit = [], []
    for row in sorted(records, key=lambda r: r["id"]):
        sid = row["id"]
        selected = positions[sid]
        assert row["completed"] is True
        assert row["research_ms_requested"] == 3000000
        assert 2990 <= row["elapsed_seconds"] <= 3020
        assert row["sfen"] == selected["sfen"]
        assert row["history_moves"] == selected["history_moves"]
        key = row["sfen"]
        assert len(key.split()) == 3 and key not in known
        board = legal_history(row["history_moves"], sid)
        assert " ".join(board.sfen().split()[:3]) == key
        final = row["final"]
        assert final["depth"] > 0 and final["nodes"] > 0
        assert final["score_type"] in ("cp", "mate")
        assert isinstance(final["score_value"], int)
        pv = final["pv"]
        assert len(pv) >= 3 and pv[0] == row["bestmove"]
        for n, usi in enumerate(pv, 1):
            move = shogi.Move.from_usi(usi)
            assert move in board.legal_moves, f"{sid}: illegal research ply {n}: {usi}"
            board.push(move)
        changes = row["move_changes"]
        assert changes and changes[-1]["move"] == row["bestmove"]
        stable_ms = round((row["elapsed_seconds"] - changes[-1]["seconds"]) * 1000)
        assert stable_ms >= 0
        fields = [
            key, row["bestmove"], "owner-adopted-position10-" + RUN, "1",
            str(round(row["elapsed_seconds"] * 1000)), str(final["depth"]),
            str(final["nodes"]), final["score_type"], str(final["score_value"]),
            str(stable_ms), "research_decision", "position10-" + RUN + "-" + sid,
            " ".join(pv), " ".join(row["history_moves"]),
        ]
        assert len(fields) == 14 and all("\t" not in f and "\n" not in f for f in fields)
        added.append("\t".join(fields))
        known.add(key)
        audit.append({"id": sid, "stage": selected["stage"], "bestmove": row["bestmove"],
                      "score": final["score_value"], "depth": final["depth"],
                      "nodes": final["nodes"], "stable_ms": stable_ms})
    assert len(added) == 10 and len(known) == 163
    # Keep the exact original result objects, including PV and score provenance.
    RECORD.parent.mkdir(exist_ok=True)
    with gzip.open(RECORD, "wt", encoding="utf8") as f:
        json.dump({"schema": "position10-results-v1", "run_id": RUN,
                   "selection": selection, "results": records, "received": 10,
                   "completed": 10, "missing": [], "knowledge_adopted": False},
                  f, ensure_ascii=False)
    BASE.write_text(old.rstrip("\n") + "\n" + "\n".join(added) + "\n", encoding="utf8")
    old_manifest["adopted_positions"] = 163
    old_manifest["output_sha256"] = sha(BASE)
    old_manifest.setdefault("owner_approved_research_additions", []).append({
        "request": "User 2026-10-11: save ten completed studies into adopted position knowledge",
        "research_run": RUN,
        "research_asset": RECORD.name,
        "research_source_sha256": sha(RECORD),
        "positions": 10,
        "mode": "research_decision",
        "source_engine_commit": ENGINE,
        "source_knowledge_sha256": OLD_KNOWLEDGE,
        "approval_state": "explicit-owner-approval",
    })
    old_manifest["policy"] = "153 prior accepted positions preserved; ten completed 50-minute studies explicitly approved 2026-10-11 with validated legal history and PV. Other research is not auto-adopted."
    MANIFEST.write_text(json.dumps(old_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    AUDIT.write_text(json.dumps({"run_id": RUN, "before": 153, "added": 10, "after": 163,
        "old_knowledge_sha256": OLD_KNOWLEDGE, "new_knowledge_sha256": sha(BASE),
        "source_archive_sha256": sha(RECORD), "positions": audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print("OWNER_APPROVED_POSITION10 153+10=163", sha(BASE), sha(RECORD), flush=True)

if __name__ == "__main__":
    main()
