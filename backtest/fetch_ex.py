"""Download 5-minute candles from Bithumb (KRW) or OKX (USDT perpetual swaps) in backtest/data's CSV format.

Usage: python3 backtest/fetch_ex.py bithumb|okx [days] [n_markets]
Writes backtest/data_<exchange>/KRW-<COIN>.csv (utc, open, high, low, close, value) so engine.py can load
it unchanged (set RC_DATA=backtest/data_<exchange>). OKX value is in USDT, which only matters for ranking.
"""
import csv, json, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

EX = sys.argv[1]
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 28
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
OUT = Path(__file__).resolve().parent / f"data_{EX}"
KST = timezone(timedelta(hours=9))


def get(url):
    for a in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"accept": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=15) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.5 * 2 ** a)
    raise RuntimeError(url)


def top():
    if EX == "bithumb":
        mk = [m["market"] for m in get("https://api.bithumb.com/v1/market/all") if m["market"].startswith("KRW-")]
        t = []
        for i in range(0, len(mk), 100):
            t += get("https://api.bithumb.com/v1/ticker?markets=" + ",".join(mk[i:i + 100]))
        t.sort(key=lambda x: -x["acc_trade_price_24h"])
        return [x["market"] for x in t[:N]]
    t = [x for x in get("https://www.okx.com/api/v5/market/tickers?instType=SWAP")["data"] if x["instId"].endswith("-USDT-SWAP")]
    t.sort(key=lambda x: -float(x["volCcy24h"]) * float(x["last"]))
    return [x["instId"] for x in t[:N]]


def candles(m, start):
    rows = {}
    if EX == "bithumb":
        to = datetime.now(KST)
        while to > start:
            b = get(f"https://api.bithumb.com/v1/candles/minutes/5?market={m}&count=200&to={to.strftime('%Y-%m-%dT%H:%M:%S')}")
            if not b:
                break
            for c in b:
                rows[c["candle_date_time_utc"]] = [c["opening_price"], c["high_price"], c["low_price"], c["trade_price"], c["candle_acc_trade_price"]]
            to = datetime.fromisoformat(b[-1]["candle_date_time_kst"]).replace(tzinfo=KST)
            time.sleep(0.08)
    else:
        after = int(time.time() * 1000)
        while after > start.timestamp() * 1000:
            b = get(f"https://www.okx.com/api/v5/market/history-candles?instId={m}&bar=5m&limit=100&after={after}")["data"]
            if not b:
                break
            for c in b:
                t = datetime.fromtimestamp(int(c[0]) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                rows[t] = [float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[7])]
            after = int(b[-1][0])
            time.sleep(0.11)
    return [[t] + rows[t] for t in sorted(rows) if t >= start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")]


OUT.mkdir(exist_ok=True)
start = datetime.now(timezone.utc) - timedelta(days=DAYS)
ms = top()
if EX == "okx" and "BTC-USDT-SWAP" not in ms:
    ms.append("BTC-USDT-SWAP")
for k, m in enumerate(ms):
    rows = candles(m, start)
    name = ("KRW-" + m.split("-")[0]) if EX == "okx" else m
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["utc", "open", "high", "low", "close", "value"]); w.writerows(rows)
    print(k, m, len(rows), flush=True)
