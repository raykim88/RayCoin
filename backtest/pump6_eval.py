"""Live pump-6 rules on any 5-minute data dir (RC_DATA=...): 2h rise > 10% -> short; conviction score
(backtest/conviction.py) >= 2 -> 3x, else 2x above +20%, else 1x; score 0 -> skip.

Usage: RC_DATA=backtest/data_bithumb python3 backtest/pump6_eval.py
"""
import sys; sys.path.insert(0, '.')
import numpy as np
import universe as U, run as R, engine as E


def plan_trades(cost_mult=1.0, conv=True):
    out = []
    for e, x, r, n, rk in U.trades(60, th=0.10, lev=1):
        m = R.M[n]; i = e - 1
        rise2 = m.c[i] / m.c[i - 24] - 1
        r30 = m.c[i] / m.c[i - 6] - 1
        r24 = m.c[i] / m.c[max(0, i - 288)] - 1
        vs = m.v[i - 24:i].sum() / max(m.v[i - 288:i - 24].mean() * 24, 1e-9)
        sc = int(0.06 <= r30 < 0.10) + int(4 <= vs < 8) + int(r24 < 0.20) + int(0.20 <= rise2 < 0.30)
        if conv and sc == 0:
            continue
        lev = 3 if conv and sc >= 2 else (2 if rise2 > 0.20 else 1)
        g = r + 2 * E.COST
        out.append((e, x, lev * g - lev * 2 * E.COST * cost_mult, n, rk))
    return out


if __name__ == "__main__":
    print(f"{E.DATA.name}: {len(R.names)} markets, {R.stamps[0]} .. {R.stamps[-1]}")
    U.line("pump-4 (+20% 2x)", U.trades(60, th=0.20, lev=2))
    U.line("pump-5 tiers", plan_trades(conv=False))
    U.line("pump-6", plan_trades())
    U.line("pump-6 2x cost", plan_trades(2.0))
    U.line("pump-6 3x cost", plan_trades(3.0))
