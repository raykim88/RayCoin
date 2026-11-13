"""Mirror of the live pump fade: LONG a coin after a sharp crash, with the live exits (or wider).
Also tests running it alongside the live pump short on the same 4 slots.

Usage: python3 backtest/crash_long.py
"""
import numpy as np

import engine as E
import pump_grid as G
import run as R
import xs_tp as X


def crash(th, look, sl=0.07, tp=0.12, trail=(0.06, 0.03), hold=144, lev=2):
    out = []
    for n in R.names:
        if n == "KRW-BTC":
            continue
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[look:] = m.c[look:] / m.c[:-look] - 1
        for i in np.nonzero(r < -th)[0]:
            if i <= busy or i < 288:
                continue
            t = X.trade(m, i, 1, sl, tp, trail, hold)
            if t:
                out.append((i + 1, t[0], lev * (t[1] + 2 * E.COST) - lev * 2 * E.COST, n)); busy = t[0]
    return out


def line(name, tr):
    f, wk = G.judge(tr)
    print(f"{name:<40} {f['ret']:+8.2f} mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} "
          f"avg {f['avg']:+6.2f} wk {wk}", flush=True)


if __name__ == "__main__":
    print(f"{len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    live = G.trades(lev=2)
    line("LIVE pump short 2x", live)
    best = None
    for th, look in ((.08, 12), (.10, 12), (.10, 24), (.15, 24), (.20, 24), (.15, 72), (.25, 72)):
        for sl, tp, trail in ((.07, .12, (.06, .03)), (.05, .08, (.04, .02)), (.10, .15, None)):
            tr = crash(th, look, sl, tp, trail)
            nm = f"crash {th:.0%}/{look*5//60}h sl{sl:.0%} tp{tp:.0%}"
            line(nm, tr)
            f, _ = G.judge(tr)
            if best is None or f["ret"] > best[0]:
                best = (f["ret"], nm, tr)
    line("LIVE + best crash: " + best[1], live + best[2])
