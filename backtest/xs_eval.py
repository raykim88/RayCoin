"""Evaluate the live strategy (12h short-only reversal, SL 5%, TP 8%) and improvement candidates on the
refreshed data, split into the in-sample window the strategy was chosen on and the new data since.

Usage: python3 backtest/xs_eval.py
"""
from collections import defaultdict

import numpy as np

import engine as E
import run as R
import xs_tp as X

OOS = next(i for i, t in enumerate(R.stamps) if t >= "2026-11-06T22:00:00")   # data the choice never saw
WEEK = 2016
BTC = R.M["KRW-BTC"].c


def book(k=3, L=288, Rb=144, sl=0.05, tp=0.08, btc_max=None, skip_top=0):
    C = np.vstack([R.M[n].c for n in R.names])
    out = []
    for i in range(L, R.T - 1, Rb):
        if btc_max is not None and BTC[i] / BTC[i - 288] - 1 > btc_max:
            continue                                   # market rallying: no new shorts this window
        ret = C[:, i] / C[:, i - L] - 1
        order = np.argsort(ret)
        picks = order[len(order) - k - skip_top:len(order) - skip_top]
        for j in picks:
            n = R.names[j]
            r = X.trade(R.M[n], i, -1, sl, tp, None, Rb - 1)
            if r:
                out.append((i + 1, r[0], r[1], n))
    return out


def report(name, K=6, **kw):
    tr = book(**kw)
    full = E.portfolio(tr, K, 0, R.T)
    ins = E.portfolio(tr, K, 0, OOS)
    oos = E.portfolio(tr, K, OOS, R.T)
    wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
    by = defaultdict(float)
    for t in tr:
        by[t[3]] += t[2]
    top3 = set(sorted(by, key=lambda n: -by[n])[:3])
    wo = E.portfolio([t for t in tr if t[3] not in top3], K, 0, R.T)["ret"]
    E.COST = 0.002
    dc = E.portfolio(book(**kw), K, 0, R.T)["ret"]
    E.COST = 0.001
    print(f"{name:<30} full {full['ret']:+7.2f} mdd {full['mdd']:5.1f} n {full['n']:3d} win {full['win']:5.1f} | "
          f"in {ins['ret']:+6.2f} new {oos['ret']:+6.2f} | weeks {wk} | w/o top3 {wo:+.2f} 2x {dc:+.2f}")


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}, new data from {R.stamps[OOS]} "
          f"({(R.T - OOS) / 12:.0f}h)")
    report("LIVE: k3 /6 L24h sl5 tp8")
    report("no tp (before 11-07 16:45)", tp=None)
    report("size /3 (all cash used)", K=3)
    report("k4 /6", k=4)
    report("k6 /6 (all cash, 6 shorts)", k=6)
    report("L 12h", L=144)
    report("L 48h", L=576)
    report("tp 6", tp=0.06)
    report("tp 10", tp=0.10)
    report("sl 7", sl=0.07)
    report("sl 3", sl=0.03)
    report("skip if BTC 24h > +2%", btc_max=0.02)
    report("skip if BTC 24h > 0%", btc_max=0.0)
    report("skip the top-1 gainer", skip_top=1)
    report("rebalance 24h", Rb=288)
    report("rebalance 6h", Rb=72)
