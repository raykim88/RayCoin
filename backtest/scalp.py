"""Idle-time scalps vs the live pump fade: does a small, frequent trade add anything after fees?
Each variant is shown with real costs (0.2% round trip at 1x) and with zero cost.

Usage: python3 backtest/scalp.py
"""
import numpy as np

import engine as E
import pump_grid as G
import run as R
import xs_tp as X


def scalp(kind, th, look, sl, tp, hold, lev=1, free=False):
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        if kind == "dip":      # long after a sharp drop
            ok, side = r < -th, 1
        elif kind == "fade":   # short a smaller spike (below the live 20% trigger)
            ok, side = (r > th) & (r < 0.20), -1
        else:                  # momentum long
            ok, side = (r > th) & (r < 0.20), 1
        for i in np.nonzero(ok)[0]:
            if i <= busy or i < 288:
                continue
            t = X.trade(m, i, side, sl, tp, None, hold)
            if t:
                g = t[1] + (2 * E.COST if free else 0)
                out.append((i + 1, t[0], lev * (g + 2 * E.COST) - lev * 2 * E.COST * (not free), n))
                busy = t[0]
    return out


def line(name, tr):
    f, wk = G.judge(tr)
    print(f"{name:<44} {f['ret']:+8.2f} mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} "
          f"avg {f['avg']:+6.2f} wk {wk}", flush=True)


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    live = G.trades(lev=2)
    line("LIVE pump 2x", live)
    for kind, th, look in (("dip", .05, 12), ("dip", .08, 24), ("dip", .03, 6), ("fade", .08, 12),
                           ("fade", .10, 24), ("fade", .05, 6), ("mom", .03, 6), ("mom", .05, 12)):
        for sl, tp, hold in ((.02, .015, 24), (.03, .03, 48), (.015, .01, 12)):
            nm = f"{kind} {th:.0%}/{look*5}m sl{sl:.1%} tp{tp:.1%} {hold*5}m"
            line(nm + " fee", scalp(kind, th, look, sl, tp, hold))
            line(nm + " 0fee", scalp(kind, th, look, sl, tp, hold, free=True))
