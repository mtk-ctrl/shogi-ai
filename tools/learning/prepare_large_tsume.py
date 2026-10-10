#!/usr/bin/env python3
"""Verify the official public 5M mate archive and select unseen study problems.

Only board positions are borrowed; proof labels and decisions are computed by
KUMOJI's own bounded mate solver. The fixed 5,000 benchmark problems are
excluded, so an increase in sample count represents genuinely new positions.
"""
import argparse
import hashlib
import json
import random
import zipfile
from pathlib import Path

PLIES = (3, 5, 7, 9, 11)
EXPECTED = "b8c89b98662d01447230bac481c875729cb54145a1eca8a7d52e2b9474812a8b"
SOURCE_ID = "1nJbFFaQeOx3gFafiVIR_oDIcG8iCOHf4"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sample(archive, fixed_dir, output, per_ply, seed):
    if digest(archive) != EXPECTED:
        raise ValueError("Official archive SHA-256 mismatch, refusing unverified input")
    output.mkdir(parents=True, exist_ok=True)
    summary = {"source_drive_file_id": SOURCE_ID, "source_sha256": EXPECTED,
               "seed": seed, "per_ply": per_ply, "files": {}}
    with zipfile.ZipFile(archive) as full:
        for ply in PLIES:
            fixed = set((fixed_dir / f"mate{ply}_1000.sfen").read_text(encoding="ascii").splitlines())
            # Published source is roughly 1M examples per group. Select more
            # index candidates than needed to compensate for fixed-set overlap.
            total = {3: 998404, 5: 998824, 7: 999071, 9: 999672, 11: 999998}[ply]
            candidates = set(random.Random(seed + ply).sample(
                range(total), min(total, per_ply + max(500, per_ply // 20))))
            lines = []
            with full.open(f"mate{ply}.sfen") as stream:
                for idx, raw in enumerate(stream):
                    if idx not in candidates:
                        continue
                    sfen = raw.decode("ascii").strip()
                    if sfen and sfen not in fixed:
                        lines.append((idx, sfen))
            lines.sort(key=lambda item: item[0])
            distinct, seen = [], set()
            for idx, sfen in lines:
                if sfen in seen:
                    continue
                seen.add(sfen)
                distinct.append(sfen)
                if len(distinct) == per_ply:
                    break
            if len(distinct) != per_ply:
                raise ValueError(f"not enough unseen mate{ply} positions: {len(distinct)}/{per_ply}")
            file = output / f"mate{ply}_{per_ply}.sfen"
            file.write_text("\n".join(distinct) + "\n", encoding="ascii")
            summary["files"][str(ply)] = {"file": file.name, "count": len(distinct),
                                        "sha256": digest(file),
                                        "excluded_fixed_count": len(fixed)}
    (output / "source-manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--fixed-dir", type=Path, default=Path("benchmarks/tsume_dataset"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per-ply", type=int, default=20000)
    p.add_argument("--seed", type=int, default=20261011)
    args = p.parse_args()
    if not 1 <= args.per_ply <= 100000:
        p.error("per-ply must be 1..100000")
    sample(args.archive, args.fixed_dir, args.out, args.per_ply, args.seed)
