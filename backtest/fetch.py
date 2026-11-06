"""Download Upbit KRW 5-minute candles for the top markets by 24h traded value.

Usage: python3 backtest/fetch.py [days] [n_markets]
Writes backtest/data/<market>.csv (utc, open, high, low, close, value), oldest first.
"""
import csv, json, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.upbit.com/v1"
OUT = Path(__file__).resolve().parent / "data"


def get(path):
    for attempt in range(6):
        try:
            req = urllib.request.Request(API + path, headers={"accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except Exception as e:  # 429 / transient
            time.sleep(0.5 * 2 ** attempt)
    raise RuntimeError("failed: " + path)


def top_markets(n):
    mk = [m["market"] for m in get("/market/all") if m["market"].startswith("KRW-")]
    tick = []
    for i in range(0, len(mk), 100):
        tick += get("/ticker?markets=" + ",".join(mk[i:i + 100]))
    tick.sort(key=lambda t: -t["acc_trade_price_24h"])
    return [t["market"] for t in tick[:n]]


def candles(market, days):
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    rows, to = {}, end
    while to > start:
        batch = get(f"/candles/minutes/5?market={market}&count=200&to={to.strftime('%Y-%m-%dT%H:%M:%S')}Z")
        if not batch:
            break
        for c in batch:
            rows[c["candle_date_time_utc"]] = (c["opening_price"], c["high_price"], c["low_price"],
                                               c["trade_price"], c["candle_acc_trade_price"])
        to = datetime.fromisoformat(batch[-1]["candle_date_time_utc"]).replace(tzinfo=timezone.utc)
        time.sleep(0.12)
    return [(k, *v) for k, v in sorted(rows.items()) if k >= start.strftime("%Y-%m-%dT%H:%M:%S")]


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    OUT.mkdir(parents=True, exist_ok=True)
    markets = top_markets(n)
    if "KRW-BTC" not in markets:
        markets.append("KRW-BTC")
    for m in markets:
        if (OUT / f"{m}.csv").exists() and "--refresh" not in sys.argv:
            continue
        rows = candles(m, days)
        with open(OUT / f"{m}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["utc", "open", "high", "low", "close", "value"])
            w.writerows(rows)
        print(m, len(rows), flush=True)


if __name__ == "__main__":
    main()
