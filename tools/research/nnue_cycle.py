#!/usr/bin/env python3
"""Resumable, bounded NNUE generation from OWN verified selfplay.

One command drives: verified archive -> deep study (checkpointed) ->
grouped outcome/own-search labels -> train/quantize -> native candidate
load/evaluation verification -> immutable research manifest.
It does NOT run evaluation games, promote a research parent, modify formal
Engine defaults, or persist raw games. Other existing arena/Release pathways
remain authoritative for actual selfplay and durable archive publication.
"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.research import nnue_deep_study, nnue_labels, train_nnue


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    part.replace(path)


def immutable_file(path, content):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable training input changed: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def verify_native(binary, model, sfen, expected_cp, knowledge, expected_positions=163):
    # Proper USI handshake and asynchronous search: avoid sending quit before
    # a move has actually been searched.
    p = subprocess.Popen([str(Path(binary).resolve())], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    messages = queue.Queue()
    def reader():
        for message in p.stdout:
            messages.put(message)
        messages.put(None)
    threading.Thread(target=reader, daemon=True).start()
    try:
        for line in (
            "usi",
            f"setoption name EvalNeuralFile value {Path(model).resolve()}",
            "setoption name EvalNeural value true",
            "setoption name OpeningRandomNonLance value false",
            "setoption name SearchThreads value 1",
            "setoption name PositionKnowledge value true",
            f"setoption name PositionKnowledgeFile value {Path(knowledge).resolve()}",
            "isready", "position sfen " + sfen,
            "eval", "go depth 1",
        ):
            p.stdin.write(line + "\n")
            p.stdin.flush()
        # Bounded watchdog even if engine deadlocks or stops producing output.
        transcript = []
        end = time.monotonic() + 60
        while time.monotonic() < end:
            try:
                line = messages.get(timeout=max(.01, end - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            transcript.append(line.rstrip())
            if line.startswith("bestmove "):
                break
        joined = "\n".join(transcript)
        if "neural_evaluation loaded width " not in joined:
            raise ValueError("candidate native NNUE did not load")
        if f"info string position_knowledge loaded {expected_positions} positions file " not in joined:
            raise ValueError("adopted position-knowledge asset not verified in candidate search")
        match = re.search(r"neural_evaluation static_cp_black (-?\d+)", joined)
        if not match or int(match.group(1)) != expected_cp:
            raise ValueError("native and training quantized evaluation disagree")
        if not any(line.startswith("info depth ") for line in transcript):
            raise ValueError("candidate had no completed alpha-beta search depth")
        if not any(line.startswith("bestmove ") for line in transcript):
            raise ValueError("candidate had no actual search response")
        return {
            "native_cp": int(match.group(1)),
            "search_completed": True,
            "bestmove": next(line.split()[1] for line in transcript if line.startswith("bestmove ")),
        }
    finally:
        if p.poll() is None:
            try:
                p.stdin.write("quit\n")
                p.stdin.flush()
                p.wait(timeout=3)
            except Exception:
                p.kill()
                p.wait(timeout=3)


def execute(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.parent_commit):
        raise ValueError("parent_commit must be immutable 40-hex source commit")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    input_record = {
        "schema": "nnue-generation-v1",
        "parent_commit": args.parent_commit,
        "engine_sha256": sha(args.engine.read_bytes()),
        "knowledge_sha256": sha(args.knowledge.read_bytes()),
        "archives": sorted([
            {"path": str(p.resolve()), "manifest_sha256": sha((p / "manifest.json").read_bytes())}
            for p in args.archive_dir
        ], key=lambda item: item["path"]),
        "study": {"max_cases": args.max_cases, "medium_ms": args.medium_ms,
                  "long_ms": args.long_ms, "branch_ms": args.branch_ms},
        "train": {"width": args.hidden, "epochs": args.epochs, "seed": args.seed}
    }
    immutable_file(out / "input-plan.json",
                   (json.dumps(input_record, sort_keys=True, indent=2) + "\n").encode())
    analysis_path = out / "deep-study.json"
    studied = nnue_deep_study.execute(
        args.archive_dir, args.engine, args.knowledge, analysis_path,
        max_cases=args.max_cases, per_game=4, short_ms=50,
        medium_ms=args.medium_ms, long_ms=args.long_ms,
        branch_ms=args.branch_ms, expected_positions=args.expected_positions)
    if studied["status"] != "analysis_complete_not_training_or_strength":
        raise ValueError("study did not complete")
    labels, meta = nnue_labels.convert(args.archive_dir, analysis_path, per_game=8)
    data = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                   for row in labels).encode()
    immutable_file(out / "nnue-labels.jsonl", data)
    meta["label_sha256"] = sha(data)
    immutable_file(out / "nnue-labels.manifest.json",
                   (json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    model = out / "candidate.nnue"
    training_report = out / "training.json"
    if model.exists() or training_report.exists():
        if not (model.exists() and training_report.exists()):
            raise ValueError("partial candidate publication: inspect and repair explicitly")
        if json.loads(training_report.read_text())["model_sha256"] != sha(model.read_bytes()):
            raise ValueError("saved model hash differs from previous training")
    else:
        subprocess.run([sys.executable, str(ROOT / "tools/research/train_nnue.py"),
                        "--data", str(out / "nnue-labels.jsonl"),
                        "--model", str(model), "--report", str(training_report),
                        "--hidden", str(args.hidden), "--epochs", str(args.epochs),
                        "--seed", str(args.seed)], check=True)
    report = json.loads(training_report.read_text())
    first = next(item for item in labels if item["sfen"])
    expected = train_nnue.evaluate_quantized(
        {"features": train_nnue.sparse_features(first["sfen"])}, model.read_bytes())
    native = verify_native(args.engine, model, first["sfen"], expected,
                           args.knowledge, args.expected_positions)
    final = dict(
        schema="nnue-generation-v1",
        state="research_candidate_ready_for_independent_evaluation",
        parent_commit=args.parent_commit, source_plan_sha256=sha((out/"input-plan.json").read_bytes()),
        analysis_checkpoint_sha256=sha(analysis_path.read_bytes()),
        study_completed=len(studied["results"]),
        focused_labels=meta["labels_by_origin"]["own_search"],
        regular_labels=meta["labels_by_origin"]["selfplay_result"],
        labels_sha256=sha(data), model_sha256=sha(model.read_bytes()),
        training_test_mae_cp=report["test_mae_cp"],
        native_verification=native,
        independent_matches="not_run",
        research_parent_promoted=False, formal_engine_adopted=False,
        caveat="training/USI plumbing proven, not playing-strength improvement",
    )
    atomic_json(out / "status.json", final)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return final


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-dir", type=Path, action="append", required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--knowledge", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--parent-commit", required=True)
    p.add_argument("--max-cases", type=int, default=4)
    p.add_argument("--medium-ms", type=int, default=600000)
    p.add_argument("--long-ms", type=int, default=3000000)
    p.add_argument("--branch-ms", type=int, default=600000)
    p.add_argument("--expected-positions", type=int, default=163)
    p.add_argument("--hidden", type=int, default=128)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--seed", type=int, default=20261021)
    args = p.parse_args()
    execute(args)


if __name__ == "__main__":
    main()
