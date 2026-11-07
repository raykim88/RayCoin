"""12h short-only cross-sectional reversal: does a take-profit or a trailing stop help?

Usage: python3 backtest/xs_tp.py
"""
from collections import defaultdict

import numpy as np

import engine as E
import run as R

WEEK = 2016


def trade(m, i, side, sl, tp, trail, hold):
    """Like engine.simulate_trade at 1x, plus a trailing stop: once favour reached trail[0], exit if it
    falls back by trail[1] from its peak."""
    T = len(m.c)
    e = i + 1
    if e >= T:
        return None
    px = m.o[e]
    end = min(T - 1, e + hold)
    peak = 0.0
    for j in range(e, end + 1):
        adverse = (m.h[j] - px) / px if side < 0 else (px - m.l[j]) / px
        favour = (px - m.l[j]) / px if side < 0 else (m.h[j] - px) / px
        if adverse >= sl:
            ret = -sl
            break
        if tp and favour >= tp:
            ret = tp
            break
        peak = max(peak, favour)
        cur = side * (m.c[j] / px - 1)
        if trail and peak >= trail[0] and cur <= peak - trail[1]:
            ret = cur
            break
        if j == end:
            ret = cur
            break
    return j, ret - 2 * E.COST


def book(tp=None, trail=None, k=3, L=288, Rb=144, sl=0.05):
    C = np.vstack([R.M[n].c for n in R.names])
    out = []
    for i in range(L, R.T - 1, Rb):
        ret = C[:, i] / C[:, i - L] - 1
        for j in np.argsort(ret)[-k:]:
            n = R.names[j]
            r = trade(R.M[n], i, -1, sl, tp, trail, Rb - 1)
            if r:
                out.append((i + 1, r[0], r[1], n))
    return out


def report(name, **kw):
    tr = book(**kw)
    K = 6
    full = E.portfolio(tr, K, 0, R.T)
    wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
    by = defaultdict(float)
    for t in tr:
        by[t[3]] += t[2]
    top3 = set(sorted(by, key=lambda n: -by[n])[:3])
    wo = E.portfolio([t for t in tr if t[3] not in top3], K, 0, R.T)["ret"]
    E.COST = 0.002
    dc = E.portfolio(book(**kw), K, 0, R.T)["ret"]
    E.COST = 0.001
    print(f"{name:<26} full {full['ret']:+7.2f} mdd {full['mdd']:5.1f} n {full['n']:3d} weeks {wk} "
          f"w/o top3 {wo:+.2f} 2x cost {dc:+.2f}")


report("short only (live)")
for tp in (0.04, 0.06, 0.08, 0.12):
    report(f"tp {tp:.0%}", tp=tp)
for tr in ((0.04, 0.02), (0.05, 0.03), (0.06, 0.03), (0.08, 0.04)):
    report(f"trail {tr[0]:.0%}/{tr[1]:.0%}", trail=tr)
