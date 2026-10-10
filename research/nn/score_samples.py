#!/usr/bin/env python3
"""Offline static scores for historical games from the chosen current KUMOJI binary.

This never runs "go" and never modifies the engine's playing policy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


def score_samples(input_path: Path, output_path: Path, engine_path: Path):
    p = subprocess.Popen([str(engine_path.resolve())], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, bufsize=1)
    if not p.stdin or not p.stdout:
        raise RuntimeError("engine pipes unavailable")
    def send(command):
        p.stdin.write(command + "\n")
        p.stdin.flush()
    try:
        send("usi")
        banner = []
        for _ in range(100):
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("engine failed to start USI")
            banner.append(line.strip())
            if line.strip() == "usiok":
                break
        if not any(line.startswith("id name KUMOJI") for line in banner):
            raise ValueError("not a KUMOJI evaluation engine")
        count = 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with input_path.open(encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as target:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                send("position sfen " + record["sfen"])
                send("eval")
                response = p.stdout.readline().strip()
                if not response.startswith("info string evaluation ") or " total " not in response:
                    raise RuntimeError("unexpected static evaluation response: " + response)
                value = response.rsplit(" total ", 1)[1].split()[0]
                record["static_cp_black"] = int(value)
                target.write(json.dumps(record, separators=(",", ":")) + "\n")
                count += 1
        return count
    finally:
        try:
            send("quit")
            p.wait(timeout=5)
        except Exception:
            p.kill()
            p.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({"evaluated_positions": score_samples(args.input, args.output, args.engine)}))


if __name__ == "__main__":
    main()
