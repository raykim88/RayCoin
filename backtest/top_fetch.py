"""Download the current top-N Upbit KRW markets (+BTC) into a fresh directory, so a test runs on one
consistent window. Usage: python3 backtest/top_fetch.py <out_dir> [days] [n]"""
import csv, sys
from pathlib import Path
import fetch as F

out = Path(sys.argv[1]); days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
n = int(sys.argv[3]) if len(sys.argv) > 3 else 60
out.mkdir(parents=True, exist_ok=True)
for m in sorted(set(F.top_markets(n)) | {"KRW-BTC"}):
    rows = F.candles(m, days)
    with open(out / f"{m}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["utc", "open", "high", "low", "close", "value"]); w.writerows(rows)
    print(m, len(rows), flush=True)
