"""Swing sleeve: US first, KR index ETF pullbacks with spare cash only (user, 11-16).
US: TQQQ/UPRO RSI(2)<30 conviction sizing (live rules). KR: RSI(2)<lo above the 200-day average, fixed weight
of the sleeve, capped by free cash, KR cost 0.1%/side. 10 years of daily bars.
Usage: python3 stock/bt/kr_spare.py"""
import numpy as np
import review2 as V
import news_proxy as N   # adds VIX to US trades (prints its own tables)

us = N.tr
score = lambda f: int(f["drop5"] < -0.05) + int(0.05 <= f["dist"] < 0.20) + int(f["gap"] <= 0) + int(20 <= f.get("vix", 0) < 30)
def w_us(f): return {0: 0, 1: 0.5}.get(score(f), 1.0)
print("\n==== spare-cash KR ====")
V.line("US only (live)", us, w_us, 2)
for kr_syms, lab in ((["122630.KS"], "KOSPI2x"), (["069500.KS"], "KOSPI1x"), (["122630.KS", "069500.KS"], "both")):
    for lo in (10, 20):
        kr = V.trades(kr_syms, lo, cost=0.002)
        for wk in (0.3, 0.5):
            for slots in (3,):
                V.line(f"US + {lab} rsi<{lo} w{wk}", us + kr, lambda f, wk=wk: wk if f["sym"].endswith(".KS") else w_us(f), slots)
