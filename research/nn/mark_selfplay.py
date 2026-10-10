#!/usr/bin/env python3
"""Mark a freshly-generated match only after checking its engine binary hashes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def mark(input_path: Path, engine_path: Path, output_path: Path):
    data = json.loads(input_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    if data.get("sha256_a") != actual or data.get("sha256_b") != actual:
        raise ValueError("match binaries do not match the trusted self-play engine")
    if not isinstance(data.get("details"), list) or not data["details"]:
        raise ValueError("missing match details")
    if data.get("learning_origin") not in (None, "kumoji_selfplay"):
        raise ValueError("dataset is labelled with a different origin")
    data["learning_origin"] = "kumoji_selfplay"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    mark(args.input, args.engine, args.output)


if __name__ == "__main__":
    main()
