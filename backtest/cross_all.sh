#!/bin/bash
# Daily cross-exchange check of the live pump-fade rules (2h +20% short, 7% stop, last 30 days).
# Refreshes Upbit, Bithumb, OKX (crypto swaps) and Binance spot candles, runs sl_width.py on each,
# and writes the summary to backtest/cross_all.txt. Run detached: setsid nohup bash backtest/cross_all.sh &
cd "$(dirname "$0")/.." || exit 1
OUT=backtest/cross_all.txt
TMP=$(mktemp)
echo "cross_all $(date -u +%Y-%m-%dT%H:%MZ)" > "$TMP"
python3 backtest/refresh_all.py 30 60 > /dev/null 2>&1
for ex in bithumb okx binance; do
  rm -rf "backtest/data_$ex"; python3 backtest/fetch_ex.py "$ex" 30 60 > /dev/null 2>&1
done
# OKX top list mixes in stock/commodity tokens: keep only coins listed on OKX or Binance spot
python3 - > backtest/okx_crypto.txt <<'PY'
import json, urllib.request
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
s = {x["baseCcy"] for x in g("https://www.okx.com/api/v5/public/instruments?instType=SPOT")["data"] if x["quoteCcy"] == "USDT"}
s |= {x["baseAsset"] for x in g("https://data-api.binance.vision/api/v3/exchangeInfo")["symbols"] if x["quoteAsset"] == "USDT"}
print("\n".join(sorted(s)))
PY
rm -rf backtest/data_okxc; mkdir backtest/data_okxc
for f in backtest/data_okx/KRW-*.csv; do
  c=$(basename "$f" .csv); c=${c#KRW-}
  grep -qx "$c" backtest/okx_crypto.txt && ln -s "../data_okx/KRW-$c.csv" backtest/data_okxc/
done
for d in data:upbit data_bithumb:bithumb data_okxc:okx data_binance:binance; do
  dir=${d%%:*}; name=${d##*:}
  echo "== $name" >> "$TMP"
  RC_DATA=backtest/$dir COOLS=0 SLS=0.07 python3 backtest/sl_width.py 2>&1 | tail -3 >> "$TMP"
done
mv "$TMP" "$OUT"
echo done >> "$OUT"
