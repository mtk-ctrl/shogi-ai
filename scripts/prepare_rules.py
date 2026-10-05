"""Prepare a pinned, auditable YaneuraOu rules subset; never follow latest."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "c1b80eaa09fe13d5f12b1599d1ae4d53c224de30"


def prepare(source=None):
    source = Path(source).resolve() if source else ROOT / "build/upstream/YaneuraOu"
    if not source.exists():
        source.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "fetch", "--depth=1",
                        "https://github.com/yaneurao/YaneuraOu.git", REVISION], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"], check=True)
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != REVISION:
        raise RuntimeError(f"Unexpected YaneuraOu revision: {head}")
    manifest = json.loads((ROOT / "third_party/yaneuraou/manifest.json").read_text())
    dest = ROOT / "build/yaneuraou-rules"
    dest.mkdir(parents=True, exist_ok=True)
    for name, expected in manifest["files"].items():
        data = (source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Upstream file changed: {name}")
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    subprocess.run(["git", "apply", "--unsafe-paths", "--directory", str(dest),
                    str(ROOT / "third_party/yaneuraou/rules-only.patch")], check=True, cwd=ROOT)
    return dest / "source"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    print(prepare(parser.parse_args().source))
