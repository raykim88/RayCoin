"""KR individual stocks, intraday only (closed by 15:30, so cash is free for the US session).
5-minute bars, last ~60 sessions (data/5m). Cost ab.KR_COST (incl. 0.20% sell tax).
Ideas: opening-range breakout, first-30-min momentum, gap-down fade, mid-day dip buy.
Usage: python3 stock/bt/kr_intraday2.py"""
import numpy as np
import ab

SY = sorted(p.stem for p in (ab.D / "5m").glob("*.K?.csv"))
KST = ab.timezone(ab.timedelta(hours=9)) if hasattr(ab, "timezone") else None
from datetime import timezone, timedelta
KST = timezone(timedelta(hours=9))
B = {s: ab.load("5m", s, KST) for s in SY}
C = ab.KR_COST
def rep(name, rs):
    rs = np.array(rs)
    if len(rs) == 0:
        print(f"{name:<44} n 0"); return
    print(f"{name:<44} n{len(rs):5d} avg {100*rs.mean():+.3f}% win {100*(rs>0).mean():4.0f}% sum {100*rs.sum():+7.1f}%")
for R in (3, 6):
    for sl in (None, 0.01, 0.02):
        rs = []
        for s, days in B.items():
            for d, b in days.items():
                if len(b) < R + 3: continue
                hi = max(x[2] for x in b[:R]); lo = min(x[3] for x in b[:R])
                for j in range(R, len(b) - 1):
                    if b[j][4] > hi:
                        px = b[j + 1][1]; stop = max(lo, px * (1 - sl)) if sl else lo; ret = None
                        for k in range(j + 1, len(b)):
                            if b[k][3] <= stop: ret = min(stop, b[k][1]) / px - 1; break
                        rs.append((ret if ret is not None else b[-1][4] / px - 1) - C); break
        rep(f"ORB {R*5}m sl{sl}", rs)
for th in (0.02, 0.03, 0.05):
    up, dn = [], []
    for s, days in B.items():
        for d, b in days.items():
            if len(b) < 10: continue
            r30 = b[5][4] / b[0][1] - 1; px = b[6][1]; ex = b[-1][4]
            if r30 > th: up.append(ex / px - 1 - C)
            if r30 < -th: dn.append(ex / px - 1 - C)
    rep(f"first30m >+{th:.0%} -> hold to close", up); rep(f"first30m <-{th:.0%} -> buy, hold to close", dn)
prev = {}
for g in (0.02, 0.03, 0.05):
    rs = []
    for s, days in B.items():
        ks = sorted(days)
        for a, b in zip(ks, ks[1:]):
            pc = days[a][-1][4]; o = days[b][0][1]
            if o / pc - 1 < -g and len(days[b]) > 3:
                rs.append(days[b][-1][4] / o - 1 - C)
    rep(f"gap down >{g:.0%} buy open -> close", rs)

print("== 10-year daily check of the gap-down open->close rule")
import swing as S
SYMS = [s for s in SY if (S.D / f"{s}.csv").exists()]
for g in (0.03, 0.05, 0.07):
    rows = []
    for s in SYMS:
        t, o, h, l, c = S.daily(s)
        for i in range(1, len(c)):
            if o[i] / c[i - 1] - 1 < -g:
                rows.append((t[i], c[i] / o[i] - 1 - C))
    rows.sort(); r = np.array([x[1] for x in rows]); H = np.arange(len(r)) < len(r) // 2
    yrs = {}
    for ts, x in rows:
        yrs.setdefault(ab.datetime.fromtimestamp(ts).year if hasattr(ab, "datetime") else 0, []).append(x)
    print(f"gap<-{g:.0%}: n{len(r)} avg {100*r.mean():+.3f}% win {100*(r>0).mean():.0f}% halves {100*r[H].mean():+.3f}/{100*r[~H].mean():+.3f} | "
          + " ".join(f"{y%100}:{100*np.mean(v):+.1f}({len(v)})" for y, v in sorted(yrs.items())))
