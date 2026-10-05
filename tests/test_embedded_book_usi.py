#!/usr/bin/env python3
"""Verify the standalone engine can load its compiled-in default opening book."""

from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_embedded_book_usi.py ENGINE")
    engine = Path(sys.argv[1]).resolve()
    if not engine.is_file():
        raise SystemExit(f"engine not found: {engine}")

    with tempfile.TemporaryDirectory(prefix="kumoji-book-") as cwd:
        proc = subprocess.run(
            [str(engine)],
            input="usi\nisready\nquit\n",
            text=True,
            capture_output=True,
            cwd=cwd,
            timeout=15,
            check=False,
        )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"engine exited with {proc.returncode}")
    if "usiok" not in proc.stdout or "readyok" not in proc.stdout:
        raise SystemExit(f"USI handshake failed:\n{proc.stdout}")
    if "info string opening_book loaded " not in proc.stdout:
        raise SystemExit(
            "embedded opening book was not loaded when external TSV was absent:\n"
            + proc.stdout
        )
    print("embedded opening book USI test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
