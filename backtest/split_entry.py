"""Split entry for the pump fade: short half at the signal, add the other half only if the spike runs
a further `add` (a better average price), each half with its own stop. Targets the 'stopped within
40 minutes' weakness. Same 4 slots; a trade's return is the average of its two halves.

Usage: python3 backtest/split_entry.py
"""
import numpy as np

import engine as E
import pump_grid as G
import run as R
import xs_tp as X


def split(add=0.05, wait=24, sl=0.07, sl2=None, tp=0.12, trail=(0.06, 0.03), hold=144, lev=2, th=0.20):
    sl2 = sl2 or sl
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        for i in np.nonzero(r > th)[0]:
            if i <= busy or i < 288:
                continue
            a = X.trade(m, i, -1, sl, tp, trail, hold)
            if not a:
                continue
            px = m.o[i + 1]; b, ex = None, a[0]
            for j in range(i + 1, min(len(m.c) - 2, i + 1 + wait)):
                if m.h[j] >= px * (1 + add):
                    b = X.trade(m, j, -1, sl2, tp, trail, hold); break
            rb = b[1] if b else 0.0
            if b:
                ex = max(ex, b[0])
            g = lambda x: lev * (x + 2 * E.COST) - lev * 2 * E.COST
            out.append((i + 1, ex, (g(a[1]) + (g(rb) if b else 0)) / 2, n)); busy = ex
    return out


def line(name, tr):
    f, wk = G.judge(tr)
    print(f"{name:<34} {f['ret']:+8.2f} mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} wk {wk}", flush=True)


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    line("LIVE (all-in at signal) 2x", G.trades(lev=2))
    for add in (0.03, 0.05, 0.08):
        for wait in (12, 24, 48):
            for sl, sl2 in ((0.07, 0.07), (0.10, 0.07), (0.12, 0.08)):
                line(f"split add{add:.0%} {wait*5}m sl{sl:.0%}/{sl2:.0%}", split(add, wait, sl, sl2))
    for lev in (3, 4):
        line(f"split add5% 120m sl10/7 lev{lev}", split(0.05, 24, 0.10, 0.07, lev=lev))
    line("LIVE 3x", G.trades(lev=3))
