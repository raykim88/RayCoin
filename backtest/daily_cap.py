"""Per-coin entry cap for the live pump-fade short: allow at most CAP entries per coin in any 24h window.
Same entry/exit rules as sl_width.py (7% stop, pessimistic intrabar order, gap fills at open).
Idea from 11/20-21 shadow trades: KERNEL x5, DEBIT x3, LM x3 (all three LM shorts stopped).
Judged on full sample, each half and each week, cap 0 = no cap (current rule).

Usage: RC_DATA=/abs/path/backtest/data_bithumb CAPS=0,1,2,3 python3 backtest/daily_cap.py
"""
import os
import numpy as np
import engine as E
import run as R
from sl_width import trade, names, rank, WEEK

CAPS = [int(x) for x in os.environ.get("CAPS", "0,1,2,3").split(",")]


def trades(cap, sl=0.07):
    out = []
    for k, n in enumerate(names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > 0.20) & (r30 < 0.10) & (rank[k] < 60)
        busy, entries = -1, []
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288:
                continue
            if cap and sum(1 for e in entries if i - e < 288) >= cap:
                continue
            t = trade(m, i, sl)
            if t:
                out.append((i + 1, t[0], t[1], n)); busy = t[0]; entries.append(i)
    return out


if __name__ == "__main__":
    print(f"{len(names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    H = R.T // 2
    print("cap    n   win%  full%   1st%   2nd%   mdd%  weeks")
    for cap in CAPS:
        tr = trades(cap)
        f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T)
        wk = [E.portfolio(tr, 4, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T - WEEK // 2, WEEK)]
        print(f"{cap:3d} {f['n']:4d} {f['win']:5} {f['ret']:6} {a['ret']:6} {b['ret']:6} {f['mdd']:6}  {wk}")
