"""After the NCT loss (11-15 10:36, 3x short stopped at -14.3% price instead of -7%): re-test pump variants with
stop fills that can slip past the stop, and with a filter on spikes still accelerating (30-min rise >= 10%).
stop modes: exact (-7%), open (a 5-min bar that opens beyond the stop fills at its open), close (fills at the
close of the bar that touched the stop, if worse).  Usage: RC_DATA=<dir> python3 backtest/stop_gap.py"""
import sys; sys.path.insert(0, '.')
import numpy as np
import universe as U, run as R, engine as E

SL, TP, TRAIL, HOLD = 0.07, 0.12, (0.06, 0.03), 144


def trade(m, i, mode):
    e = i + 1; px = m.o[e]; end = min(len(m.c) - 1, e + HOLD); peak = 0.0
    for j in range(e, end + 1):
        adverse = (m.h[j] - px) / px; favour = (px - m.l[j]) / px
        if adverse >= SL:
            ret = -SL
            if mode in ("open", "close") and j > e:
                ret = min(ret, -(m.o[j] - px) / px)
            if mode == "close":
                ret = min(ret, -(m.c[j] - px) / px)
            return j, ret - 2 * E.COST
        if favour >= TP:
            return j, TP - 2 * E.COST
        peak = max(peak, favour); cur = -(m.c[j] / px - 1)
        if peak >= TRAIL[0] and cur <= peak - TRAIL[1]:
            return j, cur - 2 * E.COST
    return end, -(m.c[end] / px - 1) - 2 * E.COST


def build(mode, lev_f, accel_max=None, min_px=None):
    out = []
    for k, n in enumerate(U.names):
        m = R.M[n]; busy = -1
        r = np.zeros(len(m.c)); r[24:] = m.c[24:] / m.c[:-24] - 1
        for i in np.nonzero(r > 0.20)[0]:
            if i <= busy or i < 288 or U.RANK[k, i] >= 60:
                continue
            r30 = m.c[i] / m.c[i - 6] - 1; r24 = m.c[i] / m.c[i - 288] - 1
            vs = m.v[i - 24:i].sum() / max(m.v[i - 288:i - 24].mean() * 24, 1e-9)
            if accel_max is not None and r30 >= accel_max:
                continue
            if min_px and m.c[i] < min_px:
                continue
            sc = int(0.06 <= r30 < 0.10) + int(4 <= vs < 8) + int(r24 < 0.20) + int(r[i] < 0.30)
            j, g = trade(m, i, mode); lev = lev_f(sc)
            out.append((i + 1, j, lev * (g + 2 * E.COST) - lev * 2 * E.COST, n, int(U.RANK[k, i]))); busy = j
    return out


print(E.DATA.name)
for mode in ("exact", "open", "close"):
    U.line(f"{mode:<5} 2x", build(mode, lambda sc: 2))
    U.line(f"{mode:<5} 2x/3x(score>=2) pump-7", build(mode, lambda sc: 3 if sc >= 2 else 2))
    U.line(f"{mode:<5} pump-7 skip 30m>=10%", build(mode, lambda sc: 3 if sc >= 2 else 2, accel_max=0.10))
    U.line(f"{mode:<5} 2x skip 30m>=10%", build(mode, lambda sc: 2, accel_max=0.10))
