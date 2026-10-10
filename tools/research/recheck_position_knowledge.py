#!/usr/bin/env python3
"""Read-only, same-time recheck of every adopted research PV with the current engine."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "position-knowledge-v1.tsv"
MANIFEST = ROOT / "position-knowledge-v1.manifest.json"

def read_rows():
    manifest = json.loads(MANIFEST.read_text(encoding="utf8"))
    raw = KNOWLEDGE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["output_sha256"]:
        raise ValueError("Adopted knowledge hash does not match manifest")
    rows = []
    for line in raw.decode("utf8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) != 14 or p[10] != "research_decision":
            raise ValueError("Unexpected adopted knowledge format")
        rows.append(dict(
            index=len(rows), sfen=p[0], bestmove=p[1],
            old_ms=int(p[4]), old_depth=int(p[5]), old_nodes=int(p[6]),
            old_score_kind=p[7], old_score_value=int(p[8]),
            id=p[11], old_pv=p[12].split(), moves=p[13].split(),
            knowledge_sha256=manifest["output_sha256"]))
    if len(rows) != manifest["adopted_positions"] or len(rows) != 153:
        raise ValueError("Adopted knowledge count mismatch")
    if len({x["sfen"] for x in rows}) != len(rows):
        raise ValueError("Duplicate position in adopted snapshot")
    return rows

def validate():
    import shogi
    rows = read_rows()
    for r in rows:
        b = shogi.Board()
        for move in r["moves"]:
            m = shogi.Move.from_usi(move)
            if m not in b.legal_moves:
                raise ValueError("Illegal history for " + r["id"] + " " + move)
            b.push(m)
        if " ".join(b.sfen().split()[:3]) != r["sfen"]:
            raise ValueError("History and position differ for " + r["id"])
        if not r["old_pv"] or r["old_pv"][0] != r["bestmove"]:
            raise ValueError("Stored research PV first move mismatch " + r["id"])
        for move in r["old_pv"]:
            m = shogi.Move.from_usi(move)
            if m not in b.legal_moves:
                raise ValueError("Illegal stored research PV for " + r["id"] + " " + move)
            b.push(m)
    print("Validated original histories and all existing research PVs:", len(rows), flush=True)

def study(index, engine, output, override_ms=None):
    from run_opening20 import Usi
    rows = read_rows()
    r = rows[index]
    ms = int(override_ms) if override_ms is not None else (60000 if r["old_ms"] < 120000 else 3000000)
    if not 100 <= ms <= 3000000:
        raise ValueError("Invalid study duration")
    e = Usi(engine, KNOWLEDGE)
    try:
        # CRITICAL: previous research decisions otherwise force the old bestmove.
        # This is an independent search using the same engine and position,
        # with no stored research move or continuation allowed to influence it.
        e.send("setoption name PositionKnowledge value false")
        e.send("setoption name OpeningRandomNonLance value false")
        e.send("setoption name AdaptiveLongThink value false")
        e.send("isready")
        e.wait("readyok", 30)
        if index == 0:
            print("Independent PV recheck: PositionKnowledge=false, OpeningRandomNonLance=false", flush=True)
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(prefix="pv-check-", suffix=".json", delete=False) as temp:
            intermediate = temp.name
        try:
            new = e.research(r, ms, intermediate)
        finally:
            Path(intermediate).unlink(missing_ok=True)
    finally:
        e.close()
    pv = new.get("final", {}).get("pv") or [new["bestmove"]]
    common = 0
    for a, b in zip(r["old_pv"], pv):
        if a != b:
            break
        common += 1
    result = dict(
        id=r["id"], index=index, sfen=r["sfen"], source_history_plies=len(r["moves"]),
        original_ms=r["old_ms"], research_ms_requested=ms,
        old_move=r["bestmove"], new_move=new["bestmove"],
        same_first_move=(r["bestmove"] == new["bestmove"]),
        old_pv=r["old_pv"], new_pv=pv, matching_prefix_plies=common,
        same_full_saved_line=(common == len(r["old_pv"]) and len(pv) >= len(r["old_pv"])),
        old_score={"kind":r["old_score_kind"],"value":r["old_score_value"],"depth":r["old_depth"],"nodes":r["old_nodes"]},
        new_score={key:new.get("final", {}).get(key) for key in ["score_type","score_value","depth","nodes","time"]},
        new_elapsed_seconds=new["elapsed_seconds"], new_move_changes=new["move_changes"],
        knowledge_sha256=r["knowledge_sha256"], knowledge_used=False, completed=bool(new["completed"]),
        engine_label="KUMOJI v2.0.7", research_adopted=False)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n",encoding="utf8")
    print("CHECKED",r["id"],"first_same=",result["same_first_move"],
          "prefix=",common,"/",len(r["old_pv"]),"newpv=",len(pv), flush=True)

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode", choices=["validate","study"])
    p.add_argument("--index", type=int,default=0)
    p.add_argument("--engine",default="build/kumoji")
    p.add_argument("--output",default="recheck.json")
    p.add_argument("--ms-override",type=int)
    a=p.parse_args()
    if a.mode=="validate": validate()
    else:study(a.index,a.engine,a.output,a.ms_override)
