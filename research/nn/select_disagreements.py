#!/usr/bin/env python3
"""Research-only disagreement screen, official KUMOJI phase and diverse 30-position handoff."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import shogi

from network import PositionNet, encode_sfen, sigmoid
from train_history import assign_groups


STAGES = ("opening", "middle", "end")
QUOTA = 10


def norm(sfen: str) -> str:
    return " ".join(sfen.split()[:3])


def official_maturity(development: int, battle: int, invasion: int):
    if not all(isinstance(x, int) and 0 <= x <= 100
               for x in (development, battle, invasion)):
        raise ValueError("phase probe returned invalid component")
    raw = (4408*development + 3852*battle + 1739*invasion + 5000)//10000 - 5
    maturity = min(100, max(0, raw))
    stage = ("opening" if maturity <= 33 else "middle" if maturity <= 66 else "end")
    return maturity, stage


class PhaseProbe:
    def __init__(self, executable: Path):
        self.proc = subprocess.Popen(
            [str(executable.resolve())], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, bufsize=1)
        if not self.proc.stdin or not self.proc.stdout:
            raise RuntimeError("cannot start phase probe")

    def classify(self, sfen: str):
        self.proc.stdin.write("position sfen " + sfen + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().strip()
        tokens = line.split()
        if len(tokens) != 11 or tokens[0:2] != ["phase", "development"]:
            raise RuntimeError("unexpected KUMOJI phase output: " + line)
        fields = {tokens[i]: int(tokens[i+1]) for i in range(1, 11, 2)}
        maturity, stage = official_maturity(
            fields["development"], fields["battle"], fields["invasion"])
        return maturity, stage, fields

    def close(self):
        try:
            self.proc.stdin.close()
            if self.proc.wait(timeout=3) != 0:
                raise RuntimeError("phase probe exited with error")
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=3)
            raise


def read_rows(path: Path):
    rows = []
    with path.open(encoding="utf8") as source:
        for line in source:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("source") != "kumoji_selfplay":
                raise ValueError("ineligible training source")
            if r.get("match_type") not in ("same_binary", "mixed_versions"):
                raise ValueError("match version provenance is required")
            moves = r.get("history_moves")
            if not isinstance(moves, list) or not all(isinstance(m, str) for m in moves):
                raise ValueError("historical move list is required")
            if type(r.get("static_cp_black")) is not int:
                raise ValueError("current KUMOJI static score required")
            rows.append(r)
    if not rows:
        raise ValueError("no research source data")
    return rows


def calculate_probabilities(rows: list[dict], model: PositionNet, temperature: float):
    for start in range(0, len(rows), 512):
        batch = rows[start:start + 512]
        x = np.stack([encode_sfen(r["sfen"]) for r in batch])
        predicted = model.predict(x)
        cp = np.asarray([r["static_cp_black"] for r in batch], dtype=np.float32)
        baseline = sigmoid(cp / temperature)
        for row, neural, old in zip(batch, predicted, baseline):
            row["nn_probability_black"] = float(neural)
            row["static_probability_black"] = float(old)
            row["probability_gap"] = abs(float(neural) - float(old))


def validate_history(row):
    board = shogi.Board()
    for token in row["history_moves"]:
        move = shogi.Move.from_usi(token)
        if move not in board.legal_moves:
            raise ValueError("invalid archived history move: " + token)
        board.push(move)
    if norm(board.sfen()) != norm(row["sfen"]):
        raise ValueError("reconstructed history does not match recorded SFEN")


def select(source: Path, model_path: Path, model_report: Path,
           phase_executable: Path, knowledge: Path, opening: Path, older: Path,
           destination: Path):
    from sys import path as import_paths
    import_paths.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "research"))
    from timebox40 import prior

    report = json.loads(model_report.read_text(encoding="utf8"))
    temperature = report.get("static_score_temperature_fitted_on_training")
    if type(temperature) not in (float, int) or not 100 <= temperature <= 100000:
        raise ValueError("invalid saved training-only static calibration")
    selected_model = PositionNet.load(model_path)
    rows = read_rows(source)
    groups = assign_groups(rows)
    # Test runs remain sealed for performance assessment: active research does not
    # use them. Validation run first, then training run only as a fallback.
    pool = [r for r in rows if groups[r["source_group"]] != "test"]
    calculate_probabilities(pool, selected_model, float(temperature))
    pool.sort(key=lambda r: (
        groups[r["source_group"]] == "train",
        -r["probability_gap"], r["source_group"], r["game_id"], r["ply"]))
    known = prior(knowledge, opening, older)
    used_boards, used_games = set(), set()
    counts = Counter()
    candidates = {stage: [] for stage in STAGES}
    stage_groups = {stage: Counter() for stage in STAGES}
    probe = PhaseProbe(phase_executable)
    try:
        for row in pool:
            key = norm(row["sfen"])
            if key in known or key in used_boards or row["game_id"] in used_games:
                continue
            maturity, stage, components = probe.classify(row["sfen"])
            counts["eligible_" + stage] += 1
            if len(candidates[stage]) >= QUOTA:
                continue
            # Avoid one source run filling a stage; this is only a diversity
            # control for exploratory research, not a statistical significance rule.
            if stage_groups[stage][row["source_group"]] >= 5:
                continue
            validate_history(row)
            item = dict(
                stage=stage, maturity=maturity,
                sfen=key, history_moves=row["history_moves"],
                game_id=row["game_id"], source_run=row["source_group"],
                source_match=row["match_type"], source_ply=row["ply"],
                static_cp_black=row["static_cp_black"],
                nn_probability_black=round(row["nn_probability_black"], 8),
                static_probability_black=round(row["static_probability_black"], 8),
                absolute_gap=round(row["probability_gap"], 8),
                phase_components=components)
            candidates[stage].append(item)
            stage_groups[stage][row["source_group"]] += 1
            used_boards.add(key)
            used_games.add(row["game_id"])
            if all(len(candidates[s]) == QUOTA for s in STAGES):
                break
    finally:
        probe.close()
    missing = {s: QUOTA-len(candidates[s]) for s in STAGES if len(candidates[s]) != QUOTA}
    if missing:
        raise ValueError("cannot fill balanced 30 positions under diversity constraints: " +
                         json.dumps(missing))
    ordered = []
    for stage, short in (("opening", "O"), ("middle", "M"), ("end", "E")):
        for i, row in enumerate(candidates[stage], 1):
            row["id"] = f"nn-disagreement-{short}{i:02d}"
            ordered.append(row)
    destination.mkdir(parents=True, exist_ok=True)
    positions_path = destination / "positions.tsv"
    positions_path.write_text("#id\tSFEN\tUSI move history\n" + "".join(
        f"{r['id']}\t{r['sfen']}\t{' '.join(r['history_moves'])}\n" for r in ordered),
        encoding="utf8")
    # Do not compare NN to '50-min correct answer' at this step.
    metadata = dict(
        schema="nn-disagreement-selection-v1",
        purpose="30 candidate discrepancies, 10 in each official phase",
        selection_policy="largest absolute predicted win probability gap; diverse games and source runs",
        preserved_test_partition=True,
        training_label_caveat="Older mixed-version KUMOJI results are confounded by engine strengths.",
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        model_report_sha256=hashlib.sha256(model_report.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        phase_executable_sha256=hashlib.sha256(phase_executable.read_bytes()).hexdigest(),
        calibration_temperature=float(temperature),
        quotas={stage: QUOTA for stage in STAGES},
        positions=ordered, automatically_adopted=False)
    (destination / "selection.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return metadata


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--model-report", type=Path, required=True)
    p.add_argument("--phase-probe", type=Path, required=True)
    p.add_argument("--knowledge", type=Path, required=True)
    p.add_argument("--opening", type=Path, required=True)
    p.add_argument("--older", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    result = select(a.source, a.model, a.model_report,
                    a.phase_probe, a.knowledge, a.opening, a.older,
                    a.output_dir)
    print(json.dumps({"selected": len(result["positions"]),
                      "stage_counts": result["quotas"],
                      "model_sha256": result["model_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
