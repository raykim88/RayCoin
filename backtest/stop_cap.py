import sys, os
sys.path.insert(0, "/home/user/RayCoin/backtest")
os.chdir("/home/user/RayCoin/backtest")
import numpy as np
import sl_width as S
E, R = S.E, S.R
def trades(sl, cap):
    out = []
    for k, n in enumerate(S.names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > 0.20) & (r30 < 0.10) & (S.rank[k] < 60)
        busy, stops = -1, []
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288: continue
            if cap and sum(1 for s in stops if i - s < 288) >= cap: continue
            t = S.trade(m, i, sl)
            if t:
                out.append((i + 1, t[0], t[1], n)); busy = t[0]
                if t[1] <= -sl - 2 * E.COST + 1e-9: stops.append(t[0])
    return out
H = R.T // 2
print(os.environ["RC_DATA"].split("/")[-1])
for cap in (0, 1, 2, 3):
    tr = trades(0.07, cap)
    f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T)
    wk = [E.portfolio(tr, 4, w, min(R.T, w + S.WEEK))["ret"] for w in range(0, R.T - S.WEEK // 2, S.WEEK)]
    print(f"cap {cap} n {f['n']} win {f['win']} full {f['ret']} 1st {a['ret']} 2nd {b['ret']} mdd {f['mdd']} {wk}")
