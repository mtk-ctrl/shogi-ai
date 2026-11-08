"""Texel-style fit of the profile-47 anchor weights to own self-play results.

eval_black = (board_mat + hand_mat) + sum_i sign_i * d_i * w_i(maturity) / 100
P(black wins) = sigmoid(eval_black / S). Parameters: 27 anchor weights (9 axes x opening/
middle/end) and the scale S. Regularised toward the adopted values; scored by grouped
cross-validation over games. Only the engine's own games are used (no external teacher).
"""
import argparse, subprocess, sys
import numpy as np
from scipy.optimize import minimize

AXES = ['safety', 'pressure', 'activity', 'danger', 'influence', 'potential', 'coordination', 'hand_potential', 'threat']
OPEN = [480, 469, 600, 168, 180, 300, 500, 60, 20]  # v2.0.26 adopted
MID  = [480, 1282, 500, 221, 240, 210, 340, 60, 49]
END  = [480, 2817, 101, 150, 65, 160, 220, 60, 40]
SIGN = np.array([1, 1, 1, -1, 1, 1, 1, 1, 1], float)
THETA0 = np.array(OPEN + MID + END, float)

def smooth(x):
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

def basis(m):
    m = np.clip(m, 0, 100).astype(float)
    t = smooth(m / 50.0); u = smooth((m - 50.0) / 50.0)
    lo = m <= 50
    bA = np.where(lo, 1 - t, 0.0); bB = np.where(lo, t, 1 - u); bC = np.where(lo, 0.0, u)
    return bA, bB, bC

def load(dataset, probe):
    rows = [l.rstrip('\n').split('\t') for l in open(dataset, encoding='utf-8')]
    sfens = '\n'.join(r[3] for r in rows) + '\n'
    out = subprocess.run([probe], input=sfens, capture_output=True, text=True, check=True).stdout
    feats = np.array([[float(x) for x in l.split('\t')] for l in out.strip().split('\n')])
    gid = np.array([r[0] for r in rows]); y = np.array([float(r[2]) for r in rows])
    ply = np.array([int(r[1]) for r in rows])
    return gid, ply, y, feats

def model_eval(theta, feats):
    m = feats[:, 0]; mat = feats[:, 1] + feats[:, 2]; d = feats[:, 3:12]
    bA, bB, bC = basis(m)
    w = (bA[:, None] * theta[0:9] + bB[:, None] * theta[9:18] + bC[:, None] * theta[18:27])
    return mat + (d * SIGN * w).sum(1) / 100.0

def nll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())

def sigmoid(z): return 1 / (1 + np.exp(-z))

def fit_scale(e, y):
    r = minimize(lambda s: nll(sigmoid(e / np.exp(s[0])), y), [np.log(400.0)], method='Nelder-Mead')
    return float(np.exp(r.x[0]))

def fit(theta0, feats, y, lam, log_s0):
    def f(z):
        theta = z[:27]; s = np.exp(z[27])
        reg = lam * (((theta - THETA0) / np.maximum(THETA0, 20.0)) ** 2).mean()
        return nll(sigmoid(model_eval(theta, feats) / s), y) + reg
    z0 = np.concatenate([theta0, [log_s0]])
    bounds = [(0, 3000)] * 27 + [(np.log(50), np.log(3000))]
    r = minimize(f, z0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
    return r.x[:27], float(np.exp(r.x[27]))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', required=True); ap.add_argument('--probe', default='build/feature_probe')
    ap.add_argument('--folds', type=int, default=5); ap.add_argument('--lams', default='0.003,0.01,0.03,0.1')
    ap.add_argument('--output')
    a = ap.parse_args()
    gid, ply, y, F = load(a.dataset, a.probe)
    print('samples', len(y), 'games', len(set(gid)), 'mean result', y.mean().round(3))
    # sanity: our reconstruction vs the engine's own total (rounding/clamp differences only)
    mine = model_eval(THETA0, F); print('recon vs engine total: max|diff|', np.abs(mine - F[:, 12]).max().round(1), ' median', np.median(np.abs(mine - F[:, 12])).round(2))
    games = sorted(set(gid)); rng = np.random.default_rng(1); rng.shuffle(games)
    fold_of = {g: i % a.folds for i, g in enumerate(games)}; fold = np.array([fold_of[g] for g in gid])
    res = {}
    for lam in [float(x) for x in a.lams.split(',')]:
        base, mat, fitd = [], [], []
        for k in range(a.folds):
            tr, te = fold != k, fold == k
            s_cur = fit_scale(model_eval(THETA0, F[tr]), y[tr])
            base.append(nll(sigmoid(model_eval(THETA0, F[te]) / s_cur), y[te]))
            s_mat = fit_scale(F[tr, 1] + F[tr, 2], y[tr])
            mat.append(nll(sigmoid((F[te, 1] + F[te, 2]) / s_mat), y[te]))
            th, s = fit(THETA0, F[tr], y[tr], lam, np.log(s_cur))
            fitd.append(nll(sigmoid(model_eval(th, F[te]) / s), y[te]))
        res[lam] = (np.mean(base), np.mean(mat), np.mean(fitd))
        print(f'lam={lam}: held-out logloss  material-only {np.mean(mat):.4f} | adopted weights {np.mean(base):.4f} | refit {np.mean(fitd):.4f}')
    best = min(res, key=lambda l: res[l][2])
    s_cur = fit_scale(model_eval(THETA0, F), y)
    th, s = fit(THETA0, F, y, best, np.log(s_cur))
    print('best lam', best, 'scale S (adopted)', round(s_cur, 1), 'S (refit)', round(s, 1))
    for name, off in (('opening', 0), ('middle', 9), ('end', 18)):
        print(name, {ax: (int(o), int(round(t))) for ax, o, t in zip(AXES, THETA0[off:off + 9], th[off:off + 9])})
    if a.output:
        np.savetxt(a.output, th.reshape(3, 9), fmt='%.1f')
