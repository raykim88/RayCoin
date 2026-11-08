"""Can the live short-only reversal climb faster? Compare more exposure, faster rebalancing and an
event-driven "pump fade" (short a coin right after a sharp multi-hour spike) against the live rules.

Usage: python3 backtest/xs_boost.py
"""
from collections import defaultdict

import numpy as np

import engine as E
import run as R
import xs_eval as V
import xs_tp as X

WEEK = 2016
THIRD = int(R.T * 2 / 3)


def pump(th=0.15, look=48, sl=0.07, tp=0.10, hold=144, btc_max=0.02):
    """Short any coin whose `look`-bar return exceeds th, one position per coin at a time."""
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]
        busy = -1
        r = np.zeros(len(m.c))
        r[look:] = m.c[look:] / m.c[:-look] - 1
        for i in np.nonzero(r > th)[0]:
            if i <= busy or i < 288:
                continue
            if btc_max is not None and V.BTC[i] / V.BTC[i - 288] - 1 > btc_max:
                continue
            t = X.trade(m, i, -1, sl, tp, None, hold)
            if t:
                out.append((i + 1, t[0], t[1], n))
                busy = t[0]
    return out


def show(name, build, K=6):
    tr = build()
    full = E.portfolio(tr, K, 0, R.T)
    a = E.portfolio(tr, K, 0, THIRD)
    b = E.portfolio(tr, K, THIRD, R.T)
    wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
    by = defaultdict(float)
    for t in tr:
        by[t[3]] += t[2]
    top3 = set(sorted(by, key=lambda n: -by[n])[:3])
    wo = E.portfolio([t for t in tr if t[3] not in top3], K, 0, R.T)["ret"]
    E.COST = 0.002
    dc = E.portfolio(build(), K, 0, R.T)["ret"]
    E.COST = 0.001
    print(f"{name:<34} full {full['ret']:+7.2f} mdd {full['mdd']:5.1f} n {full['n']:3d} win {full['win']:5.1f} | "
          f"first2/3 {a['ret']:+6.2f} last1/3 {b['ret']:+6.2f} | weeks {wk} | w/o top3 {wo:+.2f} 2x {dc:+.2f}")


if __name__ == "__main__":
    live = dict(btc_max=0.02, skip_top=1)
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    show("LIVE k3 skip1 btc2 /6", lambda: V.book(**live))
    show("LIVE but /4", lambda: V.book(**live), K=4)
    show("LIVE but /3 (2x exposure)", lambda: V.book(**live), K=3)
    show("k4 skip1 btc2 /4 (all cash in)", lambda: V.book(k=4, **live), K=4)
    show("rebalance 8h", lambda: V.book(Rb=96, **live))
    show("rebalance 6h", lambda: V.book(Rb=72, **live))
    show("L12h rebalance 6h", lambda: V.book(L=144, Rb=72, **live))
    for th in (0.10, 0.15, 0.20):
        for look in (24, 48):
            show(f"pump {th:.0%} in {look * 5 // 60}h sl7 tp10", lambda: pump(th, look), K=6)
    show("pump 15%/4h sl5 tp8", lambda: pump(0.15, 48, 0.05, 0.08))
    show("pump 15%/4h sl10 tp15", lambda: pump(0.15, 48, 0.10, 0.15))
    show("pump 15%/4h hold 24h", lambda: pump(0.15, 48, hold=288))
    show("LIVE + pump15/4h /6", lambda: V.book(**live) + pump(0.15, 48))
    show("LIVE + pump15/4h /4", lambda: V.book(**live) + pump(0.15, 48), K=4)
