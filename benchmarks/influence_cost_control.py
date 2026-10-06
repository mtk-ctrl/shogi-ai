"""Preregister/run score-identical control for the extra influence computation."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--lanes', type=int, default=4)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    options = {'EvalInfluence': True, 'EvalInfluenceLegacyMix': 100}
    plan = {
        'engine_sha256': hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
        'options_a': options, 'options_b': {'EvalInfluence': False},
        'hypothesis': 'same score function, extra influence computation under equal wall time',
        'seed': 2026101040, 'games': 100, 'go_command': 'go movetime 50',
        'book': True, 'experience': False, 'mate_assist': True, 'max_plies': 200,
        'selection': 'none; this control is never a candidate',
    }
    pp = out / 'plan.json'
    if pp.exists() and json.loads(pp.read_text()) != plan:
        raise SystemExit('Plan changed; use a new experiment directory')
    pp.write_text(json.dumps(plan, indent=2) + '\n')
    if args.plan_only:
        return
    subprocess.run([
        sys.executable, 'benchmarks/influence_validation.py', '--engine', args.engine,
        '--baseline', args.baseline, '--options-on', json.dumps(options),
        '--expect-equivalent', '--output', str(out / 'equivalence.json')], check=True)
    subprocess.run([
        sys.executable, 'benchmarks/influence_match.py', '--engine', args.engine,
        '--options-a', json.dumps(options), '--options-b', json.dumps(plan['options_b']),
        '--pairs', '50', '--lanes', str(args.lanes), '--seed', str(plan['seed']),
        '--output-dir', str(out / 'match')], check=True)


if __name__ == '__main__':
    main()
