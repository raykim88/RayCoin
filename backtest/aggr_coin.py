"""Aggressive coin sleeve candidates (user, 11-25: "a separate $50 that trades often"): pump-fade shorts with lower
entry thresholds and faster exits, pessimistic stops (stop before tp inside a bar, gaps fill at the open).
Usage: [RC_DATA=backtest/data_bithumb] python3 backtest/aggr_coin.py"""
import numpy as np
import engine as E
import run as R
import sl_width as W

def trade(m, i, sl, tp, trail, hold):
    e = i + 1
    if e >= len(m.c): return None
    px = m.o[e]; end = min(len(m.c) - 1, e + hold); peak = 0.0
    for j in range(e, end + 1):
        if (m.o[j] - px) / px >= sl and j > e: return j, -(m.o[j] - px) / px - 2 * E.COST
        if (m.h[j] - px) / px >= sl: return j, -sl - 2 * E.COST
        fav = (px - m.l[j]) / px
        if fav >= tp: return j, tp - 2 * E.COST
        peak = max(peak, fav); cur = -(m.c[j] / px - 1)
        if peak >= trail[0] and cur <= peak - trail[1]: return j, cur - 2 * E.COST
    return end, -(m.c[end] / px - 1) - 2 * E.COST

def trades(th, look, sl, tp, trail, hold, accel=0.10, uni=60):
    out = []
    for k, n in enumerate(W.names):
        m = R.M[n]
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        r30 = np.zeros(len(m.c)); r30[6:] = m.c[6:] / m.c[:-6] - 1
        ok = (r > th) & (r30 < accel) & (W.rank[k] < uni)
        busy = -1
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288: continue
            t = trade(m, i, sl, tp, trail, hold)
            if t: out.append((i + 1, t[0], t[1], n)); busy = t[0]
    return out

if __name__ == "__main__":
    H = R.T // 2; days = R.T / 288
    print(f"{len(W.names)} markets, {R.stamps[0]} .. {R.stamps[-1]} ({days:.0f}d)")
    print("name                                   n  /day  win%   full%   1st%   2nd%  mdd%")
    C = [("live: 2h>20% tp12 trail6/3 12h", .20, 24, .07, .12, (.06, .03), 144, .10)]
    for th in (.10, .12, .15):
        for look in (12, 24):
            C.append((f"{look*5}m>{int(th*100)}% tp12 trail6/3 12h", th, look, .07, .12, (.06, .03), 144, .10))
            C.append((f"{look*5}m>{int(th*100)}% tp6 trail3/1.5 3h", th, look, .05, .06, (.03, .015), 36, .10))
            C.append((f"{look*5}m>{int(th*100)}% tp8 trail4/2 6h", th, look, .06, .08, (.04, .02), 72, .10))
    for name, th, look, sl, tp, tr, hold, acc in C:
        t = trades(th, look, sl, tp, tr, hold, acc)
        f = E.portfolio(t, 4, 0, R.T); a = E.portfolio(t, 4, 0, H); b = E.portfolio(t, 4, H, R.T)
        print(f"{name:36s} {f['n']:4d} {f['n']/days:5.1f} {f['win']:5} {f['ret']:7} {a['ret']:6} {b['ret']:6} {f['mdd']:5}")
