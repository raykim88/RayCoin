"""Backtest the two stock day-trade candidates on Yahoo candles (stock/bt/data).

A  US 3x ETFs, opening-range breakout: range = first R minutes; buy the next bar after a close above the
   range high; stop at the range low (or sl), optional take-profit, always flat at the close.
B  KR large caps, gap-down rebound: if a stock opens >= g below yesterday's close, buy at the open
   (or after the first green bar); take-profit tp, stop sl, else sell at the close.

Costs per side: US 0.10% fee + 0.05% slip; KR 0.015% fee + 0.05% slip, plus 0.20% sell tax.
Portfolio: $50, K slots, each entry uses equity/K; KR entries are skipped when one share costs more
than the slot (no intraday fractional shares in Korea).

Usage: python3 stock/bt/ab.py
"""
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

D = Path(__file__).resolve().parent / "data"
NY = timezone(timedelta(hours=-5))      # EST; DST shifts the clock by an hour but not the bar order
KST = timezone(timedelta(hours=9))
US_COST = 0.0015 * 2
KR_COST = (0.00015 + 0.0005) * 2 + 0.0020
USDKRW = 1360.0
LEV_ETF = ["TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXU", "TNA", "TZA", "TECL", "FNGU", "LABU", "LABD", "TSLL", "NVDL"]


def load(interval, sym, tz):
    p = D / interval / f"{sym}.csv"
    if not p.exists():
        return {}
    days = defaultdict(list)
    with open(p) as f:
        for r in list(csv.reader(f))[1:]:
            t = int(r[0]); o, h, l, c = map(float, r[1:5])
            dt = datetime.fromtimestamp(t, tz)
            if interval == "1d":
                days[dt.date()].append((t, o, h, l, c))
            else:
                days[dt.date()].append((t, o, h, l, c))
    return dict(sorted(days.items()))


def orb(interval, R_bars, sl=None, tp=None, syms=LEV_ETF):
    out = []
    for s in syms:
        for day, b in load(interval, s, NY).items():
            if len(b) < R_bars + 2:
                continue
            hi = max(x[2] for x in b[:R_bars]); lo = min(x[3] for x in b[:R_bars])
            for j in range(R_bars, len(b) - 1):
                if b[j][4] > hi:
                    px = b[j + 1][1]; stop = max(lo, px * (1 - sl)) if sl else lo
                    ret = None
                    for k in range(j + 1, len(b)):
                        if b[k][3] <= stop:
                            ret = min(stop, b[k][1]) / px - 1; break
                        if tp and b[k][2] >= px * (1 + tp):
                            ret = tp; break
                    if ret is None:
                        ret = b[-1][4] / px - 1; k = len(b) - 1
                    out.append((b[j + 1][0], b[k][0] + 1, ret - US_COST, s, px / USDKRW * 0))
                    break
    return out


def gap(interval, g, tp, sl, confirm=False, syms=None):
    syms = syms or [p.stem for p in (D / interval).glob("*.K?.csv")]
    out = []
    for s in syms:
        days = load(interval, s, KST); prev = None
        for day, b in days.items():
            if prev is not None and b:
                o = b[0][1]
                if o <= prev * (1 - g):
                    start = 0
                    if confirm:
                        start = 1 if len(b) > 1 and b[0][4] > b[0][1] else None
                    if start is not None and start < len(b):
                        px = b[start][1] if start else o
                        ret = None
                        for k in range(start, len(b)):
                            if b[k][3] <= px * (1 - sl):
                                ret = -sl; break
                            if b[k][2] >= px * (1 + tp):
                                ret = tp; break
                        if ret is None:
                            ret = b[-1][4] / px - 1; k = len(b) - 1
                        out.append((b[start][0], b[k][0] + 1, ret - KR_COST, s, px))
            prev = b[-1][4] if b else prev
    return out


def portfolio(trades, K, cap=50.0):
    trades = sorted(trades)
    eq, open_, taken, peak, mdd = cap, [], [], cap, 0.0
    curve = []
    for ent, ex, r, s, px in trades:
        still = []
        for x, mg, rr in open_:
            if x <= ent:
                eq += mg * rr
            else:
                still.append((x, mg, rr))
        open_ = still; peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        if len(open_) >= K:
            continue
        mg = eq / K
        if px and px > mg * USDKRW:       # KR: cannot afford one share
            continue
        open_.append((ex, mg, r)); taken.append((ent, r))
    for x, mg, rr in open_:
        eq += mg * rr
    peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    rs = np.array([t[1] for t in taken]) if taken else np.zeros(1)
    days = (taken[-1][0] - taken[0][0]) / 86400 if len(taken) > 1 else 1
    return dict(ret=(eq / cap - 1) * 100, mdd=mdd * 100, n=len(taken), win=(rs > 0).mean() * 100, avg=rs.mean() * 100,
                per_month=((eq / cap) ** (30 / max(days, 1)) - 1) * 100)


def show(name, tr, K):
    f = portfolio(tr, K)
    print(f"{name:<46} {f['ret']:+8.1f}% mdd {f['mdd']:5.1f} n {f['n']:4d} win {f['win']:5.1f} avg {f['avg']:+6.2f}% "
          f"월 {f['per_month']:+6.1f}%", flush=True)


if __name__ == "__main__":
    print("== A: US 3x ETF opening-range breakout ==")
    for interval, R_bars, label in (("5m", 3, "15분"), ("5m", 6, "30분"), ("5m", 12, "60분"), ("1h", 1, "60분(2년)")):
        for sl, tp in ((None, None), (0.02, None), (0.02, 0.04), (0.03, 0.06)):
            for K in (1, 2):
                show(f"A {interval} 범위{label} sl{sl} tp{tp} K{K}", orb(interval, R_bars, sl, tp), K)
    print("== A on plain QQQ/SPY (1x) ==")
    show("A 5m 30분 QQQ+SPY K1", orb("5m", 6, syms=["QQQ", "SPY"]), 1)
    show("A 1h 60분 QQQ+SPY K1", orb("1h", 1, syms=["QQQ", "SPY"]), 1)
    print("== B: KR gap-down rebound ==")
    for interval in ("5m", "1h", "1d"):
        for g in (0.03, 0.04, 0.06):
            for tp, sl in ((0.02, 0.02), (0.03, 0.03), (0.05, 0.03)):
                for confirm in (False, True):
                    if interval == "1d" and confirm:
                        continue
                    show(f"B {interval} gap{g:.0%} tp{tp:.0%} sl{sl:.0%} {'확인' if confirm else '시가'}",
                         gap(interval, g, tp, sl, confirm), 2)
