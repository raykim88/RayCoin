"""Can "news" help the swing sleeve? Free-text news is not backtestable here, so test the measurable parts of
it: fear level (VIX at the signal) and scheduled macro events (FOMC decision days) inside the holding window.

Usage: python3 stock/bt/news_proxy.py   (downloads ^VIX daily once into data/1d)
"""
import csv, time
from datetime import datetime, timezone
import numpy as np
import fetch as F, review2 as V

p = F.OUT / "1d" / "^VIX.csv"
if not p.exists():
    r = F.get("^VIX", "1d", "10y"); q = r["indicators"]["quote"][0]
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for i, t in enumerate(r["timestamp"]):
            if q["close"][i] is not None:
                w.writerow([t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], 0])
vt, _, _, _, vc = V.S.daily("^VIX")
vday = {datetime.fromtimestamp(t, timezone.utc).date(): c for t, c in zip(vt, vc)}
# FOMC statement days 2017-2026 (Fed calendar)
FOMC = """2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13 2018-01-31 2018-03-21
2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19 2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31
2019-09-18 2019-10-30 2019-12-11 2020-01-29 2020-03-03 2020-03-15 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05
2020-12-16 2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15 2022-01-26 2022-03-16
2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14 2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26
2023-09-20 2023-11-01 2023-12-13 2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10 2026-01-28 2026-03-18 2026-04-29
2026-06-17 2026-07-29 2026-09-16 2026-10-28""".split()
fomc = {datetime.strptime(d, "%Y-%m-%d").date() for d in FOMC}

tr = V.trades(["TQQQ", "UPRO"], 30)
r = np.array([z[2] for z in tr]); mid = sorted(z[0] for z in tr)[len(tr) // 2]; H = np.array([z[0] < mid for z in tr])
d = lambda ts: datetime.fromtimestamp(ts, timezone.utc).date()
vix = []
for z in tr:
    prev = [k for k in vday if k < d(z[0])]
    vix.append(vday[max(prev)] if prev else np.nan)
vix = np.array(vix)
print(f"{len(tr)} trades avg {100*r.mean():+.2f}%")
for a, b in ((0, 15), (15, 20), (20, 25), (25, 30), (30, 99)):
    s = (vix >= a) & (vix < b)
    if s.sum() >= 10:
        print(f"VIX [{a},{b}) n{s.sum():3d} avg {100*r[s].mean():+.2f}% win {100*(r[s]>0).mean():.0f}% | halves {100*r[s&H].mean():+.2f} / {100*r[s&~H].mean():+.2f}")
ev = np.array([any(d(z[0]) <= f <= d(z[1]) for f in fomc) for z in tr])
for lab, s in (("FOMC inside hold", ev), ("no FOMC", ~ev)):
    print(f"{lab:<17} n{s.sum():3d} avg {100*r[s].mean():+.2f}% win {100*(r[s]>0).mean():.0f}% | halves {100*r[s&H].mean():+.2f} / {100*r[s&~H].mean():+.2f}")

vmap = {z[0]: v for z, v in zip(tr, vix)}
base = lambda f: int(f["drop5"] < -0.05) + int(0.05 <= f["dist"] < 0.20) + int(f["gap"] <= 0)
for z in tr:
    z[4]["vix"] = vmap[z[0]]
withv = lambda f: base(f) + int(20 <= f["vix"] < 30)
for lab, sc in (("live score", base), ("score + VIX 20-30", withv)):
    s_ = np.array([sc(z[4]) for z in tr])
    print(lab, " | ".join(f"{k}: n{(s_==k).sum()} {100*r[s_==k].mean():+.2f}%" for k in range(5) if (s_ == k).sum()))
    V.line(f"{lab}: >=2 100%, 1 50%, 0 skip", tr, lambda f, sc=sc: {0: 0, 1: 0.5}.get(sc(f), 1.0), 2)
