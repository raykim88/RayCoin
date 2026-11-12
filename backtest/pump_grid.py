"""Robust grid over the pump-fade short: entry confirmation, spike cap, cooldown, exits, leverage.
Judged per week (4 weeks), not just on the full sample, so one lucky week cannot carry a variant.

Usage: python3 backtest/pump_grid.py
"""
import itertools

import numpy as np

import engine as E
import run as R
import xs_tp as X

WEEK = 2016


def trades(th=0.20, look=24, conf=0.0, cap=9.9, sl=0.07, tp=0.12, trail=(0.06, 0.03), hold=144,
           lev=1, cool=0):
    """conf: only enter once price is conf below its high of the last 12 bars (the spike has stalled)."""
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        hi = np.maximum.accumulate(np.lib.stride_tricks.sliding_window_view(
            np.r_[np.full(11, m.h[0]), m.h], 12), axis=1)[:, -1]
        ok = (r > th) & (r < cap) & (m.c <= hi * (1 - conf))
        busy, last_stop = -1, -10 ** 9
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288 or i - last_stop < cool:
                continue
            t = X.trade(m, i, -1, sl, tp, trail, hold)
            if t:
                out.append((i + 1, t[0], lev * (t[1] + 2 * E.COST) - lev * 2 * E.COST, n))
                busy = t[0]
                if t[1] <= -sl:
                    last_stop = t[0]
    return out


def judge(tr, K=4):
    f = E.portfolio(tr, K, 0, R.T)
    wk = [E.portfolio(tr, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T - WEEK // 2, WEEK)]
    return f, wk


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}", flush=True)
    rows = []
    grid = dict(th=(0.15, 0.20, 0.25), conf=(0.0, 0.02, 0.04), cap=(9.9, 0.40), sl=(0.07, 0.10),
                tp=(0.12, 0.20), cool=(0, 288))
    keys = list(grid)
    for vals in itertools.product(*grid.values()):
        kw = dict(zip(keys, vals))
        f, wk = judge(trades(**kw))
        rows.append((min(wk), f["ret"], f["mdd"], f["n"], f["win"], wk, kw))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print("worst-week  full   mdd   n  win  weeks  params")
    for r in rows[:25]:
        print(f"{r[0]:+7.2f} {r[1]:+7.2f} {r[2]:5.1f} {r[3]:4d} {r[4]:5.1f} {r[5]} {r[6]}")
    live = [r for r in rows if r[6] == dict(th=0.20, conf=0.0, cap=9.9, sl=0.07, tp=0.12, cool=0)][0]
    print("LIVE", live[:6])
