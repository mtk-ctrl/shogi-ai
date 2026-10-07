#!/usr/bin/env python3
"""Archive played moves from arena JSON; never persist PV or unplayed candidates."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

SCHEMA = 1
SEARCH_FIELDS = (
    "depth", "seldepth", "time", "elapsed_ms", "nodes", "nps",
    "score_cp_stm", "score_black_cp", "score_mate_stm", "score_black_mate",
    "score_lowerbound", "score_upperbound",
    "full_nodes", "cutoffs", "tt_probes", "tt_hits",
    "experience_probes", "experience_hits",
    "knowledge_probes", "knowledge_hits", "knowledge_promotions",
    "knowledge_disabled_repetition", "qnodes", "qcutoffs",
    "long_think_used", "long_think_reason", "long_think_base_ms", "long_think_max_ms",
)
META_FIELDS = (
    "telemetry_schema_version", "engine_a", "engine_b", "sha256_a", "sha256_b",
    "options_a", "options_b", "seed", "max_plies", "go_command",
    "position_knowledge",
    "response_watchdog_seconds", "timing_note", "start_sfen",
)
MOVE_FIELDS = (
    "ply", "side_to_move", "engine", "move", "in_check_before",
    "legal_moves_before", "is_capture", "is_promotion", "is_drop", "gave_check",
)
GAME_FIELDS = (
    "winner", "reason", "plies", "a_black", "start_sfen", "final_sfen", "illegal_by",
)


def clean_search(search):
    search = search or {}
    row = {k: search[k] for k in SEARCH_FIELDS if k in search}
    score_count = sum(row.get(k) is not None for k in ("score_cp_stm", "score_mate_stm"))
    # Legacy readers could retain both an old cp score and a newer mate score.
    # Keep the original values; their order cannot be inferred from this row.
    row["score_status"] = "ambiguous" if score_count == 2 else "recorded" if score_count else "not_recorded"
    # Absence of a score is not a zero evaluation.
    if not score_count:
        row["score_cp_stm"] = None
        row["score_mate_stm"] = None
    return row


def archive(inputs, output_dir, run_id=None, ref_a=None, ref_b=None):
    games = []
    sources = []
    seen = set()
    plies = scored = ambiguous = no_telemetry = 0
    for path in inputs:
        path = Path(path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            raise ValueError("duplicate input source: " + str(path))
        seen.add(digest)
        data = json.loads(raw)
        details = data.get("details")
        if not isinstance(details, list):
            raise ValueError("missing game details: " + str(path))
        declared = data.get("games")
        if isinstance(declared, int) and declared != len(details):
            raise ValueError("game count mismatch: " + str(path))
        metadata = {k: data[k] for k in META_FIELDS if k in data}
        sources.append({
            "source_id": digest, "file": path.name, "bytes": len(raw),
            "metadata": metadata,
            "provenance_note": "Only observed metadata is retained; absent engine/Book/Experience versions or file hashes remain unknown.",
        })
        for index, game in enumerate(details):
            moves = game.get("moves")
            if not isinstance(moves, list):
                raise ValueError("missing played moves: " + str(path))
            if "plies" in game and game["plies"] != len(moves):
                raise ValueError("ply count mismatch: " + str(path))
            records = game.get("move_records")
            if records is not None and len(records) != len(moves):
                raise ValueError("move telemetry count mismatch: " + str(path))
            selected = []
            for ply, move in enumerate(moves, 1):
                original = records[ply - 1] if records is not None else {}
                if original and (original.get("move") != move or original.get("ply") != ply):
                    raise ValueError("played move / telemetry mismatch: " + str(path))
                record = {k: original[k] for k in MOVE_FIELDS if k in original}
                record.update(ply=ply, move=move)
                search = clean_search(original.get("search"))
                record["search"] = search
                selected.append(record)
                plies += 1
                scored += search["score_status"] == "recorded"
                ambiguous += search["score_status"] == "ambiguous"
                no_telemetry += not bool(original)
            row = {k: game[k] for k in GAME_FIELDS if k in game}
            row.update(
                schema_version=SCHEMA, game_id=digest + ":" + str(index),
                source_id=digest, source_game_index=index, moves=selected,
            )
            # A terminal observation is separate from an actual played move.
            if "terminal_search" in game:
                row["terminal_search"] = clean_search(game["terminal_search"])
            games.append(row)
    if not games:
        raise ValueError("no games to archive")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "played-games.jsonl.gz"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with temporary.open("wb") as raw_out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as out:
                for game in games:
                    out.write((json.dumps(game, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        archive_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
        manifest = {
            "schema_version": SCHEMA, "archive": destination.name,
            "archive_sha256": archive_hash, "archive_bytes": temporary.stat().st_size,
            "games": len(games), "plies": plies, "scored_plies": scored,
            "missing_score_plies": plies - scored - ambiguous,
            "ambiguous_score_plies": ambiguous, "without_telemetry_plies": no_telemetry,
            "run_id": run_id, "requested_ref_a": ref_a, "requested_ref_b": ref_b,
            "scope": "Played moves only; PV, candidate moves and search trees are excluded.",
            "sources": sources,
        }
        manifest_tmp = output_dir / "manifest.json.tmp"
        manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        manifest_tmp.replace(output_dir / "manifest.json")
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--ref-a")
    parser.add_argument("--ref-b")
    args = parser.parse_args()
    result = archive(args.input, args.output_dir, args.run_id, args.ref_a, args.ref_b)
    print(json.dumps({k: result[k] for k in ("games", "plies", "scored_plies", "missing_score_plies", "ambiguous_score_plies", "archive_bytes", "archive_sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
