#!/usr/bin/env python3
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ENGINE = str(Path(sys.argv[1]).resolve())


class Usi:
    def __init__(self, cwd=None):
        self.p = subprocess.Popen(
            [ENGINE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=cwd,
        )
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))

    def send(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()

    def until(self, prefix, timeout=10):
        end = time.monotonic() + timeout
        seen = []
        while time.monotonic() < end:
            try:
                line = self.q.get(timeout=max(0.01, end-time.monotonic()))
            except queue.Empty:
                continue
            seen.append(line)
            if line.startswith(prefix):
                return line, seen
        raise RuntimeError(f"timeout waiting for {prefix}: {seen[-10:]}")

    def close(self):
        if self.p.poll() is None:
            self.send("quit")
            self.p.wait(timeout=3)


def run_once(enabled):
    start_key = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -"
    with tempfile.TemporaryDirectory() as td:
        knowledge = Path(td) / "knowledge.tsv"
        knowledge.write_text(
            "# position-knowledge-v1-active\n"
            + start_key + "\t7g7f\ttest\t2\n",
            encoding="utf-8",
        )
        u = Usi()
        try:
            u.send("usi")
            _, usi = u.until("usiok")
            assert any("option name PositionKnowledge type check default true" in x for x in usi)
            u.send(f"setoption name PositionKnowledgeFile value {knowledge}")
            u.send(f"setoption name PositionKnowledge value {'true' if enabled else 'false'}")
            u.send("isready")
            _, ready = u.until("readyok")
            if enabled:
                assert any("position_knowledge loaded 1 positions" in x for x in ready), ready
            u.send("usinewgame")
            u.send("position startpos")
            u.send("go depth 1")
            _, lines = u.until("bestmove")
            stat = next((x for x in reversed(lines) if "knowledge_probes" in x), "")
            assert stat, lines
            if enabled:
                assert "knowledge_probes 1" in stat, stat
                assert "knowledge_hits 1" in stat, stat
                assert "knowledge_promotions 1" in stat, stat
            else:
                assert "knowledge_probes 0" in stat, stat
                assert "knowledge_hits 0" in stat, stat
        finally:
            u.close()


def embedded_default_fallback():
    # Derive the expected count from the adopted snapshot so every refresh is CI-checked.
    expected = sum(
        1 for line in (Path(__file__).resolve().parents[1] / "position-knowledge-v1.tsv").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    with tempfile.TemporaryDirectory() as td:
        u = Usi(cwd=td)
        try:
            u.send("usi")
            u.until("usiok")
            u.send("setoption name OpeningBook value false")
            u.send("setoption name ExperienceCache value false")
            u.send("isready")
            _, ready = u.until("readyok")
            assert any(f"position_knowledge loaded {expected} positions file position-knowledge-v1.tsv" in x for x in ready), ready
        finally:
            u.close()



def direct_research_line():
    sf = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -"
    with tempfile.TemporaryDirectory() as td:
        knowledge = Path(td) / "studied.tsv"
        knowledge.write_text(
            "# position-knowledge-v1-active\n" +
            sf + "\t2g2f\tresearch-test\t1\t60000\t6\t10000\tcp\t100\t"
            "\tresearch_decision\ttest-study\t2g2f 8c8d 7g7f 3c3d\n", encoding="utf-8")
        u = Usi()
        try:
            u.send("setoption name PositionKnowledgeFile value " + str(knowledge))
            u.send("isready")
            _, ready = u.until("readyok")
            assert any("loaded 1 positions" in x for x in ready), ready
            u.send("usinewgame")
            u.send("position startpos")
            u.send("go depth 1")
            best, logs = u.until("bestmove ")
            assert best == "bestmove 2g2f", logs
            assert any("research_decision id test-study step 1 total 4" in x for x in logs), logs
            u.send("position startpos moves 2g2f 8c8d")
            u.send("go depth 1")
            best, logs = u.until("bestmove ")
            assert best == "bestmove 7g7f", logs
            assert any("research_decision id test-study step 3 total 4" in x for x in logs), logs
            u.send("position startpos moves 2g2f 3c3d")
            u.send("go depth 1")
            _, logs = u.until("bestmove ")
            assert not any("research_decision" in x for x in logs), logs
            u.send("position startpos")
            u.send("go searchmoves 7g7f depth 1")
            best, logs = u.until("bestmove ")
            assert best == "bestmove 7g7f", logs
            assert not any("research_decision" in x for x in logs), logs
            u.send("setoption name PositionKnowledge value false")
            u.send("position startpos")
            u.send("go depth 1")
            _, logs = u.until("bestmove ")
            assert not any("research_decision" in x for x in logs), logs
            u.send("setoption name PositionKnowledge value true")
            u.send("position startpos")
            u.send("go depth 1")
            _, logs = u.until("bestmove ")
            assert any("research_decision" in x for x in logs), logs
        finally:
            u.close()


def adopted_real_snapshot():
    # Exercise a real adopted 60-second research position, not only the
    # hand-crafted start-position fixture above.
    source = Path(__file__).resolve().parents[1] / "position-knowledge-v1.tsv"
    rows = [line.split("\t") for line in source.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]
    adopted = [row for row in rows if len(row) == 13 and row[10] == "research_decision"]
    assert adopted and len(adopted) == len(rows), (len(adopted), len(rows))
    key, studied = adopted[0][0], adopted[0][1]
    pv = adopted[0][12].split()
    assert pv[0] == studied and len(pv) >= 3
    u = Usi()
    try:
        u.send("isready")
        _, ready = u.until("readyok")
        assert any(f"loaded {len(rows)} positions" in x for x in ready), ready
        u.send("usinewgame")
        u.send("position sfen " + key + " 1")
        u.send("go depth 1")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + studied, (best, lines)
        assert any("research_decision" in x for x in lines), lines
        u.send("position sfen " + key + " 1 moves " + " ".join(pv[:2]))
        u.send("go depth 1")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + pv[2], (best, lines)
        assert any("research_decision" in x and "step 3 " in x for x in lines), lines
    finally:
        u.close()

run_once(True)
run_once(False)
embedded_default_fallback()
direct_research_line()
adopted_real_snapshot()
print("PASS position knowledge USI load/probe/order, real PV adoption and fallback")
