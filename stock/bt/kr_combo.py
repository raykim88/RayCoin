"""Can KR 52-week-high breakouts (hold 20 sessions, KOSPI > 200d) use idle stock-sleeve cash without hurting the US rules?
A) swing sleeve: US first, KR breakouts on spare cash.  B) trend sleeve: when QQQ < 200d (sleeve in cash), KR breakouts.
Usage: python3 stock/bt/kr_combo.py"""
import sys, io
import numpy as np
_o = sys.stdout; sys.stdout = io.StringIO()
import kr_stocks as K, news_proxy as N, review2 as V, swing as S
sys.stdout = _o
def brk(hold=20):
    out = []
    for s in K.SYMS:
        t, o, h, l, c = K.D[s]; i = 252
        while i < len(c) - hold - 1:
            if c[i] > c[i - 252:i].max() and K.mkt_up(t[i]):
                out.append((t[i + 1], t[i + hold], c[i + hold] / o[i + 1] - 1 - K.C, s, dict(sym=s))); i += hold
            else:
                i += 1
    return out
kr = brk()
score = lambda f: int(f["drop5"] < -0.05) + int(0.05 <= f["dist"] < 0.20) + int(f["gap"] <= 0) + int(20 <= f.get("vix", 0) < 30)
w_us = lambda f: {0: 0, 1: 0.5}.get(score(f), 1.0)
print("== A) swing sleeve")
V.line("US only", N.tr, w_us, 2)
for wk, slots in ((0.2, 4), (0.2, 7), (0.3, 5)):
    V.line(f"US + KR breakout w{wk} slots{slots}", N.tr + kr, lambda f, wk=wk: wk if f["sym"].endswith((".KS", ".KQ")) else w_us(f), slots)
print("== B) trend sleeve: TQQQ while QQQ>200d, else KR breakouts (5 x 20%)")
t, o, h, l, c = S.daily("TQQQ"); _, _, _, _, q = S.daily("QQQ"); m = S.sma(q, 200)
qin = {t[i]: q[i] > m[i] for i in range(200, len(c))}
qts = np.array(sorted(qin)); qv = np.array([qin[x] for x in qts])
def us_in(ts):
    j = np.searchsorted(qts, ts) - 1; return j >= 0 and qv[j]
# trend legs as trades: each IN stretch = one trade at next open
legs, i = [], 201
while i < len(c) - 1:
    if q[i - 1] > m[i - 1]:
        j = i
        while j < len(c) - 1 and q[j] > m[j]:
            j += 1
        legs.append((t[i], t[min(j + 1, len(c) - 1)], o[min(j + 1, len(c) - 1)] / o[i] * (1 - 0.0015) ** 2 - 1, "TQQQ", dict(sym="TQQQ"))); i = j + 1
    else:
        i += 1
V.line("trend only (TQQQ legs, 1 slot 100%)", legs, lambda f: 1.0, 1)
kr_out = [z for z in kr if not us_in(z[0])]
V.line("trend + KR breakouts when QQQ<200d", legs + kr_out, lambda f: 1.0 if f["sym"] == "TQQQ" else 0.2, 6)
