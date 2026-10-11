#!/usr/bin/env python3
"""Discover and audit all accessible standard KUMOJI played-move archives.

This deliberately does not assign winner labels to inter-version matches:
their results also reflect the differing player strengths. League/legacy raw
formats are inventoried as not covered, rather than relabelled as same-binary.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import shogi


ARCHIVE_PATTERN = re.compile(r"^played-move-archive-(\d+)$")
MAX_SAMPLES_PER_GAME = 6


def execute(*argv):
    p = subprocess.run(argv, capture_output=True, text=True, check=True)
    return p.stdout


def discovered_archives(repository):
    """List the whole repository artifact index, including expired records."""
    matches = []
    seen = set()
    page = 1
    total = 0
    while True:
        data = json.loads(execute("gh", "api",
            f"repos/{repository}/actions/artifacts?per_page=100&page={page}"))
        entries = data.get("artifacts", [])
        total = int(data.get("total_count", total))
        for artifact in entries:
            name = artifact["name"]
            match = ARCHIVE_PATTERN.fullmatch(name)
            if not match:
                continue
            aid = artifact["id"]
            if aid in seen:
                continue
            seen.add(aid)
            matches.append({
                "id": aid, "name": name, "run_id": int(match.group(1)),
                "expired": bool(artifact.get("expired")),
                "size_bytes": int(artifact.get("size_in_bytes", 0))
            })
        if len(entries) < 100:
            break
        page += 1
        if page > 100:
            raise RuntimeError("artifact index unexpectedly large")
    return total, sorted(matches, key=lambda a: (a["run_id"], a["id"]))


def verify_archive_payload(raw_gzip, raw_manifest, *, label):
    manifest = json.loads(raw_manifest)
    actual = hashlib.sha256(raw_gzip).hexdigest()
    if manifest.get("archive_sha256") != actual:
        raise ValueError(f"{label}: source archive SHA256 mismatch")
    sources = {}
    for row in manifest.get("sources", []):
        key = row["source_id"]
        if key in sources:
            raise ValueError(f"{label}: repeated source identifier")
        sources[key] = row.get("metadata", {})
    if not sources:
        raise ValueError(f"{label}: missing metadata sources")
    return sources


def valid_outcome(game):
    # Abort/timeout/limit/illegal do not have trustworthy winner labels.
    if game.get("illegal_by") or type(game.get("a_black")) is not bool:
        return None
    reason = game.get("reason")
    winner = game.get("winner")
    if winner in ("A", "B") and reason in (
        "resign", "checkmate", "no_legal_moves",
        "declare_win", "perpetual_check"):
        return float((winner == "A") == game["a_black"])
    if winner is None and reason == "fourfold_repetition":
        return 0.5
    return None


def extract_games(raw_gzip, sources, *, group, counters, seen_games, output):
    with gzip.open(io.BytesIO(raw_gzip), mode="rt", encoding="utf-8") as reader:
        for line in reader:
            if not line.strip():
                continue
            game = json.loads(line)
            counters["archive_games_seen"] += 1
            source_id = game.get("source_id")
            if source_id not in sources:
                raise ValueError(f"{group}: game references unknown metadata source")
            meta = sources[source_id]
            sa, sb = meta.get("sha256_a"), meta.get("sha256_b")
            if not (isinstance(sa, str) and re.fullmatch(r"[a-f0-9]{64}", sa) and
                    isinstance(sb, str) and re.fullmatch(r"[a-f0-9]{64}", sb)):
                counters["excluded_missing_binary_hashes"] += 1
                continue
            if sa != sb:
                counters["excluded_different_binary_versions"] += 1
                continue
            outcome = valid_outcome(game)
            if outcome is None:
                counters["excluded_no_final_result"] += 1
                continue
            recorded = game.get("moves")
            if not isinstance(recorded, list) or not recorded:
                counters["excluded_empty_games"] += 1
                continue
            moves = [r.get("move") for r in recorded]
            if not all(isinstance(m, str) for m in moves):
                raise ValueError(f"{group}: invalid played move field")
            if game.get("plies") not in (None, len(moves)):
                raise ValueError(f"{group}: plies mismatch")
            start_sfen = game.get("start_sfen")
            board = shogi.Board(start_sfen) if start_sfen else shogi.Board()
            game_id = hashlib.sha256(
                (board.sfen() + "\n" + " ".join(moves)).encode()).hexdigest()
            if game_id in seen_games:
                counters["duplicate_games"] += 1
                continue
            seen_games.add(game_id)
            # Choose up to six roughly equally spaced positions, not just openings.
            selected = set((len(moves) * (2*k+1)) // (2*min(len(moves), MAX_SAMPLES_PER_GAME))
                           for k in range(min(len(moves), MAX_SAMPLES_PER_GAME)))
            rows = []
            for index, token in enumerate(moves):
                move = shogi.Move.from_usi(token)
                if move not in board.legal_moves:
                    raise ValueError(f"{group}: illegal move in {game_id} at {index+1}")
                if index in selected:
                    rows.append({
                        "source": "kumoji_selfplay",
                        "source_group": str(group),
                        "engine_binary_sha256": sa,
                        "game_id": game_id,
                        "sfen": board.sfen(),
                        "ply": index + 1,
                        "target_black": outcome
                    })
                board.push(move)
            for row in rows:
                output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            counters["labelled_games"] += 1
            counters["sampled_positions"] += len(rows)


def from_release(repository, directory):
    execute("gh", "release", "download", "records-2026-10-01",
            "--repo", repository,
            "--pattern", "played-games-37671846680.jsonl.gz",
            "--pattern", "played-games-manifest-37671846680.json",
            "--dir", str(directory))
    archived = directory / "played-games-37671846680.jsonl.gz"
    manifest = directory / "played-games-manifest-37671846680.json"
    return archived.read_bytes(), manifest.read_bytes()


def from_artifact(repository, artifact, directory):
    location = directory / str(artifact["run_id"])
    location.mkdir(parents=True, exist_ok=True)
    execute("gh", "run", "download", str(artifact["run_id"]), "--repo", repository,
            "-n", artifact["name"], "-D", str(location))
    return (location / "played-games.jsonl.gz").read_bytes(), (location / "manifest.json").read_bytes()


def collect(repository: str, target: Path, working: Path, artifact_limit=100):
    if artifact_limit < 1:
        raise ValueError("artifact_limit must be positive")
    working.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    summary = Counter()
    index_total, artifacts = discovered_archives(repository)
    if len(artifacts) > artifact_limit:
        raise ValueError(
            f"found {len(artifacts)} archives, above configured limit {artifact_limit}; "
            "increase the limit explicitly rather than silently excluding files")
    summary["github_artifacts_indexed"] = index_total
    summary["candidate_move_archives"] = len(artifacts)
    summary["expired_move_archives"] = sum(a["expired"] for a in artifacts)
    seen_games = set()
    retrieved = []
    failures = []
    with target.open("w", encoding="utf-8") as out:
        raw_archive, raw_manifest = from_release(repository, working)
        sources = verify_archive_payload(raw_archive, raw_manifest, label="release")
        extract_games(raw_archive, sources, group="37671846680", counters=summary,
                      seen_games=seen_games, output=out)
        retrieved.append("records-2026-10-01")
        for artifact in artifacts:
            if artifact["expired"]:
                continue
            try:
                raw_archive, raw_manifest = from_artifact(repository, artifact, working)
                sources = verify_archive_payload(raw_archive, raw_manifest, label=artifact["name"])
                extract_games(raw_archive, sources, group=artifact["run_id"],
                              counters=summary, seen_games=seen_games, output=out)
                retrieved.append(artifact["name"])
            except (OSError, subprocess.CalledProcessError, ValueError,
                    KeyError, zipfile.BadZipFile) as exc:
                failures.append({"name": artifact["name"], "error": str(exc)[:220]})
                # Distinguish a failed source from a legitimate zero-contribution source.
                # Fatal if the archive itself fails integrity or validation: partial
                # line output must not be declared successful.
                if not isinstance(exc, (OSError, subprocess.CalledProcessError)):
                    raise
    if summary["labelled_games"] < 10 or summary["sampled_positions"] < 50:
        raise ValueError("insufficient verified self-play data")
    summary_result = {
        "scope": "All accessible standard played-move archives plus pinned long-term release.",
        "excluded_scope": "League/raw game artifacts without standard archive manifest; expired artifacts; external human/AI records.",
        "source_archive_count_retrieved": len(retrieved),
        "source_archive_names": retrieved,
        "download_failures": failures,
        "counts": dict(summary),
        "sampling": f"up to {MAX_SAMPLES_PER_GAME} actual positions per eligible completed game",
        "truth": "Same-engine outcomes predict game result, not best move. No engine modifications.",
        "dataset_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    result_path = target.parent / "history-inventory.json"
    result_path.write_text(json.dumps(summary_result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return summary_result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--working", required=True, type=Path)
    p.add_argument("--max-archives", type=int, default=100)
    a = p.parse_args()
    print(json.dumps(collect(a.repository, a.output, a.working,
                             a.max_archives), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
