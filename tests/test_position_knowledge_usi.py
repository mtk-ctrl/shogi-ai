#!/usr/bin/env python3
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import shogi
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
        # Knowledge tests exercise root search, not the adopted random opening.
        # It is disabled explicitly so root knowledge telemetry is observable.
        self.send("setoption name OpeningRandomNonLance value false")

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
            "\tresearch_decision\ttest-study\t2g2f 8c8d 7g7f 3c3d\t-\n", encoding="utf-8")
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
    adopted = [row for row in rows if len(row) == 14 and row[10] == "research_decision"]
    assert adopted and len(adopted) == len(rows), (len(adopted), len(rows))
    key, studied = adopted[0][0], adopted[0][1]
    pv = adopted[0][12].split()
    history = adopted[0][13].split() if adopted[0][13] != "-" else []
    assert history, "real research test must cover a nontrivial original arrival history"
    command = "position startpos" + (" moves " + " ".join(history) if history else "")
    assert pv[0] == studied and len(pv) >= 3
    u = Usi()
    try:
        u.send("isready")
        _, ready = u.until("readyok")
        assert any(f"loaded {len(rows)} positions" in x for x in ready), ready
        u.send("usinewgame")
        u.send(command)
        u.send("go depth 1")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + studied, (best, lines)
        assert any("research_decision" in x for x in lines), lines
        u.send("position startpos moves " + " ".join(history + pv[:2]))
        u.send("go depth 1")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + pv[2], (best, lines)
        assert any("research_decision" in x and "step 3 " in x for x in lines), lines
        # Same board reached without original history must force the study.
        u.send("position sfen " + key + " 1")
        u.send("go movetime 200")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + studied, (best, lines)
        assert any("research_decision" in x for x in lines), lines
        # Once we adopt, continuation uses actual history, not the study's route.
        u.send("position sfen " + key + " 1 moves " + " ".join(pv[:2]))
        u.send("go depth 1")
        best, lines = u.until("bestmove ")
        assert best == "bestmove " + pv[2], (best, lines)
        assert any("research_decision" in x and "step 3 " in x for x in lines), lines
    finally:
        u.close()



def all_adopted_research_positions():
    """Regress all approved studies, WITHOUT the source game's arrival history."""
    source = Path(__file__).resolve().parents[1] / "position-knowledge-v1.tsv"
    entries = [line.split("\t") for line in source.read_text(encoding="utf-8").splitlines()
               if line and not line.startswith("#")]
    assert len(entries) == 153, len(entries)
    u = Usi()
    try:
        u.send("isready")
        _, ready = u.until("readyok")
        assert any("loaded 153 positions" in x for x in ready), ready
        for i, row in enumerate(entries, 1):
            assert len(row) == 14 and row[10] == "research_decision"
            key, move = row[0], row[1]
            u.send("position sfen " + key + " 1")
            u.send("go movetime 200")
            actual, logs = u.until("bestmove ", timeout=10)
            assert actual == "bestmove " + move, (i, row[11], actual, move, logs)
            assert any(x.startswith("info string research_decision id " + row[11])
                       for x in logs), (i, row[11], logs)
    finally:
        u.close()




def newer_direct_study_overrides_previous_continuation():
    """A separately adopted study of the reached position wins over old PV."""
    source = Path(__file__).resolve().parents[1] / "position-knowledge-v1.tsv"
    row = next(line.split("\t") for line in source.read_text(encoding="utf-8").splitlines()
               if line and not line.startswith("#"))
    original_pv = row[12].split()
    original_history = row[13].split()
    board = shogi.Board(row[0] + " 1")
    for move in original_pv[:2]:
        board.push_usi(move)
    next_key = " ".join(board.sfen().split()[:3])
    alternate = next((m.usi() for m in board.legal_moves
                      if m.usi() != original_pv[2]), None)
    assert alternate, "need another legal move to distinguish direct study"
    alternate_pv = [alternate]
    for _ in range(2):
        board.push_usi(alternate_pv[-1])
        alternate_pv.append(next(iter(board.legal_moves)).usi())
    next_row = [
        next_key, alternate, "second-research", "1", "3000000", "7", "1234",
        "cp", "100", "", "research_decision", "new-direct-study",
        " ".join(alternate_pv), " ".join(original_history + original_pv[:2]),
    ]
    assert len(next_row) == 14
    with tempfile.TemporaryDirectory() as td:
        knowledge = Path(td) / "overlap.tsv"
        knowledge.write_text("# position-knowledge-v1-active\n"
                             + "\t".join(row) + "\n"
                             + "\t".join(next_row) + "\n", encoding="utf-8")
        u = Usi()
        try:
            u.send("setoption name PositionKnowledgeFile value " + str(knowledge))
            u.send("isready")
            _, ready = u.until("readyok")
            assert any("loaded 2 positions" in line for line in ready), ready
            u.send("position startpos moves " + " ".join(original_history))
            u.send("go depth 1")
            first, lines = u.until("bestmove ")
            assert first == "bestmove " + original_pv[0], (first, lines)
            u.send("position startpos moves " + " ".join(original_history + original_pv[:2]))
            u.send("go depth 1")
            second, lines = u.until("bestmove ")
            assert second == "bestmove " + alternate, (second, lines)
            assert any("research_decision id new-direct-study" in line
                       for line in lines), lines
        finally:
            u.close()

def no_forced_research_in_repeated_history():
    """Do not force a stored research move on repetition-sensitive boards."""
    key = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b -"
    with tempfile.TemporaryDirectory() as td:
        knowledge = Path(td) / "repeat.tsv"
        knowledge.write_text(
            "# position-knowledge-v1-active\n"
            + key + "\t7g7f\ttest\t1\t60000\t3\t1000\tcp\t1\t"
            "\tresearch_decision\trepeated-test\t7g7f 3c3d 2g2f\t-\n",
            encoding="utf-8",
        )
        u = Usi()
        try:
            u.send("setoption name PositionKnowledgeFile value " + str(knowledge))
            u.send("isready")
            _, ready = u.until("readyok")
            assert any("loaded 1 positions" in line for line in ready), ready
            cycle = ["7i6h", "3a4b", "6h7i", "4b3a"]
            u.send("position sfen " + key + " 1 moves " + " ".join(cycle))
            u.send("go depth 1")
            _, logs = u.until("bestmove ")
            assert not any(x.startswith("info string research_decision ") for x in logs), logs
            assert any("knowledge_disabled_repetition 1" in x for x in logs), logs
        finally:
            u.close()

run_once(True)
run_once(False)
embedded_default_fallback()
direct_research_line()
adopted_real_snapshot()
all_adopted_research_positions()
newer_direct_study_overrides_previous_continuation()
no_forced_research_in_repeated_history()
print("PASS position knowledge: 153 direct decisions by matching SFEN, PV continuation, repetition safety and fallback")
