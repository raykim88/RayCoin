#!/usr/bin/env python3
"""Performance breakdown of every RayCoin trade, for the hourly review.

Usage: python3 web/review_stats.py [status.json] [--json]
Everything is measured against the fixed $50 initial capital.
"""
import json
import sys
from collections import defaultdict


def usd(p):
    return p["cost_usd"] * p["pnl"] / 100


def bucket(rows):
    n = len(rows)
    if not n:
        return None
    wins = [p for p in rows if p["pnl"] > 0]
    loss = [p for p in rows if p["pnl"] <= 0]
    return dict(n=n, pnl_usd=round(sum(usd(p) for p in rows), 3),
                win_rate=round(len(wins) / n * 100, 1),
                avg_win_roe=round(sum(p["pnl"] for p in wins) / len(wins), 2) if wins else None,
                avg_loss_roe=round(sum(p["pnl"] for p in loss) / len(loss), 2) if loss else None,
                avg_margin=round(sum(p["cost_usd"] for p in rows) / n, 2))


def reason_kind(r):
    r = r or ""
    for key, name in (("청산", "liquidation"), ("강제", "hard_stop"), ("익절", "take_profit"),
                      ("손절", "stop_loss"), ("방향 전환", "flip"), ("교체", "swap"), ("현물", "spot_switch")):
        if key in r:
            return name
    return "other"


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), "status.json")
    st = json.load(open(path, encoding="utf-8"))
    P = st["positions"]
    fut = [p for p in P if "side" in p]
    closed = [p for p in fut if p["status"] == "CLOSED"]
    open_ = [p for p in fut if p["status"] == "OPEN"]
    total_usd = sum(usd(p) for p in P)
    fee_usd = sum(p["cost_usd"] * 0.0005 * p["lev"] * 2 for p in fut)   # approx. round-trip fees

    out = dict(
        capital=50.0, equity=round(50 + total_usd, 3), total_pnl_usd=round(total_usd, 3),
        total_pnl_pct=round(total_usd / 50 * 100, 2), cash=st.get("cash"),
        futures_closed=bucket(closed), futures_open=bucket(open_),
        spot=bucket([p for p in P if "side" not in p]),
        approx_fees_usd=round(fee_usd, 3),
        by_side={k: bucket([p for p in closed if p["side"] == k]) for k in ("LONG", "SHORT")},
        by_lev={str(l): bucket([p for p in closed if p["lev"] == l]) for l in sorted({p["lev"] for p in closed})},
        by_exit={}, by_round={}, params=st.get("params"), round=st.get("round"), minute=st.get("minute"),
    )
    g = defaultdict(list)
    for p in closed:
        g[reason_kind(p.get("reason"))].append(p)
    out["by_exit"] = {k: bucket(v) for k, v in g.items()}
    r = defaultdict(list)
    for p in closed:
        r[p.get("round")].append(p)
    out["by_round"] = {str(k): bucket(v) for k, v in sorted(r.items())}
    out["round_reports"] = [dict(round=x["round"], pnl_usd=x.get("round_pnl_usd"), pnl_pct=x.get("pnl_pct"))
                            for x in st.get("reports", []) if x.get("kind") not in ("tuning", "review")]
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"equity ${out['equity']} ({out['total_pnl_pct']:+.2f}% on $50), cash ${out['cash']}, fees~${out['approx_fees_usd']}")
    for k in ("futures_closed", "futures_open", "spot"):
        print(f"{k:15} {out[k]}")
    for sec in ("by_side", "by_lev", "by_exit", "by_round"):
        print(sec)
        for k, v in out[sec].items():
            print(f"   {k:12} {v}")
    print("params", out["params"])


if __name__ == "__main__":
    main()
