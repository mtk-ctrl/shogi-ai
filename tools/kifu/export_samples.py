#!/usr/bin/env python3
"""Export per-position supervised samples after rule-layer validation."""
import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1


def iter_games(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc


def make_validator_input(games: Iterable[dict]) -> str:
    rows = []
    for game in games:
        fields = [
            game["game_id"],
            game["split"],
            game.get("winner") or "unknown",
            game["start_sfen"],
            " ".join(game["moves_usi"]),
        ]
        if any("\t" in str(field) or "\n" in str(field) for field in fields):
            raise ValueError(f"tab/newline in validator field for game {game['game_id']}")
        rows.append("\t".join(fields))
    return "\n".join(rows) + ("\n" if rows else "")


def export_samples(dataset: Path, validator: Path, output: Path) -> dict:
    payload = make_validator_input(iter_games(dataset))
    proc = subprocess.run(
        [str(validator)],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rule validation failed ({proc.returncode}): {proc.stderr.strip()}")

    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    split_counts = {"train": 0, "validation": 0, "test": 0}
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row_no, row in enumerate(proc.stdout.splitlines(), 1):
            fields = row.split("\t")
            if len(fields) != 7:
                raise RuntimeError(f"validator row {row_no}: expected 7 fields, got {len(fields)}")
            game_id, split, ply, hash_key, sfen, move, outcome = fields
            if split not in split_counts:
                raise RuntimeError(f"validator row {row_no}: bad split {split!r}")
            sample = {
                "schema_version": SCHEMA_VERSION,
                "game_id": game_id,
                "split": split,
                "ply": int(ply),
                "position_hash": int(hash_key),
                "sfen": sfen,
                "move_usi": move,
                # 1 = side to move eventually wins, -1 = loses, 0 = draw,
                # 2 = result unknown/unusable for value supervision.
                "outcome_for_side_to_move": int(outcome),
            }
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
            split_counts[split] += 1
    return {"samples_written": count, "split_counts": split_counts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--validator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = export_samples(args.dataset, args.validator, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
