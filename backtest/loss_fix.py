"""Loss review 11-16: test fixes for the live pump-8 losses (stop slippage on tiny coins, repeated re-entries into
a coin that keeps pumping, extreme volume surges). Base = pump-8: 2h rise > 20%, 2x, skip if 30-min rise >= 10%.
Each fix on Upbit and Bithumb, with exact stops and with stops filled at the touching bar's close.
Usage: RC_DATA=<dir> python3 backtest/loss_fix.py"""
import sys; sys.path.insert(0, '.')
import numpy as np
import universe as U, run as R, engine as E
import stop_gap as G

def build(mode, min_px=0, cool=0, max_vs=None, max_hits=None):
    out = []
    for k, n in enumerate(U.names):
        m = R.M[n]; busy = -1; last_stop = -10**9; hits = []
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        for i in np.nonzero(r > 0.20)[0]:
            if i <= busy or i < 288 or U.RANK[k, i] >= 60:
                continue
            if m.c[i] / m.c[i - 6] - 1 >= 0.10 or m.c[i] < min_px or i - last_stop < cool:
                continue
            vs = m.v[i - 24:i].sum() / max(m.v[i - 288:i - 24].mean() * 24, 1e-9)
            if max_vs and vs > max_vs:
                continue
            hits = [h for h in hits if i - h < 288]
            if max_hits and len(hits) >= max_hits:
                continue
            j, g = G.trade(m, i, mode)
            out.append((i + 1, j, 2 * (g + 2 * E.COST) - 2 * 2 * E.COST, n, int(U.RANK[k, i]))); busy = j; hits.append(i)
            if g < -0.06:
                last_stop = j
    return out

print(E.DATA.name)
for mode in ("exact", "close"):
    U.line(f"{mode} pump-8 base", build(mode))
    for px in (20, 100):
        U.line(f"{mode} price >= {px} KRW", build(mode, min_px=px))
    for cool in (72, 288):
        U.line(f"{mode} cooldown {cool*5//60}h after stop", build(mode, cool=cool))
    U.line(f"{mode} max 2 entries/coin/24h", build(mode, max_hits=2))
    for vs in (30, 100):
        U.line(f"{mode} skip volume surge > {vs}x", build(mode, max_vs=vs))
    U.line(f"{mode} price>=20 + cooldown 24h", build(mode, min_px=20, cool=288))
