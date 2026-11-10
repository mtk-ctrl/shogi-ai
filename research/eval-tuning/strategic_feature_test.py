"""Do candidate *strategic* features add information beyond the current evaluation?

Same method as king_feature_test.py (logit P(black wins) = total/S + sum_j beta_j * D_j,
game-grouped 5-fold held-out log-loss), but D_j = feature_j(Black) - feature_j(White) from
feature_probe2, plus one side-to-move column (+1 Black / -1 White, not differenced).
Reports single-feature gains, a joint gain, forward selection, and a repeat-the-split noise floor.
Usage: strategic_feature_test.py <dataset.tsv> <feature_probe2 binary> [bootstrap_n]
"""
import sys, subprocess, numpy as np
from king_feature_test import fit, fit_scale, cv, sigmoid, nll

def load(dataset, probe):
    names = subprocess.run([probe, '--names'], capture_output=True, text=True, check=True).stdout.strip().split('\t')
    rows = [l.rstrip('\n').split('\t') for l in open(dataset, encoding='utf-8')]
    out = subprocess.run([probe], input='\n'.join(r[3] for r in rows) + '\n', capture_output=True, text=True, check=True).stdout
    F = np.array([[float(x) for x in l.split('\t')] for l in out.strip().split('\n')])
    gid = np.array([r[0] for r in rows]); y = np.array([float(r[2]) for r in rows])
    return names, gid, y, F

if __name__ == '__main__':
    data, probe = sys.argv[1], sys.argv[2]; nb = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    names, gid, y, F = load(data, probe); NF = len(names)
    m, total, stm = F[:, 0], F[:, 1], F[:, 2]
    D = np.column_stack([F[:, 3:3 + NF] - F[:, 3 + NF:3 + 2 * NF], stm]); names = names + ['side_to_move']
    print(f'samples {len(y)} games {len(set(gid))}  black score {y.mean():.3f}')
    for lo in (0, 34, 50, 67):
        keep = m >= lo
        if keep.sum() < 300: continue
        Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
        b0, a0 = cv(total[keep], Z, y[keep], gid[keep])
        print(f'maturity>={lo}: samples {keep.sum()} games {len(set(gid[keep]))}  base {b0:.4f} | +all {a0:.4f} (gain {b0 - a0:+.4f} = {100*(b0-a0)/b0:.2f}%)')
        gains = [cv(total[keep], Z[:, [j]], y[keep], gid[keep])[0] - cv(total[keep], Z[:, [j]], y[keep], gid[keep])[1] for j in range(len(names))]
        print('   single: ' + ', '.join(f'{names[j]} {100*gains[j]/b0:+.2f}%' for j in np.argsort(gains)[::-1][:8]))
    for lo in (34, 50):
        keep = m >= lo; Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
        chosen = []; best = cv(total[keep], Z[:, :0], y[keep], gid[keep])[0]; b00 = best
        for _ in range(6):
            cand = [(cv(total[keep], Z[:, chosen + [j]], y[keep], gid[keep])[1], j) for j in range(len(names)) if j not in chosen]
            v, j = min(cand)
            if v > best - 0.0005: break
            best = v; chosen.append(j); print(f'  forward (maturity>={lo}) +{names[j]} -> {v:.4f} ({100*(b00-v)/b00:.2f}% total gain)')
    keep = m >= 34; Dk = D[keep]; sd = Dk.std(0); sd[sd == 0] = 1; Z = Dk / sd
    S0 = fit_scale(total[keep], y[keep]); S, b = fit(total[keep], Z, y[keep], 0.02, S0)
    print('joint fit (maturity>=34) S', round(S))
    if nb:
        g = gid[keep]; games = np.array(sorted(set(g))); idx = {x: np.where(g == x)[0] for x in games}; rng = np.random.default_rng(5); bs = []
        for _ in range(nb):
            ii = np.concatenate([idx[x] for x in rng.choice(games, len(games))]); bs.append(fit(total[keep][ii], Z[ii], y[keep][ii], 0.02, S0)[1])
        lo_, hi_ = np.percentile(bs, [5, 95], axis=0)
        for j in range(len(names)): print(f'  {names[j]:28s} beta {b[j]:+.3f} 90%CI {lo_[j]:+.3f}..{hi_[j]:+.3f} {"*" if lo_[j]>0 or hi_[j]<0 else ""}')
