"""Portfolio test of US surge-chasing: day close >= +thr vs previous close -> buy next open with 1/slots of equity,
sell after `hold` sessions at the close, or at the stop (checked on the daily low, filled at the stop or the open if gapped).
Usage: python3 stock/bt/us_surge_port.py"""
import csv, numpy as np
from pathlib import Path
B = Path(__file__).resolve().parent / "data"
C = 0.0015
def load(p):
    a = np.array([[float(x) for x in r[:5]] for r in list(csv.reader(open(p)))[1:]]); return a[:, 0].astype(int), a[:, 1], a[:, 2], a[:, 3], a[:, 4]
D = {p.stem: load(p) for p in (B / "1d_us").glob("*.csv")}
qt = load(B / "1d" / "QQQ.csv")[0]
idx = {s: {t: i for i, t in enumerate(d[0])} for s, d in D.items()}
def run(thr, hold, slots, sl, t0=None, t1=None):
    eq = 100.0; cash = eq; pos = []; curve = []; n = w = 0
    days = [t for t in qt if (t0 is None or t >= t0) and (t1 is None or t < t1)]
    pend = []
    for t in days:
        # fills at open
        for s in pend:
            if len(pos) >= slots: break
            i = idx[s].get(t)
            if i is None: continue
            o = D[s][1][i]; amt = min(cash, (cash + sum(p["v"] for p in pos)) / slots)
            if amt < 1: break
            cash -= amt; pos.append(dict(s=s, e=o, q=amt * (1 - C) / o, d=0, v=amt))
        pend = []
        keep = []
        for p in pos:
            i = idx[p["s"]].get(t)
            if i is None: keep.append(p); continue
            o, h, l, c = D[p["s"]][1][i], D[p["s"]][2][i], D[p["s"]][3][i], D[p["s"]][4][i]
            p["d"] += 1; stop = p["e"] * (1 - sl) if sl else None
            if stop and l <= stop:
                x = min(o, stop)
            elif p["d"] >= hold:
                x = c
            else:
                p["v"] = p["q"] * c; keep.append(p); continue
            cash += p["q"] * x * (1 - C); n += 1; w += x > p["e"]
        pos = keep
        # signals at close
        sig = []
        for s, (ts, o, h, l, c) in D.items():
            i = idx[s].get(t)
            if i and c[i] / c[i - 1] - 1 >= thr and all(p["s"] != s for p in pos): sig.append((c[i] / c[i - 1], s))
        pend = [s for _, s in sorted(sig, reverse=True)]
        eq = cash + sum(p["v"] for p in pos); curve.append(eq)
    cv = np.array(curve); mdd = (1 - cv / np.maximum.accumulate(cv)).max()
    return eq, n, w, mdd
mid = qt[len(qt) // 2]
for thr in (0.08, 0.12):
    for slots in (3, 5):
        for sl in (0, 0.10, 0.15):
            for hold in (10, 20):
                a = run(thr, hold, slots, sl); h1 = run(thr, hold, slots, sl, t1=mid); h2 = run(thr, hold, slots, sl, t0=mid)
                print(f"+{int(thr*100)}% 슬롯{slots} 손절{int(sl*100):2d}% {hold}일: ${a[0]:8.0f} 거래{a[1]:4d} 승률{100*a[2]/max(a[1],1):3.0f}% 낙폭{100*a[3]:3.0f}% | 전반 ${h1[0]:6.0f} 후반 ${h2[0]:6.0f}")
