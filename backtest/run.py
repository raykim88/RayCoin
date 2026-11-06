"""Search strategy families on the first 2/3 of the data, judge them on the last 1/3.

Usage: python3 backtest/run.py  -> prints a table and writes backtest/results.json
"""
import itertools, json, sys, time
from pathlib import Path

import numpy as np

import engine as E

stamps, M = E.load()
M.pop("KRW-USDT", None)
names = sorted(M)
T = len(stamps)
SPLIT = int(T * 2 / 3)
BTC = M["KRW-BTC"]
btc_up = BTC.c > E.ema(BTC.c, 288)          # BTC above its 24h EMA


def per_market(gen):
    """gen(m) yields (i, side, kwargs) candidates in time order; keep them non-overlapping per market."""
    def build(lev, **kw):
        out = []
        for n in names:
            m = M[n]; busy = -1
            for i, side, extra in gen(m, **kw):
                if i <= busy:
                    continue
                r = E.simulate_trade(m, i, side, lev, **extra)
                if r:
                    out.append((i + 1, r[0], r[1], n)); busy = r[0]
        return out
    return build


# ---------- 1. momentum chase (what the live bot does, roughly) ----------
def g_mom(m, th, tp, sl, hold):
    mom = np.full(len(m.c), 0.0); mom[3:] = m.c[3:] / m.c[:-3] - 1
    for i in np.nonzero(np.abs(mom) > th)[0]:
        yield i, (1 if mom[i] > 0 else -1), dict(tp=tp, sl=sl, hold=hold)


# ---------- 2. mean reversion on z-score ----------
def g_rev(m, n, k, sl, hold, side_mode):
    mu, sd = E.sma(m.c, n), E.rstd(m.c, n)
    z = (m.c - mu) / np.where(sd > 0, sd, np.nan)
    back_long = m.c >= mu; back_short = m.c <= mu
    for i in np.nonzero(np.abs(np.nan_to_num(z)) > k)[0]:
        side = -1 if z[i] > 0 else 1
        if side_mode == "long" and side < 0 or side_mode == "short" and side > 0:
            continue
        yield i, side, dict(tp=None, sl=sl, hold=hold, exit_sig=back_long if side > 0 else back_short)


# ---------- 3. breakout (Donchian) with trailing channel exit ----------
def g_brk(m, N, sl, side_mode, btc_filter):
    hi, lo = E.rolling_max(m.h, N), E.rolling_min(m.l, N)
    hi_prev = np.roll(hi, 1); lo_prev = np.roll(lo, 1)
    tlo, thi = E.rolling_min(m.l, N // 2), E.rolling_max(m.h, N // 2)
    ex_long = m.c < np.roll(tlo, 1); ex_short = m.c > np.roll(thi, 1)
    for i in range(N + 1, len(m.c)):
        if side_mode != "short" and m.c[i] > hi_prev[i] and (not btc_filter or btc_up[i]):
            yield i, 1, dict(tp=None, sl=sl, hold=2016, exit_sig=ex_long)
        elif side_mode != "long" and m.c[i] < lo_prev[i] and (not btc_filter or not btc_up[i]):
            yield i, -1, dict(tp=None, sl=sl, hold=2016, exit_sig=ex_short)


# ---------- 4. cross-sectional momentum / reversal (rank coins, hold R bars) ----------
def xs(lev, R, L, k, sign, sides, sl):
    C = np.vstack([M[n].c for n in names])
    out = []
    for i in range(L, T - 1, R):
        ret = C[:, i] / C[:, i - L] - 1
        order = np.argsort(ret * sign)[::-1]          # sign=+1 momentum (buy winners), -1 reversal
        picks = []
        if "long" in sides: picks += [(names[j], 1) for j in order[:k]]
        if "short" in sides: picks += [(names[j], -1) for j in order[-k:]]
        for n, s in picks:
            r = E.simulate_trade(M[n], i, s, lev, tp=None, sl=sl, hold=R - 1)
            if r:
                out.append((i + 1, r[0], r[1], n))
    return out


def grid():
    for lev in (1, 2, 3):
        for th, tp, sl, hold in itertools.product((0.01, 0.02, 0.03), (0.03, 0.05), (0.02, 0.03), (6, 36)):
            yield "mom_chase", dict(lev=lev, th=th, tp=tp, sl=sl, hold=hold), per_market(g_mom)
        for n, k, sl, hold, sm in itertools.product((12, 48, 144), (2.5, 3.0, 3.5), (0.03, 0.06), (12, 48),
                                                    ("both", "long")):
            yield "mean_reversion", dict(lev=lev, n=n, k=k, sl=sl, hold=hold, side_mode=sm), per_market(g_rev)
        for N, sl, sm, bf in itertools.product((48, 144, 288), (0.03, 0.06), ("both", "long", "short"), (0, 1)):
            yield "breakout", dict(lev=lev, N=N, sl=sl, side_mode=sm, btc_filter=bf), per_market(g_brk)
        for R, L, k, sign, sides, sl in itertools.product((12, 48, 288), (12, 48, 288), (2, 4), (1, -1),
                                                           (("long",), ("long", "short")), (None, 0.05)):
            yield "xs_" + ("momentum" if sign > 0 else "reversal"), \
                dict(lev=lev, R=R, L=L, k=k, sign=sign, sides=sides, sl=sl), None


def main():
    t0 = time.time()
    res = []
    for fam, p, build in grid():
        kw = {k: v for k, v in p.items() if k != "lev"}
        trades = build(p["lev"], **kw) if build else xs(p["lev"], **kw)
        K = 4 if fam.startswith("xs") else 5
        if fam.startswith("xs"):
            K = p["k"] * len(p["sides"])
        tr = E.portfolio(trades, K, 0, SPLIT)
        te = E.portfolio(trades, K, SPLIT, T)
        res.append(dict(family=fam, params={k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()},
                        train=tr, test=te))
    # benchmarks: buy & hold
    bench = {}
    for n in ("KRW-BTC", "KRW-ETH", "KRW-XRP"):
        if n in M:
            c = M[n].c
            bench[n] = dict(train=round((c[SPLIT - 1] / c[0] - 1) * 100, 2), test=round((c[-1] / c[SPLIT] - 1) * 100, 2))
    ew = np.mean([M[n].c[-1] / M[n].c[SPLIT] - 1 for n in names]) * 100
    ew_tr = np.mean([M[n].c[SPLIT - 1] / M[n].c[0] - 1 for n in names]) * 100
    bench["equal_weight_all"] = dict(train=round(ew_tr, 2), test=round(ew, 2))
    meta = dict(markets=names, bars=T, start=stamps[0], split=stamps[SPLIT], end=stamps[-1],
                cost_per_side_pct=E.COST * 100, seconds=round(time.time() - t0))
    Path(__file__).with_name("results.json").write_text(json.dumps(dict(meta=meta, bench=bench, results=res),
                                                                   ensure_ascii=False))
    print(json.dumps(meta)); print("bench", bench)
    # best per family on TRAIN (min 20 trades), and how it did on TEST
    for fam in sorted({r["family"] for r in res}):
        rs = [r for r in res if r["family"] == fam and r["train"]["n"] >= 20]
        rs.sort(key=lambda r: -r["train"]["ret"])
        top = rs[:10]
        med = np.median([r["test"]["ret"] for r in top]) if top else float("nan")
        frac = np.mean([r["test"]["ret"] > 0 for r in rs]) * 100 if rs else 0
        print(f"\n== {fam}: {len(rs)} configs, test>0 in {frac:.0f}%, top-10-by-train median test {med:+.2f}%")
        for r in top[:3]:
            print("  ", r["params"], "TRAIN", r["train"], "TEST", r["test"])


if __name__ == "__main__":
    main()
