#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.kifu.build_dataset import build_dataset
from tools.kifu.export_samples import export_samples

SAMPLE = """V2.2
N+Black
N-White
PI
+
+7776FU
-3334FU
%TORYO
"""


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_kifu_validation.py VALIDATOR")
    validator = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        source = tmp / "sample.csa"
        source.write_text(SAMPLE, encoding="utf-8")
        games = tmp / "games.jsonl"
        manifest = tmp / "manifest.json"
        samples = tmp / "samples.jsonl"
        summary = build_dataset([source], games, manifest, strict=True)
        assert summary["games_written"] == 1
        exported = export_samples(games, validator, samples)
        assert exported["samples_written"] == 2
        rows = [json.loads(line) for line in samples.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["move_usi"] == "7g7f"
        assert rows[0]["outcome_for_side_to_move"] == -1
        assert rows[1]["move_usi"] == "3c3d"
        assert rows[1]["outcome_for_side_to_move"] == 1
        assert rows[0]["sfen"].endswith(" b - 1")
        assert rows[1]["sfen"].split()[1] == "w"

        # The validator, not the notation parser, is the final authority on
        # whether a move is legal in the reconstructed position.
        bad = subprocess.run(
            [str(validator)],
            input="bad\ttrain\tunknown\tlnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1\t7g7e\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert bad.returncode == 4, (bad.returncode, bad.stdout, bad.stderr)

    print("kifu learning validation: ok")


if __name__ == "__main__":
    main()
