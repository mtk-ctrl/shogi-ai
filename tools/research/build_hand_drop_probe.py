#!/usr/bin/env python3
"""Instrument a build-only header copy; never modify production search.

Run scripts/build.py first. The probe shares that build's sources and flags.
Root return values may be alpha-beta bounds; a single forced root move gives
an exact score at a completed depth. Trace callbacks add a small runtime cost.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-manifest', default='build/shogi-ai.build.json')
    args = parser.parse_args()
    source = (ROOT / 'engine/strategy/iterative_search.h').read_text()
    changes = [
        ('    const Stats& last_stats() const { return stats_; }',
         '    const Stats& last_stats() const { return stats_; }\n'
         '    void set_root_diagnostic(std::function<void(int,const std::string&,bool,int)> f) { root_diagnostic_ = std::move(f); }'),
        ('                for (const auto& move : moves) {\n                    check_stop();\n                    Node child;',
         '                for (const auto& move : moves) {\n                    check_stop();\n'
         '                    if (root_diagnostic_) root_diagnostic_(depth,move,false,0);\n                    Node child;'),
        ('                    const int value = child.value;',
         '                    const int value = child.value;\n'
         '                    if (root_diagnostic_) root_diagnostic_(depth,move,true,value);'),
        ('    std::mt19937 rng_;',
         '    std::function<void(int,const std::string&,bool,int)> root_diagnostic_;\n    std::mt19937 rng_;'),
    ]
    for old, new in changes:
        if source.count(old) != 1:
            raise RuntimeError('Search header changed; update diagnostic instrumentation explicitly')
        source = source.replace(old, new)
    include = ROOT / 'build/hand-drop-include'
    header = include / 'strategy/iterative_search.h'
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(source)
    command = json.loads((ROOT / args.build_manifest).read_text())['command']
    command.insert(1, '-I' + str(include))
    command = [str(ROOT / 'benchmarks/hand_drop_probe.cpp') if s.endswith('/engine/main.cpp') else s for s in command]
    output=ROOT / 'build/hand-drop-probe'
    temporary=output.with_suffix('.tmp')
    command[-1] = str(temporary)
    subprocess.run(command, check=True, cwd=ROOT)
    if temporary.stat().st_size == 0:
        raise RuntimeError('Compiler produced an empty probe')
    temporary.replace(output)
    print(output)


if __name__ == '__main__':
    main()
