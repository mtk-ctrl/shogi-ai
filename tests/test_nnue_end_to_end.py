#!/usr/bin/env python3
"""Full, cheap, *synthetic* archive -> deep study -> NNUE -> native search smoke.

All game origins and outcomes are constructed solely for testing the plumbing.
Their repeated kings are NOT actual independently earned playing strength.
"""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shogi
from tools.research.nnue_cycle import execute


def make_archive(directory):
    starts = [
        ({"9i": "K", "5a": "k"}, ["9i8i", "5a4a", "8i9i", "4a5a"]),
        ({"1i": "K", "5a": "k"}, ["1i2i", "5a6a", "2i1i", "6a5a"]),
        ({"5i": "K", "9a": "k"}, ["5i6i", "9a8a", "6i5i", "8a9a"]),
    ]
    games = []
    for index, (pieces, cycle) in enumerate(starts):
        board = shogi.Board()
        board.clear()
        for sq, piece in pieces.items():
            board.set_piece_at(shogi.SQUARE_NAMES.index(sq), shogi.Piece.from_symbol(piece))
        start = board.sfen()
        rows = []
        for ply, token in enumerate(cycle * 3, 1):
            move = shogi.Move.from_usi(token)
            assert move in board.legal_moves, (index, ply, token)
            rows.append(dict(ply=ply, move=token, engine="A" if ply % 2 else "B",
                             side_to_move="black" if ply % 2 else "white", search={}))
            board.push(move)
        games.append(dict(schema_version=1, game_id=f"sample:{index}",
                          source_id="sample", source_game_index=index,
                          start_sfen=start, final_sfen=board.sfen(),
                          winner=None, reason="fourfold_repetition",
                          plies=12, a_black=True, moves=rows))
    data = "".join(json.dumps(game) + "\n" for game in games).encode()
    blob = gzip.compress(data, mtime=0)
    archive = directory / "played-games.jsonl.gz"
    archive.write_bytes(blob)
    manifest = {
        "schema_version": 1, "archive": archive.name,
        "archive_sha256": hashlib.sha256(blob).hexdigest(),
        "archive_bytes": len(blob), "games": len(games), "plies": 36,
        "run_id": "synthetic-nnue-only",
        "sources": [{"source_id": "sample", "metadata": {
            "engine_a": "KUMOJI v2.0.21", "engine_b": "KUMOJI v2.0.21",
            "max_plies": 400, "go_command": "go depth 1"}}]
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 tests/test_nnue_end_to_end.py build/shogi-ai")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        archive = root / "archive"
        archive.mkdir()
        make_archive(archive)
        args = SimpleNamespace(
            archive_dir=[archive], engine=Path(sys.argv[1]).resolve(),
            knowledge=Path("position-knowledge-v1.tsv").resolve(),
            output_dir=root / "research-output",
            parent_commit="0" * 40, max_cases=1, medium_ms=1000,
            long_ms=2000, branch_ms=1000, expected_positions=163,
            hidden=16, epochs=3, seed=20261021,
        )
        result = execute(args)
        assert result["state"] == "research_candidate_ready_for_independent_evaluation"
        assert result["regular_labels"] > 0
        assert result["study_completed"] == 1
        assert result["native_verification"]["search_completed"] is True
        assert result["independent_matches"] == "not_run"
        # Idempotency: all completed cases, dataset and training hashes unchanged.
        repeated = execute(args)
        assert repeated["source_plan_sha256"] == result["source_plan_sha256"]
        assert repeated["model_sha256"] == result["model_sha256"]
        # This is synthetic observation; no strength improvement claimed.


if __name__ == "__main__":
    main()
