"""Robustness checks for the breakout family: parameter neighbourhood, week by week,
large caps vs small caps, per-coin concentration, and cost sensitivity.

Usage: python3 backtest/robust.py
"""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import engine as E
import run as R

M, names, T = R.M, R.names, R.T
WEEK = 2016                                   # 5-minute bars in 7 days
MAJORS = [n for n in ("KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA", "KRW-SUI",
                      "KRW-LINK", "KRW-TRX", "KRW-AVAX", "KRW-XLM", "KRW-NEAR", "KRW-ENA", "KRW-ONDO") if n in M]


def trades_for(lev, N, sl, side_mode="both", btc_filter=0, universe=None):
    keep = set(universe or names)
    out = []
    for n in names:
        if n not in keep:
            continue
        m = M[n]; busy = -1
        for i, side, extra in R.g_brk(m, N=N, sl=sl, side_mode=side_mode, btc_filter=btc_filter):
            if i <= busy:
                continue
            r = E.simulate_trade(m, i, side, lev, **extra)
            if r:
                out.append((i + 1, r[0], r[1], n)); busy = r[0]
    return out


def weeks(trades, K=5):
    out = []
    for w0 in range(0, T, WEEK):
        out.append(E.portfolio(trades, K, w0, min(T, w0 + WEEK))["ret"])
    return out


def main():
    rep = dict(majors=MAJORS)
    print("universe", len(names), "majors", MAJORS)

    # 1. neighbourhood at 1x, both sides
    grid = {}
    print("\n1) full-period return % at 1x (rows N bars, cols stop %), both sides, no BTC filter")
    Ns, SLs = (72, 96, 144, 192, 288), (0.03, 0.04, 0.06, 0.08, 0.10)
    print("      " + " ".join(f"{s*100:>6.0f}" for s in SLs))
    for N in Ns:
        row = []
        for sl in SLs:
            tr = trades_for(1, N, sl)
            row.append(E.portfolio(tr, 5, 0, T)["ret"])
        grid[N] = row
        print(f"N={N:<4}" + " ".join(f"{x:+6.1f}" for x in row))
    rep["grid_1x"] = dict(N=Ns, sl=SLs, ret=grid)

    # 2. the chosen centre, week by week, side splits
    print("\n2) N=144 sl=6% 1x, weekly returns (each week restarts at $50)")
    for sm in ("both", "long", "short"):
        for bf in (0, 1):
            tr = trades_for(1, 144, 0.06, sm, bf)
            full = E.portfolio(tr, 5, 0, T)
            print(f"  {sm:<5} btcfilter={bf}  weeks {weeks(tr)}  full {full}")
            rep[f"weekly_{sm}_{bf}"] = dict(weeks=weeks(tr), full=full)

    # 3. large caps only vs the rest
    print("\n3) universe split (N=144 sl=6% 1x both)")
    small = [n for n in names if n not in MAJORS]
    for label, uni in (("majors", MAJORS), ("small", small)):
        tr = trades_for(1, 144, 0.06, universe=uni)
        full = E.portfolio(tr, 5, 0, T)
        print(f"  {label:<7} n_coins={len(uni)} weeks {weeks(tr)} full {full}")
        rep[f"universe_{label}"] = dict(weeks=weeks(tr), full=full)

    # 4. concentration: sum of margin returns per coin
    tr = trades_for(1, 144, 0.06)
    by = defaultdict(list)
    for t in tr:
        by[t[3]].append(t[2])
    conc = sorted(((n, round(sum(v) * 100, 1), len(v)) for n, v in by.items()), key=lambda x: -x[1])
    print("\n4) per-coin sum of trade returns % (N=144 sl=6% 1x):", conc)
    rep["per_coin"] = conc
    top3 = {c[0] for c in conc[:3]}
    tr_wo = [t for t in tr if t[3] not in top3]
    rep["without_top3"] = E.portfolio(tr_wo, 5, 0, T)
    print("   without top-3 coins", top3, rep["without_top3"])

    # 5. cost sensitivity
    print("\n5) cost per side 0.10% (base) -> 0.20%")
    E.COST = 0.002
    tr = trades_for(1, 144, 0.06)
    rep["cost_0.2"] = E.portfolio(tr, 5, 0, T)
    print("  ", rep["cost_0.2"], "weeks", weeks(tr))
    E.COST = 0.001

    # 6. leverage at the centre
    for lev in (1, 2, 3):
        tr = trades_for(lev, 144, 0.06)
        rep[f"lev{lev}"] = dict(full=E.portfolio(tr, 5, 0, T), weeks=weeks(tr))
        print(f"\n6) lev {lev}: {rep[f'lev{lev}']}")

    Path(__file__).with_name("robust.json").write_text(json.dumps(rep, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
