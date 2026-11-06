"""Cross-sectional reversal with a 12-hour rebalance (twice a day): pick the ranking lookback.

Usage: python3 backtest/xs12h.py
"""
from collections import defaultdict

import engine as E
import run as R

WEEK = 2016
print("R=144 bars (12h), 1x, sign=-1 (reversal)")
for L in (36, 72, 144, 288):
    for k in (3, 4):
        for sides in (("long", "short"), ("long",)):
            for sl in (None, 0.05, 0.08):
                tr = R.xs(1, R=144, L=L, k=k, sign=-1, sides=sides, sl=sl)
                K = k * len(sides)
                full = E.portfolio(tr, K, 0, R.T)
                wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
                by = defaultdict(float)
                for t in tr:
                    by[t[3]] += t[2]
                top3 = set(sorted(by, key=lambda n: -by[n])[:3])
                wo = E.portfolio([t for t in tr if t[3] not in top3], K, 0, R.T)["ret"]
                E.COST = 0.002
                dc = E.portfolio(R.xs(1, R=144, L=L, k=k, sign=-1, sides=sides, sl=sl), K, 0, R.T)["ret"]
                E.COST = 0.001
                print(f"L={L:<4}k={k} {'+'.join(s[0] for s in sides):<4} sl={sl}  full {full['ret']:+7.2f} "
                      f"mdd {full['mdd']:5.1f} n {full['n']:3d} win {full['win']:5.1f}  weeks {wk}  "
                      f"w/o top3 {wo:+.2f}  2x cost {dc:+.2f}")
