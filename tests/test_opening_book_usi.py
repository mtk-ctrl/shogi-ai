#!/usr/bin/env python3
import argparse
import queue
import subprocess
import threading
import time


def wait_until(lines, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        seen.append(line)
        if predicate(line):
            return seen
    raise RuntimeError(f"timeout; seen={seen[-20:]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine")
    parser.add_argument("book")
    args = parser.parse_args()
    proc = subprocess.Popen([args.engine], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x.rstrip("\n")) for x in proc.stdout], daemon=True).start()
    send = lambda s: (proc.stdin.write(s + "\n"), proc.stdin.flush())
    try:
        send("usi")
        wait_until(lines, lambda x: x == "usiok")
        send("setoption name ExperienceCache value false")
        send("setoption name OpeningBook value true")
        send(f"setoption name OpeningBookFile value {args.book}")
        send("isready")
        ready = wait_until(lines, lambda x: x == "readyok")
        assert any("opening_book loaded" in x for x in ready), ready

        send("position startpos")
        send("go movetime 50")
        played = wait_until(lines, lambda x: x.startswith("bestmove "))
        assert any("opening_book hit" in x for x in played), played

        send("setoption name OpeningBook value false")
        send("isready")
        wait_until(lines, lambda x: x == "readyok")
        send("position startpos")
        send("go movetime 50")
        searched = wait_until(lines, lambda x: x.startswith("bestmove "))
        assert not any("opening_book hit" in x for x in searched), searched
        assert any(x.startswith("info depth ") or "mate_assist" in x for x in searched), searched
        print("opening book USI test passed")
    finally:
        if proc.poll() is None:
            try:
                send("quit")
                proc.wait(timeout=3)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
