#!/usr/bin/env python3
"""Provenance-checked conversion of a pinned KUMOJI self-play archive into arena JSON."""
from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path


def convert_archive(archive: Path, manifest_path: Path, output_dir: Path, max_games: int = 300):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest.get("archive_sha256"):
        raise ValueError("archive hash mismatch: data cannot be trusted")
    by_source = {}
    for source in manifest.get("sources", []):
        meta = source.get("metadata", {})
        a, b = meta.get("sha256_a"), meta.get("sha256_b")
        if not a or a != b or len(a) != 64 or source["source_id"] in by_source:
            raise ValueError("not verified same-binary self-play source")
        by_source[source["source_id"]] = meta
    if not by_source:
        raise ValueError("missing source metadata")
    groups = defaultdict(list)
    total = 0
    with gzip.open(archive, "rt", encoding="utf-8") as fp:
        for line in fp:
            if total >= max_games:
                break
            row = json.loads(line)
            source_id = row.get("source_id")
            if source_id not in by_source:
                raise ValueError("unknown source in archive")
            records = row.get("moves")
            if not isinstance(records, list) or not records:
                raise ValueError("archive game has no played moves")
            moves = [r["move"] for r in records]
            if len(moves) != row.get("plies", len(moves)):
                raise ValueError("archive game ply mismatch")
            game = {"winner": row.get("winner"), "reason": row.get("reason"),
                    "a_black": row.get("a_black"), "moves": moves,
                    "move_records": [{"move": r["move"], "search": r.get("search", {})}
                                     for r in records]}
            if row.get("start_sfen"):
                game["start_sfen"] = row["start_sfen"]
            if row.get("illegal_by"):
                game["illegal_by"] = row["illegal_by"]
            groups[source_id].append(game)
            total += 1
    if total < 3:
        raise ValueError("too few archived games")
    output_dir.mkdir(parents=True, exist_ok=True)
    for n, source_id in enumerate(sorted(groups)):
        meta = by_source[source_id]
        data = {"learning_origin": "kumoji_selfplay",
                "sha256_a": meta["sha256_a"],
                "sha256_b": meta["sha256_b"],
                "details": groups[source_id]}
        (output_dir / f"selfplay-{n:03d}.json").write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {"sources": len(groups), "games": total,
            "archive_sha256": digest, "verified": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--max-games", type=int, default=300)
    args = p.parse_args()
    if args.max_games < 3:
        p.error("--max-games must be >= 3")
    print(json.dumps(convert_archive(args.archive, args.manifest,
                                     args.output_dir, args.max_games)))


if __name__ == "__main__":
    main()
