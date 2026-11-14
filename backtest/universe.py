"""How wide should the pump-fade scan be? Rank coins by trailing 24h traded value at every bar (as the
live bot does) and only allow entries inside the top N. Trades from coins ranked beyond 60 can be
charged double cost to account for thinner books.

Usage: python3 backtest/universe.py
"""
import numpy as np

import engine as E
import pump_grid as G
import run as R
import xs_tp as X

names = [n for n in R.names if n != "KRW-BTC"]
V = np.vstack([np.convolve(R.M[n].v, np.ones(288), "full")[:R.T] for n in names])   # trailing 24h value
RANK = np.argsort(np.argsort(-V, axis=0), axis=0)                                    # 0 = most traded


def trades(N, lev=2, thin_cost=1.0, th=0.20, look=24, sl=0.07, tp=0.12, trail=(0.06, 0.03), hold=144):
    out = []
    for k, n in enumerate(names):
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        for i in np.nonzero(r > th)[0]:
            if i <= busy or i < 288 or RANK[k, i] >= N:
                continue
            t = X.trade(m, i, -1, sl, tp, trail, hold)
            if t:
                c = E.COST * (thin_cost if RANK[k, i] >= 60 else 1.0)
                g = t[1] + 2 * E.COST - 2 * c
                out.append((i + 1, t[0], lev * (g + 2 * c) - lev * 2 * c, n, int(RANK[k, i]))); busy = t[0]
    return out


def line(name, tr):
    f, wk = G.judge([t[:4] for t in tr])
    print(f"{name:<28} {f['ret']:+8.2f} mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} avg {f['avg']:+6.2f} wk {wk}",
          flush=True)


if __name__ == "__main__":
    print(f"{len(names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    for N in (40, 60, 80, 100, 150, 400):
        line(f"top {N}", trades(N))
    for N in (100, 400):
        line(f"top {N} thin cost x2", trades(N, thin_cost=2.0))
        line(f"top {N} thin cost x3", trades(N, thin_cost=3.0))
    tr = trades(400)
    for lo, hi in ((0, 60), (60, 100), (100, 150), (150, 400)):
        rs = np.array([t[2] for t in tr if lo <= t[4] < hi])
        if len(rs):
            print(f"rank {lo:3d}-{hi:3d}: n {len(rs):4d} avg {rs.mean()*100:+6.2f}% win {(rs > 0).mean()*100:5.1f}%"
                  f" median {np.median(rs)*100:+6.2f}%")
