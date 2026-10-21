#!/usr/bin/env python3
"""Restore a verified played-game archive from a bounded GitHub Release package.

Research-only extraction. Refuse unsafe paths, links, device files or archives
without independently replayable finished selfplay. No remote input is trusted
because a Release checksum exists; inspect the contained game manifest anew.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.research.postgame_cases import load_archive
from tools.research.nnue_labels import source_is_owned_selfplay


def safely_extract(bundle, destination, max_bytes=512 * 1024 * 1024):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must start empty")
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 15000:
            raise ValueError("unbounded archive member count")
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.name or path.is_absolute()
                or not path.parts or any(part in (".", "..") for part in path.parts)
                or "\\" in member.name or ":" in member.name
                or not (member.isfile() or member.isdir())):
                raise ValueError(f"unsafe research bundle member: {member.name!r}")
            total += member.size
            if total > max_bytes:
                raise ValueError("research bundle exceeds extraction limit")
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("xb") as out:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
    return len(members)


def find_source(root):
    candidates = []
    examined = []
    for manifest in Path(root).rglob("manifest.json"):
        directory = manifest.parent
        if not (directory / "played-games.jsonl.gz").is_file():
            continue
        try:
            games = load_archive(directory)
            proven_selfplay = source_is_owned_selfplay(directory, games)
            completed = sum(g.outcome_status != "unresolved" for g in games)
            examined.append({"directory": str(directory), "games": len(games),
                             "completed": completed, "all_selfplay": proven_selfplay})
            if completed >= 3 and proven_selfplay:
                candidates.append((completed, len(games), directory, games))
        except Exception as e:
            examined.append({"directory": str(directory), "invalid": str(e)[:200]})
    if not candidates:
        raise ValueError("bundle has no all-KUMOJI archive with >=3 independently verified completed games: "
                         + json.dumps(examined, ensure_ascii=False))
    candidates.sort(key=lambda item: (-item[0], -item[1], str(item[2])))
    return candidates[0], examined


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    args = p.parse_args()
    count = safely_extract(args.bundle, args.output_dir)
    (finished, n, directory, games), reviewed = find_source(args.output_dir)
    result = {"schema": "nnue-release-source-v1",
              "bundle_sha256": hashlib.sha256(args.bundle.read_bytes()).hexdigest(),
              "archive_dir": str(directory.resolve()),
              "verified_games": n, "completed_games": finished,
              "verified_plies": sum(len(g.moves) for g in games),
              "archive_sha256": games[0].archive_sha256,
              "entry_count": count, "inspected": reviewed,
              "status": "source_verified_only_not_trained"}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
