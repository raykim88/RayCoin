"""Which pump-fade entries deserve more leverage? Bucket 1x trades (2h rise > 10%) by features known at
entry, then test conviction-scaled leverage.  Usage: python3 backtest/conviction.py"""
import sys; sys.path.insert(0, '.')
import numpy as np
import universe as U, run as R, engine as E

tr = U.trades(60, th=0.10, lev=1)                       # (entry, exit, net 1x ret, name, rank)
btc = R.M["KRW-BTC"].c
rows = []
for e, x, r, n, rk in tr:
    m = R.M[n]; i = e - 1
    rise2 = m.c[i] / m.c[i - 24] - 1
    rise30 = m.c[i] / m.c[i - 6] - 1                    # last 30 min: still accelerating?
    rise24 = m.c[i] / m.c[max(0, i - 288)] - 1
    vs = m.v[i - 24:i].sum() / max(m.v[i - 288:i - 24].mean() * 24, 1e-9)   # 2h value vs prior 22h pace
    wick = (m.h[i - 24:i + 1].max() - m.c[i]) / m.c[i]  # already off the 2h high?
    b = btc[i] / btc[i - 24] - 1
    rows.append(dict(r=r, rise2=rise2, rise30=rise30, rise24=rise24, vs=vs, wick=wick, btc=b, rank=rk, e=e, x=x, n=n))
r = np.array([d["r"] for d in rows])
print(f"{len(r)} trades, avg {100*r.mean():+.2f}% win {100*(r>0).mean():.0f}%")
for f, edges in (("rise2", (0.10, 0.15, 0.20, 0.30, 0.5, 9)), ("rise30", (-1, 0, 0.03, 0.06, 0.1, 9)),
                 ("rise24", (-1, 0.2, 0.4, 0.8, 99)), ("vs", (0, 2, 4, 8, 999)), ("wick", (0, 0.01, 0.03, 0.06, 9)),
                 ("btc", (-1, -0.01, 0, 0.01, 1)), ("rank", (0, 10, 20, 40, 60))):
    v = np.array([d[f] for d in rows])
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        s = (v >= a) & (v < b)
        if s.sum() >= 15:
            h1 = s & (np.array([d["e"] for d in rows]) < R.SPLIT)
            out.append(f"[{a:g},{b:g}) n{s.sum():3d} {100*r[s].mean():+5.2f}% w{100*(r[s]>0).mean():.0f} (1st2/3 {100*r[h1].mean():+5.2f} / last1/3 {100*r[s & ~h1].mean():+5.2f})")
    print(f"{f:>6}: " + " | ".join(out))

H = np.array([d["e"] < R.SPLIT for d in rows])
def score(d):
    return int(0.06 <= d["rise30"] < 0.10) + int(4 <= d["vs"] < 8) + int(d["rise24"] < 0.20) + int(0.20 <= d["rise2"] < 0.30)
S = np.array([score(d) for d in rows])
for k in range(5):
    s = S == k
    if s.sum(): print(f"score {k}: n{s.sum():3d} avg {100*r[s].mean():+5.2f}% win {100*(r[s]>0).mean():.0f}% | 1st2/3 {100*r[s&H].mean():+5.2f} n{(s&H).sum()} / last1/3 {100*r[s&~H].mean():+5.2f} n{(s&~H).sum()}")
hi = np.array([d["rise2"] > 0.20 for d in rows])
def lev_plan(f):
    return [(d["e"], d["x"], f(d, sc) * (d["r"] + 2 * E.COST) - f(d, sc) * 2 * E.COST, d["n"], d["rank"]) for d, sc in zip(rows, S)]
U.line("tiered (live pump-5)", lev_plan(lambda d, sc: 2 if d["rise2"] > 0.20 else 1))
for top in (2, 3):
    for need in (2, 3):
        U.line(f"+score>={need} -> {top}x", lev_plan(lambda d, sc: top if sc >= need else (2 if d["rise2"] > 0.20 else 1)))
U.line("score>=2 3x, 2x cost", [(a, b, c - 2 * E.COST * l, n, k) for (a, b, c, n, k), l in
       zip(lev_plan(lambda d, sc: 3 if sc >= 2 else (2 if d["rise2"] > 0.20 else 1)),
           [3 if sc >= 2 else (2 if d["rise2"] > 0.20 else 1) for d, sc in zip(rows, S)])])
U.line("tiered, 2x cost", [(a, b, c - 2 * E.COST * l, n, k) for (a, b, c, n, k), l in
       zip(lev_plan(lambda d, sc: 2 if d["rise2"] > 0.20 else 1), [2 if d["rise2"] > 0.20 else 1 for d in rows])])
plan = lambda d, sc: 3 if sc >= 2 else (2 if d["rise2"] > 0.20 else 1)
U.line("3x plan, skip score0 <20%", [t for t, d, sc in zip(lev_plan(plan), rows, S) if not (sc == 0 and d["rise2"] <= 0.20)])
U.line("3x plan, skip all score0", [t for t, d, sc in zip(lev_plan(plan), rows, S) if sc > 0])
fin = [(t, plan(d, sc)) for t, d, sc in zip(lev_plan(plan), rows, S) if sc > 0]
U.line("FINAL 2x cost", [(a, b, c - 2 * E.COST * l, n, k) for (a, b, c, n, k), l in fin])
U.line("FINAL 3x cost", [(a, b, c - 4 * E.COST * l, n, k) for (a, b, c, n, k), l in fin])
