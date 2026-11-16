"""Floodgate専用の局面知識（正式163件＋追加分）の整合性。追加分は手順から局面キーが再現でき、手が合法であること。"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "floodgate"))
import build_knowledge as bk  # noqa: E402

_, base = bk.read_rows(ROOT / "position-knowledge-v1.tsv")
_, add = bk.read_rows(ROOT / "tools" / "floodgate" / "knowledge-additions.tsv")
assert len(base) == 163 and len(add) >= 1, (len(base), len(add))
bk.check_additions(add)
assert len({r[0] for r in add}) == len(add), "追加分の局面が重複している"
assert len({r[11] for r in add}) == len(add), "追加分のresearch_idが重複している"

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "merged.tsv"
    res = subprocess.run([sys.executable, str(ROOT / "tools/floodgate/build_knowledge.py"), "--out", str(out)],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    _, merged = bk.read_rows(out)
    assert len(merged) == len({r[0] for r in base} | {r[0] for r in add}), res.stdout
    keys = {r[0]: r[1] for r in merged}
    for r in add:
        assert keys[r[0]] == r[1]

print(f"PASS floodgate knowledge: base {len(base)} + additions {len(add)}")
