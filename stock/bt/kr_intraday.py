"""KR session (09:00-15:30 KST) ideas while the US market is closed. Daily bars, 10 years.
Signal = previous US session (QQQ close-to-close, or QQQ/TQQQ RSI) known before the KR open.
Trade = KR ETF open -> same-day close. Cost 0.1% per side (ETF: no transaction tax).
Usage: python3 stock/bt/kr_intraday.py"""
from datetime import datetime, timezone, timedelta
import numpy as np
import swing as S

KST = timezone(timedelta(hours=9)); COST = 0.002
def kday(ts): return datetime.fromtimestamp(ts, KST).date()
def uday(ts): return datetime.fromtimestamp(ts, timezone(timedelta(hours=-5))).date()
qt, qo, qh, ql, qc = S.daily("QQQ")
qret = {uday(t): qc[i] / qc[i - 1] - 1 for i, t in enumerate(qt) if i}
qd = sorted(qret)
def prev_us(d):          # last US session that closed before KR date d opens
    import bisect
    j = bisect.bisect_left(qd, d) - 1
    return qd[j] if j >= 0 else None
for sym in ("122630.KS", "233740.KS", "069500.KS"):
    t, o, h, l, c = S.daily(sym)
    rows = []
    for i in range(1, len(c)):
        d = kday(t[i]); u = prev_us(d)
        if u is None: continue
        rows.append((d, qret[u], o[i] / c[i - 1] - 1, c[i] / o[i] - 1))
    d_, us, gap, oc = map(np.array, zip(*rows)); half = len(oc) // 2; H = np.arange(len(oc)) < half
    print(f"== {sym}: open->close all days avg {100*(oc.mean()-COST):+.3f}% (n {len(oc)})")
    for lab, s in (("US >+2%", us > 0.02), ("US +1~2%", (us > 0.01) & (us <= 0.02)), ("US -1~+1%", abs(us) <= 0.01),
                   ("US -2~-1%", (us < -0.01) & (us >= -0.02)), ("US <-2%", us < -0.02),
                   ("gap < -1.5%", gap < -0.015), ("gap > +1.5%", gap > 0.015)):
        r = oc[s] - COST
        if s.sum() >= 20:
            print(f"  {lab:<12} n{s.sum():4d} long avg {100*r.mean():+.3f}% win {100*(r>0).mean():.0f}% | halves {100*(oc[s&H]-COST).mean():+.3f} / {100*(oc[s&~H]-COST).mean():+.3f}"
                  f" | short avg {100*(-oc[s]-COST).mean():+.3f}%")

print("== inverse ETFs bought at the KR open after a strong US session (real data)")
for sym in ("251340.KS", "114800.KS"):      # KODEX 코스닥150선물인버스, KODEX 인버스
    t, o, h, l, c = S.daily(sym)
    rows = [(qret[prev_us(kday(t[i]))], c[i] / o[i] - 1, kday(t[i]).year) for i in range(1, len(c)) if prev_us(kday(t[i]))]
    us, oc, yr = map(np.array, zip(*rows))
    for th in (0.01, 0.015, 0.02, 0.025, 0.03):
        s = us > th; r = oc[s] - COST; H = np.arange(len(oc))[s] < len(oc) // 2
        if s.sum() >= 15:
            eq = np.prod(1 + r)
            print(f"  {sym} US>{th:.1%} n{s.sum():3d} avg {100*r.mean():+.3f}% win {100*(r>0).mean():.0f}% halves {100*r[H].mean():+.3f}/{100*r[~H].mean():+.3f} compound {100*(eq-1):+.0f}%"
                  f" | by year " + " ".join(f"{y%100}:{100*r[yr[s]==y].mean():+.1f}" for y in sorted(set(yr[s]))))
