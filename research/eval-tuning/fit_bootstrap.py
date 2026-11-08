"""Better-conditioned refit with game-level bootstrap intervals for each anchor weight."""
import sys, numpy as np
from scipy.optimize import minimize
sys.path.insert(0, 'research/eval-tuning')
from fit_weights import *

def fit_scaled(F, y, lam, r0=None):
    # parameters: r (27 multiplicative factors on the adopted anchors) and log S
    S0 = fit_scale(model_eval(THETA0, F), y)
    def f(z):
        r = z[:27]; s = np.exp(z[27])
        reg = lam * ((r - 1.0) ** 2).mean()
        return nll(sigmoid(model_eval(THETA0 * r, F) / s), y) + reg
    z0 = np.concatenate([np.ones(27) if r0 is None else r0, [np.log(S0)]])
    bounds = [(0.0, 4.0)] * 27 + [(np.log(300), np.log(20000))]
    res = minimize(f, z0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 500, 'ftol': 1e-13, 'gtol': 1e-9})
    return res.x[:27], float(np.exp(res.x[27])), res.fun

if __name__ == '__main__':
    data, lam, nb = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
    gid, ply, y, F = load(data, 'build/feature_probe')
    keep = ply >= 16; gid, ply, y, F = gid[keep], ply[keep], y[keep], F[keep]
    r, S, _ = fit_scaled(F, y, lam)
    games = np.array(sorted(set(gid))); rng = np.random.default_rng(7)
    idx = {g: np.where(gid == g)[0] for g in games}
    boots = []
    for b in range(nb):
        pick = rng.choice(games, len(games))
        ii = np.concatenate([idx[g] for g in pick])
        rb, _, _ = fit_scaled(F[ii], y[ii], lam, r)
        boots.append(rb)
    boots = np.array(boots); lo, hi = np.percentile(boots, [5, 95], axis=0)
    print('S', round(S), 'samples', len(y))
    for name, off in (('opening', 0), ('middle', 9), ('end', 18)):
        for i, ax in enumerate(AXES):
            k = off + i
            flag = '*' if (lo[k] > 1.0 or hi[k] < 1.0) else ' '
            print(f'{name:8s}{ax:15s} adopted {THETA0[k]:6.0f} fit x{r[k]:.2f} -> {THETA0[k]*r[k]:6.0f}  90%CI x{lo[k]:.2f}-x{hi[k]:.2f} {flag}')
