"""Korean index ETFs with the US stock rules (RSI(2) pullback swing + 200-day trend hold).
KODEX 레버리지 122630, KODEX 코스닥150레버리지 233740, KODEX 200 069500, KODEX 코스닥150 229200.
ETF sales are exempt from the securities transaction tax; cost 0.1% per side (fee + slippage).
Usage: python3 stock/bt/kr_etf.py"""
import numpy as np
import swing as S, review2 as V

KR_COST = 0.002
for syms, lab in ((["122630.KS"], "KOSPI 2x"), (["233740.KS"], "KOSDAQ 2x"), (["122630.KS", "233740.KS"], "both 2x"),
                  (["069500.KS"], "KOSPI 1x")):
    for lo in (20, 30):
        tr = V.trades(syms, lo, cost=KR_COST)
        V.line(f"{lab} rsi<{lo} swing", tr, lambda f: 1.0 if len(syms) == 1 else 0.5, 1 if len(syms) == 1 else 2)
for s, sig in (("122630.KS", "069500.KS"), ("233740.KS", "229200.KS"), ("069500.KS", "069500.KS")):
    t, o, h, l, c = S.daily(s); _, _, _, _, q = S.daily(sig); m = S.sma(q, 200)
    inn = q[200:-1] > m[200:-1]; rr = c[201:] / c[200:-1] - 1
    sw = np.abs(np.diff(np.r_[0, inn.astype(int)]))
    eq = np.cumprod((1 + rr * inn) * (1 - 0.001 * sw)); dd = 1 - eq / np.maximum.accumulate(eq)
    bh = c[-1] / c[200] - 1; bdd = (1 - c[200:] / np.maximum.accumulate(c[200:])).max()
    h2 = len(eq) // 2
    print(f"{s} buy&hold {100*bh:+.0f}% (mdd {100*bdd:.0f}%) | trend hold while {sig}>200d {100*(eq[-1]-1):+.0f}% (mdd {100*dd.max():.0f}%, halves {100*(eq[h2]-1):+.0f}%/{100*(eq[-1]/eq[h2]-1):+.0f}%) now {'IN' if q[-1] > m[-1] else 'OUT'}")
