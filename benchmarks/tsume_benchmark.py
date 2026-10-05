#!/usr/bin/env python3
"""Benchmark the engine's USI `go mate` against fixed labelled-ply SFEN sets."""

import argparse
import json
import queue
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path

INFO_RE = re.compile(r"mate maxply (\d+) nodes (\d+) time (\d+)")


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
    return values[idx]


def normalize_sfen(line: str) -> str:
    line = line.strip()
    if line.startswith("position sfen "):
        line = line[len("position sfen "):]
    elif line.startswith("sfen "):
        line = line[len("sfen "):]
    return line


class MateEngine:
    def __init__(self, path: Path):
        self.proc = subprocess.Popen(
            [str(path.resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("usi")
        self.wait_prefix("usiok", 10)
        self.send("isready")
        self.wait_prefix("readyok", 10)

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))

    def send(self, command: str):
        if self.proc.poll() is not None:
            raise RuntimeError(f"engine exited with {self.proc.returncode}")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait_prefix(self, prefix: str, timeout: float):
        deadline = time.monotonic() + timeout
        seen = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-8:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-8:]}") from exc
            seen.append(line)
            if line.startswith(prefix):
                return line

    def solve(self, sfen: str, time_ms: int):
        self.send("position sfen " + normalize_sfen(sfen))
        started = time.monotonic()
        self.send(f"go mate {time_ms}")
        deadline = time.monotonic() + max(5.0, time_ms / 1000.0 + 3.0)
        info = None
        seen = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"go mate watchdog; seen={seen[-8:]}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"go mate watchdog; seen={seen[-8:]}") from exc
            seen.append(line)
            if line.startswith("info string mate maxply "):
                info = line
                continue
            if line.startswith("checkmate "):
                wall_ms = (time.monotonic() - started) * 1000.0
                tokens = line.split()[1:]
                result = {
                    "response": line,
                    "wall_ms": wall_ms,
                    "mate_plies": None if tokens == ["timeout"] else len(tokens),
                    "nodes": None,
                    "engine_ms": None,
                    "maxply": None,
                }
                if info:
                    match = INFO_RE.search(info)
                    if match:
                        result["maxply"] = int(match.group(1))
                        result["nodes"] = int(match.group(2))
                        result["engine_ms"] = int(match.group(3))
                return result

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


def summarize(expected_ply, rows):
    exact = sum(r["mate_plies"] == expected_ply for r in rows)
    shorter = sum(r["mate_plies"] is not None and r["mate_plies"] < expected_ply for r in rows)
    longer = sum(r["mate_plies"] is not None and r["mate_plies"] > expected_ply for r in rows)
    timeout = sum(r["mate_plies"] is None for r in rows)
    within = exact + shorter
    wall = [r["wall_ms"] for r in rows]
    eng = [r["engine_ms"] for r in rows if r["engine_ms"] is not None]
    nodes = [r["nodes"] for r in rows if r["nodes"] is not None]
    return {
        "expected_ply": expected_ply,
        "problems": len(rows),
        "solved_within_horizon": within,
        "solve_rate": within / len(rows) if rows else 0.0,
        "solved_exact": exact,
        "solved_shorter": shorter,
        "solved_longer": longer,
        "timeout_or_unproven": timeout,
        "exact_rate": exact / len(rows) if rows else 0.0,
        "wall_ms_median": statistics.median(wall) if wall else None,
        "wall_ms_mean": statistics.mean(wall) if wall else None,
        "wall_ms_p95": percentile(wall, 0.95),
        "engine_ms_median": statistics.median(eng) if eng else None,
        "nodes_median": statistics.median(nodes) if nodes else None,
        "nodes_mean": statistics.mean(nodes) if nodes else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=Path("benchmarks/tsume_dataset"))
    parser.add_argument("--plies", default="3,5,7,9,11")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--time-ms", type=int, default=2000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    plies = [int(x) for x in args.plies.split(",") if x]
    engine = MateEngine(args.engine)
    result = {
        "engine": str(args.engine),
        "time_ms": args.time_ms,
        "limit_per_ply": args.limit,
        "dataset_dir": str(args.dataset_dir),
        "by_ply": {},
    }
    try:
        for ply in plies:
            path = args.dataset_dir / f"mate{ply}_1000.sfen"
            lines = [x for x in path.read_text(encoding="ascii").splitlines() if x.strip()][:args.limit]
            rows = []
            for index, sfen in enumerate(lines):
                row = engine.solve(sfen, args.time_ms)
                row["index"] = index
                rows.append(row)
            entry = summarize(ply, rows)
            if args.details:
                entry["details"] = rows
            result["by_ply"][str(ply)] = entry
            print(json.dumps(entry, ensure_ascii=False))
    finally:
        engine.close()

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
