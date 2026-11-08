#!/usr/bin/env python3
"""Reread experiment (research, own engine only): are lost-game turning points caused by too little
search time, or by the evaluation? For each lost game, find the first own move whose evaluation was
>= +300 (own view) but dropped by >= 600 at the next own move; re-search that position (before the
move) with more time and compare the move and score. Opponent PVs are never used."""
import json, subprocess, re, statistics, argparse

def load_games(paths):
    for p in paths:
        d = json.load(open(p))
        for g in (d.get('details') or d.get('games') or []):
            yield p, g

def loser_records(g):
    """Works for both self-play (engine A/B with telemetry on both) and ladder (actor self/opponent)."""
    recs = []
    for r in g['move_records']:
        sr = r.get('search') or r.get('self_search')
        if sr and 'score_cp_stm' in sr:
            recs.append(dict(r, search=sr, who=r.get('actor') or r.get('engine')))
    labels = {r['who'] for r in recs}
    w = g.get('winner')
    if w is None: return None, []
    if labels == {'self'}:
        return ('self', recs) if w != 'self' else (None, [])
    lose = [l for l in labels if l != w]
    if len(lose) != 1: return None, []
    return lose[0], [r for r in recs if r['who'] == lose[0]]

def find_event(recs, lead, drop):
    for a, b in zip(recs, recs[1:]):
        ca, cb = a['search']['score_cp_stm'], b['search']['score_cp_stm']
        if ca >= lead and cb <= ca - drop:
            return a, b
    return None

class Usi:
    def __init__(self, path, options):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.send('usi'); self.wait('usiok')
        for k, v in options.items(): self.send(f'setoption name {k} value {v}')
        self.send('isready'); self.wait('readyok'); self.send('usinewgame')
    def send(self, s): self.p.stdin.write(s + '\n'); self.p.stdin.flush()
    def wait(self, token):
        while True:
            l = self.p.stdout.readline()
            if not l: raise RuntimeError('engine ended')
            if l.strip().startswith(token): return l
    def search(self, moves, ms):
        self.send('position startpos' + (' moves ' + ' '.join(moves) if moves else ''))
        self.send(f'go movetime {ms}')
        score = None; depth = 0
        while True:
            l = self.p.stdout.readline()
            if l.startswith('info') and ' score ' in l:
                m = re.search(r'score (cp|mate) (-?\d+)', l); d = re.search(r' depth (\d+)', l)
                if m:
                    v = int(m.group(2))
                    score = v if m.group(1) == 'cp' else (30000 - abs(v)) * (1 if v > 0 else -1)
                if d: depth = int(d.group(1))
            if l.startswith('bestmove'): return l.split()[1], score, depth
    def close(self):
        try: self.send('quit'); self.p.wait(timeout=3)
        except Exception: self.p.kill()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', required=True); ap.add_argument('--files', nargs='+', required=True)
    ap.add_argument('--times', default='200,1000,3000'); ap.add_argument('--max-events', type=int, default=60)
    ap.add_argument('--options', default='{}'); ap.add_argument('--lead', type=int, default=300); ap.add_argument('--drop', type=int, default=600)
    a = ap.parse_args()
    times = [int(x) for x in a.times.split(',')]
    events = []; lost = 0
    for p, g in load_games(a.files):
        label, recs = loser_records(g)
        if not recs: continue
        lost += 1
        ev = find_event(recs, a.lead, a.drop)
        if ev:
            r0, r1 = ev; ply = r0['ply']
            events.append(dict(moves=g['moves'][:ply - 1], played=r0['move'], orig=r0['search']['score_cp_stm'], after=r1['search']['score_cp_stm'],
                               ply=ply, plies=g['plies'], reason=g.get('reason'), depth=r0['search'].get('depth'), mat=r0['search'].get('phase_maturity')))
    print(f'lost games {lost}, with lead-then-drop event {len(events)}')
    if not lost:
        import collections
        c = collections.Counter(); first = None
        for _, g in load_games(a.files):
            c[(g.get('winner'), g.get('reason'))] += 1; first = first or g
        print('winner/reason counts', dict(c)); print('game keys', list(first)); print('record', first['move_records'][:2] if first else None)
    events = events[:a.max_events]
    eng = Usi(a.engine, json.loads(a.options)); rows = []
    for e in events:
        res = {t: eng.search(e['moves'], t) for t in times}
        rows.append((e, res))
        print(f"ply {e['ply']:3d}/{e['plies']:3d} mat {e['mat']} d{e['depth']} orig {e['orig']:+6d} -> {e['after']:+6d} played {e['played']} | " +
              ' | '.join(f"{t}ms {res[t][0]} {res[t][1]:+d} d{res[t][2]}" for t in times))
    eng.close()
    n = len(rows)
    if not n: return
    print(f'\n== summary over {n} turning points ==')
    mate_loss = [e for e, _ in rows if e['reason'] == 'checkmate' and e['plies'] - e['ply'] <= 30]
    print(f'loss by checkmate within 30 plies of the turning point: {len(mate_loss)}/{n}')
    for t in times:
        changed = sum(1 for e, r in rows if r[t][0] != e['played'])
        vs = [r[t][1] - e['orig'] for e, r in rows if r[t][1] is not None]
        found = sum(1 for e, r in rows if r[t][1] is not None and r[t][1] <= e['orig'] - 400)
        depth = statistics.mean(r[t][2] for e, r in rows)
        near = sum(1 for e, r in rows if r[t][1] is not None and r[t][1] <= e['after'] + 300)
        print(f'{t}ms: different move {changed}/{n} ({100*changed/n:.0f}%), mean depth {depth:.1f}, score vs original median {statistics.median(vs):+.0f}, '
              f'sees the trouble (score <= original-400) {found}/{n}, within 300cp of what really followed {near}/{n}')

if __name__ == '__main__':
    main()
