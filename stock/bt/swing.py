"""Short swing (2-10 day) candidates on daily bars, 10 years, $100, costs included.

US1  RSI(2) pullback: close above its 200-day average and RSI(2) below `lo` -> buy next open;
     sell at the open after close > 5-day average (or after `maxd` days).
US2  N down closes in a row (same exit).
KR1  big drop: a large cap closes `d` or more below the previous close -> buy next open, hold until
     +tp / -sl (checked on daily high/low, stop first) or `maxd` days, then sell at that close.

Usage: python3 stock/bt/swing.py
"""
import csv
from datetime import datetime
from pathlib import Path

import numpy as np

import ab

CAP = 100.0
D = Path(__file__).resolve().parent / "data" / "1d"


def daily(sym):
    with open(D / f"{sym}.csv") as f:
        rows = [r for r in list(csv.reader(f))[1:]]
    a = np.array([[float(x) for x in r[:5]] for r in rows])
    return a[:, 0].astype(int), a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def rsi(c, n=2):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.zeros_like(c); ad = np.zeros_like(c)
    for i in range(1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def sma(c, n):
    out = np.full_like(c, np.nan); cs = np.cumsum(np.r_[0, c])
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def us(syms, kind="rsi", lo=10, downs=3, maxd=10, trend=True, cost=ab.US_COST):
    out = []
    for s in syms:
        t, o, h, l, c = daily(s)
        r2, m200, m5 = rsi(c), sma(c, 200), sma(c, 5)
        i = 200
        while i < len(c) - 2:
            ok = (not trend) or c[i] > m200[i]
            sig = r2[i] < lo if kind == "rsi" else all(c[i - k] < c[i - k - 1] for k in range(downs))
            if ok and sig:
                e = i + 1; px = o[e]; x = e
                while x < len(c) - 1 and x - e < maxd and not (c[x] > m5[x]):
                    x += 1
                xp = o[x + 1] if x + 1 < len(c) else c[x]
                out.append((t[e], t[min(x + 1, len(c) - 1)], xp / px - 1 - cost, s, 0)); i = x + 1
            else:
                i += 1
    return out


def kr(drop=0.05, tp=0.05, sl=0.05, maxd=5):
    out = []
    for p in sorted(D.glob("*.K?.csv")):
        s = p.stem; t, o, h, l, c = daily(s); i = 1
        while i < len(c) - 2:
            if c[i] <= c[i - 1] * (1 - drop):
                e = i + 1; px = o[e]; ret = None
                for k in range(e, min(len(c), e + maxd)):
                    if l[k] <= px * (1 - sl):
                        ret = -sl; break
                    if h[k] >= px * (1 + tp):
                        ret = tp; break
                if ret is None:
                    k = min(len(c) - 1, e + maxd - 1); ret = c[k] / px - 1
                out.append((t[e], t[k] + 1, ret - ab.KR_COST, s, px)); i = k + 1
            else:
                i += 1
    return out


def show(name, tr, K):
    ab.portfolio.__defaults__ = (CAP,)
    f = ab.portfolio(tr, K, CAP)
    yrs = {}
    for ent, ex, r, s, px in tr:
        yrs.setdefault(datetime.fromtimestamp(ent).year, []).append(r)
    by = " ".join(f"{y % 100:02d}:{np.mean(v) * 100:+.1f}" for y, v in sorted(yrs.items()))
    print(f"{name:<40} {f['ret']:+9.1f}% mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} avg {f['avg']:+5.2f}% "
          f"월 {f['per_month']:+5.2f}% | 연도별 평균 {by}", flush=True)


if __name__ == "__main__":
    for s in ("QQQ", "SPY", "TQQQ"):
        t, o, h, l, c = daily(s)
        print(f"buy&hold {s}: {(c[-1] / c[200] - 1) * 100:+.0f}% over {(t[-1] - t[200]) / 86400 / 365:.1f}y")
    for syms, K in ((["QQQ", "SPY"], 1), (["TQQQ", "UPRO"], 1), (["TQQQ", "UPRO", "SOXL", "TECL"], 2)):
        for lo in (5, 10, 20):
            show(f"US1 rsi2<{lo} {'+'.join(syms)} K{K}", us(syms, "rsi", lo), K)
        show(f"US1 rsi2<10 no-trend {'+'.join(syms)} K{K}", us(syms, "rsi", 10, trend=False), K)
        for dn in (3, 4):
            show(f"US2 {dn} down days {'+'.join(syms)} K{K}", us(syms, "down", downs=dn), K)
    for drop in (0.05, 0.07, 0.10):
        for tp, sl, md in ((0.05, 0.05, 5), (0.08, 0.06, 10), (0.03, 0.05, 3)):
            show(f"KR1 drop{drop:.0%} tp{tp:.0%} sl{sl:.0%} {md}d K2", kr(drop, tp, sl, md), 2)
