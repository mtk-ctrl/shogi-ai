#!/usr/bin/env python3
"""Update opening-book evidence and weights from exact book-hit outcomes.

The arena records only moves that were actually selected by OpeningBook. A
rule-layer validator supplies the corresponding position hash and the final
outcome from the mover's point of view. This tool merges that fresh evidence
into the existing book and reweights weak moves without deleting them, so a
suppressed line retains a small exploration chance and can recover later.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Entry:
    key: int
    move: str
    samples: int
    wins: int
    draws: int
    losses: int
    score_milli: int
    weight: int


@dataclass
class Feedback:
    wins: int = 0
    draws: int = 0
    losses: int = 0

    @property
    def samples(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws + 1.0) / (self.samples + 2.0)

    def add(self, outcome: int) -> None:
        if outcome == 1:
            self.wins += 1
        elif outcome == 0:
            self.draws += 1
        elif outcome == -1:
            self.losses += 1
        else:
            raise ValueError(f"invalid outcome: {outcome}")


def posterior_score(wins: int, draws: int, samples: int) -> float:
    return (wins + 0.5 * draws + 2.0) / (samples + 4.0)


def quality_weight(samples: int, score: float, recent: Feedback | None = None) -> int:
    """Confidence-aware weight with an exploration floor."""
    quality = max(0.02, score - 0.30)
    factor = 1.0
    if samples >= 12:
        if score < 0.35:
            factor *= 0.05
        elif score < 0.40:
            factor *= 0.12
        elif score < 0.45:
            factor *= 0.30
        elif score < 0.50:
            factor *= 0.65

    if recent is not None and recent.samples >= 6:
        if recent.score < 0.35:
            factor *= 0.25
        elif recent.score < 0.45:
            factor *= 0.55
        elif recent.score > 0.60:
            factor *= 1.15

    return max(1, int(round(1000.0 * quality * math.sqrt(max(samples, 1)) * factor)))


def load_book(path: Path) -> list[Entry]:
    entries = []
    with path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 8:
                raise ValueError(f"book line {line_no}: expected 8 fields, got {len(fields)}")
            key, move, samples, wins, draws, losses, score_milli, weight = fields
            entry = Entry(int(key), move, int(samples), int(wins), int(draws), int(losses),
                          int(score_milli), int(weight))
            if min(entry.samples, entry.wins, entry.draws, entry.losses, entry.weight) < 0:
                raise ValueError(f"book line {line_no}: negative count")
            if entry.samples != entry.wins + entry.draws + entry.losses or entry.samples == 0:
                raise ValueError(f"book line {line_no}: inconsistent W/D/L")
            entries.append(entry)
    if not entries:
        raise ValueError("book has no entries")
    return entries


def load_samples(path: Path) -> dict[tuple[str, int], tuple[int, str, int]]:
    rows = {}
    with path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 7:
                raise ValueError(f"sample line {line_no}: expected 7 fields, got {len(fields)}")
            game_id, _split, ply, key, _sfen, move, outcome = fields
            rows[(game_id, int(ply))] = (int(key), move, int(outcome))
    return rows


def load_feedback(samples_path: Path, hits_path: Path) -> tuple[dict[tuple[int, str], Feedback], dict]:
    samples = load_samples(samples_path)
    feedback: dict[tuple[int, str], Feedback] = defaultdict(Feedback)
    report = {"hit_rows": 0, "matched_hits": 0, "unmatched_hits": 0, "move_mismatches": 0}
    with hits_path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip() or line.startswith("#"):
                continue
            report["hit_rows"] += 1
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4:
                raise ValueError(f"hit line {line_no}: expected at least 4 fields")
            game_id, ply_text, _engine, move = fields[:4]
            sample = samples.get((game_id, int(ply_text)))
            if sample is None:
                report["unmatched_hits"] += 1
                continue
            key, sample_move, outcome = sample
            if sample_move != move:
                report["move_mismatches"] += 1
                continue
            if outcome not in (-1, 0, 1):
                report["unmatched_hits"] += 1
                continue
            feedback[(key, move)].add(outcome)
            report["matched_hits"] += 1
    return feedback, report


def update(entries: list[Entry], feedback: dict[tuple[int, str], Feedback], feedback_weight: int,
           max_down_factor: float, max_up_factor: float, reweight_all: bool) -> tuple[list[Entry], dict]:
    changed = []
    low_recent = []
    matched_entries = 0
    output = []
    entry_keys = {(entry.key, entry.move) for entry in entries}
    feedback_without_entry = sum(f.samples for key, f in feedback.items() if key not in entry_keys)

    for entry in entries:
        recent = feedback.get((entry.key, entry.move))
        if recent is None and not reweight_all:
            output.append(entry)
            continue

        wins, draws, losses = entry.wins, entry.draws, entry.losses
        if recent is not None:
            matched_entries += 1
            wins += recent.wins * feedback_weight
            draws += recent.draws * feedback_weight
            losses += recent.losses * feedback_weight
        samples = wins + draws + losses
        score = posterior_score(wins, draws, samples)
        desired = quality_weight(samples, score, recent)

        if reweight_all or recent is None:
            new_weight = desired
        else:
            lower = max(1, int(round(entry.weight * max_down_factor)))
            upper = max(lower, int(round(entry.weight * max_up_factor)))
            new_weight = min(upper, max(lower, desired))

        new_entry = Entry(entry.key, entry.move, samples, wins, draws, losses,
                          int(round(score * 1000.0)), new_weight)
        output.append(new_entry)
        if new_entry.weight != entry.weight or new_entry.samples != entry.samples:
            changed.append({
                "key": entry.key,
                "move": entry.move,
                "old_weight": entry.weight,
                "new_weight": new_entry.weight,
                "old_score": entry.score_milli / 1000.0,
                "new_score": score,
                "recent_samples": recent.samples if recent else 0,
                "recent_score": recent.score if recent else None,
            })
        if recent is not None and recent.samples >= 3:
            low_recent.append({
                "key": entry.key,
                "move": entry.move,
                "samples": recent.samples,
                "wins": recent.wins,
                "draws": recent.draws,
                "losses": recent.losses,
                "score": recent.score,
                "new_weight": new_weight,
            })

    low_recent.sort(key=lambda row: (row["score"], -row["samples"], row["key"], row["move"]))
    biggest_changes = sorted(changed, key=lambda row: abs(row["new_weight"] - row["old_weight"]), reverse=True)
    report = {
        "book_entries": len(entries),
        "feedback_entries_matched": matched_entries,
        "feedback_hits_without_book_entry": feedback_without_entry,
        "entries_changed": len(changed),
        "feedback_weight": feedback_weight,
        "max_down_factor": max_down_factor,
        "max_up_factor": max_up_factor,
        "reweight_all": reweight_all,
        "worst_recent": low_recent[:20],
        "largest_weight_changes": biggest_changes[:20],
    }
    return output, report


def write_book(path: Path, entries: list[Entry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# shogi-ai opening book v1: key move samples wins draws losses score_milli weight\n")
        for entry in sorted(entries, key=lambda row: (row.key, row.move)):
            out.write("\t".join(map(str, (
                entry.key, entry.move, entry.samples, entry.wins, entry.draws,
                entry.losses, entry.score_milli, entry.weight))) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--samples", type=Path)
    parser.add_argument("--hits", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--feedback-weight", type=int, default=4)
    parser.add_argument("--max-down-factor", type=float, default=0.50)
    parser.add_argument("--max-up-factor", type=float, default=1.35)
    parser.add_argument("--reweight-all", action="store_true")
    args = parser.parse_args()

    if args.feedback_weight < 1:
        raise SystemExit("feedback-weight must be positive")
    if not 0 < args.max_down_factor <= 1 or args.max_up_factor < 1:
        raise SystemExit("weight change factors must satisfy 0 < down <= 1 <= up")
    if (args.samples is None) != (args.hits is None):
        raise SystemExit("--samples and --hits must be supplied together")
    if args.samples is None and not args.reweight_all:
        raise SystemExit("feedback files or --reweight-all are required")

    entries = load_book(args.book)
    feedback = {}
    match_report = {"hit_rows": 0, "matched_hits": 0, "unmatched_hits": 0, "move_mismatches": 0}
    if args.samples is not None:
        feedback, match_report = load_feedback(args.samples, args.hits)

    updated, report = update(entries, feedback, args.feedback_weight,
                             args.max_down_factor, args.max_up_factor, args.reweight_all)
    report.update(match_report)
    write_book(args.output, updated)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
