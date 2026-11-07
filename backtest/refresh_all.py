"""Re-download every market already in backtest/data plus today's top-N, so all series end now.

Usage: python3 backtest/refresh_all.py [days] [n_markets]
"""
import csv
import sys

import fetch as F


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 23
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    F.OUT.mkdir(parents=True, exist_ok=True)
    markets = sorted({p.stem for p in F.OUT.glob("KRW-*.csv")} | set(F.top_markets(n)) | {"KRW-BTC"})
    for m in markets:
        rows = F.candles(m, days)
        with open(F.OUT / f"{m}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["utc", "open", "high", "low", "close", "value"])
            w.writerows(rows)
        print(m, len(rows), flush=True)


if __name__ == "__main__":
    main()
