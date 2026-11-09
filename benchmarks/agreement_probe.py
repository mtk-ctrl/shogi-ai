#!/usr/bin/env python3
"""Self-agreement probe: does a 200 ms search find what the same engine finds in 3 s?

A cheap pre-screen for changes that should only make the search faster or deeper
(speed, pruning, parallelism). It is NOT a strength measure and NOT valid for
changes to the evaluation itself: those legitimately disagree with a reference
that uses the old evaluation. The reference is the engine's own long reading;
no external engine is used (R00/R50).

  make-positions  play short self-play games and keep positions (engine A only)
  reference       long reading (default 3000 ms) of every position -> reference file
  measure         short reading (default 200 ms) of every position -> agreement
  compare         paired comparison of two measure files (exact McNemar test)
"""
import argparse
import json
import math
import queue
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_OPTIONS = {
    # Position knowledge would replay stored moves and make agreement trivial.
    "PositionKnowledge": False,
    "AdaptiveLongThink": False,
    "USI_Ponder": False,
}


class Engine:
    def __init__(self, path, options):
        self.proc = subprocess.Popen([str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.send("usi")
        self.wait("usiok", 20)
        for key, value in options.items():
            text = str(value).lower() if isinstance(value, bool) else str(value)
            self.send(f"setoption name {key} value {text}")
        self.send("isready")
        self.wait("readyok", 60)
        self.send("usinewgame")

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)

    def send(self, text):
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def wait(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        seen = []
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"waiting for {prefix}: {seen[-5:]}")
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise TimeoutError(f"waiting for {prefix}: {seen[-5:]}")
            if line is None:
                raise RuntimeError("engine exited")
            seen.append(line)
            if line.startswith(prefix):
                return seen

    def think(self, moves, movetime_ms):
        self.send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self.send(f"go movetime {movetime_ms}")
        lines = self.wait("bestmove", movetime_ms / 1000 + 30)
        best = lines[-1].split()[1]
        depth = score = None
        for line in lines:
            if line.startswith("info depth") and " score cp " in line:
                parts = line.split()
                depth = int(parts[parts.index("depth") + 1])
                score = int(parts[parts.index("cp") + 1])
        return best, depth, score

    def new_game(self, seed):
        self.send(f"setoption name RandomSeed value {seed}")
        self.send("isready")
        self.wait("readyok", 60)
        self.send("usinewgame")

    def close(self):
        try:
            self.send("quit")
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def load_options(text):
    options = dict(DEFAULT_OPTIONS)
    options.update(json.loads(text) if text else {})
    return options


def cmd_make_positions(args):
    engine = Engine(args.engine, load_options(args.options))
    rng = random.Random(args.seed)
    positions = []
    game = 0
    while len(positions) < args.count:
        engine.new_game(args.seed * 1000 + game)
        moves = []
        for _ in range(args.max_plies):
            best, _, _ = engine.think(moves, args.movetime)
            if best in ("resign", "win") or len(best) < 4:
                break
            moves.append(best)
        game += 1
        # Skip the first 8 plies (opening noise) and the last 2 (may be terminal).
        candidates = list(range(8, len(moves) - 2))
        take = min(args.per_game, len(candidates))
        for ply in sorted(rng.sample(candidates, take)):
            positions.append({"game": game, "ply": ply, "moves": moves[:ply]})
        print(f"game {game}: {len(moves)} plies, {len(positions)} positions", file=sys.stderr, flush=True)
    engine.close()
    Path(args.output).write_text(json.dumps({"engine": str(args.engine), "movetime": args.movetime,
                                             "positions": positions[:args.count]}, ensure_ascii=False))


def read_positions(path):
    return json.loads(Path(path).read_text())["positions"]


def cmd_reference(args):
    positions = read_positions(args.positions)
    engine = Engine(args.engine, load_options(args.options))
    rows = []
    started = time.monotonic()
    for i, pos in enumerate(positions):
        best, depth, score = engine.think(pos["moves"], args.movetime)
        rows.append({"best": best, "depth": depth, "score": score})
        if (i + 1) % 25 == 0:
            print(f"{i + 1}/{len(positions)} {time.monotonic() - started:.0f}s", file=sys.stderr, flush=True)
    engine.close()
    Path(args.output).write_text(json.dumps({"engine": str(args.engine), "movetime": args.movetime,
                                             "options": load_options(args.options), "rows": rows}))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (centre - half, centre + half)


def cmd_measure(args):
    positions = read_positions(args.positions)
    reference = json.loads(Path(args.reference).read_text())["rows"]
    if len(reference) != len(positions):
        raise SystemExit("reference and positions differ in length")
    engine = Engine(args.engine, load_options(args.options))
    hits = []
    depths = []
    for _ in range(args.repeat):
        for pos, ref in zip(positions, reference):
            best, depth, _ = engine.think(pos["moves"], args.movetime)
            hits.append(best == ref["best"])
            if depth:
                depths.append(depth)
    engine.close()
    n, k = len(hits), sum(hits)
    lo, hi = wilson(k, n)
    result = {"engine": str(args.engine), "movetime": args.movetime, "options": load_options(args.options),
              "repeat": args.repeat, "positions": len(positions), "agree": k, "trials": n,
              "agreement": k / n, "wilson95": [lo, hi],
              "mean_depth": sum(depths) / len(depths) if depths else None, "hits": hits}
    Path(args.output).write_text(json.dumps(result))
    print(f"agreement {k}/{n} = {k / n:.1%} (95% {lo:.1%}-{hi:.1%}), mean depth {result['mean_depth']:.2f}")


def mcnemar_exact(b, c):
    """Two-sided exact p-value for discordant counts b (only A) and c (only B)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def cmd_compare(args):
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())
    if len(a["hits"]) != len(b["hits"]):
        raise SystemExit("different number of trials")
    only_a = sum(x and not y for x, y in zip(a["hits"], b["hits"]))
    only_b = sum(y and not x for x, y in zip(a["hits"], b["hits"]))
    print(f"A {a['agreement']:.1%}  B {b['agreement']:.1%}  difference {a['agreement'] - b['agreement']:+.1%}")
    print(f"only A agrees: {only_a}, only B agrees: {only_b}, exact McNemar p = {mcnemar_exact(only_a, only_b):.4f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, movetime):
        p.add_argument("--engine", required=True)
        p.add_argument("--options", default="", help="JSON USI options (added to the neutral defaults)")
        p.add_argument("--movetime", type=int, default=movetime)

    p = sub.add_parser("make-positions")
    common(p, 40)
    p.add_argument("--count", type=int, default=480)
    p.add_argument("--per-game", type=int, default=30)
    p.add_argument("--max-plies", type=int, default=200)
    p.add_argument("--seed", type=int, default=20261110)
    p.add_argument("--output", required=True)
    p.set_defaults(fn=cmd_make_positions)

    p = sub.add_parser("reference")
    common(p, 3000)
    p.add_argument("--positions", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(fn=cmd_reference)

    p = sub.add_parser("measure")
    common(p, 200)
    p.add_argument("--positions", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--output", required=True)
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_compare)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
