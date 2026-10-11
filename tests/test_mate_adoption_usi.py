#!/usr/bin/env python3
"""Regression: formally adopted mate model is embedded, ON by default and opt-out is real."""
from __future__ import annotations

import hashlib
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "engine/models/mate-learning-v2-100k.txt"
ENDGAME = "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105"


class Engine:
    def __init__(self, executable: str):
        self.process = subprocess.Popen([str(Path(executable).resolve())],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())

    def send(self, line: str):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def until(self, prefix: str, timeout: float = 12.0) -> list[str]:
        import time
        expiry = time.monotonic() + timeout
        seen = []
        while time.monotonic() < expiry:
            try:
                line = self.lines.get(timeout=max(0.01, expiry - time.monotonic()))
            except queue.Empty:
                break
            seen.append(line)
            if line.startswith(prefix):
                return seen
        raise AssertionError(f"Timed out waiting for {prefix}, last lines: {seen[-10:]}")

    def close(self):
        if self.process.poll() is None:
            self.send("quit")
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def stage(eng: Engine, sfen: str) -> dict:
    eng.send("position sfen " + sfen)
    eng.send("go movetime 200")
    lines = eng.until("bestmove ", 8)
    assert lines[-1].startswith("bestmove "), lines[-1]
    parsed = [x for x in lines if x.startswith("info string mate_stage ")]
    assert parsed, "No maturity-aware mate stage output: " + str(lines)
    words = parsed[-1].split()
    return {words[i]: words[i+1] for i in range(3, len(words)-1, 2)}


def main(executable: str):
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == (
        "dac182761519a1bebcf93317ebf5214d8a5ae3e65b339e93453fba023a9d0276"
    )
    eng = Engine(executable)
    try:
        eng.send("usi")
        lines = eng.until("usiok")
        assert any("id name KUMOJI v2.0.11" in x for x in lines)
        for option in ("MateLearning type check default true",
                       "MateStageBudget type check default true",
                       "MateBudgetProfile type combo default aggressive",
                       "MateLearningFile type string default embedded"):
            assert any(option in x for x in lines), option
        eng.send("isready")
        eng.until("readyok")
        eng.send("setoption name OpeningRandomNonLance value false")
        early = stage(eng, "4k4/9/9/9/9/9/9/9/4K4 b - 1")
        assert early["budget"] == "0", early
        embedded = stage(eng, ENDGAME)
        assert int(embedded["budget"]) > 0, embedded
        assert float(embedded["learned_score"]) >= 0, embedded

        eng.send("setoption name MateLearningFile value engine/models/mate-learning-v2-100k.txt")
        file_model = stage(eng, ENDGAME)
        assert file_model["learned_score"] == embedded["learned_score"], (file_model, embedded)

        eng.send("setoption name MateLearning value false")
        no_learn = stage(eng, ENDGAME)
        assert no_learn["learned_score"] == "-1", no_learn

        eng.send("setoption name MateLearning value true")
        eng.send("setoption name MateLearningFile value embedded")
        again = stage(eng, ENDGAME)
        assert again["learned_score"] == embedded["learned_score"], (again, embedded)

        eng.send("setoption name MateLearningFile value /this/file/does/not/exist")
        eng.until("info string mate_learning model_unavailable")
        no_model = stage(eng, ENDGAME)
        assert no_model["learned_score"] == "-1", no_model
        eng.send("setoption name MateLearningFile value embedded")
        restored = stage(eng, ENDGAME)
        assert restored["learned_score"] == embedded["learned_score"], (restored, embedded)
        print("PASS adopted 100k model embedded/default ON; stage budget; file equality; OFF; missing-file failure; restore")
    finally:
        eng.close()


if __name__ == "__main__":
    main(sys.argv[1])
