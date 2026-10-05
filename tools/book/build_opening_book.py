#!/usr/bin/env python3
"""Build a compact opening book from rule-layer validated self-play samples.

Input is the TSV emitted by tools/kifu/validate_games.cpp. The book contains
only early positions and keeps a few statistically plausible alternatives.
No external engine score, professional game, or opening database is used.

An existing book may be supplied with --prior-book. Its stored W/D/L counts
are treated as aggregate evidence from earlier self-play generations, then the
new validated samples are added on top. This allows later book generations to
retain earlier evidence without replaying every historical arena JSON file.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from apply_book_feedback import quality_weight


@dataclass
class MoveStats:
    samples: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0

    def add(self, outcome: int) -> None:
        self.samples += 1
        if outcome == 1:
            self.wins += 1
        elif outcome == 0:
            self.draws += 1
        elif outcome == -1:
            self.losses += 1

    def add_counts(self, samples: int, wins: int, draws: int, losses: int) -> None:
        if min(samples, wins, draws, losses) < 0 or wins + draws + losses != samples:
            raise ValueError("invalid prior-book W/D/L counts")
        self.samples += samples
        self.wins += wins
        self.draws += draws
        self.losses += losses

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws + 2.0) / (self.samples + 4.0)


def parse_row(line: str, line_no: int):
    fields = line.rstrip("\n").split("\t")
    if len(fields) != 7:
        raise ValueError(f"line {line_no}: expected 7 fields, got {len(fields)}")
    game_id, split, ply, key, sfen, move, outcome = fields
    return game_id, split, int(ply), int(key), sfen, move, int(outcome)


def load_prior_book(path: Path | None, by_position, position_samples) -> tuple[int, int]:
    if path is None:
        return 0, 0
    entries = samples_total = 0
    with path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 8:
                raise ValueError(f"prior book line {line_no}: expected 8 fields, got {len(fields)}")
            key, move, samples, wins, draws, losses, _score_milli, _weight = fields
            key_i = int(key)
            samples_i, wins_i, draws_i, losses_i = map(int, (samples, wins, draws, losses))
            by_position[key_i][move].add_counts(samples_i, wins_i, draws_i, losses_i)
            position_samples[key_i] += samples_i
            entries += 1
            samples_total += samples_i
    return entries, samples_total


def build(args) -> tuple[list[tuple], dict]:
    by_position: dict[int, dict[str, MoveStats]] = defaultdict(lambda: defaultdict(MoveStats))
    position_samples: dict[int, int] = defaultdict(int)
    prior_book = getattr(args, "prior_book", None)
    prior_entries, prior_samples = load_prior_book(prior_book, by_position, position_samples)
    raw_rows = used_rows = unknown_rows = 0

    with args.input.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            raw_rows += 1
            _, _, ply, key, _, move, outcome = parse_row(line, line_no)
            if ply > args.max_ply:
                continue
            if outcome not in (-1, 0, 1):
                unknown_rows += 1
                continue
            by_position[key][move].add(outcome)
            position_samples[key] += 1
            used_rows += 1

    entries = []
    kept_positions = 0
    for key in sorted(by_position):
        if position_samples[key] < args.min_position_samples:
            continue
        candidates = [(move, stats) for move, stats in by_position[key].items()
                      if stats.samples >= args.min_move_samples]
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[1].score, -item[1].samples, item[0]))
        best_score = candidates[0][1].score
        kept = [item for item in candidates
                if item[1].score >= best_score - args.max_score_gap][:args.max_moves]
        if not kept:
            continue
        kept_positions += 1
        for move, stats in kept:
            # Reuse the same confidence-aware weighting as the online feedback
            # learner so a full book rebuild cannot resurrect repeatedly losing
            # lines with the old, overly generous weight formula.
            weight = quality_weight(stats.samples, stats.score)
            entries.append((key, move, stats.samples, stats.wins, stats.draws,
                            stats.losses, int(round(stats.score * 1000.0)), weight))

    return entries, {
        "prior_book": str(prior_book) if prior_book is not None else None,
        "prior_book_entries": prior_entries,
        "prior_book_samples": prior_samples,
        "raw_sample_rows": raw_rows,
        "early_sample_rows": used_rows,
        "unknown_outcome_rows": unknown_rows,
        "positions_seen": len(by_position),
        "positions_kept": kept_positions,
        "book_entries": len(entries),
        "max_ply": args.max_ply,
        "min_position_samples": args.min_position_samples,
        "min_move_samples": args.min_move_samples,
        "max_moves": args.max_moves,
        "max_score_gap": args.max_score_gap,
        "weighting": "loss-aware-v2",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--prior-book", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-ply", type=int, default=20)
    parser.add_argument("--min-position-samples", type=int, default=8)
    parser.add_argument("--min-move-samples", type=int, default=3)
    parser.add_argument("--max-moves", type=int, default=3)
    parser.add_argument("--max-score-gap", type=float, default=0.12)
    args = parser.parse_args()
    if args.max_ply < 1 or args.min_position_samples < 1 or args.min_move_samples < 1 or args.max_moves < 1:
        raise SystemExit("positive thresholds are required")
    if not 0.0 <= args.max_score_gap <= 1.0:
        raise SystemExit("max-score-gap must be in [0, 1]")

    entries, report = build(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# shogi-ai opening book v1: key move samples wins draws losses score_milli weight\n")
        for row in entries:
            out.write("\t".join(map(str, row)) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
