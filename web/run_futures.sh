#!/usr/bin/env bash
# After the current bot finishes (status.json phase == done), continue in leveraged-futures mode:
# hourly tuning, endless 30-minute rounds, and the live-data pusher.
set -u
cd "$(dirname "$0")/.."
until grep -q '"phase": "done"' status.json 2>/dev/null; do sleep 3; done
sleep 5   # let the previous pusher send its final push
cp status.json "results/status_before_futures_$(date +%H%M).json"
python3 paper_futures.py --resume status.json --last-round 0 --log trade_log_v2.txt --status status.json \
  >> run_v2_stdout.txt 2>&1 &
BOT=$!
until grep -q '"mode": "futures"' status.json 2>/dev/null; do sleep 2; done
web/push_live.sh status.json 60 > push_v3.out 2>&1 &
wait "$BOT"
