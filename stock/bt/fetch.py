"""Download stock candles from Yahoo Finance's chart API into stock/bt/data/<interval>/<symbol>.csv.

Usage: python3 stock/bt/fetch.py
"""
import csv
import json
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"
US = ["TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXU", "TNA", "TZA", "TECL", "FNGU", "LABU", "LABD", "TSLL", "NVDL",
      "QQQ", "SPY"]
KR = ["005930", "000660", "373220", "207940", "005380", "000270", "068270", "035420", "035720", "105560", "055550",
      "012330", "005490", "051910", "006400", "028260", "003670", "066570", "096770", "034020", "012450", "042660",
      "329180", "009540", "010140", "086790", "316140", "032830", "017670", "030200", "015760", "033780", "011200",
      "010130", "064350", "267260", "000810", "018260", "259960", "323410", "352820", "011070", "009150", "003550",
      "034730", "402340", "138040", "047810", "079550", "272210"]
KQ = ["247540", "086520", "196170", "028300", "141080", "058470", "277810", "214150", "145020", "263750"]
SYMS = US + [s + ".KS" for s in KR] + [s + ".KQ" for s in KQ] + ["^KS11", "^KQ11"]


def get(sym, interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}"
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
        except Exception as e:
            err = e; time.sleep(2 * 2 ** a)
    raise err


def main():
    for interval, rng in (("5m", "60d"), ("1h", "730d"), ("1d", "10y")):
        d = OUT / interval; d.mkdir(parents=True, exist_ok=True)
        for s in SYMS:
            try:
                r = get(s, interval, rng)
            except Exception as e:
                print("FAIL", s, interval, e, flush=True); continue
            q = r["indicators"]["quote"][0]; ts = r.get("timestamp") or []
            with open(d / f"{s}.csv", "w", newline="") as f:
                w = csv.writer(f); w.writerow(["ts", "open", "high", "low", "close", "volume"])
                for i, t in enumerate(ts):
                    row = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
                    if None not in row[:4]:
                        w.writerow([t] + row)
            print(interval, s, len(ts), r["meta"].get("exchangeTimezoneName"), flush=True)
            time.sleep(0.4)


if __name__ == "__main__":
    main()
