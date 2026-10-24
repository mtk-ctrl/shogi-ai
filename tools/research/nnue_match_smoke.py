#!/usr/bin/env python3
"""Non-adoption comparison smoke: candidate NNUE vs same code with NNUE off.

This checks actual moves under a real USI arena, not playing-strength evidence.
Neither the game records nor the smoke summary may become selfplay teachers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_arena_options(data, candidate, baseline):
    # The standard arena explicitly adds RiskVerify=true when absent.
    # Verify that exact documented default, rather than accidentally
    # comparing an augmented live request to our pre-default dictionary.
    for side, requested in (("options_a", candidate), ("options_b", baseline)):
        expected = dict(requested, RiskVerify=True)
        if data.get(side) != expected:
            raise ValueError(f"{side} actual USI options differ from research plan")


def execute(engine, model, knowledge, out, games=2, max_plies=160):
    if not 2 <= games <= 4 or not 80 <= max_plies <= 400:
        raise ValueError("smoke scope: two to four games, 80..400 plies")
    for path in (engine, model, knowledge):
        if not Path(path).is_file():
            raise ValueError("missing fixed engine, NNUE model, or adopted knowledge")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("will not overwrite an existing smoke run")
    options = {
        "USI_Ponder": True, "AdaptiveLongThink": True,
        "PositionKnowledge": True, "PositionKnowledgeFile": str(Path(knowledge).resolve()),
        "OpeningRandomNonLance": True,
    }
    a = dict(options, EvalNeural=True, EvalNeuralFile=str(Path(model).resolve()))
    b = dict(options, EvalNeural=False)
    raw = out / "games.json"
    cmd = [sys.executable, str(ROOT / "benchmarks/arena.py"),
           "--engine-a", str(Path(engine).resolve()),
           "--engine-b", str(Path(engine).resolve()),
           "--options-a", json.dumps(a),
           "--options-b", json.dumps(b),
           "--games", str(games),
           "--max-plies", str(max_plies),
           "--seed", "20261021", "--go-command", "go movetime 200",
           "--output", str(raw)]
    subprocess.run(cmd, cwd=ROOT, timeout=1200, check=True)
    data = json.loads(raw.read_text())
    if data.get("games") != games or len(data.get("details", [])) != games:
        raise ValueError("match did not produce all trial games")
    if data.get("illegal_games") != 0:
        raise ValueError("candidate has illegal games")
    assert_arena_options(data, a, b)
    for side in ("A", "B"):
        meta = data.get("position_knowledge", {}).get(side, {})
        if meta.get("available") is not True or meta.get("sha256") != sha(knowledge):
            raise ValueError("adopted position-knowledge file not proved for both engines")
    model_turns = [m for g in data["details"] for m in g.get("move_records", [])
                   if m["engine"] == "A"]
    if not model_turns or not any(m.get("search", {}).get("nodes", 0) > 0
                                  for m in model_turns):
        raise ValueError("candidate did not actually search moves")
    candidate_static = [m.get("search", {}).get("phase_static_cp_black")
                        for m in model_turns]
    candidate_static = [v for v in candidate_static if type(v) is int]
    baseline_static = [
        m.get("search", {}).get("phase_static_cp_black")
        for g in data["details"] for m in g.get("move_records", [])
        if m["engine"] == "B"]
    baseline_static = [v for v in baseline_static if type(v) is int]
    result = {
        "schema": "nnue-independent-game-smoke-v1",
        "candidate_static_cp_span": (max(candidate_static)-min(candidate_static)
                                     if candidate_static else None),
        "baseline_static_cp_span": (max(baseline_static)-min(baseline_static)
                                    if baseline_static else None),
        "static_range_caveat": "different turns/boards; diagnostic hint, NOT paired position comparison",
        "purpose": "actual search and legal move smoke, not strength/adoption",
        "engine_sha256": sha(engine), "model_sha256": sha(model),
        "knowledge_sha256": sha(knowledge),
        "games": games, "total_plies": sum(g["plies"] for g in data["details"]),
        "nnue_actual_searched_moves": sum(m.get("search", {}).get("nodes", 0) > 0
                                           for m in model_turns),
        "illegal_games": 0,
        "winner_counts": {"NNUE": data["wins_a"], "baseline": data["wins_b"],
                          "draw_or_limit": data["draws"]},
        "status": "smoke_complete_strength_not_established",
        "model_adopted": False,
        "game_record_sha256": sha(raw),
    }
    (out / "smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--knowledge", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--games", type=int, default=2)
    p.add_argument("--max-plies", type=int, default=160)
    a = p.parse_args()
    print(json.dumps(execute(a.engine, a.model, a.knowledge, a.out,
                             a.games, a.max_plies), ensure_ascii=False))
