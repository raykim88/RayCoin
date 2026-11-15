"""Korean individual stocks (60 large caps in data/1d, 10y daily), KR round-trip cost (ab.KR_COST, incl. sell tax).
Caveat: today's large caps -> survivorship bias (results look better than reality).
Usage: python3 stock/bt/kr_stocks.py"""
import numpy as np
import ab, swing as S, review2 as V

SYMS = sorted(p.stem for p in S.D.glob("*.K?.csv") if not p.stem.startswith("^") and p.stem not in
              ("122630.KS", "233740.KS", "069500.KS", "229200.KS", "251340.KS", "114800.KS"))
C = ab.KR_COST
D = {s: S.daily(s) for s in SYMS}
kt, _, _, _, kc = S.daily("^KS11"); km = S.sma(kc, 200)
kidx = {t: i for i, t in enumerate(kt)}
def mkt_up(ts):
    i = kidx.get(ts); return i is not None and i >= 200 and kc[i] > km[i]
print(len(SYMS), "stocks, cost", C)

# 1) RSI(2) pullback per stock (same rules as US)
for lo in (5, 10, 20):
    tr = V.trades(SYMS, lo, cost=C)
    V.line(f"1 RSI2<{lo} pullback, 5 slots 20%", tr, lambda f: 0.2, 5)
    tr2 = [z for z in tr if mkt_up(z[0] - 0) or True]
# market filter: only when KOSPI above 200d (entry date)
for lo in (5, 10):
    tr = [z for z in V.trades(SYMS, lo, cost=C) if any(abs(z[0] - t) < 86400 * 2 and kc[i] > km[i] for t, i in [(t, kidx[t]) for t in kt[-2500:]] if i >= 200)]
    V.line(f"1b RSI2<{lo} + KOSPI>200d, 5 slots", tr, lambda f: 0.2, 5)

# 2) momentum rotation: every 20 sessions hold top-k by 120-session return (KOSPI>200d else cash)
def rotation(look, k, hold=20, rev=False, filt=True):
    T = min(len(D[s][4]) for s in SYMS)
    P = np.vstack([D[s][4][-T:] for s in SYMS]); O = np.vstack([D[s][1][-T:] for s in SYMS]); ts = D[SYMS[0]][0][-T:]
    out = []
    for i in range(max(look, 200), T - hold - 1, hold):
        if filt and not mkt_up(ts[i]):
            continue
        r = P[:, i] / P[:, i - look] - 1
        idx = np.argsort(r)[:k] if rev else np.argsort(-r)[:k]
        for j in idx:
            out.append((ts[i + 1], ts[i + hold], P[j, i + hold] / O[j, i + 1] - 1 - C, SYMS[j], dict(sym=SYMS[j])))
    return out
for look in (60, 120, 250):
    V.line(f"2 momentum top5 look{look} hold20", rotation(look, 5), lambda f: 0.2, 5)
V.line("2 momentum top5 look120 no filter", rotation(120, 5, filt=False), lambda f: 0.2, 5)
# 3) short-term reversal: weekly buy 5 worst of last 5 sessions
V.line("3 reversal worst5 look5 hold5", rotation(5, 5, hold=5, rev=True), lambda f: 0.2, 5)
V.line("3 reversal worst5 look5 hold5 no filter", rotation(5, 5, hold=5, rev=True, filt=False), lambda f: 0.2, 5)
# 4) 52-week high breakout, hold 20 sessions
out = []
for s in SYMS:
    t, o, h, l, c = D[s]
    i = 252
    while i < len(c) - 21:
        if c[i] > c[i - 252:i].max() and mkt_up(t[i]):
            out.append((t[i + 1], t[i + 20], c[i + 20] / o[i + 1] - 1 - C, s, dict(sym=s))); i += 20
        else:
            i += 1
V.line("4 52w-high breakout hold20", out, lambda f: 0.2, 5)
t, o, h, l, c = S.daily("069500.KS"); print(f"KODEX 200 buy&hold over same span {100*(c[-1]/c[200]-1):+.0f}%")

# survivorship check: the same 60 names bought and held equally over the same span (has the same bias)
T = min(len(D[s][4]) for s in SYMS)
P = np.vstack([D[s][4][-T:] for s in SYMS])
ew = (P[:, -1] / P[:, 252] - 1)
print(f"equal-weight buy&hold of the same 60 names from bar 252: mean {100*ew.mean():+.0f}%, median {100*np.median(ew):+.0f}%")
# EW monthly-rebalanced curve for a fair comparison with the 20-day strategies
rb = [P[:, i + 20] / P[:, i] - 1 for i in range(252, T - 21, 20)]
eq = np.cumprod([1 + r.mean() - 0.0 for r in rb]); dd = (1 - eq / np.maximum.accumulate(eq)).max()
print(f"equal-weight, rebalanced every 20 sessions: {100*(eq[-1]-1):+.0f}% mdd {100*dd:.0f}%")
for hold in (10, 40, 60):
    out = []
    for s in SYMS:
        t, o, h, l, c = D[s]; i = 252
        while i < len(c) - hold - 1:
            if c[i] > c[i - 252:i].max() and mkt_up(t[i]):
                out.append((t[i + 1], t[i + hold], c[i + hold] / o[i + 1] - 1 - C, s, dict(sym=s))); i += hold
            else:
                i += 1
    V.line(f"4 52w-high breakout hold{hold}", out, lambda f: 0.2, 5)
