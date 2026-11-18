import sys, os
sys.path.insert(0, "/home/user/RayCoin/backtest"); os.chdir("/home/user/RayCoin/backtest")
import numpy as np
import sl_width as S
E, R = S.E, S.R
def trades(r2min, r30max, sl=0.07):
    out = []
    for k, n in enumerate(S.names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > r2min) & (r30 < r30max) & (S.rank[k] < 60)
        busy = -1
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288: continue
            t = S.trade(m, i, sl)
            if t: out.append((i + 1, t[0], t[1], n)); busy = t[0]
    return out
H = R.T // 2; Q = R.T // 4
print(os.environ["RC_DATA"].split("/")[-1])
for r2 in (0.20, 0.25, 0.30, 0.40):
    for r30 in (0.10, 0.05, 0.0):
        tr = trades(r2, r30)
        f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T); q = E.portfolio(tr, 4, 3*Q, R.T)
        print(f"r2>{r2:.2f} r30<{r30:.2f} n {f['n']:3} win {f['win']} full {f['ret']:7} 1st {a['ret']:7} 2nd {b['ret']:7} lastQ {q['ret']:6} mdd {f['mdd']}")
