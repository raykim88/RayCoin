"""Strict screen over every config in run.grid(): a config 'has an edge' only if it is
profitable in EVERY week, still profitable without its 3 best coins, and still profitable
with double costs. Prints survivors (if any) and the closest candidates.

Usage: python3 backtest/screen.py
"""
import json
from collections import defaultdict
from pathlib import Path

import engine as E
import run as R

WEEK = 2016


def evaluate(fam, p, build):
    kw = {k: v for k, v in p.items() if k != "lev"}
    K = p["k"] * len(p["sides"]) if fam.startswith("xs") else 5
    trades = build(p["lev"], **kw) if build else R.xs(p["lev"], **kw)
    full = E.portfolio(trades, K, 0, R.T)
    weeks = [E.portfolio(trades, K, w, min(R.T, w + WEEK))["ret"] for w in range(0, R.T, WEEK)]
    by = defaultdict(float)
    for t in trades:
        by[t[3]] += t[2]
    top3 = set(sorted(by, key=lambda n: -by[n])[:3])
    wo = E.portfolio([t for t in trades if t[3] not in top3], K, 0, R.T)
    return trades, K, full, weeks, wo


def main():
    rows = []
    for fam, p, build in R.grid():
        if p["lev"] != 1:            # judge the edge at 1x; leverage only scales it
            continue
        trades, K, full, weeks, wo = evaluate(fam, p, build)
        if full["n"] < 30:
            continue
        rows.append(dict(family=fam, params=p, full=full, weeks=weeks, without_top3=wo, trades=trades, K=K))
    passed = []
    for r in rows:
        if min(r["weeks"]) > 0 and r["without_top3"]["ret"] > 0:
            E.COST = 0.002
            fam, p = r["family"], r["params"]
            build = None if fam.startswith("xs") else R.per_market({"mom_chase": R.g_mom, "mean_reversion": R.g_rev,
                                                                    "breakout": R.g_brk}[fam])
            kw = {k: v for k, v in p.items() if k != "lev"}
            tr2 = build(1, **kw) if build else R.xs(1, **kw)
            r["double_cost"] = E.portfolio(tr2, r["K"], 0, R.T)
            E.COST = 0.001
            if r["double_cost"]["ret"] > 0:
                passed.append(r)
    # "closest": rank by the worst of (worst week, without-top3)
    rows.sort(key=lambda r: -min(min(r["weeks"]), r["without_top3"]["ret"]))
    fams = defaultdict(lambda: [0, 0])
    for r in rows:
        fams[r["family"]][0] += 1
        fams[r["family"]][1] += r["full"]["ret"] > 0
    print("configs at 1x:", len(rows), {k: f"{v[1]}/{v[0]} profitable over 3 weeks" for k, v in fams.items()})
    print("PASSED strict screen:", len(passed))
    for r in passed:
        print("  ", r["family"], r["params"], r["full"], r["weeks"], r["without_top3"], r["double_cost"])
    print("closest 8:")
    for r in rows[:8]:
        print("  ", r["family"], {k: v for k, v in r["params"].items() if k != "lev"},
              "full", r["full"]["ret"], "weeks", r["weeks"], "w/o top3", r["without_top3"]["ret"])
    out = [dict(family=r["family"], params=r["params"], full=r["full"], weeks=r["weeks"],
                without_top3=r["without_top3"], double_cost=r.get("double_cost")) for r in rows]
    Path(__file__).with_name("screen.json").write_text(json.dumps(dict(
        meta=dict(markets=R.names, start=R.stamps[0], end=R.stamps[-1], bars=R.T),
        families={k: dict(configs=v[0], profitable=v[1]) for k, v in fams.items()},
        passed=len(passed), rows=out), ensure_ascii=False, default=lambda o: list(o) if isinstance(o, tuple) else float(o)))


if __name__ == "__main__":
    main()
