#!/usr/bin/env python3
"""Adopt precisely two owner-approved 40-position, 50-minute studies.

Keep the existing 73 adopted lines, validate original histories and every
saved research variation, and record source/archive hashes for reproducibility.
"""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import shogi

SNAPSHOT = Path("position-knowledge-v1.tsv")
MANIFEST = Path("position-knowledge-v1.manifest.json")
REQUEST = Path(".github/timebox80-adoption-request.json")
AUDIT = Path("build/timebox80-adoption-audit.json")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def play_checked(board, moves, label):
    if not isinstance(moves, list):
        raise ValueError(f"{label}: moves must be an array")
    for i, raw in enumerate(moves, 1):
        if not isinstance(raw, str) or not raw or any(c in raw for c in "\t\n"):
            raise ValueError(f"{label}: malformed move {i}: {raw!r}")
        try:
            move = shogi.Move.from_usi(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label}: invalid USI move {i}: {raw}") from exc
        if move not in board.legal_moves:
            raise ValueError(f"{label}: illegal move {i}: {raw}")
        board.push(move)


def main():
    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert req["request_id"] == "owner-20261010-adopt-timebox80"
    assert req["old_positions"] == 73 and req["add_positions"] == 80
    sources = req["sources"]
    assert [str(x["run"]) for x in sources] == ["37862974704", "37907909827"]
    old = SNAPSHOT.read_text(encoding="utf-8")
    lines = [s for s in old.splitlines() if s and not s.startswith("#")]
    old_m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len(lines) == old_m["adopted_positions"] == 73
    assert all(len(line.split("\t")) == 14 and line.split("\t")[10] == "research_decision" for line in lines)
    assert old_m["output_sha256"] == sha(SNAPSHOT)
    before_sha = sha(SNAPSHOT)
    known = {line.split("\t")[0] for line in lines}
    assert len(known) == 73
    all_new, provenance, audit = [], [], []

    for source in sources:
        run = str(source["run"])
        asset = f"timebox40-records-{run}.json.gz"
        archive = Path("build/timebox80-source") / asset
        assert sha(archive) == source["sha256"], f"{run}: release source hash changed"
        with gzip.open(archive, "rt", encoding="utf-8") as f:
            obj = json.load(f)
        assert str(obj["run"]) == run
        assert obj["received"] == obj["completed"] == 40
        assert obj["knowledge_adopted"] is False
        studies = obj["results"]
        selected = obj["selected"]["positions"]
        assert len(studies) == len(selected) == 40
        selected_by_id = {x["id"]: x for x in selected}
        assert len(selected_by_id) == 40
        assert len({x["id"] for x in studies}) == 40
        run_audit = []
        for r in sorted(studies, key=lambda x: x["id"]):
            sid = r["id"]
            assert sid in selected_by_id, f"unselected source {sid}"
            assert r.get("completed") is True
            assert r["research_ms_requested"] == 3000000
            assert 2990 <= r["elapsed_seconds"] <= 3020
            key = r["sfen"]
            assert isinstance(key, str) and len(key.split()) == 3
            assert key == selected_by_id[sid]["sfen"]
            assert key not in known, f"already accepted / duplicate {sid}"
            history = r["history_moves"]
            assert isinstance(history, list) and 16 <= len(history) <= 300
            board = shogi.Board()
            play_checked(board, history, sid + " history")
            assert " ".join(board.sfen().split()[:3]) == key, f"{sid} inconsistent position"
            info = r["final"]
            assert isinstance(info.get("depth"), int) and info["depth"] > 0
            assert isinstance(info.get("nodes"), int) and info["nodes"] > 0
            assert info["score_type"] in ("cp", "mate")
            assert isinstance(info["score_value"], int)
            move = r["bestmove"]
            pv = info.get("pv")
            assert isinstance(pv, list) and len(pv) >= 3 and pv[0] == move
            play_checked(board, pv, sid + " research pv")
            changes = r["move_changes"]
            assert changes and changes[-1]["move"] == move
            last_change = float(changes[-1]["seconds"])
            assert 0 <= last_change <= r["elapsed_seconds"]
            stable_ms = round((r["elapsed_seconds"] - last_change) * 1000)
            values = [
                key, move, f"owner-adopted-timebox80-{run}", "1",
                str(round(r["elapsed_seconds"] * 1000)), str(info["depth"]),
                str(info["nodes"]), info["score_type"], str(info["score_value"]),
                str(stable_ms), "research_decision", f"timebox40-{run}-{sid}",
                " ".join(pv), " ".join(history),
            ]
            assert len(values) == 14 and all("\t" not in s and "\n" not in s for s in values)
            all_new.append("\t".join(values))
            known.add(key)
            run_audit.append(dict(id=sid, move=move, depth=info["depth"],
                                  pv_plies=len(pv), history_plies=len(history)))
        provenance.append({
            "request": "User 2026-10-10: adopt 80 completed 50-minute studies",
            "research_run": run,
            "research_asset": asset,
            "research_source_sha256": sha(archive),
            "positions": 40,
            "mode": "research_decision",
            "approval_state": "explicit-owner-approval",
        })
        audit.extend(run_audit)

    assert len(all_new) == 80 and len(known) == 153
    SNAPSHOT.write_text(old.rstrip("\n") + "\n" + "\n".join(all_new) + "\n", encoding="utf-8")
    old_m["adopted_positions"] = 153
    old_m["output_sha256"] = sha(SNAPSHOT)
    old_m.setdefault("owner_approved_research_additions", []).extend(provenance)
    old_m["policy"] = ("Original 73 preserved. 80 completed 50-minute research positions "
                        "explicitly approved 2026-10-10, with validated original histories "
                        "and legal final PV. New future candidates are never auto-promoted.")
    MANIFEST.write_text(json.dumps(old_m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps({
        "before_positions": 73, "added_positions": 80, "after_positions": 153,
        "old_sha256": before_sha, "new_sha256": sha(SNAPSHOT),
        "sources": provenance, "positions": audit,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("TIMEBOX80_ADOPTION_OK: 73 + 80 = 153; SHA256", sha(SNAPSHOT), flush=True)


if __name__ == "__main__":
    main()
