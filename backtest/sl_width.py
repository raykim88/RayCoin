"""Stop-width check for the live pump-fade short (review-268): does a wider stop than 7% do better?
Live entry rules: 2h rise > 20%, optional same-coin cooldown after a stop (cool bars), skip if 30-minute rise >= 10%, top-60 by trailing 24h value.
Exits: tp +12%, trail 6/3, 12h hold; stop checked before tp inside a bar (pessimistic) and a gap
through the stop fills at the bar's open. Judged on full sample, each half, and each week.

Usage: [RC_DATA=backtest/data_bithumb] python3 backtest/sl_width.py
"""
import numpy as np
import engine as E
import run as R

WEEK = 2016
import os
COOLS = [int(x) for x in os.environ.get("COOLS", "0,288").split(",")]
SLS = [float(x) for x in os.environ.get("SLS", "0.07,0.10,0.12,0.15,0.20").split(",")]


def trade(m, i, sl, tp=0.12, trail=(0.06, 0.03), hold=144):
    e = i + 1
    if e >= len(m.c):
        return None
    px = m.o[e]; end = min(len(m.c) - 1, e + hold); peak = 0.0
    for j in range(e, end + 1):
        if (m.o[j] - px) / px >= sl and j > e:          # gapped through the stop
            return j, -(m.o[j] - px) / px - 2 * E.COST
        if (m.h[j] - px) / px >= sl:
            return j, -sl - 2 * E.COST
        fav = (px - m.l[j]) / px
        if fav >= tp:
            return j, tp - 2 * E.COST
        peak = max(peak, fav); cur = -(m.c[j] / px - 1)
        if peak >= trail[0] and cur <= peak - trail[1]:
            return j, cur - 2 * E.COST
    return end, -(m.c[end] / px - 1) - 2 * E.COST


names = [n for n in R.names if n != "KRW-BTC"]
V = np.array([np.convolve(R.M[n].v, np.ones(288), "full")[:R.T] for n in names])
rank = (-V).argsort(0).argsort(0)          # rank per bar by trailing 24h value


def trades(sl, lev=1, cool=0):
    out = []
    for k, n in enumerate(names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > 0.20) & (r30 < 0.10) & (rank[k] < 60)
        busy, last_stop = -1, -10 ** 9
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288 or i - last_stop < cool:
                continue
            t = trade(m, i, sl)
            if t:
                out.append((i + 1, t[0], lev * t[1], n)); busy = t[0]
                if t[1] <= -sl - 2 * E.COST + 1e-9:
                    last_stop = t[0]
    return out


if __name__ == "__main__":
    print(f"{len(names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    H = R.T // 2
    print("sl   cool    n   win%  full%   1st%   2nd%   mdd%  weeks")
    for sl, cool in [(s, c) for c in COOLS for s in SLS]:
        tr = trades(sl, cool=cool)
        f = E.portfolio(tr, 4, 0, R.T); a = E.portfolio(tr, 4, 0, H); b = E.portfolio(tr, 4, H, R.T)
        wk = [E.portfolio(tr, 4, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T - WEEK // 2, WEEK)]
        print(f"{sl:.2f} {cool:4d} {f['n']:4d} {f['win']:5} {f['ret']:6} {a['ret']:6} {b['ret']:6} {f['mdd']:6}  {wk}")
