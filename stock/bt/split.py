"""Option B: half the capital trend-holds TQQQ while QQQ closes above its 200-day average (next-open fills),
half runs the conviction-sized RSI(2) swing (review2.py). Daily combined curve.

Usage: python3 stock/bt/split.py
"""
import numpy as np
import swing as S, review2 as V

t, o, h, l, c = S.daily("TQQQ"); _, _, _, _, q = S.daily("QQQ"); m = S.sma(q, 200)
T = len(c)
# trend sleeve: signal on close i, act at open i+1
pos = np.zeros(T, bool)
for i in range(200, T - 1):
    pos[i + 1] = q[i] > m[i]
trend = np.ones(T)
for i in range(201, T):
    if pos[i] and pos[i - 1]:
        trend[i] = trend[i - 1] * c[i] / c[i - 1]
    elif pos[i] and not pos[i - 1]:
        trend[i] = trend[i - 1] * (1 - 0.0015) * c[i] / o[i]
    elif not pos[i] and pos[i - 1]:
        trend[i] = trend[i - 1] * o[i] / c[i - 1] * (1 - 0.0015)
    else:
        trend[i] = trend[i - 1]
# swing sleeve: step curve at trade exits (marked at cost while open)
tr = V.trades(["TQQQ", "UPRO"], 30)
w = lambda f: {0: 0, 1: 0.5}.get(int(f["drop5"] < -0.05) + int(0.05 <= f["dist"] < 0.20) + int(f["gap"] <= 0), 1.0)
eq, cash, open_, swing = 1.0, 1.0, [], np.ones(T)
ev = sorted(tr, key=lambda z: z[0]); k = 0
for i in range(T):
    for p in [p for p in open_ if p[0] <= t[i]]:
        cash += p[1] * (1 + p[2]); eq += p[1] * p[2]; open_.remove(p)
    while k < len(ev) and ev[k][0] <= t[i]:
        ent, ex, r, s, f = ev[k]; k += 1
        if len(open_) < 2 and w(f) > 0:
            mg = min(cash, eq * w(f))
            if mg > 1e-6:
                cash -= mg; open_.append((ex, mg, r))
    swing[i] = eq
a = slice(200, T)
for name, curve in (("trend only", trend[a]), ("swing only", swing[a] / swing[200]), ("B: 50/50", 0.5 * trend[a] + 0.5 * swing[a] / swing[200])):
    dd = 1 - curve / np.maximum.accumulate(curve)
    yrs = (t[-1] - t[200]) / 86400 / 365
    h2 = len(curve) // 2
    print(f"{name:<12} {100*(curve[-1]-1):+7.0f}%  연 {100*(curve[-1]**(1/yrs)-1):+5.1f}%  mdd {100*dd.max():4.0f}%  | 앞 절반 {100*(curve[h2]-1):+5.0f}% 뒤 절반 {100*(curve[-1]/curve[h2]-1):+5.0f}%")
print("trend now:", "IN" if q[-1] > m[-1] else "OUT", f"QQQ {q[-1]:.2f} vs 200d {m[-1]:.2f} ({100*(q[-1]/m[-1]-1):+.1f}%)")
