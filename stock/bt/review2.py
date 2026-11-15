"""Stock-side version of the coin review (review-203/204), adapted to daily US 3x ETFs:
1) wider entry (RSI(2) threshold, more ETFs), 2) conviction-based sizing, 3) long-hold alternatives.

Usage: python3 stock/bt/review2.py
"""
import numpy as np
import swing as S, ab

CAP = 100.0


def trades(syms, lo=20, maxd=10, cost=ab.US_COST):
    """Live rules: close > 200d avg and RSI(2) < lo -> buy next open; sell next open after close > 5d avg."""
    out = []
    for s in syms:
        t, o, h, l, c = S.daily(s)
        r2, m200, m5 = S.rsi(c), S.sma(c, 200), S.sma(c, 5)
        i = 200
        while i < len(c) - 2:
            if c[i] > m200[i] and r2[i] < lo:
                e = i + 1; px = o[e]; x = e
                while x < len(c) - 1 and x - e < maxd and not c[x] > m5[x]:
                    x += 1
                xp = o[x + 1] if x + 1 < len(c) else c[x]
                f = dict(rsi=r2[i], dist=c[i] / m200[i] - 1, drop5=c[i] / c[i - 5] - 1,
                         downs=next(k for k in range(10) if not c[i - k] < c[i - k - 1]),
                         gap=o[e] / c[i] - 1, sym=s)
                out.append((t[e], t[min(x + 1, len(c) - 1)], xp / px - 1 - cost, s, f)); i = x + 1
            else:
                i += 1
    return out


def sim(tr, weight, K=2):
    """Equity curve with per-trade weight (fraction of equity, capped by free cash). Returns ret, mdd, n, yearly."""
    eq, cash, open_, peak, mdd, n = CAP, CAP, [], CAP, 0.0, 0
    for ent, ex, r, s, f in sorted(tr, key=lambda z: z[0]):
        for p in [p for p in open_ if p[0] <= ent]:
            cash += p[1] * (1 + p[2]); eq += p[1] * p[2]; open_.remove(p)
        peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        if len(open_) >= K:
            continue
        w = weight(f)
        mg = min(cash, eq * w)
        if w <= 0 or mg < 1:
            continue
        cash -= mg; open_.append((ex, mg, r)); n += 1
    for p in open_:
        eq += p[1] * p[2]
    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    return (eq / CAP - 1) * 100, mdd * 100, n


def line(name, tr, weight, K=2):
    ret, mdd, n = sim(tr, weight, K)
    half = sorted(tr, key=lambda z: z[0]); mid = half[len(half) // 2][0]
    a = sim([z for z in tr if z[0] < mid], weight, K); b = sim([z for z in tr if z[0] >= mid], weight, K)
    print(f"{name:<44} {ret:+8.0f}% mdd {mdd:5.1f} n {n:4d} | 1st half {a[0]:+6.0f}% (mdd {a[1]:4.1f}) / 2nd {b[0]:+6.0f}% (mdd {b[1]:4.1f})")


if __name__ == "__main__":
    LIVE = ["TQQQ", "UPRO"]
    print("== 1) wider entry ==")
    for lo in (10, 20, 30, 40):
        line(f"TQQQ/UPRO rsi<{lo}, 1 slot 100%", trades(LIVE, lo), lambda f: 1.0, 1)
    for syms in (LIVE + ["SOXL", "TECL"], LIVE + ["SOXL", "TECL", "TNA"], LIVE + ["SOXL", "TECL", "TNA", "LABU"]):
        for lo in (20, 30):
            line(f"{'/'.join(syms)} rsi<{lo}, 2 slots 50%", trades(syms, lo), lambda f: 0.5, 2)
    print("== 2) conviction (TQQQ/UPRO/SOXL/TECL, rsi<30) ==")
    tr = trades(LIVE + ["SOXL", "TECL"], 30)
    r = np.array([z[2] for z in tr]); mid = sorted(z[0] for z in tr)[len(tr) // 2]
    H = np.array([z[0] < mid for z in tr])
    for key, edges in (("rsi", (0, 5, 10, 20, 30)), ("dist", (0, 0.05, 0.1, 0.2, 1)), ("drop5", (-1, -0.15, -0.1, -0.05, 1)),
                       ("downs", (0, 1, 2, 3, 4, 10)), ("gap", (-1, -0.01, 0, 0.01, 1))):
        v = np.array([z[4][key] for z in tr]); out = []
        for a, b in zip(edges[:-1], edges[1:]):
            s = (v >= a) & (v < b)
            if s.sum() >= 15:
                out.append(f"[{a:g},{b:g}) n{s.sum()} {100*r[s].mean():+.2f}% w{100*(r[s]>0).mean():.0f} ({100*r[s&H].mean():+.2f}/{100*r[s&~H].mean():+.2f})")
        print(f"{key:>5}: " + " | ".join(out))
    print("== 3) long hold (10y) ==")
    for s in ("QQQ", "TQQQ", "UPRO", "SOXL"):
        t, o, h, l, c = S.daily(s); m200 = S.sma(c, 200)
        bh = c[-1] / c[200] - 1
        dd = 1 - c[200:] / np.maximum.accumulate(c[200:])
        inn = c[200:-1] > m200[200:-1]; rr = c[201:] / c[200:-1] - 1
        eq = np.cumprod(1 + rr * inn) * (1 - 0.003) ** np.abs(np.diff(np.r_[0, inn.astype(int)])).cumsum()
        tdd = 1 - eq / np.maximum.accumulate(eq)
        print(f"{s}: buy&hold {100*bh:+.0f}% (mdd {100*dd.max():.0f}%) | hold only above 200d {100*(eq[-1]-1):+.0f}% (mdd {100*tdd.max():.0f}%, in market {100*inn.mean():.0f}%)")

    print("== 4) conviction sizing on TQQQ/UPRO ==")
    def score(f):
        return int(f["drop5"] < -0.05) + int(0.05 <= f["dist"] < 0.20) + int(f["gap"] <= 0)
    for lo in (20, 30):
        tr = trades(LIVE, lo)
        rr = np.array([z[2] for z in tr]); sc = np.array([score(z[4]) for z in tr])
        print(f"rsi<{lo} by score: " + " | ".join(f"{k}: n{(sc==k).sum()} {100*rr[sc==k].mean():+.2f}%" for k in range(4) if (sc == k).sum()))
        line(f"rsi<{lo} flat 100% 1 slot", tr, lambda f: 1.0, 1)
        line(f"rsi<{lo} flat 50% 2 slots", tr, lambda f: 0.5, 2)
        line(f"rsi<{lo} 2 slots: score>=2 100%, 1 50%, 0 skip", tr, lambda f: {0: 0, 1: 0.5}.get(score(f), 1.0), 2)
        line(f"rsi<{lo} 2 slots: score>=2 100%, else 50%", tr, lambda f: 1.0 if score(f) >= 2 else 0.5, 2)
        line(f"rsi<{lo} skip gap>+1% only, 100%", tr, lambda f: 0 if f["gap"] > 0.01 else 1.0, 1)
    print("== 5) trend hold TQQQ with QQQ filter ==")
    t, o, h, l, c = S.daily("TQQQ"); _, _, _, _, q = S.daily("QQQ")
    for n, buf in ((200, 0), (200, 0.02), (150, 0), (100, 0)):
        m = S.sma(q, n); st = False; inn = []
        for i in range(200, len(c) - 1):
            if not st and q[i] > m[i] * (1 + buf): st = True
            elif st and q[i] < m[i] * (1 - buf): st = False
            inn.append(st)
        inn = np.array(inn); rr = c[201:] / c[200:-1] - 1
        sw = np.abs(np.diff(np.r_[0, inn.astype(int)]))
        eq = np.cumprod((1 + rr * inn) * (1 - 0.0015 * sw)); dd = 1 - eq / np.maximum.accumulate(eq)
        h2 = len(eq) // 2
        print(f"TQQQ while QQQ>{n}d±{buf:.0%}: {100*(eq[-1]-1):+.0f}% mdd {100*dd.max():.0f}% switches {sw.sum()} | 1st half {100*(eq[h2]-1):+.0f}% 2nd {100*(eq[-1]/eq[h2]-1):+.0f}% | now {'IN' if inn[-1] else 'OUT'}")
