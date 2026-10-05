#!/usr/bin/env python3
"""Create a small reproducible benchmark set from YaneuraOu's 5M tsume archive."""

import argparse
import hashlib
import json
import random
import zipfile
from pathlib import Path

PLIES = (3, 5, 7, 9, 11)
DEFAULT_SEED = 20261005
SOURCE_PAGE = "https://yaneuraou.yaneu.com/2020/12/25/christmas-present/"
SOURCE_DRIVE_ID = "1nJbFFaQeOx3gFafiVIR_oDIcG8iCOHf4"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/tsume_dataset"))
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    archive_bytes = args.archive.read_bytes()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "YaneuraOu 5M tsume fixed benchmark subset",
        "source_page": SOURCE_PAGE,
        "source_drive_file_id": SOURCE_DRIVE_ID,
        "source_archive_bytes": len(archive_bytes),
        "source_archive_sha256": sha256(archive_bytes),
        "sample_count_per_ply": args.count,
        "base_seed": args.seed,
        "sampling": "random.Random(base_seed + ply).sample(range(nonempty_line_count), count), sorted by source index",
        "files": {},
    }

    with zipfile.ZipFile(args.archive) as archive:
        for ply in PLIES:
            member = f"mate{ply}.sfen"
            raw = archive.read(member)
            lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip()]
            if len(lines) < args.count:
                raise SystemExit(f"{member}: only {len(lines)} non-empty lines")
            rng = random.Random(args.seed + ply)
            indices = sorted(rng.sample(range(len(lines)), args.count))
            sample = [lines[i] for i in indices]
            output = args.out / f"mate{ply}_{args.count}.sfen"
            text = "\n".join(sample) + "\n"
            output.write_text(text, encoding="ascii")
            manifest["files"][str(ply)] = {
                "source_member": member,
                "source_nonempty_lines": len(lines),
                "source_member_sha256": sha256(raw),
                "sample_file": output.name,
                "sample_sha256": sha256(text.encode("ascii")),
                "first_source_index": indices[0],
                "last_source_index": indices[-1],
            }

    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
