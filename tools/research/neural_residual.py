"""Own native static offsets for a zero-initialized bounded NNUE correction.

Teacher values remain absolute. The deployable student predicts the difference
from the native baseline. Old replacement checkpoints are never reinterpreted.
"""
import copy
import json
from pathlib import Path
import queue
import subprocess
import threading
from tools.research.neural_model import digest
from tools.research.nnue_cycle import atomic_json


class StaticOracle:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(Path(binary).resolve())], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines = queue.Queue()
        def reader():
            for line in self.process.stdout:
                self.lines.put(line.rstrip())
            self.lines.put(None)
        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def evaluate(self, sfen):
        if '\n' in sfen or '\r' in sfen:
            raise ValueError('invalid static request')
        self.process.stdin.write('position sfen '+sfen+'\neval\n')
        self.process.stdin.flush()
        while True:
            line = self.lines.get(timeout=30)
            if line is None:
                raise RuntimeError('static evaluator exited')
            if 'invalid position' in line or ' error ' in line:
                raise ValueError(line)
            if line.startswith('info string evaluation '):
                return int(line.rsplit(' total ', 1)[1])

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('quit\n')
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=3)
        self.thread.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()


def correction_targets(parts, binary, cache_path):
    cache_path = Path(cache_path)
    identity = dict(schema='own-static-offset-v1', binary_sha256=digest(binary))
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else dict(identity=identity, values={})
    if cache['identity'] != identity:
        raise ValueError('static baseline binary changed')
    result = copy.deepcopy(parts)
    oracle = StaticOracle(binary)
    try:
        for rows in result.values():
            for row in rows:
                if 'baseline_cp' in row:
                    raise ValueError('correction offset already applied')
                sfen = row['sfen']
                if sfen not in cache['values']:
                    cache['values'][sfen] = oracle.evaluate(sfen)
                row['baseline_cp'] = cache['values'][sfen]
                row['absolute_target'] = row['target']
                row['target'] -= row['baseline_cp']/1000
                row['policy_weight'] = 0
    finally:
        oracle.close()
        atomic_json(cache_path, cache)
    return result
