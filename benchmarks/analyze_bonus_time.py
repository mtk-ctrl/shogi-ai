#!/usr/bin/env python3
"""Validate complete bonus-time records and export representative changed moves."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import sys
import shogi
from bonus_time_match import summarize


def analyze(directory):
    directory = Path(directory)
    files = sorted(directory.glob("pair-*-half-*.json.gz"))
    games = [json.load(gzip.open(path, "rt", encoding="utf-8")) for path in files]
    assert games and len(games) % 2 == 0
    games.sort(key=lambda g: (g["pair"], g["half"]))
    problems, manifest, extended = [], [], []
    for i, game in enumerate(games):
        assert game["pair"] == i // 2 and game["half"] == i % 2
        if i % 2:
            assert game["pair_seed"] == games[i-1]["pair_seed"]
            assert game["a_black"] != games[i-1]["a_black"]
        assert "illegal_by" not in game and game["plies"] == len(game["moves"])
        assert len(game["move_records"]) == game["plies"]
        a = game["decisions"]["A"]
        ext = [d for d in a if d["extended"]]
        assert len(ext) == game["bonus_used"] <= game.get("max_bonus_uses", 5)
        assert [d["coupon"] for d in ext] == list(range(1, len(ext)+1))
        board = shogi.Board()
        decisions = {(side, d["ply"]):d for side in ("A", "B") for d in game["decisions"][side]}
        for index, token in enumerate(game["moves"]):
            record = game["move_records"][index]
            assert record["move"] == token and record["ply"] == index+1
            assert record["side_to_move"] == ("black" if board.turn == 0 else "white")
            assert record["engine"] == ("A" if (board.turn == 0) == game["a_black"] else "B")
            decision = decisions[(record["engine"], index+1)]
            assert decision["final"]["bestmove"] == token
            assert not decision["extended"] or record["engine"] == "A"
            move = shogi.Move.from_usi(token)
            assert move in board.legal_moves
            if decision["extended"]:
                assert not decision["probe"]["book_hit"]
                assert decision["changed_move"] == (token != decision["probe"]["bestmove"])
                assert decision["final"]["elapsed_ms"] <= game.get("bonus_ms", 30000) + 500
                assert shogi.Move.from_usi(decision["probe"]["bestmove"]) in board.legal_moves
                extended.append(decision)
                if decision["changed_move"]:
                    problems.append({"id": f"{directory.name}-p{game['pair']:03d}-h{game['half']}-ply{index+1}",
                                     "tags": ["bonus-time", decision["reason"], "own-shallow-deep-disagreement"],
                                     "moves": game["moves"][:index], "sfen": board.sfen(),
                                     "winner": game["winner"], "a_black": game["a_black"],
                                     "probe": decision["probe"], "deep": decision["final"],
                                     "note": "Self-generated hypothesis, not a proven correct-move label."})
            board.push(move)
        assert board.sfen() == game["final_sfen"]
    for path in files:
        manifest.append({"path": path.name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    summary = json.loads((directory / "summary.json").read_text())
    recomputed = summarize(games)
    assert all(summary[k] == v for k,v in recomputed.items())
    normal = [d["final"] for g in games for side in ("A", "B") for d in g["decisions"][side] if not d["extended"]]
    incomplete = {side: sum(d["probe"].get("depth") == 0 and not d["probe"].get("book_hit")
                           and "score_mate" not in d["probe"]
                           for g in games for d in g["decisions"][side]) for side in ("A", "B")}
    baseline_time = [sum(d["final"]["elapsed_ms"] for d in g["decisions"]["B"]) for g in games]
    a_time = [sum(d["final"]["elapsed_ms"] for d in g["decisions"]["A"]) for g in games]
    def dist(values):
        return {"mean": statistics.mean(values), "median": statistics.median(values),
                "min": min(values), "max": max(values)} if values else None
    extra = {"verified_games": len(games), "verified_plies": sum(g["plies"] for g in games),
             "unique_full_sequences": len({tuple(g["moves"]) for g in games}),
             "unique_first24_prefixes": len({tuple(g["moves"][:24]) for g in games}),
             "reasons": dict(Counter(g["reason"] for g in games)),
             "normal_depths": dict(Counter(str(d.get("depth")) for d in normal)),
             "incomplete_probe_depth1_by_engine": incomplete,
             "extended_probe_depths": dict(Counter(str(d["probe"].get("depth")) for d in extended)),
             "extended_deep_depths": dict(Counter(str(d["final"].get("depth")) for d in extended)),
             "a_compute_ms_per_game": dist(a_time), "b_compute_ms_per_game": dist(baseline_time),
             "bonus_count_distribution": dict(Counter(str(g["bonus_used"]) for g in games)),
             "changed_positions": len(problems), "raw_manifest": manifest}
    (directory / "analysis.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2)+"\n")
    # Preserve all changed coupon decisions as research cases, without assigning
    # correctness from win/loss or from this engine's own deeper evaluation.
    (directory / "changed-positions.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in problems))
    print(json.dumps({k:v for k,v in extra.items() if k != "raw_manifest"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    analyze(parser.parse_args().directory)
