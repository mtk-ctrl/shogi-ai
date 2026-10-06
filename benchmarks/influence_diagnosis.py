"""Compare candidate static terms on the same recorded positions."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
from benchmarks.influence_validation import evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True)
    parser.add_argument('--study-dir', required=True)
    args = parser.parse_args()
    folder = Path(args.study_dir)
    plan = json.loads((folder / 'plan.json').read_text())
    positions = json.loads((folder / 'compatibility.json').read_text())['rows']
    candidates = [{'id': 'anchor', 'options': plan['anchor']}] + plan['candidates']
    rows = []
    for candidate in candidates:
        engine = Engine(args.engine, candidate['id'], {
            'ExperienceCache': False, 'OpeningBook': False,
            **candidate['options']})
        try:
            values = [evaluation(engine, p['moves']) for p in positions]
            rows.append({
                'id': candidate['id'], 'options': candidate['options'],
                'mean_abs_safety': sum(abs(v['safety']) for v in values) / len(values),
                'mean_abs_pressure': sum(abs(v['pressure']) for v in values) / len(values),
                'pressure_zero': sum(v['pressure'] == 0 for v in values),
                'clamped': sum(v['clamp'] != 0 for v in values),
                'changed_evaluations_vs_off': sum(v != p['eval_off'] for v, p in zip(values, positions)),
            })
        finally:
            engine.close()
    (folder / 'static-diagnosis.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps([{k: v for k, v in row.items() if k != 'options'} for row in rows], indent=2))


if __name__ == '__main__':
    main()
