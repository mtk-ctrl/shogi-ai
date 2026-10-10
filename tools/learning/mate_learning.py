#!/usr/bin/env python3
"""Self-supervised, bounded 7-ply mate-gate experiment.

collect: ask KUMOJI for its *own* search outcome and numeric features.
train: fit a tiny deterministic logistic gate, never treat timeouts as negatives.
Only the experimental MateLearning USI option consumes an exported model.
No external engine scores or recommended moves are used as training labels.
"""
import argparse
import hashlib
import json
import math
import queue
import random
import subprocess
import threading
import time
from pathlib import Path

SCHEMA = "mate-gate-samples-v1"
DIM = 8
PLIES = (3, 5, 7, 9, 11)
FEATURE_TAG = "info string learning_features v1 "
BOUNDED_TAG = "info string mate bounded_status "


class Engine:
    def __init__(self, executable):
        self.proc = subprocess.Popen([str(Path(executable).resolve())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.send("usi")
        self.until("usiok", 15)
        self.send("isready")
        self.until("readyok", 20)

    def _read(self):
        for line in self.proc.stdout:
            self.q.put(line.strip())

    def send(self, command):
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def until(self, prefix, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                line = self.q.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line.startswith(prefix):
                return line
        raise TimeoutError("engine did not return " + prefix)

    def observe(self, sfen, time_ms):
        self.send("position sfen " + sfen)
        self.send("learning_features")
        feature_line = self.until("info string learning_features ", 8)
        if not feature_line.startswith(FEATURE_TAG):
            raise ValueError("invalid feature response: " + feature_line)
        values = [float(x) for x in feature_line[len(FEATURE_TAG):].split()]
        if len(values) != DIM or not all(math.isfinite(x) for x in values):
            raise ValueError("invalid feature count or value")
        self.send("go mate " + str(time_ms))
        status, response = None, None
        deadline = time.monotonic() + max(8, time_ms / 1000 + 5)
        while time.monotonic() < deadline:
            try:
                line = self.q.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line.startswith(BOUNDED_TAG):
                status = line[len(BOUNDED_TAG):]
            if line.startswith("checkmate "):
                response = line
                break
        if response is None:
            raise TimeoutError("engine did not complete bounded mate")
        if status == "proven_mate" and response != "checkmate timeout":
            label = 1
        elif status == "no_mate_within_7" and response == "checkmate timeout":
            label = 0
        else:
            label = None  # interrupted and ambiguous results are NEVER negatives
        return values, label, status

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()


def normalize_sfen(value):
    value = value.strip()
    for prefix in ("position sfen ", "sfen "):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def collect(args):
    engine = Engine(args.engine)
    rows, seen = [], set()
    skipped = {}
    try:
        for ply in PLIES:
            path = args.dataset_dir / f"mate{ply}_1000.sfen"
            for sfen in path.read_text(encoding="ascii").splitlines()[:args.limit_per_ply]:
                sfen = normalize_sfen(sfen)
                if not sfen or sfen in seen:
                    continue
                seen.add(sfen)
                values, label, status = engine.observe(sfen, args.time_ms)
                if label is None:
                    skipped[status] = skipped.get(status, 0) + 1
                    continue
                rows.append({"schema": SCHEMA, "sfen": sfen, "source_ply": ply,
                             "horizon": 7, "features": values, "label": label})
    finally:
        engine.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"records": len(rows), "positive": sum(x["label"] for x in rows),
                      "negative": sum(1 - x["label"] for x in rows),
                      "excluded_unproven_or_interrupted": skipped, "output": str(args.out)},
                     ensure_ascii=False))


def sigmoid(x):
    x = max(-30, min(30, x))
    return 1 / (1 + math.exp(-x))


def parse_samples(path):
    rows, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        f = row.get("features")
        if row.get("schema") != SCHEMA or row.get("horizon") != 7 or row.get("label") not in (0, 1):
            raise ValueError("invalid sample metadata")
        if (not isinstance(f, list) or len(f) != DIM
                or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in f)):
            raise ValueError("invalid sample features")
        sfen = row["sfen"]
        if sfen in seen:
            raise ValueError("duplicate position across samples")
        seen.add(sfen)
        rows.append(row)
    return rows


def split(rows, seed):
    # Stratified deterministic split. Full near-duplicate grouping is a future
    # requirement before claiming performance on unseen positions.
    rng = random.Random(seed)
    grouped = {0: [], 1: []}
    for r in rows:
        grouped[r["label"]].append(r)
    if min(len(v) for v in grouped.values()) < 4:
        raise ValueError("need >=4 VERIFIED positive and negative examples")
    train, test = [], []
    for label in (0, 1):
        rng.shuffle(grouped[label])
        n_test = max(1, len(grouped[label]) // 4)
        test.extend(grouped[label][:n_test])
        train.extend(grouped[label][n_test:])
    return train, test


def fit(rows, epochs=350, step=0.08, regularization=0.02):
    mean = [sum(r["features"][j] for r in rows) / len(rows) for j in range(DIM)]
    scale = [max(1.0, math.sqrt(sum((r["features"][j] - mean[j]) ** 2
                    for r in rows) / len(rows))) for j in range(DIM)]
    w = [0.0] * DIM
    b = 0.0
    pos = sum(r["label"] for r in rows)
    neg = len(rows) - pos
    if not pos or not neg:
        raise ValueError("both classes required")
    # Balanced batch logistic loss; model estimates a ranking score, NOT a
    # calibrated true probability under the real-game distribution.
    for _ in range(epochs):
        dw, db = [0.0] * DIM, 0.0
        for r in rows:
            x = [(r["features"][j] - mean[j]) / scale[j] for j in range(DIM)]
            p = sigmoid(b + sum(a * t for a, t in zip(w, x)))
            sample_weight = len(rows) / (2 * (pos if r["label"] else neg))
            e = (p - r["label"]) * sample_weight / len(rows)
            db += e
            for j in range(DIM):
                dw[j] += e * x[j]
        w = [max(-30, min(30, v - step * (g + regularization * v)))
             for v, g in zip(w, dw)]
        b = max(-30, min(30, b - step * db))
    return mean, scale, w, b


def accuracy(rows, model, threshold):
    mean, scale, w, b = model
    tp = fp = tn = fn = 0
    for r in rows:
        x = [(r["features"][j] - mean[j]) / scale[j] for j in range(DIM)]
        pred = sigmoid(b + sum(a * t for a, t in zip(w, x))) >= threshold
        actual = r["label"] == 1
        if pred and actual:
            tp += 1
        elif pred:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
    return {"true_positive": tp, "false_positive": fp,
            "true_negative": tn, "false_negative": fn,
            "accuracy": (tp + tn) / len(rows),
            "precision_when_triggered": tp / (tp + fp) if (tp + fp) else None,
            "recall": tp / (tp + fn) if (tp + fn) else None}


def train(args):
    rows = parse_samples(args.samples)
    source_sha256 = hashlib.sha256(args.samples.read_bytes()).hexdigest()
    train_rows, test_rows = split(rows, args.seed)
    model = fit(train_rows)
    mean, scale, weight, bias = model
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.model.write_text(
        "KUMOJI_MATE_GATE_V1\n"
        + "mean " + " ".join(format(x, ".12g") for x in mean) + "\n"
        + "scale " + " ".join(format(x, ".12g") for x in scale) + "\n"
        + "weight " + " ".join(format(x, ".12g") for x in weight) + "\n"
        + "bias " + format(bias, ".12g") + "\n"
        + "threshold " + format(args.threshold, ".12g") + "\n", encoding="ascii")
    report = {"model": str(args.model), "training_file_sha256": source_sha256,
              "seed": args.seed, "bounded_mate_horizon": 7,
              "train_samples": len(train_rows), "holdout_samples": len(test_rows),
              "threshold": args.threshold,
              "train": accuracy(train_rows, model, args.threshold),
              "holdout": accuracy(test_rows, model, args.threshold),
              "note": "Research gate only; uncalibrated and not evidence of increased playing strength"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest="command", required=True)
    a = cmd.add_parser("collect")
    a.add_argument("--engine", type=Path, required=True)
    a.add_argument("--dataset-dir", type=Path, default=Path("benchmarks/tsume_dataset"))
    a.add_argument("--limit-per-ply", type=int, default=30)
    a.add_argument("--time-ms", type=int, default=2000)
    a.add_argument("--out", type=Path, default=Path("research/mate-learning-samples.jsonl"))
    b = cmd.add_parser("train")
    b.add_argument("--samples", type=Path, required=True)
    b.add_argument("--model", type=Path, default=Path("research/mate-learning-model.txt"))
    b.add_argument("--report", type=Path, default=Path("research/mate-learning-report.json"))
    b.add_argument("--seed", type=int, default=20261011)
    b.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    if args.command == "collect":
        if args.limit_per_ply < 1 or args.limit_per_ply > 1000 or args.time_ms < 1:
            parser.error("invalid limits")
        collect(args)
    else:
        if not 0.5 <= args.threshold <= 0.99:
            parser.error("threshold must be 0.5..0.99")
        train(args)


if __name__ == "__main__":
    main()
