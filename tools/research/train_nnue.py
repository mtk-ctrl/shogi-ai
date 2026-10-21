#!/usr/bin/env python3
"""Train a self-authored, CPU-inference NNUE from *own* terminal games/search.

JSONL input contract (one sample per line):
 {"root_game_id":"g1", "sfen":"...", "origin":"own_search",
  "cp_black":230, "confidence":0.8}
 OR
 {"root_game_id":"g2", "sfen":"...", "origin":"selfplay_result",
  "outcome_black":-1, "terminal_confirmed":true, "confidence":0.5}

Never mark a losing move inherently wrong; a game's terminal outcome only
supplies a noisy position-value observation. No opponent scores or PVs.
All child variations inherit root_game_id. Holdouts are never reanalysed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import shogi

FEATURES = 81 * 2 * 14 + 2 * 7 * 18 + 2
SCALE = 256
KIND = {c: i + 1 for i, c in enumerate("PLNSBRGK")}


def sparse_features(sfen):
    # python-shogi performs shogi position parsing/validation; the sparse
    # encoding itself is new and mirrored independently in nnue_eval.h.
    shogi.Board(sfen)
    parts = sfen.split()
    if len(parts) != 4 or parts[1] not in ("b", "w"):
        raise ValueError("invalid SFEN")
    board, turn, hands, _ = parts
    rows = board.split("/")
    if len(rows) != 9:
        raise ValueError("invalid SFEN ranks")
    result = []
    for rank, row in enumerate(rows):
        file, i = 9, 0
        while i < len(row):
            char = row[i]
            if char in "123456789":
                file -= int(char)
                i += 1
                continue
            promoted = char == "+"
            if promoted:
                i += 1
                char = row[i]
            k = KIND[char.upper()]
            if promoted and k > 6:
                raise ValueError("invalid promotion")
            channel = (k + 7) if promoted else (k - 1)
            color = 0 if char.isupper() else 1
            result.append((color * 14 + channel) * 81 + (file - 1) * 9 + rank)
            file -= 1
            i += 1
        if file != 0:
            raise ValueError("incorrect file count")
    if hands != "-":
        i = 0
        while i < len(hands):
            j = i
            while j < len(hands) and hands[j].isdigit():
                j += 1
            if j == len(hands):
                raise ValueError("incorrect hand")
            count = int(hands[i:j]) if j > i else 1
            c = hands[j]
            kind = KIND[c.upper()] - 1
            if kind > 6 or count > 18:
                raise ValueError("invalid hand")
            side = 0 if c.isupper() else 1
            for n in range(count):
                result.append(81 * 2 * 14 + (side * 7 + kind) * 18 + n)
            i = j + 1
    result.append(FEATURES - (2 if turn == "b" else 1))
    return sorted(result)


def read_samples(path):
    samples = []
    sources = Counter()
    for line_num, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        origin = row.get("origin")
        if origin not in ("own_search", "selfplay_result"):
            raise ValueError(f"line {line_num}: unapproved teacher origin")
        root = row.get("root_game_id")
        if not isinstance(root, str) or not root.strip():
            raise ValueError(f"line {line_num}: missing original game group")
        confidence = float(row.get("confidence", 1.0))
        if not (0 < confidence <= 1):
            raise ValueError(f"line {line_num}: invalid confidence")
        if origin == "own_search":
            # The observation must already be oriented to Black (not side-to-move).
            if not isinstance(row.get("cp_black"), int) or isinstance(row["cp_black"], bool):
                raise ValueError(f"line {line_num}: missing Black-relative own-search score")
            target = int(np.clip(row["cp_black"], -3000, 3000))
            if row.get("score_bound", "exact") != "exact" or row.get("score_type", "cp") != "cp":
                raise ValueError(f"line {line_num}: incomplete/bounded/mate score not an exact cp target")
        else:
            if row.get("terminal_confirmed") is not True or row.get("outcome_black") not in (-1, 0, 1):
                raise ValueError(f"line {line_num}: unresolved game has no value label")
            target = 800 * row["outcome_black"]
        sfen = row["sfen"]
        features = sparse_features(sfen)
        sources[origin] += 1
        samples.append(dict(root=root, sfen=sfen, features=features,
                            target=target / 1000.0, weight=confidence))
    if len({s["root"] for s in samples}) < 3:
        raise ValueError("at least three independent root games needed for a train/validation/test split")
    return samples, sources


def split_groups(samples, seed):
    groups = sorted({s["root"] for s in samples},
                    key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).digest())
    n = len(groups)
    n_test = max(1, n // 10)
    n_valid = max(1, n // 10)
    test = set(groups[:n_test])
    valid = set(groups[n_test:n_test+n_valid])
    subsets = [[], [], []]
    for sample in samples:
        i = 2 if sample["root"] in test else 1 if sample["root"] in valid else 0
        subsets[i].append(sample)
    # Do not allow identical positions to leak across splits, including a
    # repeated opening in separate games. Drop validation/test duplicates.
    train_positions = {s["sfen"] for s in subsets[0]}
    subsets[1] = [s for s in subsets[1] if s["sfen"] not in train_positions]
    holdout_positions = train_positions | {s["sfen"] for s in subsets[1]}
    subsets[2] = [s for s in subsets[2] if s["sfen"] not in holdout_positions]
    if not all(subsets):
        raise ValueError("nonempty leakage-free train/validation/test samples required")
    return subsets


def predict(sample, embeddings, hidden_bias, head, output_bias):
    pre = hidden_bias + embeddings[sample["features"]].sum(axis=0)
    hidden = np.clip(pre, 0.0, 4.0)
    return float(hidden @ head + output_bias)


def mae(samples, embeddings, hidden_bias, head, output_bias):
    return float(sum(abs(predict(s, embeddings, hidden_bias, head, output_bias)
                         - s["target"]) * s["weight"] for s in samples)
                 / sum(s["weight"] for s in samples) * 1000)


def train(train_rows, validation_rows, hidden, epochs, lr, seed):
    rng = np.random.default_rng(seed)
    embeddings = rng.normal(0, 0.025, (FEATURES, hidden)).astype(np.float32)
    hidden_bias = np.full(hidden, 0.15, dtype=np.float32)
    head = rng.normal(0, 0.04 / np.sqrt(hidden), hidden).astype(np.float32)
    output_bias = np.float32(0)
    best = None
    for epoch in range(epochs):
        for ix in rng.permutation(len(train_rows)):
            s = train_rows[int(ix)]
            ids = s["features"]
            pre = hidden_bias + embeddings[ids].sum(axis=0)
            h = np.clip(pre, 0, 4)
            pred = float(h @ head + output_bias)
            # Huber derivative, no trusting extreme noisy outcome as perfect.
            derivative = np.clip(pred - s["target"], -0.5, 0.5) * s["weight"]
            grad_hidden = derivative * head * ((pre > 0) & (pre < 4))
            head -= lr * derivative * h
            output_bias -= lr * derivative
            hidden_bias -= lr * grad_hidden
            embeddings[ids] -= lr * grad_hidden
        current = mae(validation_rows, embeddings, hidden_bias, head, output_bias)
        if best is None or current < best[0]:
            best = (current, embeddings.copy(), hidden_bias.copy(), head.copy(), float(output_bias), epoch)
    return best


def export(path, embeddings, bias, head, output_bias):
    width = len(bias)
    def q16(array):
        scaled = np.rint(array * SCALE)
        if np.any(np.abs(scaled) > 32767):
            raise ValueError("weights overflow int16: adjust training scale")
        return scaled.astype("<i2")
    def q32(array):
        scaled = np.rint(array)
        if np.any(np.abs(scaled) > 2147483647):
            raise ValueError("bias overflow int32")
        return scaled.astype("<i4")
    payload = bytearray(struct.pack("<8sII", b"KMNNUE01", width, FEATURES))
    payload.extend(q32(bias * SCALE).tobytes())
    payload.extend(q16(embeddings).tobytes())
    payload.extend(q16(head).tobytes())
    payload.extend(q32(np.array([output_bias * SCALE * SCALE])).tobytes())
    Path(path).write_bytes(payload)


def evaluate_quantized(s, blob):
    _, width, nfeatures = struct.unpack_from("<8sII", blob)
    assert nfeatures == FEATURES
    bias = np.frombuffer(blob, dtype="<i4", count=width, offset=16).astype(np.int64)
    weight_offset = 16 + width * 4
    weights = np.frombuffer(blob, dtype="<i2", count=FEATURES * width,
                            offset=weight_offset).reshape(FEATURES, width)
    hidden = np.clip(bias + weights[s["features"]].sum(axis=0), 0, 1024)
    offset = weight_offset + FEATURES * width * 2
    head = np.frombuffer(blob, dtype="<i2", count=width, offset=offset)
    output_bias = struct.unpack_from("<i", blob, offset + width * 2)[0]
    total = int(hidden @ head.astype(np.int64)) + output_bias
    cp = (total * 1000 + 32768) // 65536 if total >= 0 else -((-total * 1000 + 32768) // 65536)
    return max(-30000, min(30000, cp))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--hidden", type=int, choices=(16, 32, 64, 128, 256, 512), default=128)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()
    if args.epochs < 1 or not (0 < args.lr <= .2):
        ap.error("epochs and learning rate out of range")
    samples, sources = read_samples(args.data)
    (training, validation, heldout) = split_groups(samples, args.seed)
    before = float(sum(abs(s["target"] * 1000) for s in heldout) / len(heldout))
    best = train(training, validation, args.hidden, args.epochs, args.lr, args.seed)
    _, embeddings, bias, head, output_bias, epoch = best
    args.model.parent.mkdir(parents=True, exist_ok=True)
    export(args.model, embeddings, bias, head, output_bias)
    blob = args.model.read_bytes()
    heldout_error = sum(abs(evaluate_quantized(s, blob) - s["target"] * 1000)
                        for s in heldout) / len(heldout)
    report = {
        "status": "trained_candidate_not_proven_stronger",
        "source_file_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(blob).hexdigest(),
        "source_counts": dict(sources), "total_samples": len(samples),
        "independent_root_games": len({s["root"] for s in samples}),
        "train_samples": len(training), "validation_samples": len(validation),
        "untouched_test_samples": len(heldout), "selected_epoch": epoch + 1,
        "width": args.hidden, "test_mae_cp": round(heldout_error, 2),
        "zero_baseline_test_mae_cp": round(before, 2),
        "source_policy": "own_search_and_confirmed_selfplay_only",
        "strength_test": "not_run",
        "formal_engine_adopted": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
