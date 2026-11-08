"""Do candidate king-danger features add information beyond the current evaluation?

logit P(black wins) = total/S + sum_j beta_j * D_j, D_j = feature_j(White king) - feature_j(Black king)
(standardised). Held-out log-loss by game-grouped CV, computed on all quiet samples and on
late-game subsets; single-feature gains and bootstrap intervals for the joint fit.
"""
import sys, subprocess, numpy as np
from scipy.optimize import minimize
NAMES = ['safe_escapes','ring_enemy_attacks','ring_own_defence','weak_ring','enemy_hand_pieces','own_near_king',
         'king_advance','enemy_hand_value','undefended_attacked_ring','enemy_near_king','weak_ring_x_hand','open_lines']
NF = len(NAMES)
def load(dataset, probe):
    rows = [l.rstrip('\n').split('\t') for l in open(dataset, encoding='utf-8')]
    out = subprocess.run([probe], input='\n'.join(r[3] for r in rows) + '\n', capture_output=True, text=True, check=True).stdout
    F = np.array([[float(x) for x in l.split('\t')] for l in out.strip().split('\n')])
    gid = np.array([r[0] for r in rows]); y = np.array([float(r[2]) for r in rows]); ply = np.array([int(r[1]) for r in rows])
    return gid, ply, y, F
def sigmoid(z): return 1 / (1 + np.exp(-np.clip(z, -30, 30)))
def nll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6); return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
def fit(total, D, y, lam, S0):
    k = D.shape[1]
    def f(z):
        s = np.exp(z[0]); b = z[1:]
        return nll(sigmoid(total / s + D @ b), y) + lam * float((b ** 2).sum())
    r = minimize(f, np.concatenate([[np.log(S0)], np.zeros(k)]), method='L-BFGS-B', options={'maxiter': 300})
    return np.exp(r.x[0]), r.x[1:]
def fit_scale(total, y):
    r = minimize(lambda s: nll(sigmoid(total / np.exp(s[0])), y), [np.log(2000.0)], method='Nelder-Mead'); return float(np.exp(r.x[0]))
def cv(total, D, y, gid, folds=5, lam=0.02):
    games = sorted(set(gid)); rng = np.random.default_rng(3); rng.shuffle(games)
    fo = {g: i % folds for i, g in enumerate(games)}; fold = np.array([fo[g] for g in gid])
    base, aug = [], []
    for k in range(folds):
        tr, te = fold != k, fold == k
        S0 = fit_scale(total[tr], y[tr])
        base.append(nll(sigmoid(total[te] / S0), y[te]))
        S, b = fit(total[tr], D[tr], y[tr], lam, S0)
        aug.append(nll(sigmoid(total[te] / S + D[te] @ b), y[te]))
    return float(np.mean(base)), float(np.mean(aug))
if __name__ == '__main__':
    data, probe = sys.argv[1], sys.argv[2]; nb = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    gid, ply, y, F = load(data, probe)
    m = F[:, 0]; total = F[:, 1]
    Fb, Fw = F[:, 2:2 + NF], F[:, 2 + NF:2 + 2 * NF]
    D = Fw - Fb
    for lo in (0, 34, 50, 67):
        keep = m >= lo
        if keep.sum() < 300: continue
        Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
        b0, a0 = cv(total[keep], Z, y[keep], gid[keep])
        print(f'maturity>={lo}: samples {keep.sum()} games {len(set(gid[keep]))}  held-out logloss base {b0:.4f} | +all king features {a0:.4f}  (gain {b0 - a0:+.4f})')
        gains = []
        for j in range(NF):
            b1, a1 = cv(total[keep], Z[:, [j]], y[keep], gid[keep]); gains.append(b1 - a1)
        print('   single-feature gain: ' + ', '.join(f'{NAMES[j]} {gains[j]:+.4f}' for j in np.argsort(gains)[::-1][:6]))
    for lo in (50, 67):
        keep = m >= lo; Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
        chosen = []; best = cv(total[keep], Z[:, :0], y[keep], gid[keep])[0]
        for _ in range(4):
            cand = [(cv(total[keep], Z[:, chosen + [j]], y[keep], gid[keep])[1], j) for j in range(NF) if j not in chosen]
            v, j = min(cand)
            if v > best - 0.0005: break
            best = v; chosen.append(j); print(f'  forward select (maturity>={lo}) +{NAMES[j]} -> held-out logloss {v:.4f}')
    keep = m >= 50; Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
    S0 = fit_scale(total[keep], y[keep]); S, b = fit(total[keep], Z, y[keep], 0.02, S0)
    print('joint fit (maturity>=50) S', round(S), 'beta per 1 sd:', {NAMES[j]: round(float(b[j]), 3) for j in range(NF)})
    if nb:
        g = gid[keep]; games = np.array(sorted(set(g))); idx = {x: np.where(g == x)[0] for x in games}; rng = np.random.default_rng(5); bs = []
        for _ in range(nb):
            ii = np.concatenate([idx[x] for x in rng.choice(games, len(games))])
            bs.append(fit(total[keep][ii], Z[ii], y[keep][ii], 0.02, S0)[1])
        lo_, hi_ = np.percentile(bs, [5, 95], axis=0)
        for j in range(NF): print(f'  {NAMES[j]:26s} beta {b[j]:+.3f}  90%CI {lo_[j]:+.3f}..{hi_[j]:+.3f} {"*" if lo_[j]>0 or hi_[j]<0 else ""}')
