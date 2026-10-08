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



def research_direct_choice(research_ms, min_minutes, expected_direct, include_research=True):
    start_key = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -"
    with tempfile.TemporaryDirectory() as td:
        knowledge = Path(td) / "research.tsv"
        extra = f"\t{research_ms}\t8\t120000\tcp\t100\t30000" if include_research else ""
        knowledge.write_text(start_key + "\t7g7f\ttrial\t1" + extra + "\n", encoding="utf-8")
        u = Usi()
        try:
            u.send("usi")
            _, lines = u.until("usiok")
            assert any("option name ResearchDecisionMinMinutes type spin default 0" in x for x in lines)
            u.send(f"setoption name PositionKnowledgeFile value {knowledge}")
            u.send(f"setoption name ResearchDecisionMinMinutes value {min_minutes}")
            u.send("isready")
            u.until("readyok")
            u.send("usinewgame")
            u.send("position startpos")
            u.send("go depth 1")
            best, lines = u.until("bestmove")
            stat = next((x for x in reversed(lines) if "knowledge_direct_choices" in x), "")
            assert stat, lines
            assert f"knowledge_direct_choices {1 if expected_direct else 0}" in stat, stat
            if expected_direct:
                assert best == "bestmove 7g7f", best
                assert "knowledge_hits 1" in stat
        finally:
            u.close()


research_direct_choice(30 * 60 * 1000 + 1, 30, True)
research_direct_choice(30 * 60 * 1000 + 1, 60, False)
research_direct_choice(30 * 60 * 1000 + 1, 0, False)
research_direct_choice(0, 1, False, include_research=False)

run_once(True)
run_once(False)
embedded_default_fallback()
print("PASS position knowledge hint/order, embedded fallback, experimental direct-choice threshold")
