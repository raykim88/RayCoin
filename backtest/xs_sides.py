"""12h cross-sectional reversal: compare long+short, short-only, long-only, and asymmetric long stops.

Usage: python3 backtest/xs_sides.py
"""
from collections import defaultdict

import engine as E
import run as R

WEEK = 2016


def combo(sl_long, sl_short, sides, k=3, L=288):
    tr = []
    if "long" in sides:
        tr += R.xs(1, R=144, L=L, k=k, sign=-1, sides=("long",), sl=sl_long)
    if "short" in sides:
        tr += R.xs(1, R=144, L=L, k=k, sign=-1, sides=("short",), sl=sl_short)
    return tr


def report(name, build):
    tr = build()
    K = 6
    full = E.portfolio(tr, K, 0, R.T)
    wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
    by = defaultdict(float)
    for t in tr:
        by[t[3]] += t[2]
    top3 = set(sorted(by, key=lambda n: -by[n])[:3])
    wo = E.portfolio([t for t in tr if t[3] not in top3], K, 0, R.T)["ret"]
    E.COST = 0.002
    dc = E.portfolio(build(), K, 0, R.T)["ret"]
    E.COST = 0.001
    print(f"{name:<34} full {full['ret']:+7.2f} mdd {full['mdd']:5.1f} n {full['n']:3d} weeks {wk} "
          f"w/o top3 {wo:+.2f} 2x cost {dc:+.2f}")


# K=6 slots for all, so a one-sided book holds half cash (same per-position size as live)
report("L+S  sl 5/5 (live)", lambda: combo(0.05, 0.05, ("long", "short")))
report("short only sl 5", lambda: combo(None, 0.05, ("short",)))
report("long only sl 5", lambda: combo(0.05, None, ("long",)))
report("L+S  long sl 8 / short 5", lambda: combo(0.08, 0.05, ("long", "short")))
report("L+S  long no-sl / short 5", lambda: combo(None, 0.05, ("long", "short")))
report("L+S  long sl 3 / short 5", lambda: combo(0.03, 0.05, ("long", "short")))
