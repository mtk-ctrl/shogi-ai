#!/usr/bin/env python3
"""Extract new non-overlapping positions from the approved YaneuraOu archive."""
import argparse
import hashlib
import json
import random
import zipfile
from pathlib import Path

PLIES = (3, 5, 7, 9, 11)
EXPECTED_SHA = "b8c89b98662d01447230bac481c875729cb54145a1eca8a7d52e2b9474812a8b"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--exclude", type=Path, default=Path("benchmarks/tsume_dataset"))
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20261012)
    args = ap.parse_args()
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA:
        raise SystemExit("Official source archive checksum mismatch")
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"archive_sha256": digest, "seed": args.seed, "per_group": args.count, "files": {}}
    with zipfile.ZipFile(args.archive) as z:
        for ply in PLIES:
            src = z.read(f"mate{ply}.sfen").decode("ascii").splitlines()
            excluded = set((args.exclude / f"mate{ply}_1000.sfen").read_text(encoding="ascii").splitlines())
            rng = random.Random(args.seed + ply)
            indices = list(range(len(src)))
            rng.shuffle(indices)
            selected, seen = [], set()
            for i in indices:
                s = src[i].strip()
                if s and s not in excluded and s not in seen:
                    selected.append(s)
                    seen.add(s)
                    if len(selected) == args.count:
                        break
            if len(selected) != args.count:
                raise SystemExit(f"Not enough fresh positions in {ply}")
            data = ("\n".join(selected) + "\n").encode("ascii")
            name = f"mate{ply}_1000.sfen"
            (args.out / name).write_bytes(data)
            report["files"][str(ply)] = {"count": len(selected), "sha256": hashlib.sha256(data).hexdigest(), "excluded_previous": len(excluded)}
    (args.out / "expanded-manifest.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))

if __name__ == "__main__":
    main()
