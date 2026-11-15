"""Cross-exchange robustness of pump-fade variants (run per data dir with RC_DATA=...).
Usage: RC_DATA=backtest/data_bithumb python3 backtest/cross_check.py"""
import sys; sys.path.insert(0, '.')
import universe as U, run as R, engine as E

rows = []
for e, x, r, n, rk in U.trades(60, th=0.10, lev=1):
    m = R.M[n]; i = e - 1
    rise2 = m.c[i] / m.c[i - 24] - 1; r30 = m.c[i] / m.c[i - 6] - 1; r24 = m.c[i] / m.c[max(0, i - 288)] - 1
    vs = m.v[i - 24:i].sum() / max(m.v[i - 288:i - 24].mean() * 24, 1e-9)
    sc = int(0.06 <= r30 < 0.10) + int(4 <= vs < 8) + int(r24 < 0.20) + int(0.20 <= rise2 < 0.30)
    rows.append((e, x, r, n, rk, rise2, sc))
def mk(f):
    out = []
    for e, x, r, n, rk, rise2, sc in rows:
        lev = f(rise2, sc)
        if lev:
            out.append((e, x, lev * (r + 2 * E.COST) - lev * 2 * E.COST, n, rk))
    return out
print(E.DATA.name)
U.line("A pump-4: >20% 2x", mk(lambda r2, sc: 2 if r2 > 0.20 else 0))
U.line("B >20% 2x, score>=2 3x", mk(lambda r2, sc: (3 if sc >= 2 else 2) if r2 > 0.20 else 0))
U.line("C >20% 2x, +10-20% 1x", mk(lambda r2, sc: 2 if r2 > 0.20 else 1))
U.line("D C but skip score0", mk(lambda r2, sc: 0 if sc == 0 else (2 if r2 > 0.20 else 1)))
U.line("E >15% 2x", mk(lambda r2, sc: 2 if r2 > 0.15 else 0))
U.line("F pump-6", mk(lambda r2, sc: 0 if sc == 0 else (3 if sc >= 2 else (2 if r2 > 0.20 else 1))))
