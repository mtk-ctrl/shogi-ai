#!/usr/bin/env python3
"""Normalize CSA games into a deterministic, deduplicated JSONL corpus."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List

try:
    from .csa import CsaGame, parse_csa_file_games
except ImportError:
    from csa import CsaGame, parse_csa_file_games

SCHEMA_VERSION = 1
DEFAULT_SPLIT_SALT = "shogi-ai-kifu-v1"


def game_fingerprint(game: CsaGame) -> str:
    payload = game.start_sfen + "\n" + " ".join(game.moves_usi)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def split_for(fingerprint: str, salt: str = DEFAULT_SPLIT_SALT) -> str:
    value = int(hashlib.sha256((salt + ":" + fingerprint).encode("utf-8")).hexdigest()[:16], 16) % 1000
    if value < 800:
        return "train"
    if value < 900:
        return "validation"
    return "test"


def iter_csa_paths(inputs: Iterable[Path]) -> List[Path]:
    paths = []
    for item in inputs:
        if item.is_dir():
            paths.extend(p for p in item.rglob("*") if p.is_file() and p.suffix.lower() == ".csa")
        elif item.is_file():
            paths.append(item)
        else:
            raise FileNotFoundError(item)
    return sorted(set(p.resolve() for p in paths), key=lambda p: str(p))


def normalized_record(game: CsaGame, source_sha256: str, split_salt: str,
                      corpus: str = "", license_name: str = "") -> Dict:
    fingerprint = game_fingerprint(game)
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": fingerprint[:20],
        "fingerprint": fingerprint,
        "source_format": "CSA",
        "source_file": game.source,
        "source_record": game.source_record,
        "source_sha256": source_sha256,
        "corpus": corpus,
        "license": license_name,
        "black": game.black,
        "white": game.white,
        "metadata": game.metadata,
        "start_sfen": game.start_sfen,
        "moves_usi": game.moves_usi,
        "plies": len(game.moves_usi),
        "raw_result": game.raw_result,
        "winner": game.winner,
        "split": split_for(fingerprint, split_salt),
    }


def build_dataset(inputs: Iterable[Path], output: Path, manifest: Path,
                  split_salt: str = DEFAULT_SPLIT_SALT, strict: bool = False,
                  corpus: str = "", license_name: str = "") -> Dict:
    paths = iter_csa_paths(inputs)
    records: Dict[str, Dict] = {}
    errors = []
    duplicates = 0
    records_seen = 0
    for path in paths:
        try:
            source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            games = parse_csa_file_games(path)
        except Exception as exc:
            errors.append({"source_file": str(path), "error": str(exc)})
            if strict:
                raise
            continue
        for game in games:
            records_seen += 1
            try:
                record = normalized_record(game, source_sha256, split_salt, corpus, license_name)
                fingerprint = record["fingerprint"]
                if fingerprint in records:
                    duplicates += 1
                    continue
                records[fingerprint] = record
            except Exception as exc:
                errors.append({"source_file": str(path), "source_record": game.source_record, "error": str(exc)})
                if strict:
                    raise

    ordered = [records[key] for key in sorted(records)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in ordered:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    split_counts = {"train": 0, "validation": 0, "test": 0}
    known_results = {"black": 0, "white": 0, "draw": 0, "unknown": 0}
    for record in ordered:
        split_counts[record["split"]] += 1
        key = record["winner"] if record["winner"] in ("black", "white", "draw") else "unknown"
        known_results[key] += 1
    summary = {
        "schema_version": SCHEMA_VERSION,
        "source_format": "CSA",
        "split_salt": split_salt,
        "split_policy": "whole-game deterministic 80/10/10 by SHA-256",
        "corpus": corpus,
        "license": license_name,
        "files_seen": len(paths),
        "records_seen": records_seen,
        "games_written": len(ordered),
        "duplicates_removed": duplicates,
        "errors": errors,
        "split_counts": split_counts,
        "known_results": known_results,
        "total_plies": sum(record["plies"] for record in ordered),
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="CSA files or directories")
    parser.add_argument("--output", type=Path, required=True, help="normalized game JSONL")
    parser.add_argument("--manifest", type=Path, help="dataset summary JSON")
    parser.add_argument("--split-salt", default=DEFAULT_SPLIT_SALT)
    parser.add_argument("--corpus", default="", help="human-readable source corpus name")
    parser.add_argument("--license", dest="license_name", default="", help="source license/usage label")
    parser.add_argument("--strict", action="store_true", help="stop at the first invalid record")
    args = parser.parse_args()
    manifest = args.manifest or args.output.with_suffix(".manifest.json")
    summary = build_dataset(args.inputs, args.output, manifest, args.split_salt,
                            args.strict, args.corpus, args.license_name)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
