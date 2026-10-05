"""Regression tests for exact OpeningBook outcome feedback."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "book"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from apply_book_feedback import load_book, load_feedback, update
from book_feedback_arena import parse_book_hit_info
from extract_book_feedback import collect

assert parse_book_hit_info(
    "info string opening_book hit move 7g7f samples 20 score_milli 500"
) == {"move": "7g7f", "samples": 20, "score_milli": 500}
assert parse_book_hit_info("info depth 3 nodes 100") is None

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    book = root / "book.tsv"
    book.write_text(
        "# shogi-ai opening book v1: key move samples wins draws losses score_milli weight\n"
        "111\t7g7f\t20\t10\t0\t10\t500\t1000\n"
        "222\t2g2f\t20\t10\t0\t10\t500\t1000\n",
        encoding="utf-8",
    )
    samples = root / "samples.tsv"
    hits = root / "hits.tsv"
    sample_rows = []
    hit_rows = ["# game_id\tply\tengine\tmove\tprior_samples\tprior_score_milli"]
    for i in range(8):
        sample_rows.append(f"g{i}\tbook-feedback\t1\t111\tsfen\t7g7f\t-1")
        hit_rows.append(f"g{i}\t1\tA\t7g7f\t20\t500")
    for i in range(8, 16):
        sample_rows.append(f"g{i}\tbook-feedback\t1\t222\tsfen\t2g2f\t1")
        hit_rows.append(f"g{i}\t1\tA\t2g2f\t20\t500")
    samples.write_text("\n".join(sample_rows) + "\n", encoding="utf-8")
    hits.write_text("\n".join(hit_rows) + "\n", encoding="utf-8")

    feedback, match = load_feedback(samples, hits)
    assert match["matched_hits"] == 16, match
    updated, report = update(load_book(book), feedback, 4, 0.5, 1.35, False)
    by_key = {entry.key: entry for entry in updated}
    assert by_key[111].weight < 1000, by_key[111]
    assert by_key[222].weight > 1000, by_key[222]
    assert by_key[111].losses == 42
    assert by_key[222].wins == 42
    assert report["feedback_entries_matched"] == 2

    arena_dir = root / "arena"
    arena_dir.mkdir()
    arena = {
        "details": [{
            "winner": "A",
            "a_black": True,
            "reason": "resign",
            "moves": ["7g7f", "3c3d"],
            "book_hits": [{
                "ply": 1,
                "engine": "A",
                "move": "7g7f",
                "samples": 20,
                "score_milli": 500,
            }],
        }]
    }
    (arena_dir / "x.json").write_text(json.dumps(arena), encoding="utf-8")
    games, exact_hits, stats = collect(arena_dir)
    assert len(games) == 1 and games[0][1] == "black"
    assert exact_hits[0][1:4] == (1, "A", "7g7f")
    assert stats["book_hits"] == 1

print("PASS book feedback: exact hits, W/D/L merge, weak-line suppression and recovery")
