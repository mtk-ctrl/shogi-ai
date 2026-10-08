#!/usr/bin/env python3
"""Explicit owner-approved adoption of one completed Opening20 50m run.

Merge exactly 20 legal research decisions into the active 53-entry snapshot.
Preserve previous evidence and the full source study for reproducibility.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
import shogi

MOVE = re.compile(r"^(?:[1-9][a-i][1-9][a-i]\+?|[PLNSGBR]\*[1-9][a-i])$")

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def valid_play(board, moves, label):
    for i, raw in enumerate(moves, 1):
        if not isinstance(raw, str) or not MOVE.fullmatch(raw):
            raise ValueError(f"{label}: bad USI move at {i}: {raw}")
        move=shogi.Move.from_usi(raw)
        if move not in board.legal_moves:
            raise ValueError(f"{label}: illegal move at {i}: {raw}")
        board.push(move)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--summary",type=Path,required=True)
    ap.add_argument("--snapshot",type=Path,default=Path("position-knowledge-v1.tsv"))
    ap.add_argument("--manifest",type=Path,default=Path("position-knowledge-v1.manifest.json"))
    ap.add_argument("--audit",type=Path,default=Path("build/opening20-adoption-audit.json"))
    a=ap.parse_args()
    source=json.loads(a.summary.read_text(encoding="utf-8"))
    assert str(source.get("run_id"))=="37833560865", "wrong research run"
    assert source.get("expected")==20 and source.get("completed")==20 and source.get("received")==20
    studies=source.get("research_records")
    assert isinstance(studies,list) and len(studies)==20

    old_text=a.snapshot.read_text(encoding="utf-8")
    old_rows=[ln.split("\t") for ln in old_text.splitlines() if ln and not ln.startswith("#")]
    assert len(old_rows)==53, f"must preserve 53 adopted records, found {len(old_rows)}"
    assert all(len(f)==14 and f[10]=="research_decision" for f in old_rows)
    known={f[0] for f in old_rows}
    old_manifest=json.loads(a.manifest.read_text(encoding="utf-8"))
    assert old_manifest.get("adopted_positions")==53
    assert old_manifest.get("output_sha256")==digest(a.snapshot), "existing snapshot checksum mismatch"

    new_rows=[]
    audit=[]
    seen=set()
    for r in sorted(studies,key=lambda x:x["id"]):
        rid=r["id"]
        assert rid.startswith("kumoji-160-") and rid[-3:].isdigit()
        assert 1<=int(rid[-3:])<=20 and rid not in seen
        seen.add(rid)
        assert r.get("completed") is True
        assert r.get("research_ms_requested")==3000000
        assert 2990<=r.get("elapsed_seconds",0)<=3020
        key=r.get("sfen")
        assert isinstance(key,str) and len(key.split())==3
        assert key not in known, f"position already adopted: {rid}"
        known.add(key)
        history=r.get("history_moves")
        assert isinstance(history,list) and 25<=len(history)<=180
        historical=shogi.Board()
        valid_play(historical,history,rid+" history")
        assert " ".join(historical.sfen().split()[:3])==key, f"history/key mismatch at {rid}"
        info=r.get("final")
        assert isinstance(info,dict) and isinstance(info.get("depth"),int) and info["depth"]>0
        assert isinstance(info.get("nodes"),int) and info["nodes"]>0
        move=r.get("bestmove")
        pv=info.get("pv")
        assert isinstance(pv,list) and len(pv)>=3 and pv[0]==move
        valid_play(historical,pv,rid+" final research line")
        assert info.get("score_type") in ("cp","mate")
        assert isinstance(info.get("score_value"),int)
        changes=r.get("move_changes")
        assert isinstance(changes,list) and changes
        assert changes[-1]["move"]==move
        stable_ms=int(max(0,round((r["elapsed_seconds"]-changes[-1]["seconds"])*1000)))
        values=[
            key,move,"owner-adopted-opening20-37833560865","1",
            str(round(r["elapsed_seconds"]*1000)),str(info["depth"]),str(info["nodes"]),
            info["score_type"],str(info["score_value"]),str(stable_ms),
            "research_decision",f"opening20-37833560865-{rid}",
            " ".join(pv)," ".join(history)]
        assert all("\t" not in f and "\n" not in f for f in values)
        new_rows.append("\t".join(values))
        audit.append({"position":rid,"bestmove":move,"research_depth":info["depth"],
                      "research_ms":values[4],"pv_plies":len(pv),"stable_ms":stable_ms,
                      "history_plies":len(history)})
    assert seen=={f"kumoji-160-{i:03d}" for i in range(1,21)}
    assert len({s.split("\t",1)[0] for s in new_rows})==20
    old_count=len(old_rows)
    new_text=old_text.rstrip("\n")+"\n"+"\n".join(new_rows)+"\n"
    a.snapshot.write_text(new_text,encoding="utf-8")
    final_sha=digest(a.snapshot)
    manifest=old_manifest
    manifest["adopted_positions"]=old_count+len(new_rows)
    manifest["output_sha256"]=final_sha
    append=manifest.setdefault("owner_approved_research_additions",[])
    append.append({
        "request":"User 2026-10-09: adopt completed 50-minute opening20 positions",
        "research_run":"37833560865",
        "research_asset":"opening20-summary-37833560865",
        "research_source_sha256":digest(a.summary),
        "positions":len(new_rows),
        "mode":"research_decision",
        "source_engine":"KUMOJI v2.0.4 frozen at run 37833560865",
        "approval_state":"explicit-owner-approval",
        "followup_006_012_019":"Additional 30m independent research is tracked separately; not yet used to replace these adopted 50m moves."
    })
    manifest["policy"]="Original 53 preserved. Owner expressly approved the additional 20 completed 50-minute opening studies as direct research decisions; future research is never auto-promoted."
    a.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    a.audit.parent.mkdir(parents=True,exist_ok=True)
    a.audit.write_text(json.dumps({
        "snapshot_entries_before":old_count,"added":len(new_rows),"snapshot_entries_after":old_count+len(new_rows),
        "new_snapshot_sha256":final_sha,"original_snapshot_sha256":old_manifest["output_sha256"],
        "source_sha256":digest(a.summary),"positions":audit
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("OPENING20_ADOPT_OK: preserved 53, appended 20, total 73, SHA256",final_sha,flush=True)

if __name__=="__main__":
    main()
