#!/usr/bin/env python3
"""RayCoin paper trader (Upbit KRW market, 1-minute monitoring).

Rules (requested):
  1. Pick the top 5 coins with the best scalping odds right now.
  2. "Buy" $10 of each (converted to KRW via KRW-USDT on Upbit).
  3. Check every minute.
     - PnL >= +20%: sell, UNLESS the profit curve is steep -> hold
       (then trail: sell when price falls 5% from peak or the slope turns flat/down).
     - PnL <= -20%: sell, UNLESS a rebound is likely -> hold
       (hard stop at -30%; sell as soon as the rebound signal disappears).
  4. Run for N minutes (default 30), then mark open positions to market and report.

No real orders are placed. Only public quotation endpoints are used.
"""
import argparse
import json
import math
import statistics
import time
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://api.upbit.com/v1"
KST = timezone(timedelta(hours=9))
FEE = 0.0005             # Upbit KRW market fee per side (0.05%)
BUDGET_USD = 10.0
TAKE_PROFIT = 0.20
STOP_LOSS = -0.20
HARD_STOP = -0.30
TRAIL_FROM_PEAK = 0.05
STEEP_SLOPE = 1.0         # %/min over last 5 one-minute closes
EXCLUDE = {"KRW-USDT", "KRW-USDC", "KRW-USDE", "KRW-USD1"}


def get(path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API}/{path}" + (f"?{q}" if q else "")
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001 - retry on any network error
            if attempt == 3:
                raise
            time.sleep(0.5 * (2 ** attempt))


def candles_1m(market, count=60):
    c = get("candles/minutes/1", market=market, count=count)
    time.sleep(0.12)  # stay under the quotation rate limit
    return list(reversed(c))  # oldest -> newest


def slope_pct_per_min(closes):
    """Linear-regression slope of closes, as % of the mean price per minute."""
    n = len(closes)
    if n < 2:
        return 0.0
    xs = range(n)
    mx, my = (n - 1) / 2, sum(closes) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, closes))
    den = sum((x - mx) ** 2 for x in xs)
    return (num / den) / my * 100 if den and my else 0.0


def rsi(closes, period=14):
    if len(closes) <= period:
        return 50.0
    gains = losses = 0.0
    for a, b in zip(closes[-period - 1:-1], closes[-period:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def now_kst():
    return datetime.now(KST).strftime("%H:%M:%S")


def select_top5(log):
    markets = get("market/all", isDetails="true")
    krw = []
    for m in markets:
        code = m["market"]
        if not code.startswith("KRW-") or code in EXCLUDE:
            continue
        ev = m.get("market_event") or {}
        if (ev.get("warning") is True) or m.get("market_warning") == "CAUTION":
            continue  # skip coins under exchange warning
        krw.append(code)

    tickers = []
    for i in range(0, len(krw), 100):
        tickers += get("ticker", markets=",".join(krw[i:i + 100]))
        time.sleep(0.12)

    # liquidity filter: top 40 by 24h traded value (KRW)
    tickers.sort(key=lambda t: t["acc_trade_price_24h"], reverse=True)
    pool = tickers[:40]

    rows = []
    for t in pool:
        c = candles_1m(t["market"], 60)
        if len(c) < 30:
            continue
        closes = [x["trade_price"] for x in c]
        rets = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:])]
        vol = statistics.pstdev(rets)                       # 1-min volatility (%)
        tv = [x["candle_acc_trade_price"] for x in c]
        surge = (sum(tv[-10:]) / 10) / max(sum(tv[:-10]) / max(len(tv) - 10, 1), 1)
        mom15 = (closes[-1] / closes[-16] - 1) * 100
        rng24 = (t["high_price"] / t["low_price"] - 1) * 100
        rows.append(dict(market=t["market"], price=t["trade_price"], vol=vol,
                         surge=surge, mom15=mom15, chg24=t["signed_change_rate"] * 100,
                         rng24=rng24, tv24=t["acc_trade_price_24h"],
                         rsi=rsi(closes)))

    def z(key, f=lambda v: v):
        vals = [f(r[key]) for r in rows]
        mu, sd = statistics.mean(vals), statistics.pstdev(vals) or 1
        return {r["market"]: (f(r[key]) - mu) / sd for r in rows}

    zv, zs, zm, zr = z("vol"), z("surge", lambda v: math.log(max(v, 1e-6))), z("mom15"), z("rng24")
    for r in rows:
        m = r["market"]
        # scalping score: volatility + volume surge + short-term momentum + daily range
        # penalise overbought (RSI>80) entries
        r["score"] = 0.35 * zv[m] + 0.30 * zs[m] + 0.20 * zm[m] + 0.15 * zr[m] - (0.5 if r["rsi"] > 80 else 0)
    rows.sort(key=lambda r: r["score"], reverse=True)

    log("=== Candidate ranking (top 10 of 40 most-traded KRW markets) ===")
    log(f"{'market':<12}{'score':>7}{'vol1m%':>8}{'surge':>7}{'mom15%':>8}{'24h%':>8}{'rng24%':>8}{'RSI':>6}")
    for r in rows[:10]:
        log(f"{r['market']:<12}{r['score']:>7.2f}{r['vol']:>8.3f}{r['surge']:>7.2f}"
            f"{r['mom15']:>8.2f}{r['chg24']:>8.2f}{r['rng24']:>8.2f}{r['rsi']:>6.1f}")
    return rows[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--log", default="trade_log.txt")
    ap.add_argument("--json", default="trade_result.json")
    args = ap.parse_args()

    logf = open(args.log, "w", encoding="utf-8")

    def log(msg):
        line = f"[{now_kst()}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    usdkrw = get("ticker", markets="KRW-USDT")[0]["trade_price"]
    budget_krw = BUDGET_USD * usdkrw
    log(f"USD/KRW (Upbit USDT) = {usdkrw:,.1f}  ->  $10 = {budget_krw:,.0f} KRW per coin")

    picks = select_top5(log)
    pos = {}
    for r in picks:
        m, p = r["market"], r["price"]
        qty = budget_krw * (1 - FEE) / p
        pos[m] = dict(entry=p, qty=qty, peak=p, status="OPEN", mode="normal",
                      exit=None, exit_time=None, reason=None, path=[p])
        log(f"BUY  {m:<12} @ {p:,.4f} KRW  qty={qty:.6f}  (score {r['score']:.2f})")

    events = []
    start = time.time()
    for minute in range(1, args.minutes + 1):
        # wait until the next 1-minute mark
        time.sleep(max(0, start + minute * 60 - time.time()))
        open_m = [m for m, p in pos.items() if p["status"] == "OPEN"]
        if not open_m:
            log("All positions closed. Stopping early.")
            break
        prices = {t["market"]: t["trade_price"] for t in get("ticker", markets=",".join(open_m))}
        line = []
        for m in open_m:
            p = pos[m]
            px = prices[m]
            p["path"].append(px)
            p["peak"] = max(p["peak"], px)
            pnl = px * (1 - FEE) / (p["entry"] / (1 - FEE)) - 1  # net of both fees
            c = candles_1m(m, 20)
            closes = [x["trade_price"] for x in c]
            sl5 = slope_pct_per_min(closes[-5:])
            r14 = rsi(closes)
            last = c[-1]
            green = last["trade_price"] > last["opening_price"]
            lower_wick = (min(last["opening_price"], last["trade_price"]) - last["low_price"]) / max(last["low_price"], 1e-9) * 100
            action = None

            if pnl >= TAKE_PROFIT:
                if p["mode"] != "ride" and sl5 >= STEEP_SLOPE:
                    p["mode"] = "ride"
                    log(f"HOLD {m}: +{pnl*100:.1f}% but curve is steep (slope {sl5:.2f}%/min) -> riding")
                elif p["mode"] == "ride" and (px <= p["peak"] * (1 - TRAIL_FROM_PEAK) or sl5 <= 0):
                    action = f"take-profit (trail exit, slope {sl5:.2f}%/min)"
                elif p["mode"] != "ride":
                    action = f"take-profit +{pnl*100:.1f}%"
            elif p["mode"] == "ride":
                action = f"trail exit (fell back below +20%, slope {sl5:.2f}%/min)"
            elif pnl <= STOP_LOSS:
                rebound = (r14 <= 30 and (green or lower_wick >= 1.0)) or (sl5 > 0 and r14 < 40)
                if pnl <= HARD_STOP:
                    action = f"hard stop {pnl*100:.1f}%"
                elif rebound:
                    if p["mode"] != "rebound":
                        log(f"HOLD {m}: {pnl*100:.1f}% but rebound likely (RSI {r14:.0f}, slope {sl5:.2f}, green={green})")
                    p["mode"] = "rebound"
                else:
                    action = f"stop-loss {pnl*100:.1f}% (no rebound signal)"
            elif p["mode"] == "rebound" and pnl > STOP_LOSS:
                p["mode"] = "normal"
                log(f"RECOVER {m}: back above -20% ({pnl*100:.1f}%)")

            if action:
                p.update(status="CLOSED", exit=px, exit_time=now_kst(), reason=action)
                log(f"SELL {m:<12} @ {px:,.4f}  PnL {pnl*100:+.2f}%  [{action}]")
                events.append(dict(t=now_kst(), market=m, action="SELL", price=px, pnl=pnl, reason=action))
            line.append(f"{m[4:]} {pnl*100:+6.2f}% s{sl5:+.2f} r{r14:.0f}")
        log(f"t+{minute:02d}m | " + " | ".join(line))

    # final evaluation
    log("=== FINAL ===")
    total_in = total_out = 0.0
    summary = []
    final_px = {t["market"]: t["trade_price"] for t in get("ticker", markets=",".join(pos))}
    for m, p in pos.items():
        cost = budget_krw
        px = p["exit"] if p["status"] == "CLOSED" else final_px[m]
        value = p["qty"] * px * (1 - FEE)
        pnl = value / cost - 1
        maxup = max(p["path"]) / p["entry"] - 1
        maxdn = min(p["path"]) / p["entry"] - 1
        total_in += cost
        total_out += value
        state = f"SOLD ({p['reason']})" if p["status"] == "CLOSED" else "OPEN (marked to market)"
        log(f"{m:<12} entry {p['entry']:,.4f} -> {px:,.4f}  PnL {pnl*100:+6.2f}%  "
            f"${value/usdkrw:6.3f}  max+{maxup*100:.2f}% / max{maxdn*100:.2f}%  {state}")
        summary.append(dict(market=m, entry=p["entry"], exit=px, pnl_pct=pnl * 100,
                            value_usd=value / usdkrw, max_up_pct=maxup * 100,
                            max_down_pct=maxdn * 100, status=p["status"], reason=p["reason"],
                            path=p["path"]))
    tot = total_out / total_in - 1
    log(f"TOTAL: ${total_in/usdkrw:.2f} -> ${total_out/usdkrw:.3f}  ({tot*100:+.2f}%)")
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(dict(usdkrw=usdkrw, total_pct=tot * 100, positions=summary, events=events), f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
