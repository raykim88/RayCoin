"""Strategy ② variants for a live bot: when to act (next open vs at the close using a live quote just
before it), an intraday exit on crossing the 5-day average, and a hard stop.

Usage: python3 stock/bt/rsi2_live.py
"""
import numpy as np

import ab
import swing as S


def run(syms, lo=20, at_close=False, intraday_exit=False, sl=None, maxd=10):
    out = []
    for s in syms:
        t, o, h, l, c = S.daily(s)
        r2, m200 = S.rsi(c), S.sma(c, 200)
        i = 200
        while i < len(c) - 2:
            if c[i] > m200[i] and r2[i] < lo:
                e = i if at_close else i + 1
                px = c[i] if at_close else o[e]
                x, xp = None, None
                for k in range(e + (1 if at_close else 0), min(len(c), e + maxd + 1)):
                    m5 = (c[k - 4:k].sum() + c[k]) / 5              # includes today's price
                    if sl and l[k] <= px * (1 - sl):
                        x, xp = k, min(o[k], px * (1 - sl)); break
                    if intraday_exit:
                        target = c[k - 4:k].sum() / 4                # price p with (sum4 + p)/5 < p  <=> p > sum4/4
                        if h[k] > target:
                            x, xp = k, max(o[k], target); break
                    elif c[k] > m5:
                        x = k; xp = c[k] if at_close else (o[k + 1] if k + 1 < len(c) else c[k]); break
                if x is None:
                    x = min(len(c) - 1, e + maxd); xp = c[x]
                out.append((t[e], t[x] + 1, xp / px - 1 - ab.US_COST, s, 0)); i = x + 1
            else:
                i += 1
    return out


if __name__ == "__main__":
    U = ["TQQQ", "UPRO"]
    S.show("② 기준: 다음날 시가 진입·시가 청산", S.us(U, "rsi", 20), 1)
    S.show("② 종가 직전 진입·종가 청산", run(U, at_close=True), 1)
    S.show("② 종가 진입 + 장중 5일선 돌파 즉시 청산", run(U, at_close=True, intraday_exit=True), 1)
    S.show("② 시가 진입 + 장중 5일선 돌파 즉시 청산", run(U, intraday_exit=True), 1)
    for sl in (0.08, 0.12, 0.15):
        S.show(f"② 종가 진입·종가 청산 + 손절 {sl:.0%}", run(U, at_close=True, sl=sl), 1)
    for lo in (15, 25, 30):
        S.show(f"② 종가 진입·종가 청산 rsi<{lo}", run(U, lo=lo, at_close=True), 1)
    S.show("② 종가 진입·종가 청산 +SOXL+TECL K2", run(U + ["SOXL", "TECL"], at_close=True), 2)
