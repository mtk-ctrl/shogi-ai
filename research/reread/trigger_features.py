#!/usr/bin/env python3
"""Which features of a finished move predict a coming turning point? (own engine telemetry only)
Unit: every own move i in a game (score_i own view > -500). Label: the next own move's score is at
least 600 lower than score_i (a collapse). Reports AUC per feature, lift by quantile, and the share
of collapses captured when only the top q% of moves are flagged. Not a teacher; offline analysis."""
import json, sys, numpy as np

KEYS = ['depth', 'nodes', 'elapsed_ms', 'phase_maturity', 'phase_development', 'phase_battle', 'phase_invasion', 'phase_king_threat']

def rows(paths):
    X, y, meta = [], [], []
    for p in paths:
        d = json.load(open(p))
        for g in (d.get('details') or []):
            recs = []
            for r in g['move_records']:
                sr = r.get('search') or r.get('self_search')
                if sr and 'score_cp_stm' in sr:
                    recs.append((r, sr, r.get('actor') or r.get('engine')))
            who = {w for _, _, w in recs}
            for w in who:
                own = [(r, s) for r, s, a in recs if a == w]
                prev = None
                for (r, s), (r2, s2) in zip(own, own[1:]):
                    c = s['score_cp_stm']
                    if c <= -500: prev = c; continue
                    qn = s.get('qnodes', 0) / max(1, s.get('nodes', 1))
                    f = [s.get(k, 0) or 0 for k in KEYS] + [c, abs(c), (c - prev) if prev is not None else 0, qn, r['legal_moves_before'],
                         int(r['in_check_before']), int(r['is_capture']), int(r['is_drop']), int(r['is_promotion']), int(r['gave_check']),
                         len(s.get('pv') or []), r['ply'], int(s.get('elapsed_ms', 0) > 250)]
                    X.append(f); y.append(int(s2['score_cp_stm'] <= c - 600)); prev = c
    return np.array(X, float), np.array(y)

NAMES = KEYS + ['score', 'abs_score', 'score_change_vs_prev_own', 'qnode_share', 'legal_moves', 'in_check', 'capture', 'drop', 'promotion', 'gave_check', 'pv_len', 'ply', 'long_think_used']

def auc(x, y):
    order = np.argsort(x, kind='mergesort'); r = np.empty(len(x)); r[order] = np.arange(1, len(x) + 1)
    # average ranks for ties
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=r); r = (sums / cnt)[inv]
    n1 = y.sum(); n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)

if __name__ == '__main__':
    X, y = rows(sys.argv[1:])
    print(f'moves {len(y)}, collapses {int(y.sum())} ({100 * y.mean():.1f}%)')
    res = sorted(((abs(auc(X[:, j], y) - 0.5), auc(X[:, j], y), NAMES[j]) for j in range(X.shape[1])), reverse=True)
    for _, a, n in res: print(f'  AUC {a:.3f}  {n}')
    # logistic regression with standardisation
    from scipy.optimize import minimize
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1; Z = (X - mu) / sd
    def f(w):
        z = Z @ w[1:] + w[0]; p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        return -(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9)).mean() + 0.01 * (w[1:] ** 2).sum()
    w = minimize(f, np.zeros(Z.shape[1] + 1), method='L-BFGS-B').x
    s = Z @ w[1:]; print(f'combined logistic AUC {auc(s, y):.3f}')
    for j in np.argsort(-np.abs(w[1:]))[:8]: print(f'   coef {w[1 + j]:+.2f} {NAMES[j]}')
    for q in (10, 20, 30):
        thr = np.percentile(s, 100 - q); print(f'flag top {q}% by combined score: captures {100 * y[s >= thr].sum() / y.sum():.0f}% of collapses')
    # current-trigger proxy: |score change vs prev| >= 150 or in check
    cur = (np.abs(X[:, NAMES.index('score_change_vs_prev_own')]) >= 150) | (X[:, NAMES.index('in_check')] == 1)
    print(f'current-style trigger (score change >=150 vs previous turn or in check): flags {100 * cur.mean():.0f}% of moves, captures {100 * y[cur].sum() / y.sum():.0f}% of collapses')
