"""More aggressive variants of the live pump fade, plus a long-momentum filler for idle time.

Usage: python3 backtest/aggr.py
"""
import numpy as np

import engine as E
import run as R
import xs_tp as X

THIRD = int(R.T * 2 / 3)
TRAIL = (0.06, 0.03)


def pump(th=0.20, look=24, sl=0.07, tp=0.12, hold=144, trail=TRAIL):
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        for i in np.nonzero(r > th)[0]:
            if i <= busy or i < 288:
                continue
            t = X.trade(m, i, -1, sl, tp, trail, hold)
            if t:
                out.append((i + 1, t[0], t[1], n)); busy = t[0]
    return out


def mom_long(th=0.05, look=12, sl=0.03, tp=0.06, hold=48, trail=(0.03, 0.015), cap=0.12):
    """Long a coin whose `look`-bar rise is between th and cap (early breakout, not a blown-off spike)."""
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        for i in np.nonzero((r > th) & (r < cap))[0]:
            if i <= busy or i < 288:
                continue
            t = X.trade(m, i, 1, sl, tp, trail, hold)
            if t:
                out.append((i + 1, t[0], t[1], n)); busy = t[0]
    return out


def show(name, tr, K=4):
    f = E.portfolio(tr, K, 0, R.T); a = E.portfolio(tr, K, 0, THIRD); b = E.portfolio(tr, K, THIRD, R.T)
    print(f"{name:<36} full {f['ret']:+7.2f} mdd {f['mdd']:5.1f} n {f['n']:3d} win {f['win']:5.1f} | "
          f"2/3 {a['ret']:+6.2f} last1/3 {b['ret']:+6.2f}", flush=True)


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    show("LIVE pump 20%/2h", pump())
    for th, look in ((0.15, 24), (0.12, 24), (0.10, 24), (0.15, 12), (0.12, 12), (0.10, 12), (0.15, 48)):
        show(f"pump {th:.0%}/{look * 5 / 60:g}h", pump(th, look))
    show("pump 20/2h OR 12/1h", pump() + pump(0.12, 12))
    for th, look, cap in ((0.05, 12, 0.12), (0.08, 24, 0.15), (0.03, 6, 0.10), (0.10, 48, 0.20)):
        for sl, tp in ((0.03, 0.06), (0.05, 0.10)):
            show(f"long {th:.0%}/{look * 5 / 60:g}h cap{cap:.0%} sl{sl:.0%} tp{tp:.0%}",
                 mom_long(th, look, sl, tp, cap=cap))
    show("LIVE + long 5%/1h", pump() + mom_long())
