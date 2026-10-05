"""Reproducible independent match batches. No change to game/search rules.

Parallel workers are for throughput; use a separate single-worker smoke/timing
run for uncontended latency. Exact binary hashes, seeds and part results remain.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine-a', required=True); p.add_argument('--engine-b', required=True)
    p.add_argument('--games', type=int, default=100); p.add_argument('--workers', type=int, default=1)
    p.add_argument('--seed', type=int, default=20261010)
    p.add_argument('--options-a', default='{}'); p.add_argument('--options-b', default='{}')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    if args.games < 2 or args.games % 2 or args.workers < 1:
        p.error('use positive workers and an even number of games')
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    parts = out.parent / (out.stem + '-parts'); parts.mkdir(exist_ok=True)
    batches = [(offset, min(10, args.games-offset)) for offset in range(0,args.games,10)]
    def run(batch):
        offset, count = batch; dest = parts / f'{offset:03d}.json'
        cmd = [sys.executable, '-u', str(Path(__file__).with_name('arena.py')),
               '--engine-a', args.engine_a, '--engine-b', args.engine_b,
               '--options-a', args.options_a, '--options-b', args.options_b,
               '--games', str(count), '--seed', str(args.seed+2*offset), '--output', str(dest)]
        with dest.with_suffix('.log').open('w') as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        row = json.loads(dest.read_text())
        print(f'completed games {offset+1}-{offset+count}: {row["wins_a"]}/{row["draws"]}/{row["wins_b"]}',flush=True)
        return offset, row
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = sorted(f.result() for f in as_completed([pool.submit(run,b) for b in batches]))
    summary = dict(rows[0][1]); summary['seed'] = args.seed
    summary['parts'] = [str(parts/f'{offset:03d}.json') for offset,_ in rows]
    for key in ['games','wins_a','wins_b','draws','illegal_games']:
        summary[key] = sum(row[key] for _,row in rows)
    summary['details'] = [game for _,row in rows for game in row['details']]
    summary['score_a'] = (summary['wins_a']+summary['draws']/2)/args.games
    summary['average_plies'] = sum(g['plies'] for g in summary['details'])/args.games
    summary['elapsed_seconds'] = round(time.monotonic()-start,3)
    summary['workers'] = args.workers
    summary['timing_note'] += f'; {args.workers} concurrent independent games; throughput run'
    summary['host'] = {'platform':platform.platform(),'cpu_count':os.cpu_count(),
                       'lscpu':subprocess.check_output(['lscpu'],text=True)}
    cpu_max=Path('/sys/fs/cgroup/cpu.max')
    if cpu_max.exists():summary['host']['cpu_max']=cpu_max.read_text().strip()
    for label in ['A','B']:
        timings=[r['timing_ms'][label] for _,r in rows]; n=sum(t['moves'] for t in timings)
        summary['timing_ms'][label]={'moves':n,'mean':sum(t['mean']*t['moves'] for t in timings)/n,'max':max(t['max'] for t in timings)}
        searches=[r['search'][label] for _,r in rows]
        stats={k:sum(s.get(k,0) for s in searches) for k in searches[0] if k.endswith('_total') or k=='samples'}
        if stats.get('tt_probes_total'):stats['tt_hit_rate']=stats['tt_hits_total']/stats['tt_probes_total']
        summary['search'][label]=stats
    out.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(f"A {summary['wins_a']} - {summary['draws']} - {summary['wins_b']} B; illegal={summary['illegal_games']}",flush=True)

if __name__ == '__main__':main()
