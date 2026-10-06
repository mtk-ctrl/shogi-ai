#!/usr/bin/env python3
"""Same engine, 50ms normally, at most five 30s decisions per game.

Only this experimental runner changes time allocation. Production engine and
book are unchanged. A short probe is restarted with the remaining wall budget;
this is not a continuation of the original search. Every probe is retained.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import shogi
from arena import Engine, parse_info_line, play_game


def select_bonus(policy, ply, used, previous, probe, iterations, board, normal_ms):
    if policy == "none" or used >= 5 or ply < 24:
        return None
    # Do not spend a coupon on a Book decision, forced move or proven mate.
    if probe.get("book_hit") or "score_mate" in probe or len(list(board.legal_moves)) <= 1:
        return None
    starts = (24, 56, 88, 120, 160)
    ends = (54, 86, 118, 158, 198)
    if ply < starts[used]:
        return None
    if policy == "scheduled":
        return "scheduled"
    if board.is_check():
        return "in_check"
    score = probe.get("score_cp")
    if previous is not None and score is not None and previous - score >= 150:
        return "score_drop_150"
    complete = [r for r in iterations if "score_cp" in r and r.get("depth", 0) > 0]
    if len(complete) >= 2:
        a, b = complete[-2:]
        if abs(a["score_cp"] - b["score_cp"]) >= 150:
            return "iteration_score_change_150"
        if a.get("pv", [])[:1] != b.get("pv", [])[:1]:
            return "iteration_move_change"
    if probe.get("depth", 0) < 2 and probe.get("elapsed_ms", 0) >= normal_ms * .8:
        return "unfinished_depth2"
    if ply >= ends[used]:
        return "window_fallback"
    return None


class BonusEngine(Engine):
    RESPONSE_TIMEOUT = 45  # watchdog must exceed the 30s search budget

    def __init__(self, path, label, options, policy, pair_seed, normal_ms=50, bonus_ms=30000):
        self.policy = policy
        self.pair_seed = pair_seed
        self.normal_ms = normal_ms
        self.bonus_ms = bonus_ms
        self.iterations = []
        self.book_hit = False
        self.used = 0
        self.previous = None
        self.decisions = []
        super().__init__(path, label, options, f"go movetime {normal_ms}")

    def _reader(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("info string opening_book hit "):
                self.book_hit = True
            row = parse_info_line(line)
            if "depth" in row:
                self.iterations.append(row)
            self.lines.put(line)

    def configure_game(self, seed):
        # play_game assigns even/odd seeds to Black/White. Reuse those exact
        # color seeds for both halves of a pair, independent of engine label.
        super().configure_game(self.pair_seed + (seed - self.pair_seed) % 2)
        self.used = 0
        self.previous = None
        self.decisions = []

    def bestmove(self, moves):
        started = time.monotonic()
        self.iterations = []
        self.book_hit = False
        self.go_command = f"go movetime {self.normal_ms}"
        token = super().bestmove(moves)
        probe = dict(self.last_search)
        probe["book_hit"] = self.book_hit
        iterations = list(self.iterations)
        board = shogi.Board()
        for move in moves:
            board.push_usi(move)
        reason = select_bonus(self.policy, len(moves) + 1, self.used,
                              self.previous, probe, iterations, board, self.normal_ms)
        if token in ("resign", "win"):
            reason = None
        decision = {"ply": len(moves) + 1, "probe": probe,
                    "probe_iterations": iterations, "extended": False}
        if reason:
            # Count the probe, board replay and IPC against the same 30s limit.
            remaining = math.floor(self.bonus_ms - (time.monotonic() - started) * 1000)
            if remaining > self.normal_ms:
                self.used += 1
                self.iterations = []
                self.go_command = f"go movetime {remaining}"
                token = super().bestmove(moves)
                decision.update({"extended": True, "coupon": self.used,
                                 "reason": reason, "restart_movetime_ms": remaining,
                                 "deep_iterations": list(self.iterations),
                                 "changed_move": token != probe["bestmove"]})
        self.last_search["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
        self.previous = self.last_search.get("score_cp")
        decision["final"] = dict(self.last_search)
        self.decisions.append(decision)
        return token


def run_pair(job):
    engine, options, policy, index, seed, max_plies, output, cpu, normal_ms, bonus_ms = job
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})  # children inherit: no oversubscribed search
    pair_seed = seed + index * 2
    a = b = None
    games = []
    try:
        a = BonusEngine(engine, "A", options, policy, pair_seed, normal_ms, bonus_ms)
        b = BonusEngine(engine, "B", options, "none", pair_seed, normal_ms, bonus_ms)
        for half in range(2):
            started = time.monotonic()
            result = play_game(a, b, half, max_plies, pair_seed)
            result.update({"pair": index, "half": half, "pair_seed": pair_seed,
                           "elapsed_seconds": round(time.monotonic() - started, 3),
                           "decisions": {"A": a.decisions, "B": b.decisions},
                           "bonus_used": a.used})
            if "illegal_by" in result:
                raise RuntimeError(f"Illegal game: {result}")
            games.append(result)
            # Save immediately: a completed half survives process interruption.
            target = Path(output) / f"pair-{index:03d}-half-{half}.json.gz"
            with gzip.open(target, "wt", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            print(f"{policy} pair={index} half={half} winner={result['winner']} "
                  f"plies={result['plies']} bonus={a.used}", flush=True)
        return games
    finally:
        if a is not None:
            a.close()
        if b is not None:
            b.close()


def summarize(games):
    wa = sum(g["winner"] == "A" for g in games)
    wb = sum(g["winner"] == "B" for g in games)
    draws = len(games) - wa - wb
    scores = [(int(g["winner"] == "A") + .5 * int(g["winner"] is None)) for g in games]
    paired = [(scores[i] + scores[i + 1]) / 2 for i in range(0, len(scores), 2)]
    se = statistics.stdev(paired) / math.sqrt(len(paired)) if len(paired) > 1 else None
    ext = [d for g in games for d in g["decisions"]["A"] if d["extended"]]
    depths = lambda key: [d[key]["depth"] for d in ext if "depth" in d[key]]
    reasons = {reason: sum(d["reason"] == reason for d in ext) for reason in sorted({d["reason"] for d in ext})}
    return {"games": len(games), "pairs": len(paired), "wins_a": wa, "wins_b": wb,
            "draws": draws, "score_a": statistics.mean(scores),
            "pair_normal_95_ci": [max(0, statistics.mean(paired) - 1.96 * se),
                                  min(1, statistics.mean(paired) + 1.96 * se)] if se is not None else None,
            "illegal_games": sum("illegal_by" in g for g in games),
            "average_plies": statistics.mean(g["plies"] for g in games),
            "bonus_uses": len(ext), "bonus_per_game": len(ext) / len(games),
            "changed_moves": sum(d["changed_move"] for d in ext),
            "probe_depth_mean": statistics.mean(depths("probe")) if depths("probe") else None,
            "deep_depth_mean": statistics.mean(depths("final")) if depths("final") else None,
            "bonus_time_mean_ms": statistics.mean(d["final"]["elapsed_ms"] for d in ext) if ext else None,
            "bonus_time_max_ms": max((d["final"]["elapsed_ms"] for d in ext), default=0),
            "bonus_reasons": reasons,
            "by_color": {str(color): {"games": len([g for g in games if g["a_black"] == color]),
                         "score": statistics.mean(scores[i] for i,g in enumerate(games) if g["a_black"] == color)}
                         for color in (True, False)}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True)
    p.add_argument("--policy", choices=["adaptive", "scheduled", "none"], default="adaptive")
    p.add_argument("--pairs", type=int, default=20)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--max-plies", type=int, default=400)
    p.add_argument("--normal-ms", type=int, default=50)
    p.add_argument("--bonus-ms", type=int, default=30000)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if not 1 <= args.normal_ms <= args.bonus_ms <= 30000 or args.pairs < 1 or args.workers < 1:
        p.error("positive pairs/workers; 1 <= normal-ms <= bonus-ms <= 30000 required")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    options = {"OpeningBook": True, "MateAssist": True, "ExperienceCache": False}
    cpus = sorted(os.sched_getaffinity(0))
    workers = min(args.workers, len(cpus))
    started = time.monotonic()
    jobs = [(str(Path(args.engine).resolve()), options, args.policy, i, args.seed,
             args.max_plies, str(out), cpus[i % workers], args.normal_ms, args.bonus_ms) for i in range(args.pairs)]
    # Assign one stable CPU per process rather than one per job. ProcessPool may
    # otherwise run different job IDs concurrently on the same chosen CPU.
    import multiprocessing
    context = multiprocessing.get_context("fork")
    cpu_queue = context.Queue()
    for cpu in cpus[:workers]:
        cpu_queue.put(cpu)
    with ProcessPoolExecutor(max_workers=workers, mp_context=context,
                             initializer=pin_worker, initargs=(cpu_queue,)) as pool:
        futures = [pool.submit(run_pair, (*job[:7], None, *job[8:])) for job in jobs]
        results = []
        for future in as_completed(futures):
            results.extend(future.result())
            print(f"completed {len(results)}/{args.pairs * 2} games", flush=True)
    results.sort(key=lambda g: (g["pair"], g["half"]))
    summary = summarize(results)
    summary.update({"base_commit": "8a750d9f90395b6f9a1cee49547b125c52a6f60b",
                    "engine_sha256": hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
                    "options": options, "policy": args.policy, "seed": args.seed,
                    "normal_ms": args.normal_ms, "bonus_ms": args.bonus_ms,
                    "max_plies": args.max_plies, "workers": workers,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "method_note": "Restarted short probe plus remaining budget; RNG advances on both searches. Pair shares color seeds, not forced opening. CI is pair-normal approximation."})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def pin_worker(cpu_queue):
    os.sched_setaffinity(0, {cpu_queue.get()})


if __name__ == "__main__":
    main()
